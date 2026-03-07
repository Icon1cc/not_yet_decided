"""
scraper_brave.py — Brave Search API competitor scraper
=======================================================
Scrapes 4 hidden Austrian electronics retailers for each source product.

Hidden retailers:
  Expert AT         → expert.at        → URLs contain ~pNNNN
  Cyberport AT      → cyberport.at     → URLs contain /pdp/
  electronic4you.at → electronic4you.at → URLs end with -NNNNN.html
  E-Tec             → e-tec.at         → URLs contain /shop/produkt/NNN/ or
                                          details.php?artnr=NNN (with any spacing)

Query priority per product:
  1. EAN/GTIN (from ean field OR specifications.GTIN) — most precise
  2. Brand + model number from name/specs — precise
  3. Brand + first meaningful name words — fallback

FIXED BUGS vs previous version:
  - get_model() now strips '| electronic4you' suffix before model extraction
    (was producing model='ELECTRONIC4YOU' for P_E7E4FF67)
  - Modellnummer blocked if: pure digits (internal SKUs like 300921, 601013, 19170),
    12+ digits (EAN-like: 6941948705807), contains spaces (descriptions),
    volume/wattage patterns (500ML, 500-ML, 1300W)
  - Volume tokens (500-ML, 500ML) blocked from name model extraction
    (was making P_32E93F6C query 'Kenwood 500-ML')
  - E-Tec URL validator fixed: now matches artnr= 123, artnr=+123, artnr= +123
    (21 valid E-Tec product pages were being rejected due to spaces/+ in artnr)
  - 13-digit EAN-like Modellnummer blocked (was querying 'XIAOMI 6941948705807')
  - Result is resumable: delete output file to restart from scratch

Setup:
  pip3 install python-dotenv --break-system-packages
  scrape/.env:  BRAVE_API_KEY=BSAxxxx...

Usage (run from inside scrape/):
  python3 scraper_brave.py --test
  python3 scraper_brave.py --input "../data/source_products_tv_&_audio.json"
  python3 scraper_brave.py --input "../data/source_products_tv_&_audio.json" \\
                            --output "../output/scraped_tv_audio.json"
  python3 scraper_brave.py --input "../data/source_products_small_appliances.json" \\
                            --output "../output/scraped_small_appliances.json"
"""

import re, sys, os, json, time, hashlib, argparse
import urllib.request, urllib.parse
from pathlib import Path
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent

# ── Config ────────────────────────────────────────────────────────────────────
RATE                 = 1.1    # seconds between Brave API calls
TOUT                 = 14     # HTTP timeout
RESULTS_PER_QUERY    = 10

BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"

RETAILERS = [
    ("Expert AT",         "expert.at"),
    ("Cyberport AT",      "cyberport.at"),
    ("electronic4you.at", "electronic4you.at"),
    ("E-Tec",             "e-tec.at"),
]

# Tokens blocked from being treated as model numbers
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


# ── E-Tec URL patterns ────────────────────────────────────────────────────────
# E-Tec has 3 URL shapes observed in real data:
#   https://www.e-tec.at/details.php?artnr=+333031   (with + before number)
#   https://www.e-tec.at/details.php?artnr= 311475   (with space before number)
#   https://www.e-tec.at/details.php?artnr= +296621  (with space+plus)
#   https://www.e-tec.at/shop/produkt/12345/name
#   https://e-tec.at/frame2/details.php?art=208560   (art= instead of artnr=)
_ETEC_PATTERNS = [
    re.compile(r'/shop/produkt/\d+/'),
    re.compile(r'details\.php\?artnr=[\s+]*\d'),   # covers artnr=NNN, artnr= NNN, artnr=+NNN
    re.compile(r'details\.php\?art=\d'),
]

def _is_etec_product(url: str) -> bool:
    return any(p.search(url) for p in _ETEC_PATTERNS)


# ── Product URL validators ────────────────────────────────────────────────────

PRODUCT_URL_RULES = {
    "Expert AT":         lambda u: bool(re.search(r'~p\d+', u)),
    "Cyberport AT":      lambda u: '/pdp/' in u,
    "electronic4you.at": lambda u: (
        bool(re.search(r'-\d{5,7}(?:-l\d+)?\.html$', u))
        and not any(x in u for x in [
            '/service-center/', '/unternehmen/', '/computer-spielkonsolen.html',
            '/tv-hifi-heimkino.html', '/schnaeppchen', '/aktionen', '/topseller',
            '/teilzahlung', '/kontakt', '/impressum', '/abholshops', '/ueberuns',
            '/servicepartner', '/reparatur', '/geraeteschutz',
        ])
    ),
    "E-Tec": _is_etec_product,
}

