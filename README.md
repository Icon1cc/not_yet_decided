# Competitor Price Intelligence — Austrian Electronics Retail

Automated pipeline for discovering and surfacing competitor listings of electronics products across Austrian retail websites. Given a catalog of source products, the system finds the same products on competitor sites, extracts their prices, and exposes them through a chat-based intelligence interface.

---

## The Idea

Austrian electronics retailers — Expert, Cyberport, electronic4you, E-Tec, Amazon AT, MediaMarkt AT — sell largely overlapping product catalogs. Tracking what a competitor charges for the exact same product, across hundreds of SKUs, is impractical to do manually.

The system starts with a catalog of **source products** (your own listings, each with a name, brand, EAN, and specifications) and automatically:

1. Searches competitor sites for the same product using the Brave Search API
2. Extracts structured data — name, price, EAN, image, specs — from competitor product pages
3. Stores the results as structured competitor records, one file per retailer
4. Exposes them through a chat interface where you can query by product name, brand, category, retailer, or price range

The key distinction in data sources:

| Retailer | Type | Why |
|---|---|---|
| Amazon AT | Visible | Pre-supplied structured target pool |
| MediaMarkt AT | Visible | Pre-supplied structured target pool |
| Expert AT | Hidden | No data feed — scraped via Brave Search + Playwright |
| Cyberport AT | Hidden | No data feed — scraped via Brave Search + Playwright |
| electronic4you.at | Hidden | No data feed — scraped via Brave Search + Playwright |
| E-Tec | Hidden | No data feed — scraped via Brave Search + Playwright |

**Visible** retailers supply a structured product pool that can be matched directly. **Hidden** retailers have no data feed, so their product pages must be discovered and scraped.

---

## Data Collection

All data collection lives in `scrape/`. The pipeline has two modes: a fast Brave-Search-only mode that works even when pages block scrapers, and an optional full-extraction mode using a headless browser.

### How scraping works — overview

```
source_products_*.json
        │
        ▼
  For each source product × each hidden retailer:
        │
        ├─ Phase 1a: Brave Search API
        │    Build site: queries (EAN / model number / brand+name)
        │    → raw_brave_*.json  (URL + search snippet + price hint)
        │
        └─ Phase 1b (optional): Playwright
             Visit each URL with headless Chromium
             Extract ld+json, __NEXT_DATA__, hydration blobs
             → raw_*.json  (full structured page data)
                   │
                   ▼
             Phase 2: parser_raw.py
             Name / price / EAN / brand / specs extraction
             → matched_*.json
```

### Phase 1a — Brave Search API (`scraper_brave.py`)

For each source product and each hidden retailer, the scraper constructs `site:` queries and calls the Brave Search API. Query construction follows a strict priority:

1. **EAN/GTIN** — globally unique, used verbatim: `site:expert.at 8806097123057`
2. **Brand + model number** — extracted from spec fields or the product name: `site:cyberport.at Samsung QE55Q7FAAUXXN`
3. **Brand + meaningful name tokens** — fallback when no model number is available: `site:electronic4you.at Samsung QLED 4K TV`

Up to three query variants are tried per retailer per product, stopping once enough product URLs have been found. Results are deduplicated by URL and written to a resumable JSON output file — already-processed source references are skipped on re-run.

**Model number extraction** is validated against a blocklist of tokens that look like model numbers but are not: capacity values (`500ML`, `1000ML`), wattage (`800W`, `1300W`), voltage/frequency (`230V`, `50HZ`), technology terms (`QLED`, `OLED`, `SMART`), and retailer names. Pure-digit strings are rejected as internal SKUs, and 12+ digit numbers are rejected as EAN look-alikes. A valid model token must contain both letters and digits.

Brave Search result metadata (title, description, price snippets, thumbnail) is preserved alongside each URL — this provides a price signal even when the page itself is later blocked.

**Product URL validation** is per-retailer. Each retailer has a URL shape rule:

| Retailer | URL pattern |
|---|---|
| Expert AT | contains `~pNNNN` |
| Cyberport AT | contains `/pdp/` |
| electronic4you.at | ends with `-NNNNN.html` (5–7 digits) |
| E-Tec | `/shop/produkt/NNN/` or `details.php?artnr=NNN` |

