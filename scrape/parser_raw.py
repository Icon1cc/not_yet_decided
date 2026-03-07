"""
parser_raw.py - Phase 2: Parse raw Playwright data into matched product format
===============================================================================
Reads the 4 raw_*.json files produced by scraper_playwright.py.

For every scraped page entry:
  - Recursively traverses all nested JSON (ld+json, next_data, hydration_data)
  - Extracts every field it can find without filtering or omitting anything
  - Maps result to the exact source-product field names:
      ean, name, brand, category, image_url, price_eur, reference, specifications
  - Adds: source_reference, url, retailer

Output (../output/):
  matched_expert.json
  matched_cyberport.json
  matched_electronic4you.json
  matched_etec.json

Usage (run from inside scrape/):
  python3 parser_raw.py
"""

import hashlib
import json
import re
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────

HERE       = Path(__file__).resolve().parent
OUTPUT_DIR = (HERE / "../output").resolve()

RAW_TO_MATCHED = [
    ("raw_expert.json",         "matched_expert.json"),
    ("raw_cyberport.json",      "matched_cyberport.json"),
    ("raw_electronic4you.json", "matched_electronic4you.json"),
    ("raw_etec.json",           "matched_etec.json"),
]

# ── Generic recursive helpers ─────────────────────────────────────────────────

def deep_get(data, *keys):
    """
    Recursively search nested dicts/lists for the FIRST occurrence of any key.
    Keys are matched case-insensitively.
    Returns the value (even 0 or False) or None if not found.
    """
    if data is None:
        return None
    keys_lower = {k.lower() for k in keys}

    if isinstance(data, dict):
        for k, v in data.items():
            if k.lower() in keys_lower and v not in (None, "", [], {}):
                return v
        for v in data.values():
            found = deep_get(v, *keys)
            if found is not None:
                return found

    elif isinstance(data, list):
        for item in data:
            found = deep_get(item, *keys)
            if found is not None:
                return found

    return None


def deep_collect(data, *keys) -> list:
    """Collect ALL values for given keys from the entire nested structure."""
    keys_lower = {k.lower() for k in keys}
    results = []

    if isinstance(data, dict):
        for k, v in data.items():
            if k.lower() in keys_lower and v not in (None, "", [], {}):
                results.append(v)
            results.extend(deep_collect(v, *keys))

    elif isinstance(data, list):
        for item in data:
            results.extend(deep_collect(item, *keys))

    return results


def all_sources(raw: dict) -> list:
    """Return all JSON data blobs for searching, in priority order."""
    blobs = []
    # ld+json highest priority for schema fields
    blobs.extend(raw.get("ld_json") or [])
    # Next.js page props
    nd = raw.get("next_data")
    if nd:
        blobs.append(nd)
    # Hydration data
    for h in raw.get("hydration_data") or []:
        d = h.get("data") if isinstance(h, dict) else None
        if d:
            blobs.append(d)
    return blobs

# ── Schema.org Product finder ─────────────────────────────────────────────────

def find_schema_product(ld_jsons: list) -> dict:
    """Find the most specific schema.org Product block in ld+json."""
    for block in ld_jsons:
        if not isinstance(block, dict):
            continue
        typ = block.get("@type", "")
        types = [typ] if isinstance(typ, str) else (typ if isinstance(typ, list) else [])
        if any("product" in t.lower() for t in types):
            return block
        # @graph container
        for item in block.get("@graph", []):
            if not isinstance(item, dict):
                continue
            t = item.get("@type", "")
            ts = [t] if isinstance(t, str) else (t if isinstance(t, list) else [])
            if any("product" in x.lower() for x in ts):
                return item
    return {}

# ── Field extractors ──────────────────────────────────────────────────────────

def extract_name(raw: dict) -> str | None:
    prod = find_schema_product(raw.get("ld_json") or [])
    if prod:
        n = prod.get("name")
        if isinstance(n, str) and n.strip():
            return n.strip()

    blobs = all_sources(raw)
    for blob in blobs:
        v = deep_get(blob, "name", "title", "productName", "product_name",
                     "displayName", "produktName", "bezeichnung")
        if isinstance(v, str) and len(v.strip()) > 1:
            return v.strip()

    return (raw.get("page_title") or "").strip() or None


def extract_brand(raw: dict) -> str | None:
    prod = find_schema_product(raw.get("ld_json") or [])
    if prod:
        b = prod.get("brand")
        if isinstance(b, str) and b.strip():
            return b.strip()
        if isinstance(b, dict):
            n = b.get("name")
            if isinstance(n, str) and n.strip():
                return n.strip()

    blobs = all_sources(raw)
    for blob in blobs:
        v = deep_get(blob, "brand", "brandName", "manufacturer", "marke",
                     "hersteller", "vendorName", "maker")
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, dict):
            n = v.get("name")
            if isinstance(n, str) and n.strip():
                return n.strip()

    return None


