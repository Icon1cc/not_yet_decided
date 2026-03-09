"""
Evaluate a submission JSON against ground-truth.

Usage:
  # Auto-build pseudo GT from EAN matching (source vs target pool)
  uv run python eval.py --submission output/run.json --source data/source_products_tv_&_audio.json

  # With server GT JSON
  uv run python eval.py --submission output/run.json --gt data/gt.json --source data/source_products_tv_&_audio.json

  # Stats only, no GT
  uv run python eval.py --submission output/run.json --source data/source_products_small_appliances.json --no-gt
"""
import argparse
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

DATA_DIR = Path("data")

SOURCE_FILES = {
    "tv_audio": DATA_DIR / "source_products_tv_&_audio.json",
    "small_appliances": DATA_DIR / "source_products_small_appliances.json",
    "large_appliances": DATA_DIR / "source_products_large_appliances.json",
}
TARGET_FILES = {
    "tv_audio": DATA_DIR / "target_pool_tv_&_audio.json",
    "small_appliances": DATA_DIR / "target_pool_small_appliances.json",
    "large_appliances": DATA_DIR / "target_pool_large_appliances.json",
}


def load_json(path: str | Path) -> list | dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def detect_category(source_path: str) -> str | None:
    stem = Path(source_path).stem.lower()
    for key in SOURCE_FILES:
        if key in stem:
            return key
    return None


def build_index(products: list[dict]) -> dict[str, dict]:
    return {p["reference"]: p for p in products}


def _eans(p: dict) -> set[str]:
    eans = set()
    if p.get("ean"):
        eans.add(str(p["ean"]).strip())
    specs = p.get("specifications") or {}
    for k in ("GTIN", "EAN", "EAN-Code", "Hersteller Artikelnummer",
               "Hersteller Modellnummer", "Modellnummer", "Herstellernummer"):
        if specs.get(k):
            eans.add(str(specs[k]).strip())
    return eans


def build_pseudo_gt(sources: list[dict], targets: list[dict]) -> dict[str, set[str]]:
    """EAN-based pseudo GT: source_ref -> set of target refs with matching EAN."""
    tgt_ean_map: dict[str, list[str]] = {}
    for t in targets:
        for e in _eans(t):
            tgt_ean_map.setdefault(e, []).append(t["reference"])

    gt: dict[str, set[str]] = {}
    for s in sources:
        ref = s["reference"]
        matched = set()
        for e in _eans(s):
            for tref in tgt_ean_map.get(e, []):
                if tref != ref:  # exclude self
                    matched.add(tref)
        gt[ref] = matched
    return gt


def sep(char="─", width=72):
    print(char * width)


def eval_with_gt(
    submission: list[dict],
    gt: dict[str, set[str]],
    src_index: dict[str, dict],
    tgt_index: dict[str, dict],
    gt_label: str = "GT",
) -> None:
    sub_map: dict[str, set[str]] = {
        e["source_reference"]: {c["reference"] for c in e.get("competitors", [])}
        for e in submission
    }

    sources_in_gt = {ref for ref, refs in gt.items() if refs}
    all_sources = sorted(set(gt) | set(sub_map))

    total_gt = sum(len(v) for v in gt.values())
    total_sub = sum(len(v) for v in sub_map.values())
    tp_total = fn_total = fp_total = 0
    covered = 0

    sep("=")
    print(f"PER-SOURCE BREAKDOWN  [{gt_label}]")
    sep("=")

    for src_ref in all_sources:
        gt_refs = gt.get(src_ref, set())
        sub_refs = sub_map.get(src_ref, set())
        tp = gt_refs & sub_refs
        fn = gt_refs - sub_refs
        fp = sub_refs - gt_refs

        tp_total += len(tp)
        fn_total += len(fn)
        fp_total += len(fp)
        if tp:
            covered += 1

        src_name = (src_index.get(src_ref, {}).get("name") or "")[:62]
        gt_tag = f"GT={len(gt_refs)}" if gt_refs else "NO_GT"
        print(f"\n{src_ref} | {gt_tag} sub={len(sub_refs)} TP={len(tp)} FP={len(fp)} FN={len(fn)} | {src_name}")

        for ref in sorted(tp):
            name = (tgt_index.get(ref, {}).get("name") or "")[:60]
            retailer = tgt_index.get(ref, {}).get("retailer") or "?"
            print(f"  [TP] {ref} | {retailer:14s} | {name}")
        for ref in sorted(fp):
            name = (tgt_index.get(ref, {}).get("name") or "")[:60]
            retailer = tgt_index.get(ref, {}).get("retailer") or "?"
            print(f"  [FP] {ref} | {retailer:14s} | {name}")
        for ref in sorted(fn):
            name = (tgt_index.get(ref, {}).get("name") or "")[:60]
            retailer = tgt_index.get(ref, {}).get("retailer") or "?"
            print(f"  [FN] {ref} | {retailer:14s} | {name}")

    prec = tp_total / total_sub if total_sub else 0
    rec = tp_total / total_gt if total_gt else 0
    cov = covered / len(sources_in_gt) if sources_in_gt else 0

    sep("=")
    print("AGGREGATE  (pseudo-GT covers only EAN-matched sources)")
    sep()
    print(f"  Sources with GT       : {len(sources_in_gt)}/{len(all_sources)}")
    print(f"  Total GT links        : {total_gt}")
    print(f"  Total submitted       : {total_sub}")
    print(f"  True positives        : {tp_total}")
    print(f"  False positives       : {fp_total}")
    print(f"  False negatives       : {fn_total}")
    print(f"  Precision             : {prec:.1%}  ({tp_total}/{total_sub})")
    print(f"  Recall                : {rec:.1%}  ({tp_total}/{total_gt})")
    print(f"  Coverage              : {cov:.1%}  ({covered}/{len(sources_in_gt)} GT sources with ≥1 TP)")
    sep()
    # FP breakdown by retailer
    from collections import Counter
    fp_retailers: Counter = Counter()
    for e in submission:
        src_ref = e["source_reference"]
        gt_refs = gt.get(src_ref, set())
        for c in e.get("competitors", []):
            if c["reference"] not in gt_refs:
                fp_retailers[c.get("competitor_retailer") or "?"] += 1
    print("  FP by retailer:")
    for retailer, count in fp_retailers.most_common():
        print(f"    {retailer:20s}: {count}")