URLs that match category pages, promotional pages, or service pages are excluded before any page visit is attempted.

### Phase 1b — Optional Playwright scraper (`scraper_playwright.py`)

The Playwright scraper builds on the same Brave Search discovery but visits each product URL with a headless Chromium browser (via `playwright-stealth` to reduce bot detection). For each page it extracts:

- **ld+json blocks** — schema.org Product, BreadcrumbList, and other structured data embedded in `<script type="application/ld+json">` tags
- **`__NEXT_DATA__`** — Next.js server-rendered page props
- **Hydration variables** — `__NUXT__`, `__STORE__`, `__INITIAL_STATE__`, `__APP_DATA__`, `__PRELOADED_STATE__`

The browser context is configured with an Austrian locale, timezone, and accept-language header to match the expected visitor profile for each site. Rate limiting is applied between Brave API calls (1.2s) and between page visits (2.5s). The scraper is fully resumable: already-visited URLs are tracked by MD5 hash and skipped on re-run.

### Phase 2 — Optional parsing (`parser_raw.py`)

The parser converts raw page data from Phase 1b into structured product records. For each page entry it runs a series of field extractors in priority order:

**Name**: schema.org `Product.name` → deep search across all embedded JSON blobs → page title (stripped of retailer suffixes) → search result title → URL slug

**Price**: schema.org `offers.price` / `lowPrice` → deep search for price keys across all blobs → regex extraction from Brave search snippets (handles European decimal format: `1.299,00 €`)

**EAN**: schema.org `gtin13` / `gtin` → deep search for `ean`, `gtin`, `barcode`, `EAN-Code`, `GTIN/EAN` → must be all-digits, 8+ characters

**Brand**: schema.org `Product.brand` → deep search for `brand`, `manufacturer`, `marke`, `hersteller` → source brand from original query → first token of product name

**Specifications**: collected from schema.org `additionalProperty` arrays, named containers (`attributes`, `specs`, `technicalDetails`, etc.), plus fallback search metadata (`_search_query`, `_search_rank`, `_search_snippets`). Nothing is filtered — the intent is to preserve as much structured data as possible for downstream matching.

Pages that returned an HTTP error or contain no extractable fields are dropped. All others are written to `matched_*.json`.

### Clearance rules (quality gates)

Before writing final matched records, we apply strict acceptance rules:

- **Domain allowlist per retailer**: records are kept only if URL host matches the retailer domain (`expert.at`, `e-tec.at`, `cyberport.at`, `electronic4you.at`).
- **Retailer-specific product URL validators**: non-product pages (category, promo, service pages) are excluded.
- **Hard dedupe**: unique key is `(retailer, url)`; duplicates are removed across category files.
- **Blocked/empty extraction filtering**: entries with no usable fields or clear block/forbidden responses are dropped.
- **URL-derived mode for Cloudflare-sensitive outputs** (`matched_cyberport.json`, `matched_electronic4you.json`): name/brand/category are inferred from URL structure only; unverifiable fields remain `null` (`ean`, `price_eur`, `image_url`).
- **Minimum record validity**: if URL is invalid, source reference is missing, or both inferred name and brand are empty, the row is excluded.

### Matching against visible retailers (`match_targets.py`)

For Amazon AT and MediaMarkt AT, the target pool is available as structured JSON. Matching runs deterministically in priority order:

1. **Direct reference** — `source.reference == target.reference` (score 1.0)
2. **EAN/GTIN** — exact string match (score 0.99)
3. **ASIN** — exact string match (score 0.98)
4. **Model number** — pool index lookup, model ≥ 5 chars with both letters and digits (score 0.90)
5. **Name similarity** — Jaccard overlap of token sets ≥ 0.55, only used when no higher-confidence match exists

Name similarity uses step 5 only as a fallback to avoid the class of false positives where a model prefix (e.g. `QA10`) appears across dozens of unrelated products. A per-retailer cap of 5 results prevents Amazon from dominating the match list.