def extract_price(raw: dict) -> float | None:
    # 1. Schema.org offers
    prod = find_schema_product(raw.get("ld_json") or [])
    if prod:
        offers = prod.get("offers") or {}
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        if isinstance(offers, dict):
            for key in ("price", "lowPrice", "highPrice"):
                val = offers.get(key)
                if val is not None:
                    try:
                        p = float(str(val).replace(",", "."))
                        if 0.5 < p < 50_000:
                            return round(p, 2)
                    except (ValueError, TypeError):
                        pass

    # 2. Deep search across all sources
    blobs = all_sources(raw)
    for blob in blobs:
        v = deep_get(blob,
                     "price", "salePrice", "currentPrice", "regularPrice",
                     "finalPrice", "offerPrice", "preis", "verkaufspreis",
                     "listPrice", "netPrice", "grossPrice")
        if v is not None:
            raw_str = str(v).replace("\xa0", "").replace("€", "").replace("EUR", "").strip()
            # Handle "99,99" and "99.99" and "1.299,99"
            raw_str = re.sub(r"\.(?=\d{3})", "", raw_str)  # remove thousands separator
            raw_str = raw_str.replace(",", ".")
            try:
                p = float(raw_str)
                if 0.5 < p < 50_000:
                    return round(p, 2)
            except (ValueError, TypeError):
                pass

    return None


def extract_ean(raw: dict) -> str | None:
    # 1. Schema.org product identifiers
    prod = find_schema_product(raw.get("ld_json") or [])
    if prod:
        for key in ("gtin13", "gtin12", "gtin8", "gtin", "ean", "isbn", "mpn"):
            val = prod.get(key)
            if val and isinstance(val, str):
                v = val.strip()
                if v.isdigit() and len(v) >= 8:
                    return v

    blobs = all_sources(raw)
    for blob in blobs:
        v = deep_get(blob,
                     "ean", "gtin", "gtin13", "gtin12", "barcode",
                     "ean13", "EAN", "EAN-Code", "GTIN", "gtin/ean",
                     "europeanArticleNumber", "internationalArticleNumber")
        if v is not None:
            s = str(v).strip()
            if s.isdigit() and len(s) >= 8:
                return s

    return None


def extract_image_url(raw: dict) -> str | None:
    def valid_url(u) -> str | None:
        if isinstance(u, str) and u.startswith("http"):
            return u
        return None

    prod = find_schema_product(raw.get("ld_json") or [])
    if prod:
        img = prod.get("image")
        if isinstance(img, str):
            r = valid_url(img)
            if r:
                return r
        if isinstance(img, list) and img:
            first = img[0]
            r = valid_url(first)
            if r:
                return r
            if isinstance(first, dict):
                for k in ("url", "contentUrl", "src"):
                    r = valid_url(first.get(k))
                    if r:
                        return r

    blobs = all_sources(raw)
    for blob in blobs:
        v = deep_get(blob,
                     "image", "imageUrl", "image_url", "thumbnail",
                     "primaryImage", "mainImage", "coverImage",
                     "defaultImage", "productImage", "imgUrl")
        if isinstance(v, str):
            r = valid_url(v)
            if r:
                return r
        if isinstance(v, dict):
            for k in ("url", "src", "contentUrl", "originalSrc"):
                r = valid_url(v.get(k))
                if r:
                    return r
        if isinstance(v, list) and v:
            first = v[0]
            r = valid_url(first)
            if r:
                return r
            if isinstance(first, dict):
                for k in ("url", "src", "contentUrl"):
                    r = valid_url(first.get(k))
                    if r:
                        return r

    return None


def extract_category(raw: dict) -> str | None:
    prod = find_schema_product(raw.get("ld_json") or [])
    if prod:
        cat = prod.get("category")
        if isinstance(cat, str) and cat.strip():
            return cat.strip()
        if isinstance(cat, list) and cat:
            return str(cat[-1]).strip()

    # BreadcrumbList in ld+json
    for block in raw.get("ld_json") or []:
        if isinstance(block, dict) and block.get("@type") == "BreadcrumbList":
            items = block.get("itemListElement") or []
            names = []
            for item in items:
                if isinstance(item, dict):
                    n = item.get("name") or (item.get("item") or {}).get("name", "")
                    if n:
                        names.append(str(n).strip())
            if names:
                return " > ".join(names)

    blobs = all_sources(raw)
    for blob in blobs:
        v = deep_get(blob,
                     "category", "categoryName", "productCategory",
                     "categoryPath", "breadcrumb", "kategorien")
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, list) and v:
            last = v[-1]
            if isinstance(last, str):
                return last.strip()
            if isinstance(last, dict):
                n = last.get("name") or last.get("item") or last.get("title")
                if n and isinstance(n, str):
                    return n.strip()

    return None


