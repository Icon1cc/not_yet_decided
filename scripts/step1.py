"""
STEP 1: Match source products to target pool (visible retailers)
Strategy:
  1. EAN matching  — exact EAN from source specs vs target specs
  2. Model number matching — extract model numbers from names
  3. Fuzzy name matching — screen size + brand + key specs
"""

import json
import re
from difflib import SequenceMatcher

# ── Load data ──────────────────────────────────────────────────────────────
with open("data/source_products_tv_&_audio.json") as f:
    sources = json.load(f)

with open("data/target_pool_tv_&_audio.json") as f:
    targets = json.load(f)

print(f"Loaded {len(sources)} source products")
print(f"Loaded {len(targets)} target products")

# ── Helper: extract EAN from a product (ean field + specs) ─────────────────
def get_eans(product):
    eans = set()
    if product.get("ean"):
        eans.add(str(product["ean"]).strip())
    specs = product.get("specifications") or {}
    for key in ["EAN", "EAN-Code", "GTIN", "EAN_Code", "ean"]:
        if specs.get(key):
            eans.add(str(specs[key]).strip())
    # Also check ASIN / model in name — sometimes EAN is in the name
    return eans

# ── Helper: extract screen size in inches from product name ────────────────
def extract_size(text):
    # Matches: 65", 65 Zoll, 65-Zoll, 65 Zoll
    matches = re.findall(r'(\d{2})\s*(?:"|Zoll|zoll|-Zoll)', text)
    return int(matches[0]) if matches else None

# ── Helper: extract model number tokens from product name ─────────────────
def extract_model_tokens(name):
    # Look for patterns like: QE50Q7F, 65T69C, 32S5403A, HP6265E etc.
    tokens = re.findall(r'\b[A-Z0-9]{4,}\b', name.upper())
    return set(tokens)

# ── Helper: extract brand ──────────────────────────────────────────────────
KNOWN_BRANDS = ["samsung", "sharp", "lg", "tcl", "hisense", "peaq", "chiq",
                "xiaomi", "sony", "philips", "grundig", "panasonic", "loewe"]

def get_brand(product):
    name_lower = (product.get("name") or "").lower()
    brand = (product.get("brand") or "").lower()
    for b in KNOWN_BRANDS:
        if b in name_lower or b in brand:
            return b
    return None

# ── Helper: similarity score between two strings ──────────────────────────
def similarity(a, b):
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

# ── Build EAN index for targets ───────────────────────────────────────────
target_ean_index = {}  # ean -> list of target products
for t in targets:
    for ean in get_eans(t):
        if ean not in target_ean_index:
            target_ean_index[ean] = []
        target_ean_index[ean].append(t)

print(f"\nTarget EAN index size: {len(target_ean_index)} unique EANs")

# ── Build model token index for targets ───────────────────────────────────
target_model_index = {}  # token -> list of target products
for t in targets:
    for tok in extract_model_tokens(t.get("name", "")):
        if len(tok) >= 5:  # only meaningful tokens
            if tok not in target_model_index:
                target_model_index[tok] = []
            target_model_index[tok].append(t)

# ── MAIN MATCHING LOOP ─────────────────────────────────────────────────────
results = []
match_summary = []

