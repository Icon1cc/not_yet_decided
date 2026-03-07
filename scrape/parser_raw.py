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
import urllib.parse
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


# ── Fallback helpers for Cloudflare/403 pages ─────────────────────────────────

_RETAILER_SUFFIX = re.compile(
    r"\s*[|\-]\s*(electronic4you|mediamarkt|expert\.at|cyberport|e-tec|amazon).*$",
    re.IGNORECASE,
)
_BLOCKED_TITLE = re.compile(
    r"access denied|attention required|forbidden|just a moment|cloudflare|captcha|verify",
    re.IGNORECASE,
)
_URL_HTML_EXT = re.compile(r"\.(?:html?|php)$", re.IGNORECASE)
_URL_TRAILING_ID = re.compile(r"-\d{5,7}(?:-l\d+)?$", re.IGNORECASE)
_URL_EXPERT_ID = re.compile(r"~p\d+$", re.IGNORECASE)
_PRICE_FROM_TEXT = [
    re.compile(r"(\d{1,3}(?:\.\d{3})+,\d{2})\s*[€EUR]", re.IGNORECASE),
    re.compile(r"(\d{1,4},\d{2})\s*[€EUR]", re.IGNORECASE),
    re.compile(r"[€EUR]\s*(\d{1,4}(?:[.,]\d{1,2})?)", re.IGNORECASE),
]


def search_blob(raw: dict) -> dict:
    val = raw.get("search_result")
    return val if isinstance(val, dict) else {}


def clean_title(text: str | None) -> str | None:
    if not isinstance(text, str):
        return None
    out = _RETAILER_SUFFIX.sub("", text).strip(" -|\t")
    if not out or _BLOCKED_TITLE.search(out):
        return None
    return out


def coerce_price(value) -> float | None:
    if value is None:
        return None
    raw_str = str(value).replace("\xa0", "").replace("€", "").replace("EUR", "").strip()
    raw_str = re.sub(r"\.(?=\d{3})", "", raw_str)
    raw_str = raw_str.replace(",", ".")
    try:
        p = float(raw_str)
        if 0.5 < p < 50_000:
            return round(p, 2)
    except (ValueError, TypeError):
        return None
    return None


def price_from_text(text: str | None) -> float | None:
    if not isinstance(text, str) or not text.strip():
        return None
    for pat in _PRICE_FROM_TEXT:
        m = pat.search(text)
        if not m:
            continue
        p = coerce_price(m.group(1))
        if p is not None:
            return p
    return None


def first_brand_token(text: str | None) -> str | None:
    if not isinstance(text, str) or not text.strip():
        return None
    tok = re.split(r"\s+", text.strip())[0]
    tok = re.sub(r"[^A-Za-z0-9&+.\-]", "", tok)
    if len(tok) < 2 or not re.search(r"[A-Za-z]", tok):
        return None
    if tok.lower() in {"www", "http", "https", "de", "at"}:
        return None
    return tok


def source_brand(raw: dict) -> str | None:
    b = raw.get("source_brand")
    if isinstance(b, str) and b.strip():
        return b.strip()
    return first_brand_token(raw.get("source_name"))


def name_from_url(url: str) -> str | None:
    if not isinstance(url, str) or not url.strip():
        return None
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return None

    parts = [p for p in parsed.path.split("/") if p]
    if not parts:
        return None

    last = urllib.parse.unquote(parts[-1]).strip()
    if not last:
        return None

    # e-tec details.php links encode only an article number in query params.
    if last.lower().startswith("details.php"):
        params = urllib.parse.parse_qs(parsed.query)
        art = (params.get("artnr") or params.get("art") or [None])[0]
        if isinstance(art, str):
            art = art.strip().strip("+").strip()
            if art:
                return f"product {art}"
        return None

    slug = _URL_HTML_EXT.sub("", last)
    slug = _URL_EXPERT_ID.sub("", slug)
    slug = _URL_TRAILING_ID.sub("", slug)
    slug = slug.replace("_", "-")
    slug = re.sub(r"[^A-Za-z0-9\-]+", " ", slug)
    slug = re.sub(r"-+", " ", slug)
    slug = re.sub(r"\s+", " ", slug).strip()
    if len(slug) < 3:
        return None
    return slug

# ── ld+json normaliser ────────────────────────────────────────────────────────

