"""
scraper_playwright.py - Phase 1: Playwright deep scraper for Austrian retailers
================================================================================
Auto-discovers every source_products_*.json in ../data/, combines them, then for
each product x 4 retailers:
  1. Brave Search API -> top 10 results
  2. Filter to valid product-page URLs
  3. Visit each URL with async Playwright + stealth (headless Chromium)
  4. Extract raw embedded JSON: ld+json, __NEXT_DATA__, hydration patterns

Output (../output/):
  raw_expert.json
  raw_cyberport.json
  raw_electronic4you.json
  raw_etec.json

Resumable: already-visited URLs are skipped on re-run.

Setup:
  pip install playwright playwright-stealth
  playwright install chromium

Usage (run from inside scrape/):
  python3 scraper_playwright.py
"""

import asyncio
import gzip
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

try:
    from playwright.async_api import async_playwright
except ImportError:
    sys.exit("Missing: pip install playwright && playwright install chromium")

try:
    from playwright_stealth import Stealth
    _stealth = Stealth()
    _STEALTH = True
except ImportError:
    print("Warning: playwright-stealth not found. Running without stealth.")
    _STEALTH = False

# ── Paths ─────────────────────────────────────────────────────────────────────

HERE       = Path(__file__).resolve().parent
DATA_DIR   = (HERE / "../data").resolve()
OUTPUT_DIR = (HERE / "../output").resolve()

# ── Config ────────────────────────────────────────────────────────────────────

BRAVE_RATE        = 1.2     # seconds between Brave API calls
PAGE_DELAY        = 2.5     # seconds between Playwright page visits
PAGE_TIMEOUT      = 30_000  # ms
RESULTS_PER_QUERY = 10

BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"

RETAILERS = [
    ("Expert AT",         "expert.at",         "raw_expert.json"),
    ("Cyberport AT",      "cyberport.at",       "raw_cyberport.json"),
    ("electronic4you.at", "electronic4you.at",  "raw_electronic4you.json"),
    ("E-Tec",             "e-tec.at",           "raw_etec.json"),
]

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# ── Model-number helpers (for query building) ─────────────────────────────────

MODEL_BLOCKLIST = {
    "500ML","1000ML","1500ML","2000ML","250ML","100ML","750ML","300ML",
    "500-ML","1000-ML","1500-ML","250-ML",
    "500W","800W","700W","1000W","1300W","1500W","2000W","2200W","400W","550W",
    "230V","220V","110V","50HZ","60HZ",
    "SMART","QLED","OLED","ANDROID","GOOGLE","TRIPLE","DUAL",
    "ZOLL","INCH","FULL","HDMI","WLAN","WIFI","WEISS","WHITE",
    "BLACK","SCHWARZ","GRAU","SILBER","SILVER",
    "MEDIAMARKT","ELECTRONIC4YOU","AMAZON","CYBERPORT","EXPERT","KAUFEN","ONLINE",
}
MODEL_MIN_LEN = 5

_RETAILER_SUFFIX = re.compile(
    r'\s*[|\-]\s*(electronic4you|mediamarkt|expert\.at|cyberport|e-tec|amazon).*$',
    re.IGNORECASE,
)

def clean_name(name: str) -> str:
    return _RETAILER_SUFFIX.sub("", name).strip()

def is_valid_model(token: str) -> bool:
    t = token.strip()
    if not t or len(t) < MODEL_MIN_LEN:
        return False
    tu = t.upper().replace("-", "").replace(".", "")
    if tu in MODEL_BLOCKLIST:
        return False
    if re.match(r"^\d+$", t) or re.match(r"^\d{12,}$", t):
        return False
    if re.search(r"\s", t):
        return False
    if re.match(r"^\d+[-]?ML$", tu) or re.match(r"^\d+W$", tu):
        return False
    if re.match(r"^\d+V$", tu) or re.match(r"^\d+HZ$", tu):
        return False
    if not re.search(r"[A-Za-z]", t) or not re.search(r"\d", t):
        return False
    return True

def get_ean(src: dict) -> str:
    specs = src.get("specifications") or {}
    val = (
        src.get("ean")
        or specs.get("GTIN")
        or specs.get("EAN-Code")
        or specs.get("EAN")
        or specs.get("GTIN/EAN")
        or ""
    )
    val = str(val).strip()
    return val if val and val.lower() != "none" else ""

def get_model(src: dict) -> str:
    specs = src.get("specifications") or {}
    name  = clean_name(src.get("name", ""))
    for key in ["Hersteller Modellnummer", "Hersteller Artikelnummer", "Modellnummer"]:
        val = str(specs.get(key) or "").strip()
        if val and is_valid_model(val):
            return val
    candidates = re.findall(r"\b[A-Z0-9]{2,}(?:[-\.][A-Z0-9]{2,})*\b", name.upper())
    valid = [c for c in candidates if is_valid_model(c)]
    return max(valid, key=len) if valid else ""

