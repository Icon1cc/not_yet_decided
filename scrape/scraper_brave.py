"""
scraper_brave.py — Brave Search API-powered competitor scraper
==============================================================
Strategy: For each source product, run one Brave search per retailer using
the `site:` operator. This gives us direct product page URLs + titles +
descriptions straight from Brave's index — no HTML parsing, no Selenium.

All output paths are relative to this script's own directory, so it works
correctly whether you run it from inside `scrape/` or from the project root.

Retailers targeted:
  - expert.at
  - cyberport.at
  - electronic4you.at
  - e-tec.at

Setup:
  pip3 install python-dotenv --break-system-packages
  Add your key to scrape/.env:
      BRAVE_API_KEY=BSAxxxxxxxxxxxxxxxxxxxxxxxxx

Usage (run from anywhere — paths always resolve correctly):
  python3 scraper_brave.py --raw-test
  python3 scraper_brave.py --test
  python3 scraper_brave.py --input ../data/source_products_tv___audio.json
  python3 scraper_brave.py --input ../data/source_products_tv___audio.json \\
                            --merge ../output/submission_step1.json
"""

import re, sys, os, json, time, hashlib, argparse
import urllib.request, urllib.parse
from pathlib import Path
from dotenv import load_dotenv

# ── Anchor all paths to the script's own directory ───────────────────────────
HERE = Path(__file__).resolve().parent   # always = .../scrape/

# ── Config ────────────────────────────────────────────────────────────────────
RATE                 = 1.0
TOUT                 = 12
RESULTS_PER_RETAILER = 10

BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"

