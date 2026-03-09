"""
Index product data files into Qdrant.
Usage:
  uv run python initialize_db.py                          # index visible target pool only
  uv run python initialize_db.py --targets scraped        # index scraped hidden-retailer files only
  uv run python initialize_db.py --targets all            # index both
  uv run python initialize_db.py --fresh --targets all    # drop + rebuild everything
  uv run python initialize_db.py --limit 10               # cap for testing
"""
import argparse
import json
import os

from dotenv import load_dotenv
from qdrant_client import QdrantClient

from constants import COLLECTION, DATA_FILES, EMBEDDING_DIM, EMBEDDING_MODEL, QDRANT_URL, SCRAPED_FILES, SCRAPED_CATEGORY
from retrieval.indexing import index_products, product_to_chunk

load_dotenv()


def load_visible(limit: int | None = None) -> list[dict]:
    products = []
    for path in DATA_FILES:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        print(f"  Loaded {len(data)} products from {path}")
        products.extend(data)
    if limit is not None:
        products = products[:limit]
        print(f"  Capped to {limit} products for testing")
    return products


def load_scraped() -> list[dict]:
    products = []
    for path in SCRAPED_FILES:
        if not os.path.exists(path):
            print(f"  Skipping missing scraped file: {path}")
            continue
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for p in data:
            p["category"] = SCRAPED_CATEGORY
        bad = [p["reference"] for p in data if p.get("category") != SCRAPED_CATEGORY]
        assert not bad, f"category overwrite failed for {bad[:5]}"
        print(f"  Loaded {len(data)} scraped products from {path} (all category='{SCRAPED_CATEGORY}')")
        products.extend(data)
    return products


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--targets", choices=["visible", "scraped", "all"], default="visible",
                        help="Which products to index: visible target pool, scraped hidden retailers, or both (default: visible)")
    parser.add_argument("--limit", type=int, default=None, help="Max products to index (testing, applies to visible only)")
    parser.add_argument("--fresh", action="store_true", help="Drop and recreate collection first")
    parser.add_argument("--enrichment-model", default="anthropic/claude-sonnet-4-5", help="LLM for product type classification")
    args = parser.parse_args()

    api_key = os.environ["OPENROUTER_API_KEY"]

    if args.fresh:
        client = QdrantClient(url=QDRANT_URL)
        existing = {c.name for c in client.get_collections().collections}
        if COLLECTION in existing:
            client.delete_collection(COLLECTION)
            print(f"Dropped collection '{COLLECTION}'")

    products = []
    if args.targets in ("visible", "all"):
        print(f"\nLoading visible target pool ({len(DATA_FILES)} file(s))...")
        products.extend(load_visible(args.limit))

    if args.targets in ("scraped", "all"):
        print(f"\nLoading scraped hidden-retailer products...")
        products.extend(load_scraped())

    print(f"\nTotal to index: {len(products)}")
    print("Sample chunk (first product):")
    print("─" * 60)
    print(product_to_chunk(products[0]))
    print("─" * 60)
    print()

    index_products(products, COLLECTION, QDRANT_URL, EMBEDDING_MODEL, EMBEDDING_DIM, api_key, enrichment_model=args.enrichment_model)

    client = QdrantClient(url=QDRANT_URL)
    info = client.get_collection(COLLECTION)
    print(f"\nCollection '{COLLECTION}' now has {info.points_count} points")


if __name__ == "__main__":
    main()
