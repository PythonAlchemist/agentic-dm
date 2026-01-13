# D&D Dungeon Master Assistant

AI-powered tool that can both assist and replace a Dungeon Master in D&D campaigns.

## Features

- **DM Assistant Mode**: RAG-powered lookup from PDFs and online content
- **Campaign Knowledge Graph**: Neo4j-based tracking of NPCs, locations, items, events
- **Hybrid RAG**: Combines vector search (rules/lore) with graph traversal (campaign state)
- **PDF Ingestion**: Intelligent chunking with D&D content awareness (stat blocks, spells)

## Quick Start

### Prerequisites

- Python 3.12+
- Docker & Docker Compose
- OpenAI API key

### Installation

```bash
# Clone the repository
git clone https://github.com/PythonAlchemist/agentic-dm.git
cd agentic-dm

# Install dependencies (using uv)
uv sync

# Or with pip
pip install -e .

# Copy environment template
cp .env.example .env
# Edit .env with your API keys

# Start Neo4j database
docker-compose up -d

# Download SpaCy model (for future NER features)
python -m spacy download en_core_web_lg
```

### Usage

#### Start the API Server

```bash
# Run the FastAPI server
uvicorn backend.api.main:app --reload --host 0.0.0.0 --port 8000
```

API will be available at `http://localhost:8000`
- Swagger docs: `http://localhost:8000/docs`
- Health check: `http://localhost:8000/health`

#### Ingest PDF Documents

```bash
# Ingest a single PDF
python -m backend.scripts.ingest_pdf /path/to/rulebook.pdf -v

# Ingest all PDFs in the default directory (data/pdfs/)
python -m backend.scripts.ingest_pdf -v --stats

# Or use the installed command
ingest-pdf /path/to/rulebook.pdf -v
```

#### API Endpoints

**Chat (DM Assistant)**
```bash
curl -X POST http://localhost:8000/api/chat/ \
  -H "Content-Type: application/json" \
  -d '{"message": "How does grappling work in 5e?"}'
```

**Search Documents**
```bash
curl "http://localhost:8000/api/search/?q=fireball&k=5"
```

**Campaign Entities**
```bash
# List entities
curl http://localhost:8000/api/campaign/entities

# Create entity
curl -X POST http://localhost:8000/api/campaign/entities \
  -H "Content-Type: application/json" \
  -d '{"name": "Gandalf", "entity_type": "NPC", "description": "A wise wizard"}'

# Search graph
curl "http://localhost:8000/api/campaign/search?q=wizard"
```

**Ingest PDFs**
```bash
# Upload PDF via API
curl -X POST http://localhost:8000/api/ingest/pdf \
  -F "file=@/path/to/rulebook.pdf"

# Check ingestion status
curl http://localhost:8000/api/ingest/status/{job_id}
```

## Project Structure

```
agentic-dm/
├── backend/
│   ├── api/              # FastAPI application
│   │   ├── main.py       # App entry point
│   │   └── routes/       # API endpoints
│   ├── core/             # Configuration & database
│   ├── ingestion/        # PDF processing & embeddings
│   ├── rag/              # Retrieval & generation
│   ├── graph/            # Neo4j operations
│   ├── ner/              # NER pipeline (Phase 2)
│   ├── agents/           # DM modes (Phase 4)
│   └── scripts/          # CLI tools
├── data/                 # PDFs, transcripts, vector DB
├── tests/                # Test suite
├── docker-compose.yml    # Neo4j service
├── pyproject.toml        # Dependencies
└── PLAN.md               # Full architecture plan
```

## Development Phases

| Phase | Status | Description |
|-------|--------|-------------|
| 1. Foundation | ✅ Complete | Project structure, PDF ingestion, basic RAG |
| 2. Knowledge Graph | 🔜 Next | NER pipeline, transcript processing |
| 3. Hybrid RAG | ⏳ Planned | Query planning, graph-augmented retrieval |
| 4. DM Modes | ⏳ Planned | Assistant & autonomous agent behaviors |
| 5. Frontend | ⏳ Planned | Web UI, campaign dashboard |

See [PLAN.md](PLAN.md) for detailed architecture and implementation roadmap.

## Configuration

Environment variables (set in `.env`):

| Variable | Description | Default |
|----------|-------------|---------|
| `OPENAI_API_KEY` | OpenAI API key | Required |
| `OPENAI_MODEL` | Chat model | `gpt-4o-mini` |
| `OPENAI_EMBEDDING_MODEL` | Embedding model | `text-embedding-3-small` |
| `NEO4J_URI` | Neo4j connection | `bolt://localhost:7687` |
| `NEO4J_USER` | Neo4j username | `neo4j` |
| `NEO4J_PASSWORD` | Neo4j password | Required |
| `CHUNK_SIZE` | Tokens per chunk | `1000` |
| `CHUNK_OVERLAP` | Overlap tokens | `200` |

## License

MIT