---

## Data Storage

All data files live in `data/`. There are three kinds:

```
data/
  source_products_tv_&_audio.json       # 17  source products  — your catalog
  source_products_small_appliances.json # 29  source products
  source_products_large_appliances.json # 44  source products

  target_pool_tv_&_audio.json           # 561   visible targets  (Amazon AT, MediaMarkt AT)
  target_pool_small_appliances.json     # 1,683 visible targets
  target_pool_large_appliances.json     # 3,543 visible targets

  matched_cyberport.json                # 160  hidden competitor records
  matched_electronic4you.json           # 299  hidden competitor records
  matched_etec.json                     # 87   hidden competitor records
  matched_expert.json                   # 31   hidden competitor records
```

**Source products** are your catalog — the products you want to find competitors for. Each has a stable `reference` (e.g. `P_0A7A0D68`), name, brand, EAN, price, and specifications.

**Target pools** (visible) are pre-supplied structured product lists from Amazon AT and MediaMarkt AT, organised by category. These are matched directly at query time without scraping.

**Matched records** (hidden) are the output of the scraping pipeline — one file per hidden retailer, each containing structured product records discovered and extracted from that retailer's site. These are treated as the "hidden" competitor pool.

The backend loads all files on startup and refreshes them automatically on each query — no restart needed when new files are added.

### Source product format

```json
{
  "reference": "P_C2CA4D4D",
  "name": "Samsung QE55Q7FAAUXXN QLED 4K TV",
  "brand": "Samsung",
  "ean": "8806097123057",
  "price_eur": 799.00,
  "specifications": {
    "GTIN": "8806097123057",
    "Hersteller Modellnummer": "QE55Q7FAAUXXN",
    "Bildschirmdiagonale": "55 Zoll"
  }
}
```

### Matched competitor record format

```json
{
  "reference": "P_SC_A1B2C3D4",
  "retailer": "Expert AT",
  "url": "https://www.expert.at/shop/...",
  "ean": "8806097123057",
  "name": "Samsung QE55Q7FAAUXXN",
  "brand": "Samsung",
  "price_eur": 819.00,
  "image_url": "https://...",
  "specifications": { ... }
}
```

---

## Retrieval Pipeline

The retrieval system identifies competitor products for a given source product using a four-stage pipeline. The target pool (visible retailers) is indexed into Qdrant.

### Stage 0 — Semantic Enrichment (Index Time)

Before indexing, every product is enriched with structured metadata extracted via two complementary methods:

- **LLM classification** (Claude Haiku, batched): assigns a `product_type` from 16 fine-grained categories (tv, soundbar, headphone, power_cable, av_cable, speaker, hair_care, etc.)
- **Regex extraction**: `size` + `size_unit`, `model_number` (from manufacturer spec fields), `resolution` (8K/4K/FHD/HD), `brand_norm` (normalised brand name)

Enrichment tags are stored as indexed Qdrant payload fields (filterable at query time) and prepended to the BM25 chunk text (searchable as tokens). This dual representation ensures enrichment benefits both structured filtering and lexical retrieval.

### Stage 1 — Exact Identifier Match

Before any vector search, the pipeline performs a deterministic exact-match pass over the full target pool using high-signal identifiers:

| Field | Weight |
|---|---|
| EAN | 1.0 |
| GTIN (specifications) | 1.0 |
| Product name | 0.4 |

A candidate is promoted as an exact match only if its cumulative weight meets a threshold of **0.4** — requiring at minimum a name match. Exact hits are prioritised in the final candidate list regardless of BM25 score.

### Stage 2 — LLM Query Expansion + BM25 Retrieval

For each source product, an LLM generates **6 discriminative search terms** — model numbers, brand+size combinations, resolution tags — targeting the most unique identifiers in the product. Each term is independently embedded with **BM25 (Qdrant/bm25 sparse vectors)** and queried against the Qdrant index. Results are unioned and deduplicated, keeping the best score per candidate across all term queries.

The Qdrant collection stores both dense vectors (`text-embedding-3-small`, 1536 dimensions) and sparse BM25 vectors. Retrieval uses Reciprocal Rank Fusion (RRF) over prefetched dense and BM25 results, combining lexical precision with semantic recall.

