"""
build_submission.py — Convert scraped results → submission format
=================================================================
Reads:   scraped_brave.json   (output of scraper_brave.py)
Writes:  submission.json      (final submission format)

Output format:
[
  {
    "source_reference": "P_XXXXXXXX",
    "competitors": [
      {
        "reference":               "P_SC_XXXXXXXX",
        "competitor_retailer":     "Expert AT",
        "competitor_product_name": "...",
        "competitor_url":          "https://...",
        "competitor_price":        499.99
      }
    ]
  }
]

Scoring rules:
  - Visible retailers  → scored by source_reference + reference (product ID)
  - Hidden/scraped     → scored by source_reference + competitor_url

Filtering applied:
  - Non-product URLs removed per retailer (homepages, category, contact, service pages)
  - Prices outside €10–€50,000 set to null
  - Duplicate URLs per source product deduplicated

Usage (run from inside scrape/):
  python3 build_submission.py
  python3 build_submission.py --input scraped_brave.json --output submission.json
"""

import re, json, argparse, hashlib
from pathlib import Path
from collections import Counter

HERE = Path(__file__).resolve().parent


def make_ref(url: str) -> str:
    return "P_SC_" + hashlib.md5(url.encode()).hexdigest()[:8].upper()


# ── Per-retailer product URL validators ──────────────────────────────────────
# These return True only for real product detail pages.

def is_product_url_expert(url: str) -> bool:
    # Expert product pages always contain ~p followed by digits
    # e.g. /shop/tv-audio-video/fernseher/samsung-qe55q7f~p3012345
    return bool(re.search(r'~p\d+', url))

def is_product_url_cyberport(url: str) -> bool:
    # Cyberport product pages always contain /pdp/
    # e.g. /tv-audio/fernseher/samsung/pdp/3275-0kb/samsung-tv.html
    return "/pdp/" in url

def is_product_url_e4y(url: str) -> bool:
    # electronic4you product pages end with -NNNNNN.html (6-digit ID)
    # e.g. /samsung-qe55q7faauxxn-qled-4k-tv-2025-267192.html
    # Also allow variant suffix: -267192-l13.html
    if re.search(r'-\d{5,7}(?:-l\d+)?\.html$', url):
        # Exclude obvious non-product paths even if they accidentally match
        bad = ["/service-center/", "/unternehmen/", "/computer-spielkonsolen.html",
               "/tv-hifi-heimkino.html", "/schnaeppchen", "/aktionen", "/topseller",
               "/teilzahlung", "/kontakt", "/impressum"]
        return not any(b in url for b in bad)
    return False

def is_product_url_etec(url: str) -> bool:
    # e-tec product pages:
    #   new style: /de/shop/produkt/NNNNN/product-name.html
    #   old style: /details.php?artnr=NNNNN
    return bool(
        re.search(r'/shop/produkt/\d+/', url) or
        re.search(r'details\.php\?artnr=[\s+]?\d+', url)
    )

PRODUCT_URL_VALIDATORS = {
    "Expert AT":         is_product_url_expert,
    "Cyberport AT":      is_product_url_cyberport,
    "electronic4you.at": is_product_url_e4y,
    "E-Tec":             is_product_url_etec,
}

def is_product_url(url: str, retailer: str) -> bool:
    validator = PRODUCT_URL_VALIDATORS.get(retailer)
    if validator:
        return validator(url)
    return True   # unknown retailer — don't filter


# ── Price validation ──────────────────────────────────────────────────────────

def clean_price(raw) -> float | None:
    if raw is None:
        return None
    try:
        p = round(float(raw), 2)
        return p if 10 < p < 50_000 else None
    except (TypeError, ValueError):
        return None


# ── Main converter ────────────────────────────────────────────────────────────

def convert(scraped_path: Path, output_path: Path):
    with open(scraped_path, encoding="utf-8") as f:
        scraped_all = json.load(f)

    submission        = []
    total_competitors = 0
    total_with_price  = 0
    skipped_no_url    = 0
    skipped_non_product = 0
    retailer_counts   = Counter()

    for entry in scraped_all:
        seen_urls   = set()
        competitors = []

        for item in entry.get("scraped", []):
            url      = (item.get("url") or "").strip()
            retailer = item.get("retailer", "")

            # Must have a real URL
            if not url or not url.startswith("http"):
                skipped_no_url += 1
                continue

            # Must be a real product page for this retailer
            if not is_product_url(url, retailer):
                skipped_non_product += 1
                continue

            # Deduplicate by URL
            if url in seen_urls:
                continue
            seen_urls.add(url)

            price = clean_price(item.get("price_eur"))
            if price is not None:
                total_with_price += 1

            competitors.append({
                "reference":               item.get("reference") or make_ref(url),
                "competitor_retailer":     retailer,
                "competitor_product_name": item.get("name", ""),
                "competitor_url":          url,
                "competitor_price":        price,
            })
            retailer_counts[retailer] += 1

        submission.append({
            "source_reference": entry["source_reference"],
            "competitors":      competitors,
        })
        total_competitors += len(competitors)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(submission, f, ensure_ascii=False, indent=2)

    print(f"✅  Written → {output_path}")
    print(f"\n    Source products      : {len(submission)}")
    print(f"    Total competitors    : {total_competitors}")
    print(f"    With price           : {total_with_price}")
    print(f"    Without price        : {total_competitors - total_with_price}")
    print(f"    Skipped (no URL)     : {skipped_no_url}")
    print(f"    Skipped (non-product): {skipped_non_product}")
    print(f"\n    Competitors per retailer:")
    for retailer, count in sorted(retailer_counts.items(), key=lambda x: -x[1]):
        print(f"      {retailer:25s} {count:>5}")

    # Warn about source products with zero competitors after filtering
    empty = [e["source_reference"] for e in submission if not e["competitors"]]
    if empty:
        print(f"\n    ⚠️  {len(empty)} products with 0 competitors after filtering:")
        for ref in empty:
            print(f"      {ref}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--input",  default="scraped_brave.json",
                    help="Scraped JSON (default: scraped_brave.json next to script)")
    ap.add_argument("--output", default="submission.json",
                    help="Output path (default: submission.json next to script)")
    args = ap.parse_args()

    inp = Path(args.input)
    if not inp.is_absolute():
        inp = (HERE / inp).resolve()

    out = Path(args.output)
    if not out.is_absolute():
        out = (HERE / out).resolve()

    print(f"📂  Input  : {inp}")
    print(f"📂  Output : {out}\n")
    convert(inp, out)