# D&D Dungeon Master Assistant

AI-powered tool that can both assist and replace a Dungeon Master in D&D 5e campaigns.

It ingests your rulebooks and PDFs into a vector store, builds a Neo4j knowledge graph of
your campaign from session transcripts, and exposes both through a single DM agent — plus
a web UI for combat, shops, players, and live session recording.

## Features

**Knowledge & retrieval**
- **Hybrid RAG** — vector search over rules/lore combined with graph traversal over
  campaign state, with query planning and reranking
- **PDF ingestion** — D&D-aware chunking that respects stat blocks, spells, and tables
- **Campaign knowledge graph** — Neo4j tracking of PCs, NPCs, locations, items, factions,
  quests, events, and sessions

**Running a session**
- **Unified DM agent** — rules lookup, scene description, NPC dialogue, encounter and NPC
  generation, dice, and session recap from one prompt
- **Combat dashboard** — initiative tracking, grid battlemap with draggable tokens, HP and
  conditions, step-by-step turns with movement stage directions, SRD weapon tables
- **Shop system** — AI shopkeepers with personality, SRD item catalogue, working buy/sell
  transactions against live inventory
- **Discord NPCs** — AI-controlled NPCs with their own bot identities, TTS voice, and
  automated combat turns

**Capturing a session**
- **Live audio transcription** — mic recording or file upload, transcribed by Deepgram
  with word-level speaker diarization
- **Transcript → graph loop** — NER extraction from transcripts, reviewed in the UI before
  anything is written to Neo4j

**Ingesting sourcebooks**
- **Vision transcription** — scanned page images (no text layer) transcribed to markdown by
  GPT-4o, preserving stat blocks, tables, and boxed read-aloud text
- **Content-hash caching** — transcription is ~90% of ingestion cost and is cached per
  page, so re-runs of downstream stages are free
- **Chapter assembly** — pages grouped into chapters by heading, tolerant of the
  running-header variants real books produce

**Multi-campaign** — each campaign carries its own setting, premise, story arc, house
rules, and DM notes; campaign-owned entities are scoped, reference data is shared.

## Status

| Phase | Status | Description |
|-------|--------|-------------|
| 1. Foundation | ✅ Complete | Project structure, PDF ingestion, basic RAG |
| 2. Knowledge Graph | ✅ Complete | NER pipeline, transcript processing, entity resolution |
| 3. Hybrid RAG | ✅ Complete | Query planning, graph-augmented retrieval, reranking |
| 4. DM Agent | ✅ Complete | Unified agent (the Assistant/Autonomous split was removed) |
| 5. Frontend | ✅ Complete | Chat, campaign dashboard, graph visualization |
| 6. Players & Discord NPCs | ✅ Complete | Player tracking, AI NPCs in Discord with voice |
| 7. Combat & Battlemap | ✅ Complete | Initiative, grid map, SRD mechanics |
| 8. Shops | ✅ Complete | AI shopkeeper, inventory, transactions |
| 9. Audio Capture | ✅ Complete | Deepgram transcription with diarization |
| 10. Multi-Campaign | 🚧 Unverified | Built but uncommitted; not yet tested end-to-end |
| 11. Canon Ingestion | ✅ Complete | Curse of Strahd transcribed from page images into ChromaDB |

**Not built**: authentication (there is none — CORS is wide open), campaign export/import,
campaign deletion, dynamic difficulty adjustment. See [PLAN.md](PLAN.md) for the full
architecture, design decisions, and next steps.

## Quick Start

### Prerequisites

- Python 3.12+
- Docker & Docker Compose (for Neo4j)
- OpenAI API key
- Deepgram API key (optional — only for audio transcription)
- Node.js `^20.19` or `>=22.12` (required by Vite 7)

### Installation

```bash
git clone https://github.com/PythonAlchemist/agentic-dm.git
cd agentic-dm

# Install dependencies (using uv)
uv sync

# Copy environment template
cp .env.example .env
# Edit .env with your API keys — see Configuration below

# Start Neo4j
docker-compose up -d
```

> **Neo4j password**: `NEO4J_PASSWORD` in `.env` must match the credential the database
> was initialized with — `testpassword`, per `docker-compose.yml`. A mismatch surfaces as
> `AuthenticationRateLimit`, not as a wrong-password error, which is confusing. Note that
> `NEO4J_AUTH` in docker-compose only applies when the data volume is first created;
> changing it later has no effect on an existing volume.

> **Healthcheck**: the container reports `unhealthy` even when working correctly. The
> healthcheck shells out to `curl`, which no longer ships in the `neo4j:5-community`
> image. Check `docker logs dnd-neo4j` for `Bolt enabled on 0.0.0.0:7687` instead.

### Running

```bash
# Backend — port 8000 is what the frontend expects by default
uvicorn backend.api.main:app --reload --host 0.0.0.0 --port 8000

# Frontend (separate terminal)
cd frontend && npm install && npm run dev
```

- API: `http://localhost:8000` · Swagger: `/docs` · Health: `/health`
- Frontend: `http://localhost:5173`

> The frontend defaults to `http://localhost:8000/api` (override with `VITE_API_URL`),
> while `backend/core/config.py` has `api_port: int = 8001`. That setting is unused by the
> uvicorn command above — pass `--port 8000` and they agree.

### Ingesting content

```bash
# Ingest a single PDF
uv run python -m backend.scripts.ingest_pdf /path/to/rulebook.pdf -v

# Ingest all PDFs in data/pdfs/
uv run python -m backend.scripts.ingest_pdf -v --stats

# Process a session transcript into the graph
uv run python -m backend.scripts.process_transcript /path/to/transcript.txt -s 1 -v

# Ingest a scanned sourcebook (no text layer) via vision transcription
uv run python -m backend.scripts.ingest_canon data/cos.pdf --estimate   # cost first
uv run python -m backend.scripts.ingest_canon data/cos.pdf --pages 60-64 --skip-embed
uv run python -m backend.scripts.ingest_canon data/cos.pdf
```

