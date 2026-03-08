"""
Data-access layer for source and target products.

All database I/O is centralised here. The rest of the application
works with plain dicts and domain objects – never with raw DB rows.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import psycopg2.extras

from backend.app.db.client import get_connection, get_cursor
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
    """Serialise ProductSignals to DB column values."""
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
    """Deserialise DB row columns back to ProductSignals."""
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
    """Extract the public product dict from a DB row."""
    price = row.get("price_eur")
    return {
        "reference":      row.get("reference", ""),
        "name":           row.get("name", ""),
        "brand":          row.get("brand"),
        "category":       row.get("category"),
        "retailer":       row.get("retailer", ""),
        "url":            row.get("url"),
        "image_url":      row.get("image_url"),
        "price_eur":      float(price) if price is not None else None,
        "specifications": row.get("specifications") or {},
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


# ── Repository ────────────────────────────────────────────────────────────────

class ProductRepository:
    """All DB access for products goes through this class."""

    # ── Sources ───────────────────────────────────────────────────────────────

    def get_all_sources(self) -> list[dict[str, Any]]:
        """Return all source products as plain dicts."""
        with get_connection() as conn:
            with get_cursor(conn) as cur:
                cur.execute("SELECT * FROM source_products ORDER BY reference")
                return [row_to_product(dict(row)) for row in cur.fetchall()]

    def upsert_sources(self, products: list[dict[str, Any]]) -> int:
        """Bulk upsert source products. Returns number upserted."""
        if not products:
            return 0

        rows = []
        for p in products:
            sig = extract_product_signals(p)
            s   = signals_to_row(sig)
            rows.append((
                p["reference"],
                p.get("name", ""),
                p.get("brand"),
                p.get("category"),
                p.get("image_url"),
                p.get("price_eur"),
                psycopg2.extras.Json(p.get("specifications") or {}),
                s["brand_norm"],
                s["kind"],
                s["screen_size_inch"],
                s["eans"],
                s["asins"],
                s["strong_models"],
                s["family_models"],
                s["name_norm"],
                s["tokens"],
            ))

        sql = """
            INSERT INTO source_products (
                reference, name, brand, category, image_url, price_eur,
                specifications, brand_norm, kind, screen_size_inch,
                eans, asins, strong_models, family_models, name_norm, tokens
            ) VALUES %s
            ON CONFLICT (reference) DO UPDATE SET
                name             = EXCLUDED.name,
                brand            = EXCLUDED.brand,
                category         = EXCLUDED.category,
                image_url        = EXCLUDED.image_url,
                price_eur        = EXCLUDED.price_eur,
                specifications   = EXCLUDED.specifications,
                brand_norm       = EXCLUDED.brand_norm,
                kind             = EXCLUDED.kind,
                screen_size_inch = EXCLUDED.screen_size_inch,
                eans             = EXCLUDED.eans,
                asins            = EXCLUDED.asins,
                strong_models    = EXCLUDED.strong_models,
                family_models    = EXCLUDED.family_models,
                name_norm        = EXCLUDED.name_norm,
                tokens           = EXCLUDED.tokens,
                updated_at       = NOW()
        """

        with get_connection() as conn:
            with get_cursor(conn) as cur:
                psycopg2.extras.execute_values(cur, sql, rows, page_size=500)

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
        """
        Fetch candidate target products with server-side pre-filtering.
        Uses the get_target_candidates() PostgreSQL function defined in schema.sql.
        Returns a list of TargetRecord objects ready for Python scoring.
        """
        with get_connection() as conn:
            with get_cursor(conn) as cur:
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
                return [_make_target_record(dict(row)) for row in cur.fetchall()]

    def upsert_targets(self, products: list[dict[str, Any]], *, visible: bool) -> int:
        """Bulk upsert target products. Returns number upserted."""
        if not products:
            return 0

        rows = []
        for p in products:
            sig     = extract_product_signals(p)
            s       = signals_to_row(sig)
            can_url = canonical_url(p.get("url"))
            lst_key = canonical_listing_key(p)
            rows.append((
                p.get("reference", ""),
                p.get("name", ""),
                p.get("brand"),
                p.get("category"),
                p.get("retailer", ""),
                p.get("url"),
                can_url,
                p.get("image_url"),
                p.get("price_eur"),
                psycopg2.extras.Json(p.get("specifications") or {}),
                visible,
                lst_key,
                s["brand_norm"],
                s["kind"],
                s["screen_size_inch"],
                s["eans"],
                s["asins"],
                s["strong_models"],
                s["family_models"],
                s["name_norm"],
                s["tokens"],
            ))

        sql = """
            INSERT INTO target_products (
                reference, name, brand, category, retailer, url, canonical_url,
                image_url, price_eur, specifications, visible, listing_key,
                brand_norm, kind, screen_size_inch,
                eans, asins, strong_models, family_models, name_norm, tokens
            ) VALUES %s
            ON CONFLICT (reference, retailer) DO UPDATE SET
                name             = EXCLUDED.name,
                brand            = EXCLUDED.brand,
                category         = EXCLUDED.category,
                url              = EXCLUDED.url,
                canonical_url    = EXCLUDED.canonical_url,
                image_url        = EXCLUDED.image_url,
                price_eur        = EXCLUDED.price_eur,
                specifications   = EXCLUDED.specifications,
                visible          = EXCLUDED.visible,
                listing_key      = EXCLUDED.listing_key,
                brand_norm       = EXCLUDED.brand_norm,
                kind             = EXCLUDED.kind,
                screen_size_inch = EXCLUDED.screen_size_inch,
                eans             = EXCLUDED.eans,
                asins            = EXCLUDED.asins,
                strong_models    = EXCLUDED.strong_models,
                family_models    = EXCLUDED.family_models,
                name_norm        = EXCLUDED.name_norm,
                tokens           = EXCLUDED.tokens,
                updated_at       = NOW()
        """

        with get_connection() as conn:
            with get_cursor(conn) as cur:
                psycopg2.extras.execute_values(cur, sql, rows, page_size=500)

        return len(rows)

    def count_sources(self) -> int:
        with get_connection() as conn:
            with get_cursor(conn) as cur:
                cur.execute("SELECT COUNT(*) AS n FROM source_products")
                row = cur.fetchone()
                return int(row["n"]) if row else 0

    def count_targets(self) -> int:
        with get_connection() as conn:
            with get_cursor(conn) as cur:
                cur.execute("SELECT COUNT(*) AS n FROM target_products")
                row = cur.fetchone()
                return int(row["n"]) if row else 0
