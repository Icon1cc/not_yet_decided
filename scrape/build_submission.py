"""
build_submission.py — Merge visible-retailer matches + scraped results
=======================================================================
Combines output from match_targets.py and scraper_brave.py into one
submission JSON with correct format for scoring.

Output format (per source product):
  {
    "source_reference": "P_XXXXXXXX",
    "competitors": [
      {
        "reference":               "P_YYYYYYYY",     ← real pool ID  (visible retailers)
        "competitor_retailer":     "Amazon AT",
        "competitor_product_name": "...",
        "competitor_url":          "https://...",
        "competitor_price":        499.99
      },
      {
        "reference":               "P_SC_ZZZZZZZZ",  ← hash (hidden/scraped retailers)
        "competitor_retailer":     "Expert AT",
        "competitor_product_name": "...",
        "competitor_url":          "https://...",
        "competitor_price":        null
      }
    ]
  }

Scoring:
  Visible retailers → scored on source_reference + reference (target pool ID)
  Hidden retailers  → scored on source_reference + competitor_url

FIXED BUGS vs previous version:
  - E-Tec URL validator updated to match artnr= 123, artnr=+123, artnr= +123
    (21 valid E-Tec product pages were being excluded due to space/+ in artnr)
  - _match_score / _match_method internal keys stripped from final output

Usage (run from inside scrape/):
  python3 build_submission.py \\
      --matches "../output/matches_tv_audio.json" "../output/matches_small_appliances.json" \\
      --scraped "../output/scraped_tv_audio.json" "../output/scraped_small_appliances.json" \\
      --output  "../output/competitor_matches.json"
"""

import re, json, argparse, hashlib
from pathlib import Path
from collections import Counter

HERE = Path(__file__).resolve().parent

# ── Price cleaner ─────────────────────────────────────────────────────────────

def clean_price(raw):
    if raw is None:
        return None
    try:
        p = round(float(raw), 2)
        return p if 10 < p < 50_000 else None
    except (TypeError, ValueError):
        return None


# ── E-Tec URL patterns (FIXED: now handles artnr=+NNN and artnr= NNN) ────────

_ETEC_PATTERNS = [
    re.compile(r'/shop/produkt/\d+/'),
    re.compile(r'details\.php\?artnr=[\s+]*\d'),   # ← space/+ allowed before digits
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


# ── Internal key stripper ─────────────────────────────────────────────────────

def strip_internal_keys(comp: dict) -> dict:
    """Remove _match_score and _match_method from final output."""
    return {k: v for k, v in comp.items() if not k.startswith('_')}


# ── Main builder ──────────────────────────────────────────────────────────────

def build(matches_paths: list, scraped_paths: list, output_path: Path):
    # Load visible-retailer matches
    matches_by_ref = {}
    for path in matches_paths:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for entry in data:
            ref = entry["source_reference"]
            if ref not in matches_by_ref:
                matches_by_ref[ref] = []
            matches_by_ref[ref].extend(entry.get("competitors", []))
        print(f"  Loaded matches : {path.name}  ({len(data)} products)")

    # Load scraped results
    scraped_by_ref = {}
    for path in scraped_paths:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for entry in data:
            ref = entry["source_reference"]
            if ref not in scraped_by_ref:
                scraped_by_ref[ref] = []
            scraped_by_ref[ref].extend(entry.get("scraped", []))
        print(f"  Loaded scraped : {path.name}  ({len(data)} products)")

    all_refs = sorted(set(list(matches_by_ref) + list(scraped_by_ref)))
    submission  = []
    total_vis   = 0
    total_hid   = 0
    skipped     = 0
    retailer_counts = Counter()

    for src_ref in all_refs:
        seen_urls = set()
        seen_refs = set()
        competitors = []

        # ── Visible retailer matches (scored by reference) ────────────────────
        for c in matches_by_ref.get(src_ref, []):
            ref = c.get("reference", "")
            url = (c.get("competitor_url") or "").strip()
            if not ref or ref in seen_refs:
                continue
            seen_refs.add(ref)
            if url:
                seen_urls.add(url)
            competitors.append(strip_internal_keys({
                "reference":               ref,
                "competitor_retailer":     c.get("competitor_retailer", ""),
                "competitor_product_name": c.get("competitor_product_name", ""),
                "competitor_url":          url,
                "competitor_price":        clean_price(c.get("competitor_price")),
            }))
            retailer_counts[c.get("competitor_retailer", "")] += 1
            total_vis += 1

        # ── Hidden retailer scrapes (scored by URL) ───────────────────────────
        for item in scraped_by_ref.get(src_ref, []):
            url      = (item.get("url") or "").strip()
            retailer = item.get("retailer", "")

            if not url or not url.startswith("http"):
                skipped += 1
                continue
            if not is_product_url(url, retailer):
                skipped += 1
                continue
            if url in seen_urls:
                continue
            seen_urls.add(url)

            competitors.append({
                "reference":               item.get("reference") or
                                           "P_SC_" + hashlib.md5(url.encode()).hexdigest()[:8].upper(),
                "competitor_retailer":     retailer,
                "competitor_product_name": item.get("name", ""),
                "competitor_url":          url,
                "competitor_price":        clean_price(item.get("price_eur")),
            })
            retailer_counts[retailer] += 1
            total_hid += 1

        submission.append({
            "source_reference": src_ref,
            "competitors":      competitors,
        })

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(submission, f, ensure_ascii=False, indent=2)

    print(f"\n✅  Written → {output_path}")
    print(f"\n    Source products       : {len(submission)}")
    print(f"    Total competitors     : {total_vis + total_hid}")
    print(f"      Visible (matching)  : {total_vis}")
    print(f"      Hidden (scraped)    : {total_hid}")
    print(f"    Skipped (invalid URL) : {skipped}")
    print(f"\n    Competitors per retailer:")
    for ret, cnt in sorted(retailer_counts.items(), key=lambda x: -x[1]):
        print(f"      {ret:28s} {cnt:>5}")

    empty = [e["source_reference"] for e in submission if not e["competitors"]]
    if empty:
        print(f"\n    ⚠️  {len(empty)} products with 0 competitors: {empty}")

    # Validate: check E-Tec URLs specifically since they had the bug
    etec_total = sum(1 for e in submission for c in e["competitors"]
                     if c["competitor_retailer"] == "E-Tec")
    print(f"\n    E-Tec URLs accepted   : {etec_total}")
    etec_bad = sum(1 for e in submission for c in e["competitors"]
                   if c["competitor_retailer"] == "E-Tec"
                   and not _is_etec_product(c["competitor_url"]))
    if etec_bad:
        print(f"    ⚠️  E-Tec bad URLs: {etec_bad}")
    else:
        print(f"    ✓  All E-Tec URLs validated")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Build final submission JSON")
    ap.add_argument("--matches", nargs="+", required=True,
                    help="match_targets.py output files (one or more)")
    ap.add_argument("--scraped", nargs="+", required=True,
                    help="scraper_brave.py output files (one or more)")
    ap.add_argument("--output",  default="../output/competitor_matches.json")
    args = ap.parse_args()

    def resolve(p):
        p = Path(p)
        return p if p.is_absolute() else (HERE / p).resolve()

    print(f"📁  Script dir : {HERE}")
    print(f"📁  Output     : {resolve(args.output)}\n")
    build(
        [resolve(p) for p in args.matches],
        [resolve(p) for p in args.scraped],
        resolve(args.output),
    )