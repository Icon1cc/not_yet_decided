"""
run_all_categories_brave.py
===========================
End-to-end pipeline for all source categories:
1) Auto-discover data/source_products_*.json
2) Scrape each category with scraper_brave.py outputting raw files
3) Convert all raw files into matched_cyberport.json + matched_electronic4you.json
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import merge_brave_to_matched as merger
import scraper_brave as brave

HERE = Path(__file__).resolve().parent
DATA_DIR = (HERE / "../data").resolve()
OUT_DIR = (HERE / "../output").resolve()


def category_from_filename(path: Path) -> str:
    name = path.stem
    # source_products_tv_&_audio -> tv_audio
    cat = re.sub(r"^source_products_", "", name)
    cat = cat.replace("&", "and")
    cat = re.sub(r"[^a-zA-Z0-9]+", "_", cat).strip("_").lower()
    return cat or "unknown"


def load_sources(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def run(scrape_limit: int | None = None):
    source_files = sorted(DATA_DIR.glob("source_products_*.json"))
    if not source_files:
        raise SystemExit(f"No source_products_*.json files found in {DATA_DIR}")

    print("Source files discovered:")
    for sf in source_files:
        print(f"  - {sf.name}")

    api_key = brave.load_api_key()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    raw_paths: list[Path] = []
    for sf in source_files:
        category = category_from_filename(sf)
        out_path = OUT_DIR / f"raw_brave_{category}.json"
        sources = load_sources(sf)
        if scrape_limit is not None:
            sources = sources[:scrape_limit]
        print(
            f"\n[{category}] scraping {len(sources)} source products "
            f"-> {out_path.name}"
        )
        brave.scrape_all(sources, out_path, api_key)
        raw_paths.append(out_path)

    print("\nConverting raw files to matched outputs...")
    items = merger.source_entries(raw_paths)
    by_retailer = merger.to_match_records(items)
    merger.write_outputs(by_retailer)
    print("Done.")


def main():
    ap = argparse.ArgumentParser(description="Run Brave scrape+merge for all categories")
    ap.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional limit of source products per category (for quick tests)",
    )
    args = ap.parse_args()
    run(scrape_limit=args.limit)


if __name__ == "__main__":
    main()
