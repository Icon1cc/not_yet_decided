"""
match_targets.py — Match source products to visible retailer target pool
========================================================================
Visible retailers: Amazon AT, MediaMarkt AT

Matching strategy (priority order):
  1. direct_ref  — source.reference == target.reference
  2. gtin        — source EAN/GTIN == target GTIN in specs
  3. asin        — source ASIN == target ASIN in specs
  4. model       — model number found in pool index (≥6 chars, letters+digits)
  5. name_sim    — Jaccard token overlap ≥0.55, only when no confident match exists

FIXED BUGS (vs previous version that produced 83/82 false matches):
  - REMOVED model_in_name scan (was scanning all 561/1683 products for each model token,
    causing CHIQ 43QA10 to match 81 unrelated QA-series products)
  - MODEL BLOCKLIST: pure-digit internal SKUs (300921, 601013, 400676, 400588),
    volume tokens (500ML, 500-ML), wattage (1300W), site names (ELECTRONIC4YOU)
  - Modellnummer field blocked if pure digits or 12+ digits (looks like EAN) or has spaces
  - Product name cleaned before model extraction: strips '| electronic4you' suffixes
    (was causing P_E7E4FF67 to extract 'ELECTRONIC4YOU' as model)
  - name_sim threshold raised 0.30→0.55 (removes wrong-brand size-matches)
  - Per-retailer cap MAX_PER_RETAILER=5 prevents Amazon flooding

Usage (run from inside scrape/):
  python3 match_targets.py \\
      --source  "../data/source_products_tv_&_audio.json" \\
      --pool    "../data/target_pool_tv_&_audio.json" \\
      --output  "../output/matches_tv_audio.json"

  python3 match_targets.py \\
      --source  "../data/source_products_small_appliances.json" \\
      --pool    "../data/target_pool_small_appliances.json" \\
      --output  "../output/matches_small_appliances.json"
"""

import re, json, argparse
from pathlib import Path
from collections import defaultdict

HERE = Path(__file__).resolve().parent

# ── Config ────────────────────────────────────────────────────────────────────
NAME_SIM_THRESHOLD = 0.55
MODEL_MIN_LEN      = 5
MAX_PER_RETAILER   = 5

# Tokens that look like model numbers but are NOT
MODEL_BLOCKLIST = {
    # Volumes / sizes
    "500ML","1000ML","1500ML","2000ML","250ML","100ML","750ML","300ML",
    "500-ML","1000-ML","1500-ML","250-ML",
    # Wattage
    "500W","800W","700W","1000W","1300W","1500W","2000W","2200W","400W","550W",
    # Voltage / frequency
    "230V","220V","110V","50HZ","60HZ",
    # Common product words that match model regex
    "SMART","QLED","OLED","ANDROID","GOOGLE","TRIPLE","DUAL",
    "ZOLL","INCH","FULL","HDMI","WLAN","WIFI","WEISS","WHITE",
    "BLACK","SCHWARZ","GRAU","SILBER","SILVER","GOLD",
    # Site/retailer names
    "MEDIAMARKT","ELECTRONIC4YOU","AMAZON","CYBERPORT",
    "EXPERT","KAUFEN","ONLINE","MEDIAMRKT",
}

# Patterns that indicate internal SKU / catalogue numbers (not product models)
_INTERNAL_SKU = re.compile(r'^\d{4,}$')          # pure digits: 300921, 601013
_EAN_LIKE     = re.compile(r'^\d{12,}$')          # 12+ digit number = EAN
_LONG_DESCR   = re.compile(r'\s')                 # contains spaces = description


# ── Name cleaner ─────────────────────────────────────────────────────────────

_RETAILER_SUFFIX = re.compile(
    r'\s*[|\-]\s*(electronic4you|mediamarkt|expert\.at|cyberport|e-tec|amazon)'
    r'.*$', re.IGNORECASE
)

def clean_name(name: str) -> str:
    """Strip retailer suffix like '| electronic4you' from product name."""
    return _RETAILER_SUFFIX.sub('', name).strip()


# ── Model validator ───────────────────────────────────────────────────────────

def is_valid_model(token: str) -> bool:
    t  = token.strip()
    if not t or len(t) < MODEL_MIN_LEN:
        return False
    tu = t.upper().replace("-", "").replace(".", "")
    # Check blocklist
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

def get_identifiers(product: dict) -> dict:
    specs     = product.get("specifications") or {}
    raw_name  = product.get("name", "")
    name      = clean_name(raw_name)

    # EAN / GTIN — check all known field name variants (differs by retailer source)
    ean_final = str(
        product.get("ean") or
        specs.get("GTIN") or
        specs.get("EAN-Code") or
        specs.get("EAN") or
        specs.get("GTIN/EAN") or ""
    ).strip()

    # ASIN
    asin = str(specs.get("ASIN") or "").strip()

    # Model from spec fields — validate each
    model_from_specs = []
    for key in ["Hersteller Modellnummer", "Hersteller Artikelnummer", "Modellnummer", "Modellname"]:
        val = str(specs.get(key) or "").strip()
        if val and is_valid_model(val):
            model_from_specs.append(val)

    # Model tokens from cleaned name
    # Allow alphanumeric + hyphens + dots (covers CHP80.000SI, QE55Q7FAAUXXN, BS-C9002)
    raw_tokens = re.findall(r'\b[A-Z0-9]{2,}(?:[-\.][A-Z0-9]{2,})*\b', name.upper())
    model_from_name = [t for t in raw_tokens if is_valid_model(t)]

    all_models = list(dict.fromkeys(model_from_specs + model_from_name))

    # Token set for name similarity (use raw_name so full context is included)
    tokens = set(re.findall(r'[a-z0-9]{2,}', raw_name.lower()))

    return {"ean": ean_final, "asin": asin, "models": all_models, "tokens": tokens}


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# ── Build pool index ──────────────────────────────────────────────────────────