> Canon ingestion caches each page by image hash, so only the first run is billed. A full
> 509-page run of Curse of Strahd cost $5.62; every re-run since has billed $0.00.

> `pyproject.toml` declares `ingest-pdf` and `process-transcript` console scripts, but
> they are **not currently present in `.venv/bin`** — reinstall the project
> (`uv pip install -e .`) if you want the short forms. The module invocations above work
> as-is.

## API

Ten routers are mounted. Highlights:

**Chat** — `/api/chat`
```bash
curl -X POST http://localhost:8000/api/chat/ \
  -H "Content-Type: application/json" \
  -d '{"message": "How does grappling work in 5e?"}'
```
Also: `POST /tools/roll` · `POST /tools/npc` · `POST /tools/encounter` ·
session history at `/sessions/{id}` · WebSocket at `/ws/{session_id}`

**Search** — `GET /api/search/?q=fireball&k=5` · `GET /api/search/sources`

**Campaign graph** — `/api/campaign`
```bash
curl http://localhost:8000/api/campaign/entities
curl "http://localhost:8000/api/campaign/search?q=wizard"
curl http://localhost:8000/api/campaign/graph
```
Also: `POST /entities` · `GET /entities/{id}/neighbors` · `POST /relationships`.
Most accept an optional `campaign_id` query parameter for scoping.

**Campaigns, players, sessions** — `/api/campaigns`, `/api/players`,
`/api/sessions/{id}/attendance` (campaign CRUD lives in `routes/players.py`)

**Ingestion** — `POST /api/ingest/pdf` · `GET /api/ingest/status/{job_id}`

**Transcripts** — `POST /api/transcript/process` · `/process/async` · `/upload` ·
`GET /status/{job_id}`

**Audio** — `POST /api/audio/upload` · `GET /status/{job_id}` ·
`POST /{job_id}/map-speakers` · `POST /{job_id}/confirm` · `GET /transcripts`

**Combat** — `POST /api/combat/start` · `/turn/advance` · `/damage` · `/heal` ·
`/condition/add` · `/end` · `GET /combat/status`

**Shops** — `POST /api/shop/generate` · `GET /api/shops` · `POST /shop/{id}/chat` ·
inventory CRUD at `/shop/{id}/inventory`

**Discord NPCs** — `POST /api/npcs/{id}/discord` · `/bot/start` · `/bot/stop` ·
`GET /npcs/bots`

## Project Structure

```
agentic-dm/
├── backend/
│   ├── api/routes/       # 10 routers (chat, campaign, combat, shop, audio, ...)
│   ├── core/             # Configuration & database
│   ├── ingestion/        # PDF processing & embeddings
│   ├── rag/              # Retrieval, query planning, reranking, hybrid pipeline
│   ├── graph/            # Neo4j schema & operations
│   ├── ner/              # SpaCy + gazetteer + LLM extraction, entity resolution
│   ├── transcript/       # Transcript parsing & processing
│   ├── audio/            # Deepgram transcription & diarization
│   ├── canon/            # Sourcebook ingestion: page images → markdown → ChromaDB
│   ├── agents/           # DMAgent, DMTools, prompts
│   ├── discord/          # NPC bots, combat manager, TTS voice
│   ├── shop/             # Shop generation, registry, SRD items
│   ├── mcp-server/       # MCP server (graph access)
│   └── scripts/          # CLI tools
├── frontend/src/         # React 19 + Tailwind 4 + Vite
├── claude-plugins/       # dm-screen: printable DM screen PDFs from D&D Beyond
├── sessions/             # Generated DM screens and adventure assets
├── data/                 # PDFs, transcripts, audio, vector DB (gitignored)
├── tests/                # Test suite
├── docker-compose.yml    # Neo4j service
└── PLAN.md               # Full architecture plan
```

## Testing

```bash
uv run pytest -q
```

Requires a running Neo4j — `tests/test_discord/test_combat_manager.py` connects to the
live database rather than mocking it, so those 11 tests fail with the DB down.

## Configuration

Environment variables (set in `.env`):

| Variable | Description | Default |
|----------|-------------|---------|
| `OPENAI_API_KEY` | OpenAI API key | Required |
| `OPENAI_MODEL` | Chat model | `gpt-4o-mini` |
| `OPENAI_EMBEDDING_MODEL` | Embedding model | `text-embedding-3-small` |
| `DEEPGRAM_API_KEY` | Deepgram key, for audio transcription | Optional |
| `NEO4J_URI` | Neo4j connection | `bolt://localhost:7687` |
| `NEO4J_USER` | Neo4j username | `neo4j` |
| `NEO4J_PASSWORD` | Neo4j password | `testpassword` |
| `CHROMA_COLLECTION_NAME` | ChromaDB collection | `dnd_documents` |
| `CHUNK_SIZE` | Tokens per chunk | `1000` |
| `CHUNK_OVERLAP` | Overlap tokens | `200` |
| `RETRIEVAL_TOP_K` | Chunks retrieved | `5` |
| `RERANK_TOP_K` | Chunks after reranking | `3` |
| `API_PORT` | API port (unused when passing `--port`) | `8001` |
| `VITE_API_URL` | Frontend → API base URL (frontend `.env`) | `http://localhost:8000/api` |

**Optional dependency**: Discord NPC features need `discord.py`, which is *not* in
`pyproject.toml`. Without it the bot manager logs a warning and those features are
unavailable; everything else runs normally.

## License

MIT
