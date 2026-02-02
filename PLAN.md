# D&D Dungeon Master Assistant - Architecture Plan

## Vision

A comprehensive AI-powered tool that can both **assist** and **replace** a Dungeon Master in D&D campaigns, featuring:
- **DM Assistant Mode**: RAG-powered lookup from PDFs (rulebooks, modules) and D&D Beyond
- **Campaign Knowledge Graph**: NER-extracted entities from session transcripts
- **Hybrid RAG**: Combines vector search (rules/lore) with graph traversal (campaign state)

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              FRONTEND                                        │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │  Chat UI    │  │  Transcript │  │  Campaign   │  │  Rules/Reference    │ │
│  │  (DM Mode)  │  │  Upload     │  │  Viewer     │  │  Browser            │ │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           API LAYER (FastAPI)                                │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │  /chat      │  │  /transcript│  │  /campaign  │  │  /search            │ │
│  │  Endpoint   │  │  Processor  │  │  Graph API  │  │  RAG Endpoint       │ │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                    ┌─────────────────┼─────────────────┐
                    ▼                 ▼                 ▼
┌──────────────────────┐  ┌──────────────────┐  ┌──────────────────────────┐
│   ORCHESTRATION      │  │   NER PIPELINE   │  │   RAG ENGINE             │
│   (LLM Agent)        │  │                  │  │                          │
│  ┌────────────────┐  │  │  ┌────────────┐  │  │  ┌────────────────────┐  │
│  │  Tool Router   │  │  │  │  SpaCy     │  │  │  │  Query Planner     │  │
│  │  (MCP Server)  │  │  │  │  + Custom  │  │  │  │                    │  │
│  └────────────────┘  │  │  │  D&D NER   │  │  │  └────────────────────┘  │
│  ┌────────────────┐  │  │  └────────────┘  │  │  ┌────────────────────┐  │
│  │  Context       │  │  │  ┌────────────┐  │  │  │  Hybrid Retriever  │  │
│  │  Manager       │  │  │  │  Entity    │  │  │  │  (Vector + Graph)  │  │
│  └────────────────┘  │  │  │  Resolver  │  │  │  └────────────────────┘  │
│  ┌────────────────┐  │  │  └────────────┘  │  │  ┌────────────────────┐  │
│  │  Session       │  │  │  ┌────────────┐  │  │  │  Reranker          │  │
│  │  Memory        │  │  │  │  Relation  │  │  │  │                    │  │
│  └────────────────┘  │  │  │  Extractor │  │  │  └────────────────────┘  │
└──────────────────────┘  │  └────────────┘  │  └──────────────────────────┘
                          └──────────────────┘
                    ┌─────────────────┼─────────────────┐
                    ▼                 ▼                 ▼