def is_product_url(url: str, retailer: str) -> bool:
    rule = PRODUCT_URL_RULES.get(retailer)
    return rule(url) if rule else True


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_api_key() -> str:
    env = HERE / ".env"
    load_dotenv(env if env.exists() else None)
    key = os.getenv("BRAVE_API_KEY", "")
    if not key:
        sys.exit(f"❌  BRAVE_API_KEY not found in {env}")
    return key


def resolve(p: str) -> Path:
    p = Path(p)
    return p if p.is_absolute() else (HERE / p).resolve()


def make_ref(url: str) -> str:
    return "P_SC_" + hashlib.md5(url.encode()).hexdigest()[:8].upper()


def brave_search(query: str, api_key: str, count: int = RESULTS_PER_QUERY) -> dict:
    params = urllib.parse.urlencode({
        "q": query, "count": count,
        "country": "AT", "search_lang": "de",
        "ui_lang": "de-AT", "safesearch": "off",
        "text_decorations": 0, "spellcheck": 0,
    })
    req = urllib.request.Request(
        f"{BRAVE_URL}?{params}",
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
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
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode('utf-8','replace')[:200]}")


def parse_price(text: str):
    for pat in [
        r'(\d{1,3}(?:\.\d{3})+,\d{2})\s*[€EUR]',
        r'(\d{1,4},\d{2})\s*[€EUR]',
        r'[€EUR]\s*(\d{1,4}[,.]?\d{0,2})',
    ]:
        m = re.search(pat, text or "")
        if m:
            try:
                p = float(m.group(1).replace(".", "").replace(",", "."))
                if 10 < p < 50_000:
                    return round(p, 2)
            except ValueError:
                pass
    return None


# ── Name cleaner ─────────────────────────────────────────────────────────────

_RETAILER_SUFFIX = re.compile(
    r'\s*[|\-]\s*(electronic4you|mediamarkt|expert\.at|cyberport|e-tec|amazon)'
    r'.*$', re.IGNORECASE
)

def clean_name(name: str) -> str:
    """Strip retailer suffix like '| electronic4you' from product name."""
    return _RETAILER_SUFFIX.sub('', name).strip()


# ── Model validation ──────────────────────────────────────────────────────────

def is_valid_model(token: str) -> bool:
    t  = token.strip()
    if not t or len(t) < MODEL_MIN_LEN:
        return False
    tu = t.upper().replace("-", "").replace(".", "")
    if tu in MODEL_BLOCKLIST:
        return False
    # Pure digits → internal SKU (300921, 601013, 400676, 19170)
    if re.match(r'^\d+$', t):
        return False
    # 12+ digit number → EAN masquerading as model (6941948705807)
    if re.match(r'^\d{12,}$', t):
        return False
    # Contains spaces → product description not model
    if re.search(r'\s', t):
        return False
    # Volume patterns: NNN-ML, NNNML (500ML, 500-ML, 1000ML)
    if re.match(r'^\d+[-]?ML$', tu):
        return False
    # Wattage: NNNW (1300W, 800W)
    if re.match(r'^\d+W$', tu):
        return False
    # Voltage: NNNV (230V, 220V)
    if re.match(r'^\d+V$', tu):
        return False
    # Frequency: NNHZ
    if re.match(r'^\d+HZ$', tu):
        return False
    # Must have both letters and digits
    if not re.search(r'[A-Za-z]', t):
        return False
    if not re.search(r'\d', t):
        return False
    return True


# ── Identifier extraction ─────────────────────────────────────────────────────

def get_ean(source: dict) -> str:
    """EAN/GTIN from ean field or specs — checks multiple field name variants."""
    specs = source.get("specifications") or {}
    # Check all known EAN/GTIN field names (varies by retailer source)
    val = (source.get("ean") or
           specs.get("GTIN") or
           specs.get("EAN-Code") or
           specs.get("EAN") or
           specs.get("GTIN/EAN") or "")
    val = str(val).strip()
    return val if val and val.lower() != "none" else ""