Retrieval is tightly scoped via payload filters applied at the Qdrant level:

- **`product_type`** — eliminates cross-category noise (e.g. power cables matching TV queries)
- **Price range** — targets within ±30% of source price; null-price targets always included
- **Size range** — targets within ±2 units (same unit) of source size; no-size targets always included

### Stage 3 — LLM Match / No-Match Filtering

The top candidates (up to 15) are passed to an LLM (Claude Sonnet) in batches of 8. The LLM receives full product details for both source and each candidate and makes a binary match/no-match decision, filtering out near-misses that share a model family but differ in model suffix, colour, or regional variant.

The LLM outputs one decision per line in the format:

```
P_XXXXX: MATCH
P_YYYYY: NO_MATCH
```

Decisions are parsed and validated — unknown references or malformed output raise an assertion error rather than silently passing bad data.

---

## User Flow

The system runs as a chat application. You talk to it in plain language and it searches the loaded product database in real time.

### Starting the app

```bash
# Backend
uv sync
uv run uvicorn backend.api:app --reload --host 0.0.0.0 --port 8000

# Frontend (separate terminal)
cd frontend && npm install && npm run dev
```

Open `http://localhost:8080`.

### Home screen

![Home screen](docs/Home%20Page.png)

The landing screen offers two entry points:

1. **Upload a JSON catalog** — drag and drop a `source_products_*.json` file onto the drop zone. The file is attached to a new session and its products become the search scope for that session.
2. **Type a query directly** — use the text bar at the bottom, or click one of the four quick-start suggestions. No upload required — the system uses the built-in product catalog by default.

### Querying

Once inside a session, you type natural language queries. The backend parses them for structured signals before searching:

| What you type | What the system understands |
|---|---|
| `Show me Samsung TVs` | product type: tv, anchor: samsung |
| `Find washing machines under €600` | product type: washer, max price: €600 |
| `Competitors for P_0A7A0D68` | direct source reference lookup |
| `Show only Cyberport results` | retailer filter: Cyberport AT |
| `Find all dishwashers` | product type: dishwasher, all sources |

The assistant always tells you what it understood — applied filters, which products had matches, which did not, and which retailers the links came from.

### Response

![Product page](docs/Product%20Page.png)

Each response includes:

- A **natural language summary** — what was found, for which products, from which retailers, and what was not matched
- A **product card grid** — one card per competitor match, showing name, retailer, price, image, and a direct link to the competitor page
- A collapsible **Submission JSON block** — the scoring-format output (`source_reference` + `competitors[]`) ready for export

Follow-up queries work within the same session. Filter-only follow-ups like "only under €500" or "only from Expert" reuse the previous product context automatically.

### Scoring output format

The backend returns and persists matches in this format:

```json
[
  {
    "source_reference": "P_49A0DBE2",
    "competitors": [
      {
        "reference": "P_0243A3DB",
        "competitor_retailer": "MediaMarkt AT",
        "competitor_product_name": "Bosch Geschirrspüler Serie 4",
        "competitor_url": "https://www.mediamarkt.at/product/12345",
        "competitor_price": 449.99
      }
    ]
  }
]
```

Scoring keys:
- Visible retailers: `source_reference` + `competitors[].reference`
- Hidden retailers: `source_reference` + `competitors[].competitor_url`