┌──────────────────────┐  ┌──────────────────┐  ┌──────────────────────────┐
│   NEO4J              │  │   VECTOR DB      │  │   DOCUMENT STORE         │
│   Knowledge Graph    │  │   (ChromaDB)     │  │                          │
│                      │  │                  │  │  ┌────────────────────┐  │
│  - Campaign entities │  │  - PDF chunks    │  │  │  PDFs (rulebooks)  │  │
│  - NPCs, Locations   │  │  - D&D Beyond    │  │  │  Session logs      │  │
│  - Session events    │  │    content       │  │  │  D&D Beyond cache  │  │
│  - Player state      │  │  - Session notes │  │  └────────────────────┘  │
└──────────────────────┘  └──────────────────┘  └──────────────────────────┘
```

---

## Component Breakdown

### 1. Document Ingestion Pipeline

#### 1.1 PDF Processor
```
PDFs (D&D Rulebooks, Modules) → Parser → Chunker → Embedder → Vector DB
```

**Responsibilities:**
- Parse PDFs using `pymupdf` or `pdfplumber`
- Intelligent chunking (respect section boundaries, tables, stat blocks)
- Generate embeddings via OpenAI `text-embedding-3-small`
- Store in ChromaDB with metadata (source, page, section type)

**Special Handling:**
- Stat blocks → Structured extraction, store as JSON
- Tables → Preserve structure, convert to markdown
- Spells/Items → Extract as discrete entities with attributes

#### 1.2 D&D Beyond Scraper
```
D&D Beyond URLs → Scraper → Content Extractor → Chunker → Vector DB
```

**Responsibilities:**
- Scrape public content from D&D Beyond (respect ToS/robots.txt)
- Extract: Spells, Monsters, Items, Classes, Races, Rules
- Cache locally to avoid repeated fetching
- Structured extraction for game mechanics

**Technical Approach:**
- Use `httpx` + `beautifulsoup4` for scraping
- Rate limiting and caching layer
- Store raw HTML + extracted content

### 2. Transcript Processing & NER Pipeline

#### 2.1 Transcript Ingestion
```
Session Transcript → Preprocessor → Speaker Diarization → Segment Storage
```

**Input Formats:**
- Plain text (copy-paste from VTT/Discord)
- JSON (structured with speakers)
- Audio files → Whisper transcription (future)

**Preprocessing:**
- Speaker identification and normalization
- Timestamp extraction (if available)
- Segment into turns/scenes

#### 2.2 Named Entity Recognition (NER)

**Entity Types (D&D-Specific):**
| Entity Type | Examples | Detection Method |
|-------------|----------|------------------|
| `PC` | "Thorin", "my character" | Player name mapping |
| `NPC` | "Gandalf the Grey", "the innkeeper" | SpaCy PERSON + context |
| `LOCATION` | "Waterdeep", "the Yawning Portal" | SpaCy GPE/LOC + gazetteers |
| `MONSTER` | "goblin", "ancient red dragon" | D&D monster list lookup |
| `ITEM` | "Bag of Holding", "longsword +1" | D&D item patterns + lists |
| `SPELL` | "Fireball", "Cure Wounds" | D&D spell list lookup |
| `FACTION` | "Zhentarim", "Harpers" | D&D faction gazetteers |
| `EVENT` | "the Battle of...", "when we rescued..." | Pattern matching |
| `QUEST` | "find the artifact", "defeat the BBEG" | LLM extraction |

**NER Architecture:**
```python
class DnDNERPipeline:
    def __init__(self):
        self.spacy_model = spacy.load("en_core_web_lg")
        self.entity_linker = EntityLinker(knowledge_graph)
        self.llm_extractor = LLMEntityExtractor()  # For complex cases

    def process(self, text: str) -> List[Entity]:
        # Stage 1: SpaCy base NER
        doc = self.spacy_model(text)
        entities = self.extract_spacy_entities(doc)

        # Stage 2: Rule-based D&D entity matching
        entities += self.match_dnd_gazetteers(text)

        # Stage 3: LLM extraction for relationships and complex entities
        entities += self.llm_extractor.extract(text, entities)

        # Stage 4: Entity resolution (link to existing graph nodes)
        resolved = self.entity_linker.resolve(entities)

        return resolved
```

#### 2.3 Relation Extraction

**Relationship Types:**
| Relationship | Example | Pattern |
|--------------|---------|---------|
| `LOCATED_IN` | "Thorin is in Waterdeep" | [PC/NPC] + location verb + [LOCATION] |
| `OWNS` | "Gimli has a +2 axe" | [PC/NPC] + possession verb + [ITEM] |
| `KILLED` | "We defeated the dragon" | [PC] + combat verb + [MONSTER] |
| `ALLIED_WITH` | "joined the Harpers" | [PC/NPC] + alliance verb + [FACTION] |
| `KNOWS` | "Elara told us about..." | [NPC] + knowledge verb + [info] |
| `QUEST_GIVER` | "Lord Neverember asked us to..." | [NPC] + quest verb + [objective] |

**Extraction Method:**
- Dependency parsing for simple relations
- LLM-based extraction for complex narrative relationships
- Temporal ordering of events

### 3. Knowledge Graph Schema (Extended)

```yaml
# Extended schema for campaign knowledge