def build_query(src: dict, site: str) -> str:
    name  = (src.get("name") or "").strip()
    brand = (src.get("brand") or "").strip()
    words = name.split()
    if not brand and words:
        brand = words[0]
    ean   = get_ean(src)
    model = get_model(src)
    if ean:
        term = ean
    elif model:
        term = f"{brand} {model}".strip()
    else:
        skip = re.compile(
            r'^[\d"\'%]+$|^(cm|zoll|inch|watt|hz|kg|liter|ltr|l)$', re.I
        )
        words_clean = clean_name(name).split()
        meaningful  = [w for w in words_clean[1:] if not skip.match(w)][:4]
        term = " ".join([brand] + meaningful).strip()
    return f"site:{site} {term}"

# ── Product-URL validators ─────────────────────────────────────────────────────

_ETEC_PAT = [
    re.compile(r"/shop/produkt/\d+/"),
    re.compile(r"details\.php\?artnr=[\s+]*\d"),
    re.compile(r"details\.php\?art=\d"),
]

PRODUCT_URL_RULES = {
    "Expert AT":         lambda u: bool(re.search(r"~p\d+", u)),
    "Cyberport AT":      lambda u: "/pdp/" in u,
    "electronic4you.at": lambda u: (
        bool(re.search(r"-\d{5,7}(?:-l\d+)?\.html$", u))
        and not any(x in u for x in [
            "/service-center/", "/unternehmen/", "/schnaeppchen",
            "/aktionen", "/topseller", "/teilzahlung", "/kontakt",
            "/impressum", "/abholshops", "/ueberuns", "/servicepartner",
            "/reparatur", "/geraeteschutz",
        ])
    ),
    "E-Tec": lambda u: any(p.search(u) for p in _ETEC_PAT),
}

def is_product_url(url: str, retailer: str) -> bool:
    rule = PRODUCT_URL_RULES.get(retailer)
    return rule(url) if rule else True

# ── Brave Search ──────────────────────────────────────────────────────────────

def load_api_key() -> str:
    env_file = HERE / ".env"
    load_dotenv(env_file if env_file.exists() else None)
    key = os.getenv("BRAVE_API_KEY", "")
    if not key:
        sys.exit(f"BRAVE_API_KEY not set in {env_file}")
    return key

def brave_search(query: str, api_key: str) -> list:
    params = urllib.parse.urlencode({
        "q":               query,
        "count":           RESULTS_PER_QUERY,
        "country":         "AT",
        "search_lang":     "de",
        "ui_lang":         "de-AT",
        "safesearch":      "off",
        "text_decorations": 0,
        "spellcheck":      0,
    })
    req = urllib.request.Request(
        f"{BRAVE_URL}?{params}",
        headers={
            "Accept":             "application/json",
            "Accept-Encoding":    "gzip",
            "X-Subscription-Token": api_key,
        },
    )
    with urllib.request.urlopen(req, timeout=14) as resp:
        raw = resp.read()
        if resp.info().get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8")).get("web", {}).get("results", [])

# ── Playwright page extraction ─────────────────────────────────────────────────

async def extract_page_data(page, url: str, retailer: str) -> dict:
    """Visit URL and pull every embedded JSON block from the DOM."""
    result: dict = {
        "url":            url,
        "retailer":       retailer,
        "page_title":     None,
        "ld_json":        [],
        "next_data":      None,
        "hydration_data": [],
        "scraped_at":     datetime.now(timezone.utc).isoformat(),
        "error":          None,
    }
    try:
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)
        if resp and resp.status >= 400:
            result["error"] = f"HTTP {resp.status}"
            return result

        # Allow lazy scripts to populate
        await asyncio.sleep(1.5)

        result["page_title"] = await page.title()

        # ── ld+json blocks ────────────────────────────────────────────────
        ld_texts = await page.eval_on_selector_all(
            'script[type="application/ld+json"]',
            "els => els.map(el => el.textContent.trim())",
        )
        for text in ld_texts:
            try:
                result["ld_json"].append(json.loads(text))
            except (json.JSONDecodeError, ValueError):
                pass

        # ── __NEXT_DATA__ ─────────────────────────────────────────────────
        next_el = await page.query_selector("script#__NEXT_DATA__")
        if next_el:
            try:
                result["next_data"] = json.loads(
                    (await next_el.text_content()).strip()
                )
            except (json.JSONDecodeError, ValueError):
                pass

        # ── Other JS hydration patterns ───────────────────────────────────
        hydration_raw = await page.evaluate(
            """() => {
            const VARS = [
                ['nuxt',          '__NUXT__'],
                ['store',         '__STORE__'],
                ['initial_state', '__INITIAL_STATE__'],
                ['app_data',      '__APP_DATA__'],
                ['preloaded',     '__PRELOADED_STATE__'],
            ];
            const found = [];
            for (const el of document.querySelectorAll('script:not([src])')) {
                const t = el.textContent;
                if (t.length < 50 || t.length > 5000000) continue;
                for (const [label, varName] of VARS) {
                    if (t.includes(varName)) {
                        found.push({ label, content: t.slice(0, 200000) });
                        break;
                    }
                }
            }
            return found;
        }"""
        )

        for item in hydration_raw or []:
            label   = item.get("label", "unknown")
            content = item.get("content", "")
            m = re.search(r"window\.__\w+__\s*=\s*(\{.*)", content, re.DOTALL)
            if m:
                raw_json = m.group(1).rstrip(";").strip()
                try:
                    result["hydration_data"].append(
                        {"type": label, "data": json.loads(raw_json)}
                    )
                except (json.JSONDecodeError, ValueError):
                    result["hydration_data"].append(
                        {"type": label, "_raw": raw_json[:3000]}
                    )

    except Exception as exc:
        result["error"] = str(exc)

    return result

