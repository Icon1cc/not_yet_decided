"""
merge_brave_to_matched.py
=========================
Build larger matched files for Cloudflare-blocked retailers from Brave search output.

Input:
  - One or more scraper_brave.py output files (array of source objects)

Output:
  - ../output/matched_cyberport.json
  - ../output/matched_electronic4you.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT_DIR = (HERE / "../output").resolve()

TARGET_RETAILERS = ("Cyberport AT", "electronic4you.at")

_RETAILER_SUFFIX = re.compile(
    r"\s*[|\-]\s*(electronic4you(?:\.at)?|cyberport(?:\.at)?).*$",
    re.IGNORECASE,
)
_URL_HTML_EXT = re.compile(r"\.(?:html?|php)$", re.IGNORECASE)
_URL_TRAILING_ID = re.compile(r"-\d{5,7}(?:-l\d+)?$", re.IGNORECASE)


def resolve(path_str: str) -> Path:
    p = Path(path_str)
    return p if p.is_absolute() else (HERE / p).resolve()


def make_ref(url: str) -> str:
    return "P_SC_" + hashlib.md5(url.encode()).hexdigest()[:8].upper()


def clean_name(text: str | None) -> str | None:
    if not isinstance(text, str):
        return None
    out = _RETAILER_SUFFIX.sub("", text).strip(" -|\t")
    out = re.sub(r"\s+", " ", out).strip()
    return out or None


def url_slug_name(url: str | None) -> str | None:
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
    slug = _URL_HTML_EXT.sub("", last)
    slug = _URL_TRAILING_ID.sub("", slug)
    slug = slug.replace("_", "-")
    slug = re.sub(r"[^A-Za-z0-9\-]+", " ", slug)
    slug = re.sub(r"-+", " ", slug)
    slug = re.sub(r"\s+", " ", slug).strip()
    return slug or None


def first_brand(*texts: str | None) -> str | None:
    for text in texts:
        if not isinstance(text, str) or not text.strip():
            continue
        tok = re.split(r"\s+", text.strip())[0]
        tok = re.sub(r"[^A-Za-z0-9&+.\-]", "", tok)
        if len(tok) >= 2 and re.search(r"[A-Za-z]", tok):
            return tok
    return None


def valid_ean(value) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    if s.isdigit() and len(s) >= 8:
        return s
    return None


def infer_category(url: str | None) -> str | None:
    if not isinstance(url, str) or not url.strip():
        return None
    try:
        parts = [p for p in urllib.parse.urlparse(url).path.split("/") if p]
    except ValueError:
        return None
    if len(parts) < 2:
        return None
    keep = []
    for p in parts[:-1]:
        if p in {"pdp", "shop", "produkt", "de"}:
            continue
        if re.match(r"^[a-z0-9]{2,5}-\d{2,4}$", p, re.IGNORECASE):
            continue
        keep.append(p.replace("-", " ").strip())
    if not keep:
        return None
    return " > ".join(keep)


def source_entries(scraped_paths: list[Path]) -> list[dict]:
    all_items: list[dict] = []
    for p in scraped_paths:
        if not p.exists():
            print(f"  Not found, skipping: {p}")
            continue
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            all_items.extend(data)
        print(f"  Loaded {p.name}: {len(data) if isinstance(data, list) else 0}")
    return all_items


def to_match_records(items: list[dict]) -> dict[str, list[dict]]:
    by_retailer: dict[str, list[dict]] = {r: [] for r in TARGET_RETAILERS}
    seen: set[tuple[str, str]] = set()

    for src in items:
        src_ref = src.get("source_reference")
        src_name = src.get("source_name")
        query_ean = valid_ean(src.get("query_ean"))
        query_model = src.get("query_model")
        if not src_ref:
            continue

        for hit in src.get("scraped", []) or []:
            retailer = hit.get("retailer")
            if retailer not in by_retailer:
                continue

            url = hit.get("url")
            if not isinstance(url, str) or not url.strip():
                continue

            dedupe_key = (str(src_ref), url)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)

            name = clean_name(hit.get("name")) or url_slug_name(url)
            brand = first_brand(name, src_name)
            ean = valid_ean(hit.get("ean")) or query_ean

            specs = {}
            desc = hit.get("description")
            if isinstance(desc, str) and desc.strip():
                specs["_search_description"] = desc.strip()[:600]
            if isinstance(query_model, str) and query_model.strip():
                specs["query_model"] = query_model.strip()
            if query_ean:
                specs["query_ean"] = query_ean
            slug_name = url_slug_name(url)
            if slug_name:
                specs["_url_slug_name"] = slug_name

            if not name and not brand and not ean:
                continue

            record = {
                "source_reference": src_ref,
                "reference": hit.get("reference") or make_ref(url),
                "retailer": retailer,
                "url": url,
                "ean": ean,
                "name": name,
                "brand": brand,
                "category": infer_category(url),
                "image_url": hit.get("image_url"),
                "price_eur": hit.get("price_eur"),
                "specifications": specs or None,
            }
            by_retailer[retailer].append(record)

    for retailer in by_retailer:
        by_retailer[retailer].sort(
            key=lambda x: (
                x.get("source_reference") or "",
                x.get("retailer") or "",
                x.get("name") or "",
                x.get("url") or "",
            )
        )
    return by_retailer


def write_outputs(by_retailer: dict[str, list[dict]]):
    out_map = {
        "Cyberport AT": OUT_DIR / "matched_cyberport.json",
        "electronic4you.at": OUT_DIR / "matched_electronic4you.json",
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for retailer, out_path in out_map.items():
        rows = by_retailer.get(retailer, [])
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=2)
        print(f"  Wrote {out_path.name}: {len(rows)} rows")


def main():
    ap = argparse.ArgumentParser(description="Build matched_* from scraper_brave outputs")
    ap.add_argument(
        "--scraped",
        nargs="+",
        required=True,
        help="One or more scraper_brave.py output files",
    )
    args = ap.parse_args()

    scraped_paths = [resolve(p) for p in args.scraped]
    print("Loading scraped files:")
    items = source_entries(scraped_paths)
    print(f"Total source entries loaded: {len(items)}")

    by_retailer = to_match_records(items)
    write_outputs(by_retailer)
    print("Done.")


if __name__ == "__main__":
    main()