def flatten_ld(blocks) -> list:
    """
    Flatten arbitrarily nested ld+json arrays into a flat list of dicts.
    expert.at wraps all schemas in a single JSON array inside one <script> tag,
    producing [[{WebSite},{Product},{BreadcrumbList}]] instead of [{...},{...}].
    """
    out = []
    if isinstance(blocks, list):
        for item in blocks:
            out.extend(flatten_ld(item))
    elif isinstance(blocks, dict):
        out.append(blocks)
    return out


# ── Schema.org Product finder ─────────────────────────────────────────────────

def find_schema_product(ld_jsons: list) -> dict:
    """Find the most specific schema.org Product block in ld+json."""
    for block in flatten_ld(ld_jsons):
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

    page_title = clean_title(raw.get("page_title"))
    if page_title:
        return page_title

    search_title = clean_title(search_blob(raw).get("title"))
    if search_title:
        return search_title

    return name_from_url(raw.get("url", ""))


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

    for candidate in (
        source_brand(raw),
        first_brand_token(clean_title(search_blob(raw).get("title"))),
        first_brand_token(name_from_url(raw.get("url", ""))),
    ):
        if candidate:
            return candidate

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
                    p = coerce_price(val)
                    if p is not None:
                        return p

    # 2. Deep search across all sources
    blobs = all_sources(raw)
    for blob in blobs:
        v = deep_get(blob,
                     "price", "salePrice", "currentPrice", "regularPrice",
                     "finalPrice", "offerPrice", "preis", "verkaufspreis",
                     "listPrice", "netPrice", "grossPrice")
        if v is not None:
            p = coerce_price(v)
            if p is not None:
                return p

    # 3. Search snippets fallback (works even when page itself is blocked)
    search = search_blob(raw)
    search_text = [search.get("description"), search.get("title")]
    search_text.extend(search.get("extra_snippets") or [])
    for text in search_text:
        p = price_from_text(text)
        if p is not None:
            return p

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

    # 3. Search result thumbnail fallback
    search = search_blob(raw)
    for key in ("thumbnail", "image", "image_url"):
        r = valid_url(search.get(key))
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
    for block in flatten_ld(raw.get("ld_json") or []):
        if block.get("@type") == "BreadcrumbList":
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

    # URL path fallback for retailer category-like segments
    url = raw.get("url", "")
    try:
        parts = [p for p in urllib.parse.urlparse(url).path.split("/") if p]
    except ValueError:
        parts = []
    if len(parts) >= 2:
        # Ignore trailing product slug and internal route markers.
        candidates = [p for p in parts[:-1] if p not in {"pdp", "shop", "produkt"}]
        if candidates:
            return " > ".join(p.replace("-", " ").strip() for p in candidates[:3])

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
    for block in flatten_ld(raw.get("ld_json") or []):
        if block.get("@type") == "BreadcrumbList":
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

    # ── Fallback metadata from search/source/url ──────────────────────────
    search = search_blob(raw)
    if search:
        if search.get("query"):
            specs.setdefault("_search_query", search["query"])
        if search.get("rank") is not None:
            specs.setdefault("_search_rank", search["rank"])
        if search.get("description"):
            specs.setdefault("_search_description", str(search["description"])[:500])
        snippets = search.get("extra_snippets") or []
        if snippets:
            joined = " | ".join(str(s) for s in snippets if s)
            if joined:
                specs.setdefault("_search_snippets", joined[:700])

    for field in ("source_brand", "source_ean", "source_model"):
        value = raw.get(field)
        if value not in (None, "", [], {}):
            specs.setdefault(field, value)

    url_name = name_from_url(raw.get("url", ""))
    if url_name:
        specs.setdefault("_url_slug_name", url_name)

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
    dropped_errors = 0
    dropped_empty = 0

    for entry in entries:
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

        if entry.get("error"):
            dropped_errors += 1
            continue

        has_useful_data = any([
            product["ean"],
            product["name"],
            product["brand"],
            product["image_url"],
            product["specifications"],
            product["price_eur"] is not None,
        ])
        if not has_useful_data:
            dropped_empty += 1
            continue

        matched.append(product)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(matched, f, ensure_ascii=False, indent=2)

    dropped_total = dropped_errors + dropped_empty
    print(
        f"  -> {out_path.name}: {len(matched)} kept, "
        f"{dropped_total} dropped ({dropped_errors} errors, {dropped_empty} empty)"
    )


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