entity_types:
  # Core Campaign Entities
  - PC           # Player Characters
  - NPC          # Non-Player Characters
  - LOCATION     # Places (cities, dungeons, rooms)
  - ITEM         # Objects, weapons, artifacts
  - MONSTER      # Creatures and enemies
  - FACTION      # Organizations and groups
  - QUEST        # Active and completed quests
  - EVENT        # Significant happenings
  - SESSION      # Game session metadata

  # D&D Reference Entities (from RAG sources)
  - SPELL        # Spell definitions
  - CLASS        # Character classes
  - RACE         # Character races
  - RULE         # Game rules

node_properties:
  # Common
  - id: string (UUID)
  - name: string
  - aliases: string[]      # Alternative names/references
  - description: string
  - source: string         # Where this info came from
  - confidence: float      # NER confidence score
  - created_at: datetime
  - updated_at: datetime

  # Entity-specific
  - PC:
      - player_name: string
      - class: string
      - level: int
      - status: string (alive/dead/unknown)
  - NPC:
      - disposition: string (friendly/neutral/hostile)
      - importance: string (major/minor/background)
  - LOCATION:
      - location_type: string (city/dungeon/building/region)
      - visited: boolean
  - ITEM:
      - rarity: string
      - magical: boolean
      - owner_id: string
  - SESSION:
      - session_number: int
      - date: date
      - summary: string
      - transcript_id: string

relationships:
  # Spatial
  - LOCATED_IN: {from: [PC, NPC, ITEM], to: [LOCATION]}
  - CONTAINS: {from: [LOCATION], to: [LOCATION, ITEM, NPC]}
  - CONNECTED_TO: {from: [LOCATION], to: [LOCATION]}

  # Social
  - KNOWS: {from: [PC, NPC], to: [PC, NPC]}
  - ALLIED_WITH: {from: [PC, NPC], to: [FACTION, PC, NPC]}
  - HOSTILE_TO: {from: [PC, NPC, FACTION], to: [PC, NPC, FACTION, MONSTER]}
  - MEMBER_OF: {from: [PC, NPC], to: [FACTION]}

  # Ownership/Possession
  - OWNS: {from: [PC, NPC], to: [ITEM]}
  - GUARDS: {from: [NPC, MONSTER], to: [LOCATION, ITEM]}

  # Quest/Narrative
  - GAVE_QUEST: {from: [NPC], to: [QUEST]}
  - PURSUING: {from: [PC], to: [QUEST]}
  - COMPLETED: {from: [PC], to: [QUEST]}
  - OBJECTIVE_AT: {from: [QUEST], to: [LOCATION]}

  # Combat/Events
  - KILLED: {from: [PC, NPC, MONSTER], to: [PC, NPC, MONSTER]}
  - PARTICIPATED_IN: {from: [PC, NPC], to: [EVENT]}
  - OCCURRED_AT: {from: [EVENT], to: [LOCATION]}
  - OCCURRED_IN: {from: [EVENT], to: [SESSION]}

  # Reference Links
  - INSTANCE_OF: {from: [MONSTER, ITEM, SPELL], to: [reference entity]}
```

### 4. Hybrid RAG Engine

#### 4.1 Query Understanding
```python
class QueryPlanner:
    """Analyzes user query and routes to appropriate retrieval strategy"""

    def plan(self, query: str) -> RetrievalPlan:
        # Classify query type
        query_type = self.classify(query)

        if query_type == "RULES_LOOKUP":
            # "How does grappling work?"
            return VectorSearchPlan(sources=["phb", "dmg"])

        elif query_type == "CAMPAIGN_STATE":
            # "Where is Thorin right now?"
            return GraphTraversalPlan(start_node="Thorin", depth=1)

        elif query_type == "CAMPAIGN_HISTORY":
            # "What happened with the dragon?"
            return HybridPlan(
                graph=GraphTraversalPlan(entity="dragon", relationships=["KILLED", "PARTICIPATED_IN"]),
                vector=VectorSearchPlan(sources=["session_transcripts"])
            )

        elif query_type == "ENCOUNTER_GENERATION":
            # "Create a goblin ambush encounter"
            return GenerativePlan(
                retrieval=VectorSearchPlan(sources=["monsters", "encounters"]),
                generation="encounter_template"
            )