def build_pool_index(pool: list) -> dict:
    idx    = defaultdict(list)
    by_ref = {}
    for p in pool:
        ids = get_identifiers(p)
        by_ref[p["reference"]] = p
        if ids["ean"]:
            idx[("ean", ids["ean"])].append(p)
        if ids["asin"]:
            idx[("asin", ids["asin"])].append(p)
        for m in ids["models"]:
            idx[("model", m.upper())].append(p)
    return {"by_ref": by_ref, "idx": idx, "all": pool}


# ── Core matching ─────────────────────────────────────────────────────────────

def find_matches(source: dict, pool_index: dict):
    src_ids = get_identifiers(source)
    idx     = pool_index["idx"]
    by_ref  = pool_index["by_ref"]
    results = {}

    def add(product, score, method):
        ref = product["reference"]
        if ref not in results or results[ref][0] < score:
            results[ref] = (score, method, product)

    # 1. Direct reference
    if source["reference"] in by_ref:
        add(by_ref[source["reference"]], 1.0, "direct_ref")

    # 2. GTIN/EAN
    if src_ids["ean"]:
        for p in idx.get(("ean", src_ids["ean"]), []):
            add(p, 0.99, "gtin")

    # 3. ASIN
    if src_ids["asin"]:
        for p in idx.get(("asin", src_ids["asin"]), []):
            add(p, 0.98, "asin")

    # 4. Model — pool index lookup ONLY (no full-text scan to avoid false positives)
    for model in src_ids["models"]:
        for p in idx.get(("model", model.upper()), []):
            add(p, 0.90, f"model:{model}")

    # 5. Name similarity — only if no confident match found yet
    best = max((v[0] for v in results.values()), default=0)
    if best < 0.90:
        for p in pool_index["all"]:
            sim = jaccard(src_ids["tokens"], get_identifiers(p)["tokens"])
            if sim >= NAME_SIM_THRESHOLD:
                add(p, sim, "name_sim")

    return sorted(results.values(), key=lambda x: -x[0])


# ── Cap per retailer ──────────────────────────────────────────────────────────

def cap_by_retailer(matches: list) -> list:
    always = {"direct_ref", "gtin", "asin"}
    counts = defaultdict(int)
    kept   = []
    for score, method, product in matches:
        base   = method.split(":")[0]
        retail = product.get("retailer", "")
        if base in always:
            kept.append((score, method, product))
        elif counts[retail] < MAX_PER_RETAILER:
            kept.append((score, method, product))
            counts[retail] += 1
    return kept


# ── Main ──────────────────────────────────────────────────────────────────────

def match_all(source_path: Path, pool_path: Path, output_path: Path,
              threshold: float = NAME_SIM_THRESHOLD):
    with open(source_path, encoding="utf-8") as f:
        sources = json.load(f)
    with open(pool_path, encoding="utf-8") as f:
        pool = json.load(f)

    print(f"📦  {len(sources)} source products")
    print(f"🎯  {len(pool)} target pool products")
    print(f"    Threshold={threshold}  ModelMinLen={MODEL_MIN_LEN}  MaxPerRetailer={MAX_PER_RETAILER}")
    print()

    pool_index = build_pool_index(pool)
    results = []
    method_counts = defaultdict(int)
    total = 0

    for src in sources:
        raw     = find_matches(src, pool_index)
        matches = cap_by_retailer(raw)

        competitors = []
        for score, method, tgt in matches:
            competitors.append({
                "reference":               tgt["reference"],
                "competitor_retailer":     tgt.get("retailer", ""),
                "competitor_product_name": tgt.get("name", ""),
                "competitor_url":          tgt.get("url", ""),
                "competitor_price":        tgt.get("price_eur"),
                "_match_score":            round(score, 3),
                "_match_method":           method,
            })
            method_counts[method.split(":")[0]] += 1

        total += len(competitors)
        results.append({
            "source_reference": src["reference"],
            "source_name":      src["name"][:80],
            "competitors":      competitors,
        })

        top     = matches[0] if matches else None
        top_str = f"{top[1].split(':')[0]} {top[0]:.2f} → {top[2]['name'][:48]}" if top else "NO MATCH"
        low     = " ⚠️  LOW" if top and top[0] < 0.55 else ""
        print(f"  [{src['reference']}] {src['name'][:45]:45s} | {top_str}{low}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n✅  Written → {output_path}")
    print(f"    Source products : {len(sources)}")
    print(f"    Total matches   : {total}")
    print(f"    Methods:")
    for m, c in sorted(method_counts.items(), key=lambda x: -x[1]):
        print(f"      {m:25s} {c:>5}")
    no_match = [r for r in results if not r["competitors"]]
    if no_match:
        print(f"\n    ⚠️  {len(no_match)} unmatched:")
        for r in no_match:
            print(f"      {r['source_reference']} {r['source_name'][:65]}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--source",    required=True)
    ap.add_argument("--pool",      required=True)
    ap.add_argument("--output",    default="matches.json")
    ap.add_argument("--threshold", type=float, default=NAME_SIM_THRESHOLD)
    args = ap.parse_args()

    def resolve(p):
        p = Path(p)
        return p if p.is_absolute() else (HERE / p).resolve()

    match_all(resolve(args.source), resolve(args.pool), resolve(args.output), args.threshold)