def get_model(source: dict) -> str:
    """
    Best model number for this product.
    Checks spec fields first (validated), then extracts from cleaned name.
    Rejects pure-digit internal SKUs, EAN-like numbers, volumes, descriptions.
    """
    specs = source.get("specifications") or {}
    name  = clean_name(source.get("name", ""))

    # Spec fields — try validated fields
    for key in ["Hersteller Modellnummer", "Hersteller Artikelnummer", "Modellnummer"]:
        val = str(specs.get(key) or "").strip()
        if val and is_valid_model(val):
            return val

    # Name tokens — allow hyphens and dots inside model numbers
    candidates = re.findall(r'\b[A-Z0-9]{2,}(?:[-\.][A-Z0-9]{2,})*\b', name.upper())
    valid = [c for c in candidates if is_valid_model(c)]
    # Prefer longer tokens (more specific model numbers)
    return max(valid, key=len) if valid else ""


# ── Query builder ─────────────────────────────────────────────────────────────

def build_query(source: dict, site: str) -> str:
    """
    Build the most precise Brave site: query for this product.
    Priority: EAN → brand+model → brand+meaningful_name_words
    """
    name  = (source.get("name") or "").strip()
    brand = (source.get("brand") or "").strip()
    words = name.split()
    if not brand and words:
        brand = words[0]  # infer brand from first word

    ean   = get_ean(source)
    model = get_model(source)

    if ean:
        # EAN is globally unique — no need for brand prefix
        term = ean
    elif model:
        term = f"{brand} {model}".strip()
    else:
        # Fallback: brand + first 4 meaningful words from name
        skip  = re.compile(r'^[\d"\'%]+$|^(cm|zoll|inch|watt|hz|kg|liter|ltr|l)$', re.I)
        words_clean = clean_name(name).split()
        meaningful  = [w for w in words_clean[1:] if not skip.match(w)][:4]
        term = " ".join([brand] + meaningful).strip()

    return f"site:{site} {term}"


# ── Result builder ────────────────────────────────────────────────────────────

def result_to_record(web_result: dict, retailer: str) -> dict:
    url  = web_result.get("url", "")
    desc = web_result.get("description", "")
    all_text = " ".join([desc] + web_result.get("extra_snippets", []))
    thumb = web_result.get("thumbnail")
    image = (thumb.get("src") or thumb.get("original")) if isinstance(thumb, dict) else None
    return {
        "retailer":    retailer,
        "name":        web_result.get("title", ""),
        "url":         url,
        "price_eur":   parse_price(all_text),
        "ean":         None,
        "image_url":   image,
        "description": desc,
        "reference":   make_ref(url),
    }


# ── Per-product scrape ────────────────────────────────────────────────────────

def scrape_product(source: dict, api_key: str) -> dict:
    ean   = get_ean(source)
    model = get_model(source)
    label = clean_name(source.get("name") or source.get("reference", "?"))[:70]
    print(f"\n  ▶ {label}")
    print(f"     EAN={ean or '—':<15}  model={model or '—'}")

    all_scraped = []
    for retailer, site in RETAILERS:
        query = build_query(source, site)
        print(f"      [{retailer:22s}] {query}")
        try:
            raw     = brave_search(query, api_key)
            records = [
                result_to_record(r, retailer)
                for r in raw.get("web", {}).get("results", [])
                if is_product_url(r.get("url", ""), retailer)
            ]
            print(f"      [{retailer:22s}] → {len(records)} product URLs")
            all_scraped.extend(records)
        except RuntimeError as e:
            print(f"      [{retailer:22s}] ✗ {e}")
        time.sleep(RATE)

    print(f"  ✓ {len(all_scraped)} product URLs total")
    return {
        "source_reference": source["reference"],
        "source_name":      label,
        "query_ean":        ean,
        "query_model":      model,
        "scraped":          all_scraped,
    }


# ── Batch scrape (resumable) ──────────────────────────────────────────────────

