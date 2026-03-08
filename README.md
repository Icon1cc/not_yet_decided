# Competitor Matcher

A production-ready competitor price intelligence system for Austrian electronics retailers. Features an AI-powered conversational agent (Claude via OpenRouter) for intelligent product matching across Amazon AT, MediaMarkt AT, Expert AT, Cyberport AT, electronic4you.at, and E-Tec.

## Features

- **AI-Powered Conversations**: Natural language chat powered by Claude for intelligent query understanding
- **Multi-Signal Matching**: Uses EAN/GTIN, model numbers, brand, name similarity, and size for accurate matching
- **Multi-Retailer Support**: Matches against 6 Austrian retailers (visible and hidden)
- **Session Persistence**: Chat history stored in browser IndexedDB
- **Follow-up Queries**: Context-aware conversation with filter refinement
- **Scalable Architecture**: Clean service-oriented backend designed for high concurrency

## Project Structure

```
├── backend/                    # Python FastAPI backend
│   ├── app/
│   │   ├── api/               # API routes and response builders
│   │   ├── core/              # Configuration and models
│   │   ├── services/          # Business logic (matching, catalog)
│   │   ├── utils/             # Utility functions
│   │   ├── retrieval/         # Vector search (Qdrant) pipeline
│   │   └── scrape/            # Web scraping modules
│   ├── tests/                 # Backend tests
│   └── app/main.py           # FastAPI application entry
│
├── frontend/                  # React + TypeScript frontend
│   ├── src/
│   │   ├── components/       # UI components
│   │   ├── pages/            # Page components
│   │   └── lib/              # API client, database
│   └── package.json
│
├── data/                      # Product data files
│   ├── source_products_*.json      # Your catalog
│   ├── target_pool_*.json          # Visible retailer products
│   └── matched_*.json              # Hidden retailer products
│
└── pyproject.toml            # Python dependencies
```

### Environment Variables

Create a `.env` file in the project root:

```bash
cp .env.example .env
```

Edit `.env` with your API keys:

```env
# Required for AI Agent conversations
OPENROUTER_API_KEY=your-openrouter-key-here

# Optional: for web search fallback
BRAVE_API_KEY=your-brave-key-here
```

Get your OpenRouter API key at: https://openrouter.ai/keys

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- (Optional) Docker for Qdrant vector database

### Backend Setup

```bash
# Install dependencies
pip install -e .

# Or with uv
uv sync

# Run the backend
uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 in your browser.

### Environment Variables

Create a `.env` file in the project root:

```env
# Optional: For web search fallback
BRAVE_API_KEY=your-brave-api-key

# Optional: For LLM features
OPENROUTER_API_KEY=your-openrouter-key
```

## API Endpoints

### Health Check
```
GET /api/v1/health
```
Returns service status and product counts.

### Chat Query
```
POST /api/v1/chat
```
Process natural language queries and return competitor matches.

**Request Body:**
```json
{
  "query": "Find Samsung TVs under €500",
  "source_products": null,
  "history": [],
  "previous_submission": [],
  "max_sources": 5,
  "max_competitors_per_source": 12
}
```

**Response:**
```json
{
  "answer": "Found 15 competitor links for 3 source products...",
  "submission": [...],
  "cards": [...],
  "stats": {...}
}
```

## Query Examples

| Query | Interpretation |
|-------|---------------|
| `Show Samsung TVs` | Product type: tv, Brand: Samsung |
| `Find washing machines under €600` | Product type: washer, Max price: €600 |
| `Competitors for P_0A7A0D68` | Direct reference lookup |
| `Show only Cyberport results` | Retailer filter: Cyberport AT |
| `Find all dishwashers` | Product type: dishwasher, All sources |

## Architecture

### Matching Algorithm

The system uses a multi-signal scoring algorithm:

1. **EAN/GTIN Match** (score: 0.99) - Exact barcode match
2. **Model Number Match** (score: 0.92+) - Manufacturer model numbers
3. **Family Model Match** (score: 0.38+) - Related model variants
4. **Name Similarity** - Token overlap + sequence matching

### Data Flow

```
User Query → Query Parser → Source Selection → Target Matching → Response Builder
                ↓                   ↓                  ↓
           Extract:            Filter by:          Score using:
           - Kind filter       - Category          - EAN
           - Price bounds      - Price range       - Model
           - Retailer          - Retailer          - Name
           - Anchors           - Kind              - Brand/Size
```

## Development

### Running Tests

```bash
# Backend tests
pytest backend/tests -v

# Frontend tests
cd frontend && npm test
```

### Code Style

```bash
# Format Python code
black backend/
ruff check backend/

# Format TypeScript
cd frontend && npm run lint
```

## Configuration

Key settings in `backend/app/core/config.py`:

| Setting | Default | Description |
|---------|---------|-------------|
| `match_threshold` | 0.80 | Minimum score for matches |
| `max_sources_default` | 5 | Default source products per query |
| `max_competitors_default` | 12 | Default competitors per source |
| `price_range_factor` | 0.30 | Price filter tolerance (±30%) |

## Data Files

### Source Products (`source_products_*.json`)
```json
{
  "reference": "P_C2CA4D4D",
  "name": "Samsung QE55Q7FAAUXXN QLED 4K TV",
  "brand": "Samsung",
  "ean": "8806097123057",
  "price_eur": 799.00,
  "specifications": {...}
}
```

### Target Products (`target_pool_*.json`, `matched_*.json`)
```json
{
  "reference": "P_43E3D659",
  "retailer": "Amazon AT",
  "name": "Samsung QE55Q7FAAUXXN",
  "url": "https://...",
  "price_eur": 819.00,
  "image_url": "https://..."
}
```

## License

MIT License - See LICENSE file for details.