RETAILERS = [
    ("Expert AT",         "expert.at"),
    ("Cyberport AT",      "cyberport.at"),
    ("electronic4you.at", "electronic4you.at"),
    ("E-Tec",             "e-tec.at"),
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_api_key() -> str:
    """Load BRAVE_API_KEY from .env sitting next to this script."""
    env_path = HERE / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    else:
        load_dotenv()
    key = os.getenv("BRAVE_API_KEY", "")
    if not key:
        sys.exit(
            f"❌  BRAVE_API_KEY not found.\n"
            f"    Expected it in: {env_path}\n"
            f"    Add a line:  BRAVE_API_KEY=BSAxxxx..."
        )
    return key


def resolve(path_str: str) -> Path:
    """Resolve a path relative to HERE (script dir), not cwd."""
    p = Path(path_str)
    return p if p.is_absolute() else (HERE / p).resolve()


def make_ref(url: str) -> str:
    return "P_SC_" + hashlib.md5(url.encode()).hexdigest()[:8].upper()


def brave_search(query: str, api_key: str,
                 count: int = RESULTS_PER_RETAILER,
                 country: str = "AT", lang: str = "de") -> dict:
    params = urllib.parse.urlencode({
        "q":                query,
        "count":            count,
        "country":          country,
        "search_lang":      lang,
        "ui_lang":          "de-AT",
        "safesearch":       "off",
        "freshness":        "",
        "text_decorations": 0,
        "spellcheck":       0,
    })
    req = urllib.request.Request(
        f"{BRAVE_SEARCH_URL}?{params}",
        headers={
            "Accept":               "application/json",
            "Accept-Encoding":      "gzip",
            "X-Subscription-Token": api_key,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=TOUT) as resp:
            raw = resp.read()
            if resp.info().get("Content-Encoding") == "gzip":
                import gzip; raw = gzip.decompress(raw)
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Brave HTTP {e.code}: {body[:200]}")


def parse_price(text: str) -> float | None:
    for pat in [
        r'(\d{1,3}(?:\.\d{3})+,\d{2})\s*[€EUR]',
        r'(\d{1,4},\d{2})\s*[€EUR]',
        r'[€EUR]\s*(\d{1,4}[,.]?\d{0,2})',
    ]:
        m = re.search(pat, text or "")
        if m:
            try:
                p = float(m.group(1).replace(".", "").replace(",", "."))
                if 5 < p < 50_000:
                    return round(p, 2)
            except ValueError:
                pass
    return None


def build_query(source: dict, site: str) -> str:
    """
    Build the tightest possible Brave query for this product on this retailer.

    Priority:
      1. EAN  — most precise, guaranteed unique product
      2. Brand + model number together (e.g. "Samsung QE55Q7FAAUXXN")
         Model must have both letters AND digits and be ≥6 chars to avoid
         bare numbers like "6000" matching thousands of unrelated products.
      3. First brand word + next 3 meaningful words as fallback.

    Always scoped to the retailer domain via site:.
    """
    name  = (source.get("name") or "").strip()
    ean   = (source.get("ean")  or "").strip()

    # Extract brand (first word, assuming name starts with brand)
    words = name.split()
    brand = words[0] if words else ""

    # Model: must contain both letters and digits, min 5 chars
    # Avoids matching bare numbers like "6000", "32", "4K"
    models = re.findall(r'\b[A-Z]{1,5}\d{2,}[A-Z0-9]{2,}\b', name.upper())
    # Also try mixed patterns like QE55Q7F or 32S5403A
    models += re.findall(r'\b[A-Z0-9]{5,}\b', name.upper())
    # Filter: must have both alpha and numeric components, length ≥ 5
    models = [m for m in models
              if re.search(r'[A-Z]', m) and re.search(r'\d', m) and len(m) >= 5]
    model = max(models, key=len) if models else None

    if ean:
        term = ean
    elif model:
        # Always pair model with brand so "QE55Q7F" doesn't match AEG products
        term = f"{brand} {model}"
    else:
        # Fallback: brand + next 3 words, skip pure-number tokens
        meaningful = [w for w in words[1:] if not re.fullmatch(r'[\d"\']+', w)]
        term = " ".join([brand] + meaningful[:3])

    return f"site:{site} {term}"


def result_to_record(web_result: dict, retailer_name: str) -> dict:
    url  = web_result.get("url", "")
    desc = web_result.get("description", "")
    all_text = " ".join([desc] + web_result.get("extra_snippets", []))

    thumb_obj = web_result.get("thumbnail")
    thumbnail = None
    if isinstance(thumb_obj, dict):
        thumbnail = thumb_obj.get("src") or thumb_obj.get("original")

    return {
        "retailer":       retailer_name,
        "name":           web_result.get("title", ""),
        "url":            url,
        "price_eur":      parse_price(all_text),
        "ean":            None,
        "image_url":      thumbnail,
        "description":    desc,
        "extra_snippets": web_result.get("extra_snippets", []),
        "reference":      make_ref(url),
        # raw Brave fields
        "brave_age":      web_result.get("age"),
        "brave_language": web_result.get("language"),
        "brave_rank":     web_result.get("rank"),
        "brave_profile":  web_result.get("profile"),
    }


# ══════════════════════════════════════════════════════════════════════════════
# PER-PRODUCT SCRAPE
# ══════════════════════════════════════════════════════════════════════════════

def scrape_product(source: dict, api_key: str) -> dict:
    label = source.get("name", source.get("reference", "?"))[:70]
    print(f"\n  ▶ {label}")
    all_scraped = []

    for retailer_name, site in RETAILERS:
        query = build_query(source, site)
        print(f"      [{retailer_name:22s}] {query}")
        try:
            raw     = brave_search(query, api_key)
            records = [result_to_record(r, retailer_name)
                       for r in raw.get("web", {}).get("results", [])]
            print(f"      [{retailer_name:22s}] → {len(records)} results")
            all_scraped.extend(records)
        except RuntimeError as e:
            print(f"      [{retailer_name:22s}] ✗ {e}")
        time.sleep(RATE)

    print(f"  ✓ Total: {len(all_scraped)} scraped matches")
    return {
        "source_reference": source["reference"],
        "source_name":      source.get("name", "")[:80],
        "scraped":          all_scraped,
    }


# ══════════════════════════════════════════════════════════════════════════════
# BATCH SCRAPE (resumable)
# ══════════════════════════════════════════════════════════════════════════════

def scrape_all(sources: list, output_path: Path, api_key: str) -> list:
    results, done = [], set()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if output_path.exists():
        with open(output_path) as f:
            results = json.load(f)
            done    = {r["source_reference"] for r in results}
        print(f"📂 Resuming: {len(done)} done, {len(sources)-len(done)} remaining")

    for i, src in enumerate(sources, 1):
        ref = src.get("reference", f"src_{i}")
        if ref in done:
            print(f"[{i}/{len(sources)}] ⏭  Skip {ref}")
            continue
        print(f"\n[{i}/{len(sources)}]", end="")
        result = scrape_product(src, api_key)
        results.append(result)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

    return results


# ══════════════════════════════════════════════════════════════════════════════
# MERGE INTO SUBMISSION FORMAT
# ══════════════════════════════════════════════════════════════════════════════

def merge_submission(scraped_path: Path, base_path: Path, out_path: Path):
    with open(scraped_path) as f: scraped_all = json.load(f)
    with open(base_path)    as f: base        = json.load(f)

    idx = {r["source_reference"]: r["scraped"] for r in scraped_all}
    for entry in base:
        scraped  = idx.get(entry["source_reference"], [])
        existing = {c.get("competitor_url") for c in entry.get("competitors", [])}
        added    = 0
        for s in scraped:
            if s.get("url") and s["url"] not in existing:
                entry.setdefault("competitors", []).append({
                    "reference":               s["reference"],
                    "competitor_retailer":     s["retailer"],
                    "competitor_product_name": s.get("name", ""),
                    "competitor_url":          s["url"],
                    "competitor_price":        s.get("price_eur"),
                })
                existing.add(s["url"])
                added += 1
        print(f"  {entry['source_reference']}: +{added}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(base, f, ensure_ascii=False, indent=2)
    total = sum(len(e.get("competitors", [])) for e in base)
    print(f"\n✅  Merged → {out_path}  (total competitors: {total})")


# ══════════════════════════════════════════════════════════════════════════════
# RAW TEST — dump full Brave API response next to the script
# ══════════════════════════════════════════════════════════════════════════════

def raw_test(api_key: str):
    test_source = {
        "reference": "P_RAW_TEST",
        "name":      'Samsung QE55Q7FAAUXXN QLED 4K Smart TV 55"',
        "ean":       "8806097123057",
    }
    out = {}
    for retailer_name, site in RETAILERS:
        query = build_query(test_source, site)
        print(f"  🔍  [{retailer_name}]  {query}")
        try:
            raw = brave_search(query, api_key, count=3)
            out[retailer_name] = {"query": query, "raw_response": raw}
            n = len(raw.get("web", {}).get("results", []))
            print(f"      → {n} results")
        except RuntimeError as e:
            out[retailer_name] = {"query": query, "error": str(e)}
            print(f"      ✗ {e}")
        time.sleep(RATE)

    out_path = HERE / "raw_brave_response.json"   # always next to script
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n✅  Raw response → {out_path}")

    print("\n── Field names in web.results[0] ──")
    for retailer_name, data in out.items():
        results = data.get("raw_response", {}).get("web", {}).get("results", [])
        keys    = list(results[0].keys()) if results else "(no results)"
        print(f"  {retailer_name}: {keys}")


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Brave Search competitor scraper — all paths relative to script dir")
    ap.add_argument("--raw-test",      action="store_true",
                    help="Dump raw Brave API JSON → raw_brave_response.json (next to script)")
    ap.add_argument("--test",          action="store_true",
                    help="Test with 3 sample products")
    ap.add_argument("--input",         help="Source products JSON path")
    ap.add_argument("--output",        default="scraped_brave.json",
                    help="Scraped output (default: scraped_brave.json next to script)")
    ap.add_argument("--merge",         help="Base submission JSON to enrich")
    ap.add_argument("--merged-output", default="../output/submission_final.json",
                    help="Merged output (default: ../output/submission_final.json)")
    args = ap.parse_args()

    api_key = load_api_key()
    print(f"📁  Script dir : {HERE}")
    print(f"📁  Output dir : {resolve(args.output).parent}\n")

    if args.raw_test:
        print("🔬  RAW TEST\n")
        raw_test(api_key)

    elif args.test:
        samples = [
            {"reference": "P_C2CA4D4D",
             "name":      'Samsung QE55Q7FAAUXXN QLED 4K Smart TV 55"',
             "ean":       "8806097123057"},
            {"reference": "P_0B4DCAE2",
             "name":      'Sharp 24FH7EA 24" HD Android TV',
             "ean":       "5905683270397"},
            {"reference": "P_979F71CF",
             "name":      'TCL 32S5403A 32" HD Smart TV',
             "ean":       "5901292520779"},
        ]
        print(f"🧪  TEST MODE — {len(samples)} products × {len(RETAILERS)} retailers\n")
        for src in samples:
            result = scrape_product(src, api_key)
            print(f"\n  Results for: {result['source_name']}")
            for r in result["scraped"]:
                price_str = f"€{r['price_eur']:.2f}" if r.get("price_eur") else "€?"
                print(f"    [{r['retailer']:22s}] {price_str:>10}  {r['name'][:55]}")
                print(f"    {'':24s} {r['url'][:70]}")
        print("\n✅  Test complete")

    elif args.input:
        output_path = resolve(args.output)
        with open(resolve(args.input)) as f:
            sources = json.load(f)
        print(f"📦  {len(sources)} products from {resolve(args.input)}")
        results = scrape_all(sources, output_path, api_key)
        print(f"\n✅  Scraped → {output_path}")
        if args.merge:
            merge_submission(output_path, resolve(args.merge),
                             resolve(args.merged_output))
    else:
        ap.print_help()
        print("""
Examples (run from inside scrape/):
  python3 scraper_brave.py --raw-test
  python3 scraper_brave.py --test
  python3 scraper_brave.py --input ../data/source_products_tv___audio.json
""")