Output is automatically saved to `data/matched_ui_output.json` after each query.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         DATA LAYER  (data/)                         │
│                                                                     │
│  source_products_*.json     target_pool_*.json    matched_*.json   │
│  (your catalog, 90 SKUs)    (visible retailers,   (hidden retailers │
│                              5,787 products)       577 products)    │
└──────────────────┬────────────────────┬───────────────────┬────────┘
                   │                    │                   │
                   │      loaded on startup, refreshed      │
                   │      automatically on each query       │
                   │                    │                   │
                   └────────────────────▼───────────────────┘
                                        │
                         ┌──────────────▼──────────────┐
                         │   CatalogMatcher             │
                         │   backend/matcher_service.py │
                         │                              │
                         │  1. Parse query intent       │
                         │     (kind, category,         │
                         │      retailer, price,        │
                         │      anchor tokens)          │
                         │                              │
                         │  2. Select source products   │
                         │     matching the query       │
                         │                              │
                         │  3. Score each source vs     │
                         │     all 6,364 targets        │
                         │     (score_product_match,    │
                         │      threshold 0.80)         │
                         │                              │
                         │  4. Deduplicate + rank       │
                         │     per source product       │
                         └──────────────┬──────────────┘
                                        │
                         ┌──────────────▼──────────────┐
                         │   FastAPI                    │
                         │   backend/api.py             │
                         │                              │
                         │  POST /api/v1/chat           │
                         │  GET  /api/v1/health         │
                         │                              │
                         │  Builds natural language     │
                         │  answer + card payload       │
                         │  + scoring-format JSON       │
                         └──────────────┬──────────────┘
                                        │  JSON over HTTP
                         ┌──────────────▼──────────────┐
                         │   React Frontend             │
                         │   frontend/src/              │
                         │                              │
                         │  Chat UI with session        │
                         │  history (IndexedDB)         │
                         │                              │
                         │  Answer text (pre-line)      │
                         │  Product card grid           │
                         │  Submission JSON toggle      │
                         └─────────────────────────────┘

                    ┌────────────────────────────────────┐
                    │   Scraping Pipeline  (scrape/)     │
                    │                                    │
                    │  Brave Search API                  │
                    │    → site: queries per retailer    │
                    │    → URL discovery + snippets      │
                    │                                    │
                    │  Playwright (optional)             │
                    │    → headless Chromium             │
                    │    → ld+json, __NEXT_DATA__,       │
                    │      hydration blobs               │
                    │                                    │
                    │  parser_raw.py (optional)          │
                    │    → structured field extraction   │
                    │                                    │
                    │  Output: matched_*.json            │
                    │  (feeds back into data layer)      │
                    └────────────────────────────────────┘
```

### Key design decisions

**No database server required for the UI.** The matching engine loads all JSON files directly into memory on startup. With ~6,400 target products this fits comfortably in RAM and keeps the deployment to a single `uvicorn` process plus the frontend dev server.

**Scoring, not vector search, for the API.** The chat API uses `score_product_match` — a deterministic scorer that checks EAN, model number, brand, name similarity, and screen size in priority order. This is fast (no network call), fully explainable, and precise enough for the product overlap seen across Austrian retailers.

**Vector search for the CLI pipeline.** The `main.py` CLI uses Qdrant with BM25 + dense vectors + LLM reranking for the harder matching task of finding candidates from scratch across a large catalog.

**Hidden vs visible split.** Visible retailer products (`target_pool_*.json`) are matched by reference. Hidden retailer products (`matched_*.json`) are matched by URL, because references are not stable across sites.

**Session persistence in the browser.** Chat history, uploaded catalogs, and previous submissions are stored in IndexedDB — nothing is stored server-side beyond `data/matched_ui_output.json`.

---

## Project Structure

```
backend/
  api.py                          # FastAPI chat endpoint (/api/v1/chat, /api/v1/health)
  matcher_service.py              # CatalogMatcher: query intent parsing + product scoring

frontend/
  src/pages/Index.tsx             # Main chat + session UI
  src/components/
    DropZone.tsx                  # JSON file upload zone
    ChatMessage.tsx               # Message renderer (text bubble or product card grid)
    ProductCard.tsx               # Single competitor match card
    SessionSidebar.tsx            # Session list + navigation
    ChatInput.tsx                 # Text input bar
  src/lib/db.ts                   # IndexedDB session persistence
  src/lib/api.ts                  # Backend API client

data/
  source_products_*.json          # Source products to match (your catalog)
  target_pool_*.json              # Visible-retailer product pools (Amazon, MediaMarkt)
  matched_*.json                  # Hidden-retailer competitor records (scraping output)