# ── Core scraping loop ────────────────────────────────────────────────────────

def make_ref(url: str) -> str:
    return "P_SC_" + hashlib.md5(url.encode()).hexdigest()[:8].upper()

async def run(sources: list, api_key: str):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Load existing data + build visited-URL sets for resumability
    retailer_data: dict[str, list] = {}
    visited_urls:  dict[str, set]  = {}
    for name, _, fname in RETAILERS:
        path = OUTPUT_DIR / fname
        if path.exists():
            with open(path, encoding="utf-8") as f:
                retailer_data[name] = json.load(f)
        else:
            retailer_data[name] = []
        visited_urls[name] = {item["url"] for item in retailer_data[name]}

    total = len(sources)
    print(f"\nScraping {total} products x {len(RETAILERS)} retailers ...\n")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--disable-infobars",
            ],
        )

        for idx, src in enumerate(sources, 1):
            ref   = src.get("reference", f"src_{idx}")
            label = clean_name(src.get("name", ref))[:70]
            print(f"[{idx}/{total}] {label}")

            for name, site, fname in RETAILERS:
                query = build_query(src, site)
                print(f"  [{name:22s}] {query[:68]}")

                try:
                    results = brave_search(query, api_key)
                    time.sleep(BRAVE_RATE)
                except Exception as exc:
                    print(f"  [{name:22s}] Brave error: {exc}")
                    continue

                new_urls = [
                    r["url"]
                    for r in results
                    if is_product_url(r.get("url", ""), name)
                    and r.get("url") not in visited_urls[name]
                ]
                print(f"  [{name:22s}] {len(new_urls)} new product URLs")

                for url in new_urls:
                    ctx = await browser.new_context(
                        user_agent=USER_AGENT,
                        viewport={"width": 1280, "height": 800},
                        locale="de-AT",
                        timezone_id="Europe/Vienna",
                        extra_http_headers={"Accept-Language": "de-AT,de;q=0.9"},
                    )
                    page = await ctx.new_page()

                    try:
                        if _STEALTH:
                            await _stealth.apply_stealth_async(page)

                        print(f"    -> {url[:75]}")
                        data = await extract_page_data(page, url, name)
                        data["source_reference"] = ref
                        data["source_name"]      = label
                        data["reference"]        = make_ref(url)

                        retailer_data[name].append(data)
                        visited_urls[name].add(url)

                        if data.get("error"):
                            print(f"       error: {data['error']}")
                        else:
                            ld  = len(data.get("ld_json", []))
                            nxt = data.get("next_data") is not None
                            hyd = len(data.get("hydration_data", []))
                            print(f"       ok  ld+json:{ld}  next_data:{nxt}  hydration:{hyd}")

                    finally:
                        await page.close()
                        await ctx.close()
                        await asyncio.sleep(PAGE_DELAY)

                # Save after each retailer for this product (resumable)
                out_path = OUTPUT_DIR / fname
                with open(out_path, "w", encoding="utf-8") as f:
                    json.dump(retailer_data[name], f, ensure_ascii=False, indent=2)

        await browser.close()

    print("\nScraping complete:")
    for name, _, fname in RETAILERS:
        count = len(retailer_data[name])
        print(f"  {OUTPUT_DIR / fname}  ({count} pages)")

# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    # Auto-discover all source product files
    source_files = sorted(DATA_DIR.glob("source_products_*.json"))
    if not source_files:
        sys.exit(f"No source_products_*.json files found in {DATA_DIR}")

    all_sources: list[dict] = []
    for sf in source_files:
        with open(sf, encoding="utf-8") as f:
            data = json.load(f)
        print(f"  {sf.name}: {len(data)} products")
        all_sources.extend(data)

    # Deduplicate by reference
    seen: set[str] = set()
    sources: list[dict] = []
    for s in all_sources:
        ref = s.get("reference", "")
        if ref and ref not in seen:
            seen.add(ref)
            sources.append(s)

    print(f"\nTotal unique source products: {len(sources)}")

    api_key = load_api_key()
    asyncio.run(run(sources, api_key))


if __name__ == "__main__":
    main()
