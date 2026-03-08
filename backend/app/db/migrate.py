"""
Migration / seed script.

Reads all existing JSON files from the data/ directory and upserts
them into Supabase.  Run once after setting up the database, and
again whenever your JSON files are updated.

Usage:
    python -m backend.app.db.migrate
    python -m backend.app.db.migrate --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)


def _load_json(path: Path) -> list[dict]:
    if not path.exists():
        logger.warning("File not found, skipping: %s", path)
        return []
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        logger.warning("Expected JSON array in %s, got %s", path, type(data).__name__)
        return []
    return data


def _is_product_row(row: object) -> bool:
    if not isinstance(row, dict):
        return False
    if "source_reference" in row and "competitors" in row and "name" not in row:
        return False
    return bool(row.get("reference")) and bool(row.get("name"))


def run(dry_run: bool = False) -> None:
    from backend.app.core.config import get_settings
    from backend.app.db.repository import ProductRepository

    settings = get_settings()
    data_dir = settings.data_dir
    output_dir = settings.output_dir

    logger.info("Data directory  : %s", data_dir)
    logger.info("Output directory: %s", output_dir)
    if dry_run:
        logger.info("DRY RUN – no data will be written to the database.")

    # ── Source products ───────────────────────────────────────────────────────
    source_rows: list[dict] = []
    seen_refs: set[str] = set()

    for path in sorted(data_dir.glob("source_products_*.json")):
        category_raw = path.stem.replace("source_products_", "").replace("_", " ").strip()
        category = category_raw.replace("tv ", "TV ").replace("audio", "Audio")
        for row in _load_json(path):
            if not _is_product_row(row):
                continue
            ref = str(row.get("reference") or "").strip()
            if not ref or ref in seen_refs:
                continue
            seen_refs.add(ref)
            product = dict(row)
            product.setdefault("category", category)
            source_rows.append(product)

    logger.info("Source products found: %d", len(source_rows))

    # ── Target products (visible pools) ───────────────────────────────────────
    visible_rows: list[dict] = []
    seen_targets: set[tuple[str, str]] = set()

    for path in sorted(data_dir.glob("target_pool_*.json")):
        category_raw = path.stem.replace("target_pool_", "").replace("_", " ").strip()
        category = category_raw.replace("tv ", "TV ").replace("audio", "Audio")
        for row in _load_json(path):
            if not _is_product_row(row):
                continue
            product = dict(row)
            product.setdefault("category", category)
            product.setdefault("retailer", "")
            ref = str(product.get("reference") or "").strip()
            retailer = str(product.get("retailer") or "").strip()
            key = (ref, retailer)
            if key in seen_targets:
                continue
            seen_targets.add(key)
            visible_rows.append(product)

    logger.info("Visible target products found: %d", len(visible_rows))

    # ── Target products (hidden/matched) ──────────────────────────────────────
    # output/ takes priority over data/ for the same filename.
    hidden_by_name: dict[str, Path] = {}
    for base in (output_dir, data_dir):
        for path in sorted(base.glob("matched_*.json")):
            if path.name == "matched_ui_output.json":
                continue
            hidden_by_name.setdefault(path.name, path)

    hidden_rows: list[dict] = []
    for name in sorted(hidden_by_name):
        path = hidden_by_name[name]
        for row in _load_json(path):
            if not _is_product_row(row):
                continue
            product = dict(row)
            product.setdefault("retailer", "")
            ref = str(product.get("reference") or "").strip()
            retailer = str(product.get("retailer") or "").strip()
            key = (ref, retailer)
            if key in seen_targets:
                continue
            seen_targets.add(key)
            hidden_rows.append(product)

    logger.info("Hidden target products found : %d", len(hidden_rows))

    if dry_run:
        logger.info(
            "DRY RUN complete. Would insert: %d sources, %d visible targets, %d hidden targets.",
            len(source_rows), len(visible_rows), len(hidden_rows),
        )
        return

    # ── Write to database ─────────────────────────────────────────────────────
    repo = ProductRepository()

    logger.info("Upserting source products…")
    n = repo.upsert_sources(source_rows)
    logger.info("  ✓ %d source products upserted.", n)

    logger.info("Upserting visible target products…")
    n = repo.upsert_targets(visible_rows, visible=True)
    logger.info("  ✓ %d visible target products upserted.", n)

    logger.info("Upserting hidden target products…")
    n = repo.upsert_targets(hidden_rows, visible=False)
    logger.info("  ✓ %d hidden target products upserted.", n)

    total_sources = repo.count_sources()
    total_targets = repo.count_targets()
    logger.info("Database totals – sources: %d, targets: %d", total_sources, total_targets)
    logger.info("Migration complete.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed Supabase from local JSON files.")
    parser.add_argument("--dry-run", action="store_true", help="Parse files without writing to DB.")
    args = parser.parse_args()
    try:
        run(dry_run=args.dry_run)
    except Exception as exc:
        logger.error("Migration failed: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
