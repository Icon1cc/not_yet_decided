-- ============================================================
-- Competitor Matcher – Database Schema
-- Provider: Supabase (PostgreSQL)
-- Run this in Supabase SQL Editor before first deployment.
-- ============================================================

-- ── Source Products ──────────────────────────────────────────
-- Your own catalog products that you want competitors found for.

CREATE TABLE IF NOT EXISTS source_products (
    reference       TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    brand           TEXT,
    category        TEXT,
    image_url       TEXT,
    price_eur       NUMERIC(10, 2),
    specifications  JSONB    NOT NULL DEFAULT '{}',
    -- Precomputed matching signals
    brand_norm      TEXT,
    kind            TEXT,
    screen_size_inch NUMERIC(6, 2),
    eans            TEXT[]   NOT NULL DEFAULT '{}',
    asins           TEXT[]   NOT NULL DEFAULT '{}',
    strong_models   TEXT[]   NOT NULL DEFAULT '{}',
    family_models   TEXT[]   NOT NULL DEFAULT '{}',
    name_norm       TEXT     NOT NULL DEFAULT '',
    tokens          TEXT[]   NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Target Products ──────────────────────────────────────────
-- Competitor products scraped from retailers.

CREATE TABLE IF NOT EXISTS target_products (
    id              BIGSERIAL PRIMARY KEY,
    reference       TEXT     NOT NULL,
    name            TEXT     NOT NULL,
    brand           TEXT,
    category        TEXT,
    retailer        TEXT     NOT NULL DEFAULT '',
    url             TEXT,
    canonical_url   TEXT,
    image_url       TEXT,
    price_eur       NUMERIC(10, 2),
    specifications  JSONB    NOT NULL DEFAULT '{}',
    visible         BOOLEAN  NOT NULL DEFAULT TRUE,
    listing_key     TEXT,
    -- Precomputed matching signals
    brand_norm      TEXT,
    kind            TEXT,
    screen_size_inch NUMERIC(6, 2),
    eans            TEXT[]   NOT NULL DEFAULT '{}',
    asins           TEXT[]   NOT NULL DEFAULT '{}',
    strong_models   TEXT[]   NOT NULL DEFAULT '{}',
    family_models   TEXT[]   NOT NULL DEFAULT '{}',
    name_norm       TEXT     NOT NULL DEFAULT '',
    tokens          TEXT[]   NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (reference, retailer)
);

-- ── Indexes ──────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_target_category        ON target_products (category);
CREATE INDEX IF NOT EXISTS idx_target_kind            ON target_products (kind);
CREATE INDEX IF NOT EXISTS idx_target_retailer        ON target_products (retailer);
CREATE INDEX IF NOT EXISTS idx_target_visible         ON target_products (visible);
CREATE INDEX IF NOT EXISTS idx_target_price           ON target_products (price_eur);
CREATE INDEX IF NOT EXISTS idx_target_eans            ON target_products USING GIN (eans);
CREATE INDEX IF NOT EXISTS idx_target_asins           ON target_products USING GIN (asins);
CREATE INDEX IF NOT EXISTS idx_target_strong_models   ON target_products USING GIN (strong_models);
CREATE INDEX IF NOT EXISTS idx_target_family_models   ON target_products USING GIN (family_models);

-- ── RPC: get_target_candidates ───────────────────────────────
-- Pre-filters target products before Python scoring.
-- Called once per API request to reduce candidates.

CREATE OR REPLACE FUNCTION get_target_candidates(
    p_category   TEXT     DEFAULT NULL,
    p_kinds      TEXT[]   DEFAULT '{}',
    p_retailers  TEXT[]   DEFAULT '{}',
    p_min_price  NUMERIC  DEFAULT NULL,
    p_max_price  NUMERIC  DEFAULT NULL,
    p_limit      INT      DEFAULT 500
)
RETURNS SETOF target_products
LANGUAGE plpgsql STABLE
AS $$
BEGIN
    RETURN QUERY
    SELECT t.*
    FROM   target_products t
    WHERE
        -- Visible products must match category; hidden products always included
        (NOT t.visible OR p_category IS NULL OR t.category = p_category)
        -- Kind: if filter provided, match kind or include unclassified products
        AND (cardinality(p_kinds) = 0 OR t.kind = ANY(p_kinds) OR t.kind IS NULL)
        -- Retailer: if filter provided, only matching retailers
        AND (cardinality(p_retailers) = 0 OR t.retailer = ANY(p_retailers))
        -- Price bounds (NULL price always included — data may be missing)
        AND (p_min_price IS NULL OR t.price_eur IS NULL OR t.price_eur >= p_min_price)
        AND (p_max_price IS NULL OR t.price_eur IS NULL OR t.price_eur <= p_max_price)
    LIMIT p_limit;
END;
$$;

-- ── Updated-at trigger ───────────────────────────────────────

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_source_products_updated_at ON source_products;
CREATE TRIGGER trg_source_products_updated_at
    BEFORE UPDATE ON source_products
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_target_products_updated_at ON target_products;
CREATE TRIGGER trg_target_products_updated_at
    BEFORE UPDATE ON target_products
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
