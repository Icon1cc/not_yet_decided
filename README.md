# Competitor Matcher

A production-ready **competitor price intelligence platform** for Austrian electronics retailers. Ask questions in plain language, upload your product catalog, and instantly see how competitors across 6 major retailers are pricing the same products.

---

## What problem does it solve?

Pricing teams manually check competitor websites every week — a slow, error-prone process that doesn't scale. Competitor Matcher automates this entirely. You upload your catalog, ask a question like *"show me washing machines under €600"*, and the system finds every matching competitor product, with prices and links, in seconds.

---

## Screenshots

**Home — upload a catalog or ask a question**

![Home Page](docs/Home%20Page.png)

**Results — competitor product cards with prices**

![Product Page](docs/Product%20Page.png)

**Uploading a catalog and querying by product type**

![Upload and Search](docs/Uploading%20the%20product%20and%20searching%20.png)

---

## Supported retailers

| Retailer | Country |
|---|---|
| Amazon AT | Austria |
| MediaMarkt AT | Austria |
| Expert AT | Austria |
| Cyberport AT | Austria |
| electronic4you.at | Austria |
| E-Tec | Austria |

---

## How the full system works

```
┌─────────────────────────────────────────────────────────────────┐
│                         User Interface                          │
│         (React + TypeScript · chat + file upload · cards)       │
└───────────────────────────┬─────────────────────────────────────┘
                            │  POST /api/v1/chat
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                       AI Agent Layer                            │
│   Gemini 2.5 Flash — parses intent, extracts structured filters │
│   → product types · brands · price bounds · retailer filters    │
└───────────────────────────┬─────────────────────────────────────┘
                            │  structured filters
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Catalog Matcher                             │
│                                                                 │
│  1. Query Parser      → kind / retailer / price / anchors       │
│  2. Source Selector   → pick relevant products from your catalog│
│  3. DB Pre-filter     → PostgreSQL fetches ~200 candidates      │
│  4. Signal Scorer     → Python scores each candidate (EAN → name│
│  5. Deduplicator      → canonical URL + reference dedup         │
│  6. Brave Fallback    → web search when local data is sparse    │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                      PostgreSQL Database                        │
│                                                                 │
│   source_products   (90 rows)   — your catalog                  │
│   target_products   (6,292 rows)— competitor products           │
│   + GIN indexes on EAN · ASIN · model arrays for fast lookup    │
└─────────────────────────────────────────────────────────────────┘
```

---

## How data is stored

All product data lives in **PostgreSQL** with precomputed matching signals stored as indexed columns — no full-text scan needed at query time.

### `source_products` — your catalog

| Column | Type | Description |
|---|---|---|
| `reference` | `TEXT PK` | Unique product ID (e.g. `P_C2CA4D4D`) |
| `name` | `TEXT` | Product name |
| `brand` | `TEXT` | Brand name |
| `category` | `TEXT` | TV & Audio / Small Appliances / Large Appliances |
| `price_eur` | `NUMERIC` | Your price |
| `specifications` | `JSONB` | Full spec sheet |
| `eans` | `TEXT[]` | EAN/GTIN barcodes (GIN indexed) |
| `asins` | `TEXT[]` | Amazon ASINs (GIN indexed) |
| `strong_models` | `TEXT[]` | High-confidence model numbers (GIN indexed) |
| `family_models` | `TEXT[]` | Model family variants (GIN indexed) |
| `kind` | `TEXT` | Normalised product type (tv, dishwasher, …) |
| `screen_size_inch` | `NUMERIC` | Screen diagonal in inches |

### `target_products` — competitor products

Same signal columns as above, plus:

| Column | Type | Description |
|---|---|---|
| `retailer` | `TEXT` | e.g. `Amazon AT` |
| `url` | `TEXT` | Product page URL |
| `canonical_url` | `TEXT` | Deduplicated URL (no tracking params) |
| `visible` | `BOOLEAN` | Visible pool vs. hidden/pre-matched |
| `listing_key` | `TEXT` | Dedup key combining retailer + model |

### Why signals are precomputed

At migration time, `extract_product_signals()` runs on every product and stores the results as typed columns. At query time, PostgreSQL can use GIN indexes to filter by EAN overlap, retailer, category, kind, and price **before** Python sees a single row — reducing candidates from 6,000+ to ~200.

