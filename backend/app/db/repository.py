"""
Data-access layer for source and target products.

Uses pg8000 (pure Python) — compatible with Vercel Lambda and any platform.
All database I/O is centralised here.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from backend.app.db.client import get_connection, get_cursor, rows_as_dicts
from backend.app.services.matching import (
    ProductSignals,
    canonical_listing_key,
    canonical_url,
    extract_product_signals,
)
from backend.app.utils.text import normalize_text

logger = logging.getLogger(__name__)


# ── Domain helpers ────────────────────────────────────────────────────────────

def signals_to_row(signals: ProductSignals) -> dict[str, Any]:
    return {
        "brand_norm":        signals.brand,
        "kind":              signals.kind,
        "screen_size_inch":  signals.screen_size_inch,
        "eans":              sorted(signals.eans),
        "asins":             sorted(signals.asins),
        "strong_models":     sorted(signals.strong_models),
        "family_models":     sorted(signals.family_models),
        "name_norm":         signals.name_norm,
        "tokens":            sorted(signals.tokens),
    }


def row_to_signals(row: dict[str, Any]) -> ProductSignals:
    return ProductSignals(
        brand=row.get("brand_norm"),
        eans=frozenset(row.get("eans") or []),
        asins=frozenset(row.get("asins") or []),
        strong_models=frozenset(row.get("strong_models") or []),
        family_models=frozenset(row.get("family_models") or []),
        name_norm=row.get("name_norm") or "",
        tokens=frozenset(row.get("tokens") or []),
        kind=row.get("kind"),
        screen_size_inch=float(row["screen_size_inch"]) if row.get("screen_size_inch") is not None else None,
    )


def row_to_product(row: dict[str, Any]) -> dict[str, Any]:
    price = row.get("price_eur")
    specs = row.get("specifications") or {}
    # pg8000 may return JSONB as a string — parse if needed
    if isinstance(specs, str):
        try:
            specs = json.loads(specs)
        except Exception:
            specs = {}
    return {
        "reference":      row.get("reference", ""),
        "name":           row.get("name", ""),
        "brand":          row.get("brand"),
        "category":       row.get("category"),
        "retailer":       row.get("retailer", ""),
        "url":            row.get("url"),
        "image_url":      row.get("image_url"),
        "price_eur":      float(price) if price is not None else None,
        "specifications": specs,
    }


def _make_target_record(row: dict[str, Any]):  # type: ignore[return]
    from backend.app.services.catalog import TargetRecord  # noqa: PLC0415

    product  = row_to_product(row)
    signals  = row_to_signals(row)
    category = row.get("category") or ""
    return TargetRecord(
        product=product,
        signals=signals,
        visible=bool(row.get("visible", True)),
        category_norm=normalize_text(category),
        canonical_url=row.get("canonical_url"),
    )


# ── Bulk insert helper ────────────────────────────────────────────────────────

def _bulk_upsert(cur, sql_template: str, rows: list[tuple]) -> None:
    """Execute a bulk INSERT … VALUES … ON CONFLICT using a single statement."""
    if not rows:
        return
    n_cols  = len(rows[0])
    single  = "(" + ",".join(["%s"] * n_cols) + ")"
    values  = ",".join([single] * len(rows))
    flat    = [v for row in rows for v in row]
    cur.execute(sql_template.replace("__VALUES__", values), flat)


# ── Repository ────────────────────────────────────────────────────────────────

class ProductRepository:
    """All DB access for products goes through this class."""

    # ── Sources ───────────────────────────────────────────────────────────────

    def get_all_sources(self) -> list[dict[str, Any]]:
        with get_connection() as conn:
            cur = get_cursor(conn)
            cur.execute("SELECT * FROM source_products ORDER BY reference")
            return [row_to_product(r) for r in rows_as_dicts(cur)]

    def upsert_sources(self, products: list[dict[str, Any]]) -> int:
        if not products:
            return 0

        rows = []
        for p in products:
            s = signals_to_row(extract_product_signals(p))
            rows.append((
                p["reference"],
                p.get("name", ""),
                p.get("brand"),
                p.get("category"),
                p.get("image_url"),
                p.get("price_eur"),
                json.dumps(p.get("specifications") or {}),
                s["brand_norm"], s["kind"], s["screen_size_inch"],
                s["eans"], s["asins"], s["strong_models"],
                s["family_models"], s["name_norm"], s["tokens"],
            ))

        sql = """
            INSERT INTO source_products (
                reference, name, brand, category, image_url, price_eur,
                specifications, brand_norm, kind, screen_size_inch,
                eans, asins, strong_models, family_models, name_norm, tokens
            ) VALUES __VALUES__
            ON CONFLICT (reference) DO UPDATE SET
                name=EXCLUDED.name, brand=EXCLUDED.brand,
                category=EXCLUDED.category, image_url=EXCLUDED.image_url,
                price_eur=EXCLUDED.price_eur, specifications=EXCLUDED.specifications::jsonb,
                brand_norm=EXCLUDED.brand_norm, kind=EXCLUDED.kind,
                screen_size_inch=EXCLUDED.screen_size_inch,
                eans=EXCLUDED.eans, asins=EXCLUDED.asins,
                strong_models=EXCLUDED.strong_models, family_models=EXCLUDED.family_models,
                name_norm=EXCLUDED.name_norm, tokens=EXCLUDED.tokens,
                updated_at=NOW()
        """

        with get_connection() as conn:
            cur = get_cursor(conn)
            # Batch in chunks of 200 to keep statement size reasonable
            for i in range(0, len(rows), 200):
                _bulk_upsert(cur, sql, rows[i : i + 200])

        return len(rows)

    # ── Targets ───────────────────────────────────────────────────────────────

    def get_target_candidates(
        self,
        category: str | None = None,
        kinds: set[str] | None = None,
        retailers: set[str] | None = None,
        min_price: float | None = None,
        max_price: float | None = None,
    ) -> list[Any]:
        """Fetch candidate targets with server-side pre-filtering via PostgreSQL function."""
        with get_connection() as conn:
            cur = get_cursor(conn)
            cur.execute(
                """
                SELECT * FROM get_target_candidates(
                    p_category  := %s,
                    p_kinds     := %s::text[],
                    p_retailers := %s::text[],
                    p_min_price := %s,
                    p_max_price := %s,
                    p_limit     := 500
                )
                """,
                (
                    category,
                    list(kinds) if kinds else [],
                    list(retailers) if retailers else [],
                    min_price,
                    max_price,
                ),
            )
            return [_make_target_record(r) for r in rows_as_dicts(cur)]

    def upsert_targets(self, products: list[dict[str, Any]], *, visible: bool) -> int:
        if not products:
            return 0

        rows = []
        for p in products:
            s       = signals_to_row(extract_product_signals(p))
            can_url = canonical_url(p.get("url"))
            lst_key = canonical_listing_key(p)
            rows.append((
                p.get("reference", ""), p.get("name", ""),
                p.get("brand"), p.get("category"),
                p.get("retailer", ""), p.get("url"), can_url,
                p.get("image_url"), p.get("price_eur"),
                json.dumps(p.get("specifications") or {}),
                visible, lst_key,
                s["brand_norm"], s["kind"], s["screen_size_inch"],
                s["eans"], s["asins"], s["strong_models"],
                s["family_models"], s["name_norm"], s["tokens"],
            ))

        sql = """
            INSERT INTO target_products (
                reference, name, brand, category, retailer, url, canonical_url,
                image_url, price_eur, specifications, visible, listing_key,
                brand_norm, kind, screen_size_inch,
                eans, asins, strong_models, family_models, name_norm, tokens
            ) VALUES __VALUES__
            ON CONFLICT (reference, retailer) DO UPDATE SET
                name=EXCLUDED.name, brand=EXCLUDED.brand,
                category=EXCLUDED.category, url=EXCLUDED.url,
                canonical_url=EXCLUDED.canonical_url, image_url=EXCLUDED.image_url,
                price_eur=EXCLUDED.price_eur, specifications=EXCLUDED.specifications::jsonb,
                visible=EXCLUDED.visible, listing_key=EXCLUDED.listing_key,
                brand_norm=EXCLUDED.brand_norm, kind=EXCLUDED.kind,
                screen_size_inch=EXCLUDED.screen_size_inch,
                eans=EXCLUDED.eans, asins=EXCLUDED.asins,
                strong_models=EXCLUDED.strong_models, family_models=EXCLUDED.family_models,
                name_norm=EXCLUDED.name_norm, tokens=EXCLUDED.tokens,
                updated_at=NOW()
        """

        with get_connection() as conn:
            cur = get_cursor(conn)
            for i in range(0, len(rows), 200):
                _bulk_upsert(cur, sql, rows[i : i + 200])

        return len(rows)

    def count_sources(self) -> int:
        with get_connection() as conn:
            cur = get_cursor(conn)
            cur.execute("SELECT COUNT(*) FROM source_products")
            row = cur.fetchone()
            return int(row[0]) if row else 0

    def count_targets(self) -> int:
        with get_connection() as conn:
            cur = get_cursor(conn)
            cur.execute("SELECT COUNT(*) FROM target_products")
            row = cur.fetchone()
            return int(row[0]) if row else 0