for src in sources:
    src_ref   = src["reference"]
    src_name  = src.get("name", "")
    src_eans  = get_eans(src)
    src_size  = extract_size(src_name)
    src_brand = get_brand(src)
    src_tokens = extract_model_tokens(src_name)

    found_competitors = {}  # ref -> competitor dict (dedup by ref)

    # ── METHOD 1: EAN match ───────────────────────────────────────────────
    ean_matches = []
    for ean in src_eans:
        if ean in target_ean_index:
            ean_matches.extend(target_ean_index[ean])

    for t in ean_matches:
        if t["reference"] not in found_competitors:
            found_competitors[t["reference"]] = {
                "reference": t["reference"],
                "competitor_retailer": t.get("retailer", ""),
                "competitor_product_name": t.get("name", ""),
                "competitor_url": t.get("url", ""),
                "competitor_price": t.get("price_eur"),
                "match_method": "EAN"
            }

    # ── METHOD 2: Model number token match ───────────────────────────────
    for tok in src_tokens:
        if len(tok) < 5:
            continue
        if tok in target_model_index:
            for t in target_model_index[tok]:
                if t["reference"] not in found_competitors:
                    # Verify it's the same brand
                    t_brand = get_brand(t)
                    if t_brand == src_brand or not src_brand:
                        found_competitors[t["reference"]] = {
                            "reference": t["reference"],
                            "competitor_retailer": t.get("retailer", ""),
                            "competitor_product_name": t.get("name", ""),
                            "competitor_url": t.get("url", ""),
                            "competitor_price": t.get("price_eur"),
                            "match_method": "MODEL_TOKEN"
                        }

    # ── METHOD 3: Fuzzy name match (same brand + same size) ──────────────
    if src_size and src_brand:
        for t in targets:
            if t["reference"] in found_competitors:
                continue
            t_name  = t.get("name", "")
            t_size  = extract_size(t_name)
            t_brand = get_brand(t)

            # Must match brand AND screen size
            if t_brand == src_brand and t_size == src_size:
                score = similarity(src_name, t_name)
                if score > 0.4:  # reasonable threshold
                    found_competitors[t["reference"]] = {
                        "reference": t["reference"],
                        "competitor_retailer": t.get("retailer", ""),
                        "competitor_product_name": t.get("name", ""),
                        "competitor_url": t.get("url", ""),
                        "competitor_price": t.get("price_eur"),
                        "match_method": f"FUZZY({score:.2f})"
                    }

    # ── METHOD 4: Competitive match (same size, any brand, high relevance) 
    # Based on sample solutions — same screen size = valid competitive match
    if src_size:
        for t in targets:
            if t["reference"] in found_competitors:
                continue
            t_name = t.get("name", "")
            t_size = extract_size(t_name)
            # Same size AND looks like an actual TV
            if t_size == src_size and any(kw in t_name.lower() for kw in
               ["smart tv", "fernseher", "qled", "oled", "led tv", "4k", "full hd"]):
                found_competitors[t["reference"]] = {
                    "reference": t["reference"],
                    "competitor_retailer": t.get("retailer", ""),
                    "competitor_product_name": t.get("name", ""),
                    "competitor_url": t.get("url", ""),
                    "competitor_price": t.get("price_eur"),
                    "match_method": "COMPETITIVE_SIZE"
                }

    competitors_list = list(found_competitors.values())

    results.append({
        "source_reference": src_ref,
        "competitors": competitors_list
    })

    match_summary.append({
        "ref": src_ref,
        "name": src_name[:60],
        "eans": list(src_eans),
        "size": src_size,
        "brand": src_brand,
        "matches": len(competitors_list),
        "methods": list(set(c["match_method"].split("(")[0] for c in competitors_list))
    })

# ── Print summary ──────────────────────────────────────────────────────────
print("\n" + "="*70)
print("MATCHING SUMMARY")
print("="*70)
total_matches = 0
for s in match_summary:
    print(f"\n[{s['ref']}]")
    print(f"  Product : {s['name']}")
    print(f"  EANs    : {s['eans']}")
    print(f"  Size    : {s['size']}\"  Brand: {s['brand']}")
    print(f"  Matches : {s['matches']}  Methods: {s['methods']}")
    total_matches += s['matches']

print(f"\n{'='*70}")
print(f"TOTAL: {len(results)} source products → {total_matches} competitor links found")
products_with_match = sum(1 for s in match_summary if s['matches'] > 0)
print(f"Coverage: {products_with_match}/{len(results)} source products have at least 1 match")

# ── Save output JSON ───────────────────────────────────────────────────────
# Remove match_method before saving (internal use only)
clean_results = []
for r in results:
    clean_comps = []
    for c in r["competitors"]:
        clean_comps.append({k: v for k, v in c.items() if k != "match_method"})
    clean_results.append({
        "source_reference": r["source_reference"],
        "competitors": clean_comps
    })

out_path = "output/submission_step1.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(clean_results, f, ensure_ascii=False, indent=2)

print(f"\n✅ Saved submission to: {out_path}")