---

## How retrieval works

Every chat query runs one PostgreSQL function call to pre-filter candidates, then Python scores them:

```
1. Agent extracts:  { kinds: ["tv"], price_max: 500, retailers: ["Amazon AT"] }
                         │
2. Query parser extracts anchor tokens, follow-up context, source refs
                         │
3. DB call (one per request):
   SELECT * FROM get_target_candidates(
     p_category  := 'TV & Audio',
     p_kinds     := ARRAY['tv'],
     p_retailers := ARRAY['Amazon AT'],
     p_max_price := 500,
     p_limit     := 500
   )
   → returns ~50–200 rows using category/kind/retailer/price indexes
                         │
4. Python scoring runs on those ~200 rows only  (not all 6,292)
```

This keeps query latency low even as the product database grows.

---

## How matching works

Each candidate is scored against the source product using a **cascading signal priority**. The first signal that fires wins — no ambiguity.

```
Source product signals:
  brand=SAMSUNG  eans={4548736132528}  strong_models={QE55Q80C}
  kind=tv  screen_size_inch=55.0  tokens={qled, 4k, smart}

For each candidate target:

  ┌── EAN exact match?          → score 0.99  ✓ MATCH (highest confidence)
  ├── ASIN exact match?         → score 0.985
  ├── Strong model match?       → score 0.92
  │     + brand bonus           →       +0.03
  │     + screen size bonus     →       +0.03
  │     + name bonus            →       +0.02
  ├── Family model match?       → score 0.38
  │     + brand/kind/size/token bonuses up to +0.56
  └── Text similarity fallback
        brand match             →       +0.22
        kind match              →       +0.18
        size match              →       +0.18
        token overlap (Jaccard) →    0–0.28
        name similarity         →    0–0.24

  Early rejection (score = 0):
    • Different confirmed brand (Samsung ≠ LG)
    • Different product kind  (tv ≠ dishwasher)
    • Screen size differs > 1 inch

  Threshold: score ≥ 0.80 → competitor match confirmed
```

Results are deduplicated by canonical URL and listing key, then sorted by score.

---

## How the AI agent works

The agent runs **before** the matcher on every message. It uses **Gemini 2.5 Flash** to interpret the user's natural language intent and return structured filters.

```
User: "show me cheap Samsung washing machines from Cyberport"

Agent response:
{
  "needs_search": true,
  "filters": {
    "product_types": ["washer"],
    "brands": ["Samsung"],
    "retailers": ["Cyberport AT"],
    "price_max": null,
    "search_query": "Samsung washing machine"
  },
  "thinking": "User wants Samsung washers filtered to Cyberport only."
}
```

The agent also handles:
- **Follow-up queries** — "show me more" / "different ones" / "only under €400"
- **Direct responses** — greetings, off-topic questions, clarifications (no search triggered)
- **Result narration** — after matching, formats a human-readable summary of what was found

If the agent is not configured, the system falls back to pure keyword-based query parsing.

---

## Project structure

```
├── backend/
│   └── app/
│       ├── api/
│       │   ├── routes.py            # FastAPI endpoints
│       │   └── response_builder.py  # Formats results for UI
│       ├── core/
│       │   └── config.py            # Settings (env vars)
│       ├── db/
│       │   ├── schema.sql           # PostgreSQL DDL + indexes + RPC function
│       │   ├── client.py            # Connection pool (psycopg2)
│       │   ├── repository.py        # All SQL queries
│       │   └── migrate.py           # Seed DB from JSON files
│       ├── services/
│       │   ├── catalog.py           # Main orchestrator (query → results)
│       │   ├── matching.py          # Signal extraction + scoring algorithm
│       │   └── agent.py             # Gemini AI agent
│       ├── retrieval/               # Optional: Qdrant vector search pipeline
│       └── scrape/                  # Web scraping (Brave, Playwright)
│
├── frontend/
│   └── src/
│       ├── components/              # Chat, cards, upload, sidebar
│       ├── pages/                   # Chat page, home
│       └── lib/                     # API client, IndexedDB session storage
│
├── data/                            # Source JSON files (used for seeding only)
│   ├── source_products_*.json
│   ├── target_pool_*.json
│   └── matched_*.json
│
├── docs/                            # Screenshots
├── api/                             # Vercel serverless entrypoints
│   ├── chat.py
│   └── health.py
├── requirements.txt
└── vercel.json
```