scrape/
  run_all_categories_brave.py     # Primary: auto-discover all source categories and scrape each
  scraper_brave.py                # Phase 1a: Brave Search API → product URLs + snippets
  merge_brave_to_matched.py       # Build matched_cyberport/electronic4you from Brave raw outputs
  scraper_playwright.py           # Optional Phase 1b: Playwright → full page JSON extraction
  parser_raw.py                   # Optional Phase 2: Raw page JSON → structured product records
  match_targets.py                # Deterministic matching against visible-retailer pool

retrieval/
  indexing.py                     # Qdrant collection setup + product upsert (dense + BM25)
  qdrant_retrieval.py             # Hybrid retrieval: dense + BM25 with RRF fusion
  exact_match.py                  # Deterministic field-weight exact match
  generation.py                   # LLM-based match / no-match filtering
  embeddings.py                   # Embedding API calls (OpenRouter)

matching_utils.py                 # Shared deterministic scorer (CLI + API)
main.py                           # CLI: full Qdrant retrieval pipeline
initialize_db.py                  # CLI: load JSON files and index into Qdrant
constants.py                      # Paths, model names, Qdrant config
```

---

## Setup

**Requirements**: Python 3.13, Node.js, Docker (for Qdrant), a Brave Search API key, an OpenRouter API key.

```bash
git clone <repo>
cd <repo>

# Install Python dependencies
uv sync

# Install Playwright browser (only needed for Phase 1b scraping)
uv run playwright install chromium
```

Create `scrape/.env`:

```
BRAVE_API_KEY=BSAxxxx...
```

Create `.env` in the project root:

```
OPENROUTER_API_KEY=sk-or-...
ANTHROPIC_BASE_URL=https://openrouter.ai/api/v1
ANTHROPIC_AUTH_TOKEN=sk-or-...
```

Start Qdrant (only needed for the CLI retrieval pipeline):

```bash
docker run -p 6333:6333 -p 6334:6334 \
  -v "$(pwd)/qdrant_storage:/qdrant/storage:z" \
  qdrant/qdrant
```

---

## Usage

### Run the chat interface (primary)

```bash
# Backend
uv run uvicorn backend.api:app --reload --host 0.0.0.0 --port 8000

# Frontend
cd frontend && npm install && npm run dev
```

Health check:

```bash
curl -sS http://127.0.0.1:8000/api/v1/health
```

### Scrape hidden retailers (all categories)

```bash
cd scrape

# Full all-category run
python3 run_all_categories_brave.py

# Quick test run (limits sources per category)
python3 run_all_categories_brave.py --limit 10
```

This generates category raw files (`output/raw_brave_*.json`) and merged matched files for Cyberport/electronic4you.

### Optional deep extraction for accessible pages

```bash
cd scrape

# Full page extraction (ld+json, next/hydration blobs)
python3 scraper_playwright.py

# Parse raw page data into matched_*.json
python3 parser_raw.py
```

### Match visible-retailer pools

```bash
cd scrape

python3 match_targets.py \
  --source "../data/source_products_tv_&_audio.json" \
  --pool   "../data/target_pool_tv_&_audio.json" \
  --output "../output/matches_tv_audio.json"

python3 match_targets.py \
  --source "../data/source_products_small_appliances.json" \
  --pool   "../data/target_pool_small_appliances.json" \
  --output "../output/matches_small_appliances.json"

python3 match_targets.py \
  --source "../data/source_products_large_appliances.json" \
  --pool   "../data/target_pool_large_appliances.json" \
  --output "../output/matches_large_appliances.json"
```

### CLI retrieval pipeline (Qdrant)

```bash
# Index all configured data files
uv run python initialize_db.py

# Test with 10 products, drop and recreate collection first
uv run python initialize_db.py --limit 10 --fresh

# Run the full retrieval pipeline
uv run python main.py
```

Data files to index are configured in `constants.py`:

```python
DATA_FILES = [
    "data/target_pool_tv_&_audio.json",
    "data/target_pool_small_appliances.json",
    "data/target_pool_large_appliances.json",
    "output/matched_expert.json",
    "output/matched_etec.json",
    "output/matched_cyberport.json",
    "output/matched_electronic4you.json",
]
```