```

#### 4.2 Retrieval Strategies

**Vector Search (Rules/Lore):**
```python
def vector_search(query: str, sources: List[str], k: int = 5) -> List[Chunk]:
    embedding = embed(query)
    results = chromadb.query(
        query_embeddings=[embedding],
        where={"source": {"$in": sources}},
        n_results=k
    )
    return results
```

**Graph Traversal (Campaign State):**
```python
def graph_search(entity: str, relationships: List[str], depth: int = 2) -> Subgraph:
    query = """
    MATCH (start {name: $entity})
    CALL apoc.path.subgraphAll(start, {
        relationshipFilter: $rel_filter,
        maxLevel: $depth
    })
    YIELD nodes, relationships
    RETURN nodes, relationships
    """
    return neo4j.run(query, entity=entity, rel_filter=relationships, depth=depth)
```

**Hybrid (Combined):**
```python
def hybrid_search(query: str) -> Context:
    # Extract entities from query
    entities = ner_pipeline.extract(query)

    # Graph: Get relevant subgraph around mentioned entities
    graph_context = []
    for entity in entities:
        graph_context.append(graph_search(entity.name, depth=2))

    # Vector: Search for relevant rules/lore
    vector_context = vector_search(query, sources=["all"])

    # Merge and deduplicate
    return merge_contexts(graph_context, vector_context)
```

### 5. DM Agent Modes

#### 5.1 Assistant Mode
- **Purpose**: Help a human DM with rules lookups, campaign tracking
- **Behavior**: Reactive, answers questions, suggests options
- **Tools Available**:
  - Rules lookup (RAG from PDFs/D&D Beyond)
  - Campaign state queries (knowledge graph)
  - Encounter/NPC generation
  - Session note taking

#### 5.2 Autonomous DM Mode
- **Purpose**: Run a game session without human DM
- **Behavior**: Proactive, drives narrative, manages game state
- **Additional Capabilities**:
  - Scene description generation
  - NPC dialogue and personality
  - Combat management (initiative, HP, actions)
  - Dice rolling and rule adjudication
  - Dynamic encounter scaling
  - Story pacing and dramatic tension

#### 5.3 Tools (MCP Interface)

```python
@mcp.tool()
def lookup_rule(query: str, source: Optional[str] = None) -> str:
    """Search D&D rules from PHB, DMG, or other sources"""

@mcp.tool()
def get_campaign_state(entity: str) -> dict:
    """Get current state of a campaign entity (PC, NPC, Location)"""

@mcp.tool()
def update_campaign_state(entity: str, updates: dict) -> bool:
    """Update campaign state after events"""

@mcp.tool()
def generate_encounter(difficulty: str, environment: str, party_level: int) -> Encounter:
    """Generate a balanced combat encounter"""

@mcp.tool()
def generate_npc(role: str, context: Optional[str] = None) -> NPC:
    """Generate an NPC with personality, motivations, and stats"""

@mcp.tool()
def roll_dice(expression: str) -> DiceResult:
    """Roll dice using standard notation (e.g., '2d6+3')"""

@mcp.tool()
def get_session_history(session_id: Optional[int] = None, last_n: int = 1) -> List[Session]:
    """Retrieve previous session summaries"""

@mcp.tool()
def search_monsters(cr_range: tuple, environment: Optional[str] = None) -> List[Monster]:
    """Search monster database by CR and environment"""

@mcp.tool()
def cast_spell(caster: str, spell: str, targets: List[str]) -> SpellResult:
    """Resolve spell casting with proper rules"""