def scrape_all(sources: list, output_path: Path, api_key: str):
    results, done = [], set()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if output_path.exists():
        with open(output_path, encoding="utf-8") as f:
            results = json.load(f)
        done = {r["source_reference"] for r in results}
        remaining = len(sources) - len(done)
        print(f"📂  Resuming: {len(done)} done, {remaining} remaining\n")

    for i, src in enumerate(sources, 1):
        ref = src.get("reference", f"src_{i}")
        if ref in done:
            print(f"[{i}/{len(sources)}] ⏭  {ref}")
            continue
        print(f"\n[{i}/{len(sources)}]", end="")
        result = scrape_product(src, api_key)
        results.append(result)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

    return results


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Brave Search scraper for Austrian retailers")
    ap.add_argument("--raw-test", action="store_true", help="Dump raw API response")
    ap.add_argument("--test",     action="store_true", help="Test 3 sample products")
    ap.add_argument("--input",    help="Source products JSON file")
    ap.add_argument("--output",   default="scraped_brave.json")
    args = ap.parse_args()

    api_key = load_api_key()
    print(f"📁  Script dir : {HERE}\n")

    if args.raw_test:
        test_src = {"reference": "P_TEST", "name": "Samsung QE55Q7FAAUXXN QLED 4K TV",
                    "brand": "Samsung", "ean": "8806097123057", "specifications": {}}
        out = {}
        for retailer, site in RETAILERS:
            q = build_query(test_src, site)
            print(f"  [{retailer}]  {q}")
            try:
                raw = brave_search(q, api_key, count=3)
                out[retailer] = {"query": q, "raw_response": raw}
                print(f"    → {len(raw.get('web',{}).get('results',[]))} results")
            except RuntimeError as e:
                out[retailer] = {"query": q, "error": str(e)}
            time.sleep(RATE)
        path = HERE / "raw_brave_response.json"
        with open(path, "w") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print(f"\n✅  Raw → {path}")

    elif args.test:
        samples = [
            # Has EAN → should use EAN
            {"reference": "P_C2CA4D4D", "name": "Samsung QE55Q7FAAUXXN QLED 4K TV (2025)",
             "brand": "Samsung", "ean": "8806097123057", "specifications": {}},
            # GTIN in specs, model in name — should use GTIN
            {"reference": "P_0A7A0D68", "name": "SAMSUNG F6000 (2025) 32 Zoll FullHD Smart TV",
             "brand": "Samsung", "ean": None,
             "specifications": {"GTIN": "8806095913964", "Hersteller Modellnummer": "UE32F6000FUXXN"}},
            # Was broken: model=ELECTRONIC4YOU — now should extract 55HP6265E
            {"reference": "P_E7E4FF67", "name": "Sharp 55HP6265E 4K UHD QLED Google TV | electronic4you",
             "brand": "Sharp", "ean": None,
             "specifications": {"EAN-Code": "5905683272902", "Hersteller Artikelnummer": "4T-C55HP6265EB"}},
            # Was broken: model=500-ML — now should use brand+name words
            {"reference": "P_32E93F6C",
             "name": "Kenwood Duo Prep 2-in-1 CHP80.000SI Multi-Zerkleinerer & Mahler, 500-ml-Behälter, 800W",
             "brand": "Kenwood", "ean": None, "specifications": {}},
            # Was broken: model=6941948705807 (EAN-like) — now should use ASIN or name
            {"reference": "P_349C559B",
             "name": "XIAOMI A Pro, 65\" (165 cm), 4K UHD QLED, Smart TV, Google TV",
             "brand": "", "ean": None,
             "specifications": {"ASIN": "B0F9XJV69Y", "Modellnummer": "6941948705807", "Modellname": "A Pro"}},
        ]
        print(f"🧪  TEST — {len(samples)} products × {len(RETAILERS)} retailers\n")
        print("Queries that will be used:")
        for src in samples:
            ean   = get_ean(src)
            model = get_model(src)
            print(f"  [{src['reference']}] EAN={ean or '—'}  model={model or '—'}")
            for _, site in RETAILERS:
                print(f"    {build_query(src, site)}")
            print()
        print("\nScraping...")
        for src in samples:
            result = scrape_product(src, api_key)
            print(f"\n  Results: {result['source_name']}")
            for r in result["scraped"]:
                price = f"€{r['price_eur']:.2f}" if r.get("price_eur") else "€?"
                print(f"    [{r['retailer']:22s}] {price:>9}  {r['name'][:55]}")
                print(f"    {'':24s} {r['url'][:75]}")
        print("\n✅  Test complete")

    elif args.input:
        out_path = resolve(args.output)
        with open(resolve(args.input), encoding="utf-8") as f:
            sources = json.load(f)
        print(f"📦  {len(sources)} products  →  {out_path}\n")
        scrape_all(sources, out_path, api_key)
        print(f"\n✅  Done → {out_path}")

    else:
        ap.print_help()
        print("""
Examples:
  python3 scraper_brave.py --test
  python3 scraper_brave.py --input "../data/source_products_tv_&_audio.json" \\
                            --output "../output/scraped_tv_audio.json"
  python3 scraper_brave.py --input "../data/source_products_small_appliances.json" \\
                            --output "../output/scraped_small_appliances.json"
""")