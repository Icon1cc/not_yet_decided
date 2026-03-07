# not_yet_decided

## Quick Start

```bash
# Clone the repository
git clone
cd not_yet_decided

# add to .env file:
OPENROUTER_API_KEY=
ANTHROPIC_BASE_URL=
ANTHROPIC_AUTH_TOKEN=OPENROUTER_API_KEY
```

Start qdrant db:

```bash
docker run -p 6333:6333 -p 6334:6334 -v "<PATH_TO_PROJECT>\qdrant_storage:/qdrant/storage:z" qdrant/qdrant
```

Initialize qdrant db from jsons:

```bash
uv run python initialize_db.py --limit 10 --fresh
```