```

---

## Implementation Phases

### Phase 1: Foundation (Core Infrastructure)
**Goal**: Set up project structure, databases, and basic pipelines

1. **Project Setup**
   - [ ] Initialize FastAPI backend structure
   - [ ] Set up ChromaDB for vector storage
   - [ ] Extend Neo4j schema for full campaign tracking
   - [ ] Configure environment and dependencies

2. **PDF Ingestion**
   - [ ] PDF parser with intelligent chunking
   - [ ] Embedding generation pipeline
   - [ ] ChromaDB storage with metadata
   - [ ] Basic vector search API

3. **Basic RAG**
   - [ ] Query → Retrieve → Generate pipeline
   - [ ] Simple chat interface for testing

### Phase 2: Knowledge Graph (Campaign Tracking)
**Goal**: NER pipeline and graph population from transcripts

1. **NER Pipeline**
   - [ ] SpaCy base model setup
   - [ ] D&D gazetteers (monsters, spells, items, locations)
   - [ ] Custom entity patterns
   - [ ] LLM-based relation extraction

2. **Transcript Processing**
   - [ ] Upload endpoint for transcripts
   - [ ] Speaker diarization
   - [ ] NER extraction
   - [ ] Graph population

3. **Entity Resolution**
   - [ ] Coreference resolution
   - [ ] Entity linking to existing graph nodes
   - [ ] Confidence scoring

### Phase 3: Hybrid RAG (Intelligent Retrieval)
**Goal**: Combine vector and graph search for better answers

1. **Query Understanding**
   - [ ] Query classification
   - [ ] Entity extraction from queries
   - [ ] Retrieval strategy selection

2. **Graph-Augmented RAG**
   - [ ] Graph context retrieval
   - [ ] Context merging and ranking
   - [ ] Response generation with citations

3. **MCP Tool Integration**
   - [ ] Implement all DM tools
   - [ ] Tool routing and orchestration
   - [ ] Context management

### Phase 4: DM Modes (Agent Behavior)
**Goal**: Implement assistant and autonomous DM capabilities

1. **Assistant Mode**
   - [ ] Reactive query handling
   - [ ] Proactive suggestions
   - [ ] Session note integration

2. **Autonomous DM Mode**
   - [ ] Narrative generation
   - [ ] Combat management
   - [ ] NPC personality and dialogue
   - [ ] Dynamic difficulty adjustment

### Phase 5: Frontend & Polish
**Goal**: User-friendly interface and production readiness

1. **Web UI**
   - [ ] Chat interface
   - [ ] Campaign dashboard
   - [ ] Transcript upload
   - [ ] Knowledge graph visualization

2. **Production**
   - [ ] Authentication
   - [ ] Multi-campaign support
   - [ ] Export/import campaigns
   - [ ] Performance optimization

---

## Technology Stack

| Component | Technology | Rationale |
|-----------|------------|-----------|
| **Backend** | FastAPI | Async, fast, modern Python |
| **LLM** | OpenAI GPT-4o / Claude | Best reasoning for DM tasks |
| **Embeddings** | OpenAI text-embedding-3-small | Good quality, reasonable cost |
| **Vector DB** | ChromaDB | Simple, embedded, good for prototyping |
| **Graph DB** | Neo4j | Existing setup, excellent for relationships |
| **NER** | SpaCy + Custom | Fast, extensible, good base models |
| **PDF Parsing** | pymupdf (fitz) | Fast, handles complex layouts |
| **Frontend** | React + Tailwind | Modern, component-based |
| **Agent Protocol** | MCP | Already integrated, tool-friendly |

---

## File Structure (Proposed)

```
agentic-dm/
├── backend/
│   ├── api/
│   │   ├── __init__.py
│   │   ├── main.py              # FastAPI app
│   │   ├── routes/
│   │   │   ├── chat.py          # Chat endpoints
│   │   │   ├── transcript.py    # Transcript upload/processing
│   │   │   ├── campaign.py      # Campaign CRUD
│   │   │   └── search.py        # RAG search endpoints
│   │   └── dependencies.py      # Shared dependencies
│   │
│   ├── core/
│   │   ├── config.py            # Settings management
│   │   ├── database.py          # DB connections
│   │   └── security.py          # Auth (future)
│   │
│   ├── ingestion/
│   │   ├── pdf_processor.py     # PDF parsing and chunking
│   │   ├── dnd_beyond.py        # D&D Beyond scraper
│   │   └── embeddings.py        # Embedding generation
│   │
│   ├── ner/
│   │   ├── pipeline.py          # Main NER pipeline
│   │   ├── extractors.py        # Entity extractors
│   │   ├── resolvers.py         # Entity resolution
│   │   ├── relations.py         # Relation extraction
│   │   └── gazetteers/          # D&D entity lists
│   │       ├── monsters.json
│   │       ├── spells.json
│   │       ├── items.json
│   │       └── locations.json
│   │
│   ├── rag/
│   │   ├── retriever.py         # Hybrid retriever
│   │   ├── query_planner.py     # Query understanding
│   │   ├── reranker.py          # Result reranking
│   │   └── generator.py         # Response generation
│   │
│   ├── graph/
│   │   ├── schema.py            # Pydantic models for graph
│   │   ├── queries.py           # Cypher query builders
│   │   └── operations.py        # Graph CRUD operations
│   │
│   ├── agents/
│   │   ├── dm_agent.py          # Main DM agent
│   │   ├── tools.py             # MCP tool definitions
│   │   └── prompts/             # Agent prompts
│   │       ├── assistant.py
│   │       └── autonomous.py
│   │
│   └── mcp_server/
│       ├── server.py            # MCP server (existing, extended)
│       └── schema.yml           # Graph schema (existing, extended)
│
├── frontend/                    # React app (Phase 5)
│   ├── src/
│   └── ...
│
├── data/                        # Gitignored
│   ├── pdfs/                    # Source PDFs
│   ├── transcripts/             # Session transcripts
│   ├── chromadb/                # Vector store
│   └── cache/                   # D&D Beyond cache
│
├── tests/
│   ├── test_ner.py
│   ├── test_rag.py
│   └── ...
│
├── scripts/
│   ├── ingest_pdf.py            # CLI for PDF ingestion
│   ├── process_transcript.py    # CLI for transcript processing
│   └── seed_gazetteers.py       # Populate D&D entity lists
│
├── pyproject.toml
├── docker-compose.yml
└── PLAN.md                      # This file
```

---

## Key Design Decisions

### 1. Hybrid RAG over Pure Vector Search
**Why**: D&D campaigns have rich relational data (who knows who, where is what). Pure vector search loses this structure. Graph traversal captures relationships that matter for gameplay.

### 2. NER + Entity Linking over LLM-Only Extraction
**Why**: Consistent entity recognition across sessions. Links new mentions to existing graph nodes. Faster and more reliable for structured extraction.

### 3. MCP for Tool Interface
**Why**: Already integrated. Standard protocol for LLM tool use. Easy to add new tools. Supports multiple LLM backends.

### 4. Separate Vector and Graph DBs
**Why**: Each optimized for its use case. ChromaDB excellent for semantic search. Neo4j excellent for relationship queries. Clean separation of concerns.

### 5. Session-Based Knowledge Growth
**Why**: Knowledge graph grows with each session. Transcript processing adds new entities and relationships. Campaign state evolves naturally.

---

## Success Metrics

1. **Rules Lookup Accuracy**: Can correctly answer 90%+ of rules questions with proper citations
2. **Entity Recognition**: 85%+ F1 score on D&D entity extraction from transcripts
3. **Campaign State Accuracy**: Correctly tracks party location, inventory, relationships
4. **Response Latency**: < 3s for simple queries, < 10s for complex generation
5. **User Satisfaction**: DM finds tool useful for actual gameplay

---

## Next Steps

1. Review and refine this plan
2. Set up the new project structure
3. Implement Phase 1 (PDF ingestion + basic RAG)
4. Test with a sample D&D PDF
5. Iterate based on results
