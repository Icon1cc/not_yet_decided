"""
match_targets.py — Match source products to visible retailer target pool
========================================================================
Visible retailers: Amazon AT, MediaMarkt AT

The original matcher mixed raw GTIN/model equality with weak fallback heuristics,
which caused obvious false positives on this dataset:
  - Samsung F6000 TVs matching across different screen sizes
  - Siemens iQ300 product-line matches across different appliance types
  - Dirty duplicated GTIN rows in the target pool matching unrelated products

This version uses a shared deterministic scorer with explicit brand/type/size
sanity checks and dedupes same-listing duplicates by canonical URL/identifier.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from matching_utils import (
    canonical_listing_key,
    extract_product_signals,
    score_product_match,
)

HERE = Path(__file__).resolve().parent
DEFAULT_THRESHOLD = 0.80
MAX_PER_RETAILER = 5
_ALWAYS_KEEP = {"direct_ref", "gtin", "asin", "model"}


def resolve(path_str: str) -> Path:
    path = Path(path_str)
    if path.is_absolute():
        return path
    if path.exists():
        return path.resolve()
    return (HERE / path).resolve()


def _score_pool(
    source: dict,
    pool: list[dict],
    pool_signals: list,
    threshold: float,
) -> list[tuple[float, str, tuple[str, ...], dict]]:
    source_signals = extract_product_signals(source)
    scored: list[tuple[float, str, tuple[str, ...], dict]] = []

    for target, target_signals in zip(pool, pool_signals):
        if target["reference"] == source["reference"]:
            scored.append((1.0, "direct_ref", ("same_reference",), target))
            continue

        result = score_product_match(
            source,
            target,
            source_signals=source_signals,
            target_signals=target_signals,
            threshold=threshold,
        )
        if result.matched:
            scored.append((result.score, result.method, result.reasons, target))

    scored.sort(key=lambda item: (-item[0], item[3].get("retailer") or "", item[3].get("name") or ""))
    return scored


def _dedupe_matches(matches: list[tuple[float, str, tuple[str, ...], dict]]) -> list[tuple[float, str, tuple[str, ...], dict]]:
    best_by_listing: dict[str, tuple[float, str, tuple[str, ...], dict]] = {}
    for score, method, reasons, product in matches:
        key = canonical_listing_key(product)
        current = best_by_listing.get(key)
        if current is None or score > current[0]:
            best_by_listing[key] = (score, method, reasons, product)
    return sorted(
        best_by_listing.values(),
        key=lambda item: (-item[0], item[3].get("retailer") or "", item[3].get("name") or ""),
    )


def cap_by_retailer(matches: list[tuple[float, str, tuple[str, ...], dict]]) -> list[tuple[float, str, tuple[str, ...], dict]]:
    counts = defaultdict(int)
    kept: list[tuple[float, str, tuple[str, ...], dict]] = []

    for score, method, reasons, product in matches:
        retailer = product.get("retailer", "")
        if method in _ALWAYS_KEEP or counts[retailer] < MAX_PER_RETAILER:
            kept.append((score, method, reasons, product))
            if method not in _ALWAYS_KEEP:
                counts[retailer] += 1

    return kept


def match_all(source_path: Path, pool_path: Path, output_path: Path, threshold: float = DEFAULT_THRESHOLD):
    with open(source_path, encoding="utf-8") as f:
        sources = json.load(f)
    with open(pool_path, encoding="utf-8") as f:
        pool = json.load(f)

    print(f"📦  {len(sources)} source products")
    print(f"🎯  {len(pool)} target pool products")
    print(f"    Threshold={threshold:.2f}  MaxPerRetailer={MAX_PER_RETAILER}")
    print()

    pool_signals = [extract_product_signals(product) for product in pool]
    results = []
    method_counts = defaultdict(int)
    total = 0

    for source in sources:
        raw_matches = _score_pool(source, pool, pool_signals, threshold)
        matches = cap_by_retailer(_dedupe_matches(raw_matches))

        competitors = []
        for score, method, reasons, target in matches:
            competitors.append(
                {
                    "reference": target["reference"],
                    "competitor_retailer": target.get("retailer", ""),
                    "competitor_product_name": target.get("name", ""),
                    "competitor_url": target.get("url", ""),
                    "competitor_price": target.get("price_eur"),
                    "_match_score": round(score, 3),
                    "_match_method": method,
                    "_match_reasons": list(reasons),
                }
            )
            method_counts[method] += 1

        total += len(competitors)
        results.append(
            {
                "source_reference": source["reference"],
                "source_name": source.get("name", "")[:80],
                "competitors": competitors,
            }
        )

        top = matches[0] if matches else None
        if top:
            score, method, reasons, target = top
            why = ",".join(reasons[:2]) if reasons else method
            top_str = f"{method} {score:.2f} ({why}) → {target.get('name', '')[:48]}"
        else:
            top_str = "NO MATCH"
        low = " ⚠️  LOW" if top and top[0] < 0.8 else ""
        print(f"  [{source['reference']}] {source.get('name', '')[:45]:45s} | {top_str}{low}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n✅  Written → {output_path}")
    print(f"    Source products : {len(sources)}")
    print(f"    Total matches   : {total}")
    print("    Methods:")
    for method, count in sorted(method_counts.items(), key=lambda item: (-item[1], item[0])):
        print(f"      {method:25s} {count:>5}")

    no_match = [row for row in results if not row["competitors"]]
    if no_match:
        print(f"\n    ⚠️  {len(no_match)} unmatched:")
        for row in no_match:
            print(f"      {row['source_reference']} {row['source_name'][:65]}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--pool", required=True)
    parser.add_argument("--output", default="matches.json")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    args = parser.parse_args()

    match_all(resolve(args.source), resolve(args.pool), resolve(args.output), args.threshold)