---

## Setup & running locally

### Prerequisites

- Python 3.11+
- Node.js 18+
- PostgreSQL 14+ (running locally)

### 1. Clone and install

```bash
git clone <repo>
cd not_yet_decided

# Python dependencies
uv sync
# or: pip install -r requirements.txt

# Frontend dependencies
cd frontend && npm install && cd ..
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:

```env
# PostgreSQL connection string
DATABASE_URL=postgresql://postgres@localhost:5432/competitor_matcher

# AI agent (Gemini)
GEMINI_API_KEY=your-gemini-key
GEMINI_MODEL=gemini-2.5-flash

# Optional: web search fallback when no local matches found
BRAVE_API_KEY=your-brave-key
```

### 3. Create the database

```bash
# Create the database
psql -U postgres -c "CREATE DATABASE competitor_matcher;"

# Run the schema (tables, indexes, RPC function)
psql -U postgres -d competitor_matcher -f backend/app/db/schema.sql
```

### 4. Seed product data

```bash
# Dry run first to verify counts
.venv/bin/python -m backend.app.db.migrate --dry-run

# Seed for real
.venv/bin/python -m backend.app.db.migrate
```

Expected output:
```
INFO  Source products found: 90
INFO  Visible target products found: 5715
INFO  Hidden target products found : 577
INFO  ✓ 90 source products upserted.
INFO  ✓ 5715 visible target products upserted.
INFO  ✓ 577 hidden target products upserted.
INFO  Database totals – sources: 90, targets: 6292
INFO  Migration complete.
```

### 5. Start the backend

```bash
.venv/bin/uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

### 6. Start the frontend

```bash
cd frontend
npm run dev
```

Open [http://localhost:5173](http://localhost:5173)

---

## API reference

### `GET /api/v1/health`

Returns service status and row counts.

```json
{
  "status": "ok",
  "sources": 90,
  "targets": 6292
}
```

### `POST /api/v1/chat`

Run a competitor search query.

**Request:**
```json
{
  "query": "Find Samsung TVs under €500",
  "source_products": null,
  "history": ["previous user message", "previous assistant reply"],
  "previous_submission": [],
  "max_sources": 5,
  "max_competitors_per_source": 12
}
```

**Response:**
```json
{
  "answer": "Found 8 competitor links across 2 products...",
  "submission": [
    {
      "source_reference": "P_C2CA4D4D",
      "competitors": [
        {
          "reference": "P_43E3D659",
          "competitor_retailer": "Amazon AT",
          "competitor_product_name": "Samsung QE55Q80C",
          "competitor_url": "https://...",
          "competitor_price": 479.00
        }
      ]
    }
  ],
  "cards": [...],
  "stats": {
    "selected_sources": 2,
    "matched_sources": 2,
    "total_links": 8,
    "candidates_fetched": 143,
    "kind_filter": ["tv"],
    "price_filter": { "min": null, "max": 500 }
  }
}
```

---

## Example queries

| Query | What it does |
|---|---|
| `Show Samsung TVs` | Filters by brand + kind |
| `Find washing machines under €600` | Filters by kind + max price |
| `Competitors for P_0A7A0D68` | Direct reference lookup |
| `Show only Cyberport results` | Retailer filter |
| `Show more` | Follow-up — expands previous results |
| `Under €400 only` | Follow-up — applies price filter to previous query |

---

## Deployment (Vercel)

Add these environment variables to your Vercel project:

```
DATABASE_URL=postgresql://user:password@your-hosted-postgres/competitor_matcher
GEMINI_API_KEY=...
BRAVE_API_KEY=...
```

> For hosted PostgreSQL on Vercel, use [Neon](https://neon.tech) or [Railway](https://railway.app) — both provide a standard `postgresql://` connection string.

Deploy:
```bash
vercel --prod
```

---

## Configuration

Key settings in [backend/app/core/config.py](backend/app/core/config.py):

| Setting | Default | Description |
|---|---|---|
| `match_threshold` | `0.80` | Minimum score to count as a match |
| `max_sources_default` | `5` | Max source products per query |
| `max_competitors_default` | `12` | Max competitors per source product |
| `gemini_model` | `gemini-2.5-flash` | AI agent model |