def eval_stats_only(
    submission: list[dict],
    src_index: dict[str, dict],
    tgt_index: dict[str, dict],
) -> None:
    sep("=")
    print("SUBMISSION STATS (no ground truth)")
    sep("=")

    total_links = 0
    for entry in submission:
        src_ref = entry["source_reference"]
        competitors = entry.get("competitors", [])
        n = len(competitors)
        total_links += n
        src_name = (src_index.get(src_ref, {}).get("name") or "")[:55]
        flag = "  <<< 0" if n == 0 else ("  <<< many" if n > 10 else "")
        print(f"\n  {src_ref} | {n:3d} matches | {src_name}{flag}")
        for c in competitors:
            ref = c["reference"]
            name = (tgt_index.get(ref, {}).get("name") or c.get("competitor_product_name") or "")[:55]
            retailer = c.get("competitor_retailer") or tgt_index.get(ref, {}).get("retailer") or "?"
            print(f"    -> {ref} | {retailer:14s} | {name}")

    sep()
    print(f"  Total sources : {len(submission)}")
    print(f"  Total links   : {total_links}")
    if submission:
        zeros = sum(1 for e in submission if not e.get("competitors"))
        print(f"  Avg per source: {total_links/len(submission):.1f}  |  sources with 0: {zeros}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--submission", required=True)
    parser.add_argument("--source", help="Source products JSON (auto-detected if omitted)")
    parser.add_argument("--target", help="Target pool JSON (auto-detected from source)")
    parser.add_argument("--gt", help="Server GT JSON (same format as submission)")
    parser.add_argument("--no-gt", action="store_true", help="Skip GT building, stats only")
    args = parser.parse_args()

    submission = load_json(args.submission)
    print(f"Submission  : {args.submission}  ({len(submission)} entries)")

    # Detect source file
    source_path = args.source
    if not source_path:
        stem = Path(args.submission).stem.lower()
        for key, path in SOURCE_FILES.items():
            if any(w in stem for w in key.split("_")):
                source_path = str(path)
                break
    if not source_path:
        raise ValueError("Cannot auto-detect source. Pass --source.")

    category = detect_category(source_path)
    target_path = args.target or (str(TARGET_FILES[category]) if category else None)

    sources = load_json(source_path)
    src_index = build_index(sources)
    print(f"Source      : {source_path}  ({len(sources)} products)")

    tgt_index = {}
    targets = []
    if target_path and Path(target_path).exists():
        targets = load_json(target_path)
        tgt_index = build_index(targets)
        print(f"Target pool : {target_path}  ({len(targets)} products)")

    if args.no_gt:
        eval_stats_only(submission, src_index, tgt_index)
        return

    if args.gt:
        raw_gt = load_json(args.gt)
        gt = {e["source_reference"]: {c["reference"] for c in e.get("competitors", [])} for e in raw_gt}
        print(f"GT          : {args.gt}  ({len(gt)} entries)")
        eval_with_gt(submission, gt, src_index, tgt_index, gt_label="server GT")
    elif targets:
        print("Building pseudo-GT from EAN matching...")
        gt = build_pseudo_gt(sources, targets)
        n_covered = sum(1 for v in gt.values() if v)
        print(f"Pseudo-GT   : {n_covered}/{len(sources)} sources have EAN matches")
        eval_with_gt(submission, gt, src_index, tgt_index, gt_label="pseudo EAN GT")
    else:
        eval_stats_only(submission, src_index, tgt_index)


if __name__ == "__main__":
    main()