def extract_specifications(raw: dict) -> dict | None:
    """
    Collect every available product attribute into a flat key->value dict.
    Nothing is filtered out - gather as much structured data as possible.
    """
    specs: dict = {}

    # ── From schema.org Product ────────────────────────────────────────────
    prod = find_schema_product(raw.get("ld_json") or [])
    if prod:
        # Top-level scalar fields
        skip_keys = {"@type", "@context", "@id", "image", "offers",
                     "brand", "name", "description", "url", "@graph"}
        for k, v in prod.items():
            if k in skip_keys:
                continue
            if isinstance(v, (str, int, float, bool)):
                specs[k] = v
            elif isinstance(v, dict) and "name" in v:
                specs[k] = v["name"]

        # additionalProperty array  [{name, value, unitText}]
        for prop in prod.get("additionalProperty") or []:
            if isinstance(prop, dict):
                pname = prop.get("name") or prop.get("propertyID")
                pval  = prop.get("value")
                if pval is None:
                    pval = prop.get("unitText")
                if pname and pval is not None:
                    specs[str(pname)] = pval

        # description
        desc = prod.get("description")
        if desc and isinstance(desc, str):
            specs["description"] = desc[:800]

    # ── From ld+json BreadcrumbList ────────────────────────────────────────
    for block in raw.get("ld_json") or []:
        if isinstance(block, dict) and block.get("@type") == "BreadcrumbList":
            items = block.get("itemListElement") or []
            bc = []
            for it in items:
                if isinstance(it, dict):
                    n = it.get("name") or ""
                    if n:
                        bc.append(str(n).strip())
            if bc:
                specs["breadcrumb"] = " > ".join(bc)

    # ── From next_data / hydration: look for attributes/specs containers ──
    blobs = []
    nd = raw.get("next_data")
    if nd:
        blobs.append(nd)
    for h in raw.get("hydration_data") or []:
        d = h.get("data") if isinstance(h, dict) else None
        if d:
            blobs.append(d)

    for blob in blobs:
        # Named containers
        for key in ("attributes", "specs", "specifications", "technicalDetails",
                    "properties", "productDetails", "technicalSpecs",
                    "featuresList", "details"):
            v = deep_get(blob, key)
            if isinstance(v, dict):
                for sk, sv in v.items():
                    if isinstance(sv, (str, int, float, bool)):
                        specs.setdefault(sk, sv)
            elif isinstance(v, list):
                for item in v:
                    if isinstance(item, dict):
                        sk = (item.get("name") or item.get("label")
                              or item.get("key") or item.get("attribute"))
                        sv = (item.get("value") or item.get("val")
                              or item.get("data"))
                        if sk and sv is not None:
                            specs.setdefault(str(sk), sv)

        # Generic EAN / brand / model if not already in specs
        for field in ("ean", "gtin", "brand", "model", "sku", "mpn",
                      "weight", "color", "colour", "dimensions"):
            if field not in specs:
                v = deep_get(blob, field)
                if v not in (None, "", [], {}):
                    specs[field] = v

    return specs if specs else None


# ── Reference generator ───────────────────────────────────────────────────────

def make_ref(url: str) -> str:
    return "P_SC_" + hashlib.md5(url.encode()).hexdigest()[:8].upper()


# ── Parse one raw file ────────────────────────────────────────────────────────

def parse_file(raw_path: Path, out_path: Path):
    if not raw_path.exists():
        print(f"  Not found: {raw_path.name} - skipping")
        return

    with open(raw_path, encoding="utf-8") as f:
        entries = json.load(f)

    print(f"  {raw_path.name}: {len(entries)} raw entries")

    matched = []
    skipped = 0

    for entry in entries:
        # Keep entries with errors in the output but mark them
        url = entry.get("url", "")

        product = {
            "source_reference": entry.get("source_reference"),
            "reference":        entry.get("reference") or make_ref(url),
            "retailer":         entry.get("retailer"),
            "url":              url,
            "ean":              extract_ean(entry),
            "name":             extract_name(entry),
            "brand":            extract_brand(entry),
            "category":         extract_category(entry),
            "image_url":        extract_image_url(entry),
            "price_eur":        extract_price(entry),
            "specifications":   extract_specifications(entry),
        }

        # If the page had an error, attach it for transparency
        if entry.get("error"):
            product["_scrape_error"] = entry["error"]
            skipped += 1

        matched.append(product)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(matched, f, ensure_ascii=False, indent=2)

    ok = len(matched) - skipped
    print(f"  -> {out_path.name}: {len(matched)} entries ({ok} ok, {skipped} with errors)")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    print(f"Output dir: {OUTPUT_DIR}\n")
    for raw_fname, matched_fname in RAW_TO_MATCHED:
        raw_path     = OUTPUT_DIR / raw_fname
        matched_path = OUTPUT_DIR / matched_fname
        print(f"Parsing {raw_fname} -> {matched_fname}")
        parse_file(raw_path, matched_path)
        print()
    print("Done.")


if __name__ == "__main__":
    main()
