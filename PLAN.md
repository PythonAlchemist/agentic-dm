# D&D Dungeon Master Assistant - Architecture Plan

> **Document status** (last reviewed 2026-08-05): Phases 1–5 of the original plan are
> built. Phases 6–9 below record subsystems that were built after this plan was first
> written and were never part of it. Sections 1–4 still describe the system accurately;
> where the implementation diverged from the original design, the divergence is called
> out inline. See [README.md](README.md) for the short status table.

## Vision

A comprehensive AI-powered tool that can both **assist** and **replace** a Dungeon Master in D&D campaigns, featuring:
- **Rules & lore lookup**: RAG-powered retrieval from ingested PDFs (rulebooks, modules)
- **Campaign Knowledge Graph**: NER-extracted entities from session transcripts
- **Hybrid RAG**: Combines vector search (rules/lore) with graph traversal (campaign state)
- **Live session capture**: Diarized audio transcription that feeds the graph
- **Table automation**: Combat with a battlemap, shops with AI shopkeepers, and
  AI-controlled NPCs that speak in Discord

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

The diagram above shows the originally planned core. Four subsystems were added later and
sit alongside it, all reading campaign context from the same knowledge graph:

```
┌────────────────┐  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐
│  AUDIO CAPTURE │  │  COMBAT ENGINE │  │  SHOP SYSTEM   │  │  DISCORD NPCs  │
│                │  │                │  │                │  │                │
│  Mic / upload  │  │  Initiative    │  │  Generator     │  │  Bot manager   │
│  Deepgram STT  │  │  Battlemap     │  │  SRD items     │  │  Msg router    │
│  Diarization   │  │  HP/conditions │  │  AI shopkeeper │  │  NPC agent     │
│  → NER → graph │  │  SRD weapons   │  │  Transactions  │  │  TTS voice     │
└────────────────┘  └────────────────┘  └────────────────┘  └────────────────┘
         │                   │                   │                   │
         └───────────────────┴───────────────────┴───────────────────┘
                                     │
                                     ▼
                           NEO4J Knowledge Graph
```

Note that the document store **no longer caches D&D Beyond content** — see Section 1.2.

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

#### 1.2 D&D Beyond Scraper — ⚠️ not built (superseded)

This was never implemented. D&D Beyond access is instead handled out-of-process by the
`ddb-mcp` MCP server, which reads owned sourcebooks directly; the `dm-screen` plugin in
`claude-plugins/` consumes it. Nothing in `backend/ingestion/` scrapes D&D Beyond, and
the `data/cache/` directory in the file structure below was never created. The original
design is retained here for reference only.

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
- Audio files → **Deepgram** transcription (built in Phase 9; the plan assumed Whisper)

**Preprocessing:**
- Speaker identification and normalization
- Timestamp extraction (if available)
- Segment into turns/scenes

Diarization uses Deepgram's **word-level** speaker labels rather than utterance-level
ones — utterance-level segmentation merged turns across speaker changes, producing worse
boundaries at a table where people talk over each other.

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

> **Implemented** in `backend/graph/schema.py` as the `EntityType` and `RelationshipType`
> enums. The lists below are kept in sync with that file — it is the source of truth.

```yaml
# Extended schema for campaign knowledge

entity_types:
  # Core Campaign Entities
  - PLAYER       # Real humans at the table (distinct from their PCs)
  - PC           # Player Characters
  - NPC          # Non-Player Characters
  - LOCATION     # Places (cities, dungeons, rooms)
  - ITEM         # Objects, weapons, artifacts
  - MONSTER      # Creatures and enemies
  - FACTION      # Organizations and groups
  - QUEST        # Active and completed quests
  - EVENT        # Significant happenings
  - SESSION      # Game session metadata
  - CAMPAIGN     # Campaign container (scopes all of the above)
  - SHOP         # Shops and merchants

  # D&D Reference Entities (from RAG sources)
  - SPELL        # Spell definitions
  - CLASS        # Character classes
  - RACE         # Character races
  - RULE         # Game rules
  - LORE         # World lore
  - SETTING      # Campaign settings

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

  # Character Attributes
  - HAS_CLASS: {from: [PC, NPC], to: [CLASS]}
  - HAS_RACE: {from: [PC, NPC], to: [RACE]}
  - HAS_SUBCLASS: {from: [PC, NPC], to: [CLASS]}
  - WIELDS: {from: [PC, NPC], to: [ITEM]}       # Equipped, vs. OWNS
  - SERVES: {from: [NPC], to: [NPC, FACTION]}   # Loyalty/service
  - RELATED_TO: {from: [PC, NPC], to: [PC, NPC]}  # Family/blood relation
  - TRAVELED_TO: {from: [PC, NPC], to: [LOCATION]}

  # Player/Campaign
  - PLAYS_AS: {from: [PLAYER], to: [PC]}
  - ATTENDED: {from: [PLAYER], to: [SESSION]}
  - BELONGS_TO: {from: [PLAYER, PC, ...], to: [CAMPAIGN]}
  - ENEMY_OF: {from: [PC, NPC, FACTION], to: [PC, NPC, FACTION]}

  # Reference Links
  - INSTANCE_OF: {from: [MONSTER, ITEM, SPELL], to: [reference entity]}
```

**Campaign scoping**: `BELONGS_TO` is what makes multi-campaign support work. Graph
queries in `backend/graph/operations.py` take an optional `campaign_id` and filter on
`(e)-[:BELONGS_TO]->(:Entity {id: $campaign_id})`. Reference entities (SPELL, CLASS,
RACE, RULE) are *not* campaign-scoped — they are shared across all campaigns, which is
why the filter is written as "belongs to this campaign OR is not a scoped type".

**Race and class as entities**: `HAS_CLASS`/`HAS_RACE` exist because the NER extractor
was changed to emit races and classes as their own nodes rather than as string
properties on a character. This makes "show me every Half-Elf in the campaign" a graph
query instead of a scan.

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

### 5. DM Agent

> **Design change.** This section originally specified two separate modes — Assistant and
> Autonomous — selected by a UI toggle. **That split has been removed.** There is now one
> unified agent. See "Key Design Decision 6" below for why.

#### 5.1 Unified Agent

- **Purpose**: Help run a game, at whatever level of involvement the moment calls for
- **Behavior**: Reactive when asked a question, generative when asked to narrate
- **Capabilities** (one prompt, `backend/agents/prompts/assistant.py`):
  - Rules lookup (RAG over ingested PDFs)
  - Campaign state queries (knowledge graph)
  - Encounter / NPC generation
  - Scene description and combat narration
  - NPC dialogue and personality
  - Dice rolling and rule adjudication
  - Session recap

Implemented as `DMAgent` in `backend/agents/dm_agent.py`. Campaign context (premise,
current story arc, house rules, DM notes) is loaded per-request from the active
campaign's graph node and injected into the system prompt.

#### 5.2 Tools

Tools are split across two surfaces, which was not the original intent:

- **`DMTools`** (`backend/agents/tools.py`) — a plain Python class the agent calls
  directly. Dice, NPC generation, encounter generation, and the full combat state
  machine (initiative, HP, conditions, grid movement, mid-combat add/remove). Also
  exposed over REST at `/api/chat/tools/*` and `/api/combat/*`.
- **MCP server** (`backend/mcp-server/server.py`) — exposes *only* graph access:
  `schema_describe`, `graph_get_node`, `graph_neighbors`, `graph_search`. This is for
  external MCP clients reading the campaign graph.

The unified MCP tool surface sketched below was **not** built as designed — `cast_spell`
and `search_monsters` do not exist, and the rest live in `DMTools` rather than MCP. Kept
as a reference for what a consolidated tool interface would look like.

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

Phases 1–5 are the original plan. Phases 6–10 were not planned here — they record work
that happened after this document was written, reconstructed from the commit history.

### Phase 1: Foundation (Core Infrastructure) — ✅ Complete
**Goal**: Set up project structure, databases, and basic pipelines

1. **Project Setup**
   - [x] Initialize FastAPI backend structure
   - [x] Set up ChromaDB for vector storage
   - [x] Extend Neo4j schema for full campaign tracking
   - [x] Configure environment and dependencies

2. **PDF Ingestion**
   - [x] PDF parser with intelligent chunking
   - [x] Embedding generation pipeline
   - [x] ChromaDB storage with metadata
   - [x] Basic vector search API

3. **Basic RAG**
   - [x] Query → Retrieve → Generate pipeline
   - [x] Simple chat interface for testing

### Phase 2: Knowledge Graph (Campaign Tracking) — ✅ Complete
**Goal**: NER pipeline and graph population from transcripts

1. **NER Pipeline**
   - [x] SpaCy base model setup
   - [x] D&D gazetteers (monsters, spells, items, locations)
   - [x] Custom entity patterns
   - [x] LLM-based relation extraction

2. **Transcript Processing**
   - [x] Upload endpoint for transcripts
   - [x] Speaker diarization *(delivered in Phase 9 via Deepgram, not text heuristics)*
   - [x] NER extraction
   - [x] Graph population

3. **Entity Resolution**
   - [x] Coreference resolution — *partial*: handled by LLM canonicalization
         (nickname merging, e.g. "Vex" → "Vex'ahlia") rather than a true coref model
   - [x] Entity linking to existing graph nodes
   - [x] Confidence scoring

### Phase 3: Hybrid RAG (Intelligent Retrieval) — ✅ Complete
**Goal**: Combine vector and graph search for better answers

1. **Query Understanding**
   - [x] Query classification
   - [x] Entity extraction from queries
   - [x] Retrieval strategy selection

2. **Graph-Augmented RAG**
   - [x] Graph context retrieval
   - [x] Context merging and ranking
   - [x] Response generation with citations

3. **MCP Tool Integration**
   - [ ] Implement all DM tools — *diverged*: MCP exposes graph access only; DM tools
         live in `DMTools` and REST. See Section 5.2.
   - [x] Tool routing and orchestration
   - [x] Context management

### Phase 4: DM Modes (Agent Behavior) — ✅ Complete (restructured)
**Goal**: Implement assistant and autonomous DM capabilities

The two-mode design was collapsed into one agent. Every capability below still exists;
the user-facing mode toggle does not.

1. **Assistant Mode**
   - [x] Reactive query handling
   - [x] Proactive suggestions
   - [x] Session note integration

2. **Autonomous DM Mode** *(merged into the unified agent)*
   - [x] Narrative generation
   - [x] Combat management
   - [x] NPC personality and dialogue
   - [ ] Dynamic difficulty adjustment — **not built**

### Phase 5: Frontend & Polish — ✅ UI complete, production hardening outstanding
**Goal**: User-friendly interface and production readiness

1. **Web UI**
   - [x] Chat interface
   - [x] Campaign dashboard
   - [x] Transcript upload
   - [x] Knowledge graph visualization

2. **Production**
   - [ ] Authentication — **not built**. No auth anywhere; CORS is `allow_origins=["*"]`.
   - [x] Multi-campaign support *(Phase 10)*
   - [ ] Export/import campaigns — **not built**
   - [ ] Performance optimization — **not started**

---

### Phase 6: Players & Discord NPCs — ✅ Complete
**Goal**: Track real players separately from their characters; let AI voice NPCs at the table

- [x] `PLAYER` entity type and `PLAYS_AS` / `ATTENDED` relationships
- [x] Player management API and UI (`/api/players`, `PlayerManager.tsx`)
- [x] Discord bot manager with per-NPC bot identities (`backend/discord/`)
- [x] Message router — decides when an NPC should respond (direct mention, name
      reference, DM command)
- [x] NPC agent with personality-driven dialogue, backed by campaign graph context
- [x] TTS voice output (`backend/discord/voice/tts_service.py`)
- [x] Automated NPC combat turns

> `discord.py` is an **optional** runtime dependency and is not in `pyproject.toml`.
> Without it the bot manager logs a warning and Discord features are unavailable; the
> rest of the app runs normally.

### Phase 7: Combat Dashboard & Battlemap — ✅ Complete
**Goal**: Run a full combat encounter in the UI

- [x] Initiative tracker with turn order and round counting
- [x] Grid battlemap with draggable tokens and auto-placement
- [x] HP, damage, healing (with max-HP cap), and conditions
- [x] Mid-combat add/remove of combatants
- [x] D&D 5e SRD battle mechanics and weapon tables (`srd_weapons.py`)
- [x] Step-by-step turns with movement stage directions
- [x] Combat log

### Phase 8: Shop System — ✅ Complete
**Goal**: Merchants the party can actually trade with

- [x] `SHOP` entity type, shop registry and generator
- [x] SRD item catalogue with pricing
- [x] AI shopkeeper with personality, driven by tool-calling
- [x] Buy/sell transactions with inventory mutation and stock checks
- [x] Shop dashboard UI (setup, inventory table, shopkeeper card)

### Phase 9: Audio Session Capture — ✅ Complete
**Goal**: Record a session and turn it into transcript + graph data

- [x] Live mic recording and file upload
- [x] Deepgram transcription with speaker diarization
- [x] Word-level diarization preferred over utterance-level (better speaker boundaries)
- [x] Background transcription jobs with status polling
- [x] Speaker → player/character mapping UI

### Phase 10: Multi-Campaign & Transcript→Graph Loop — 🚧 Implemented, not yet verified
**Goal**: Support several campaigns in one install; close the loop from audio to graph

> **Status**: complete in the working tree but **uncommitted** as of 2026-08-05, and
> never exercised end-to-end. Treat as unverified.

1. **Multi-campaign**
   - [x] Rich `CampaignEntity` — setting, theme, rule system, level range, house rules,
         allowed sources, premise, current story arc, DM notes
   - [x] Campaign CRUD API (`list` / `get` / `create` / `update`)
   - [x] `campaign_id` scoping threaded through graph ops, RAG, and chat
   - [x] Campaign landing page and picker; active campaign persisted to localStorage
   - [x] Campaign context injected into the agent's system prompt
   - [ ] Campaign deletion — no `DELETE` endpoint exists

2. **Transcript → graph review loop**
   - [x] Transcript editor with per-speaker colouring and timestamps
   - [x] Entity preview graph — review extracted entities *before* they hit Neo4j
   - [x] Confirm endpoint that commits reviewed entities (`POST /{job_id}/confirm`)
   - [x] Transcript history persistence and listing
   - [x] NER upgrades: `CLASS`/`RACE` as entities, 7 new relationship types,
         nickname deduplication

### Phase 11: Canon Ingestion — ✅ Complete
**Goal**: Turn a published sourcebook into a searchable corpus, as the foundation for a
shared canon knowledge graph

Design: [docs/superpowers/specs/2026-08-05-canon-campaign-graph-design.md](docs/superpowers/specs/2026-08-05-canon-campaign-graph-design.md)

- [x] Page image extraction from scanned PDFs (one image per page, render fallback)
- [x] Vision transcription to markdown via `gpt-4o`, preserving stat blocks, tables, and
      boxed read-aloud text
- [x] Content-hash transcript cache — transcription is ~90% of cost, so re-runs are free
- [x] Per-page failure isolation: one bad page cannot abort a 509-page run
- [x] Chapter assembly tolerant of running-header variants (`Chapter 4: X` vs
      `Chapter 4 | X`) and curly/straight apostrophes
- [x] Chunk + embed into ChromaDB with `book_slug` / `chapter_slug` / `plane=canon`
      metadata, clearing stale chunks on re-ingest
- [x] CLI with cost estimation and page-range piloting
- [ ] Canon knowledge graph (spec stages 4–6) — **not built**; this phase delivers prose
      only

**Run for real**: Curse of Strahd, 509/509 pages, $5.62 one-time, 25 chapters matching the
book's true structure, 521 chunks embedded.

> `data/cos.pdf` has **no text layer** — it is a print-to-PDF of an image flipbook. That is
> why this phase exists at all, and why vision transcription rather than `pymupdf` text
> extraction is the primary path.

---

## Technology Stack

As built. Deviations from the original picks are noted in the rationale column.

| Component | Technology | Rationale |
|-----------|------------|-----------|
| **Backend** | FastAPI | Async, fast, modern Python |
| **LLM** | OpenAI `gpt-4o-mini` (default) | Configurable via `OPENAI_MODEL`; the plan said GPT-4o/Claude, the default is the cheaper mini |
| **Embeddings** | OpenAI text-embedding-3-small | Good quality, reasonable cost |
| **Vector DB** | ChromaDB | Simple, embedded, good for prototyping |
| **Graph DB** | Neo4j 5 (community) | Excellent for relationships; runs via docker-compose |
| **NER** | SpaCy `en_core_web_sm` + gazetteers + LLM | Three-stage pipeline. Note: **sm**, not the `lg` model the plan assumed |
| **Fuzzy matching** | rapidfuzz + pyahocorasick | Gazetteer matching at speed |
| **PDF Parsing** | pymupdf (fitz) | Fast, handles complex layouts |
| **Speech-to-text** | Deepgram (`deepgram-sdk`) | Diarization quality; the plan had assumed Whisper |
| **Frontend** | React 19 + Tailwind 4 + Vite 7 | Modern, component-based |
| **Graph viz** | react-force-graph-2d | Only non-React frontend dependency |
| **Chat NPCs** | discord.py *(optional)* | Not in `pyproject.toml`; install separately |
| **Agent Protocol** | MCP | Graph access only — see Section 5.2 |
| **Packaging** | uv | Lockfile-driven installs |

---

## File Structure (Actual)

```
agentic-dm/
├── backend/
│   ├── api/
│   │   ├── main.py              # FastAPI app, mounts 10 routers
│   │   └── routes/
│   │       ├── chat.py          # Chat + dice/NPC/encounter tools + WebSocket
│   │       ├── search.py        # RAG search endpoints
│   │       ├── campaign.py      # Entity CRUD + campaign CRUD
│   │       ├── ingest.py        # PDF upload and job status
│   │       ├── transcript.py    # Transcript upload/processing
│   │       ├── players.py       # Player management
│   │       ├── npc_discord.py   # Discord NPC config
│   │       ├── combat.py        # Combat state and battlemap
│   │       ├── shop.py          # Shops, inventory, shopkeeper chat
│   │       └── audio.py         # Upload, transcribe, map speakers, confirm
│   │
│   ├── core/                    # config.py, database.py  (no security.py — no auth)
│   ├── ingestion/               # pdf_processor.py, embeddings.py
│   │
│   ├── ner/
│   │   ├── pipeline.py          # Orchestrates the three extractors
│   │   ├── config.py, models.py
│   │   ├── extractors/          # spacy_extractor, gazetteer_extractor, llm_extractor
│   │   ├── gazetteers/          # loader.py, matcher.py  (data in data/gazetteers/)
│   │   └── resolution/          # resolver.py, linker.py
│   │
│   ├── rag/
│   │   ├── pipeline.py          # Vector-only pipeline
│   │   ├── hybrid_pipeline.py   # Vector + graph
│   │   ├── retriever.py, enhanced_retriever.py
│   │   ├── query_planner.py, reranker.py
│   │
│   ├── graph/                   # schema.py (entity/rel enums), operations.py
│   ├── transcript/              # models.py, parser.py, processor.py
│   ├── audio/                   # transcriber.py (Deepgram), converter.py, models.py
│   │
│   ├── agents/
│   │   ├── dm_agent.py          # Unified DMAgent
│   │   ├── tools.py             # DMTools: dice, NPC, encounter, combat state machine
│   │   ├── conversation.py      # Session memory
│   │   └── prompts/assistant.py # Single system prompt (autonomous.py removed)
│   │
│   ├── discord/                 # bot_manager, message_router, npc_agent, npc_registry,
│   │   └── voice/               # combat_manager/controller/models, srd_weapons, tts
│   │
│   ├── shop/                    # generator.py, registry.py, models.py, srd_items.py
│   ├── mcp-server/server.py     # MCP: graph access only
│   └── scripts/                 # ingest_pdf.py, process_transcript.py
│
├── frontend/src/
│   ├── App.tsx, main.tsx
│   ├── api/client.ts            # Typed API client
│   ├── hooks/                   # useChat.ts, useCampaign.ts
│   ├── types/index.ts
│   └── components/
│       ├── CampaignLanding.tsx, CampaignDashboard.tsx, Sidebar.tsx
│       ├── ChatPanel.tsx, ChatInput.tsx, ChatMessage.tsx
│       ├── KnowledgeGraph.tsx, EntityDetail.tsx, PlayerManager.tsx
│       ├── combat/              # CombatDashboard, BattleMap, InitiativePanel, ...
│       ├── shop/                # ShopDashboard, InventoryTable, ShopkeeperCard, ...
│       └── audio/               # AudioTranscriber, TranscriptEditor,
│                                # EntityPreviewGraph, SpeakerMapper, ...
│
├── claude-plugins/dm-screen/    # Claude Code plugin: /dm-screen → printable PDF
├── sessions/                    # Generated DM screens and adventure assets
│
├── data/                        # Gitignored
│   ├── pdfs/  transcripts/  chromadb/  audio/  gazetteers/  graph/
│
├── tests/                       # test_agents, test_api, test_discord, test_ner,
│                                # test_rag, test_transcript, test_pdf_processor
├── scripts/
├── pyproject.toml
├── docker-compose.yml           # Neo4j
├── README.md
└── PLAN.md                      # This file
```

---

## Key Design Decisions

### 1. Hybrid RAG over Pure Vector Search
**Why**: D&D campaigns have rich relational data (who knows who, where is what). Pure vector search loses this structure. Graph traversal captures relationships that matter for gameplay.

### 2. NER + Entity Linking over LLM-Only Extraction
**Why**: Consistent entity recognition across sessions. Links new mentions to existing graph nodes. Faster and more reliable for structured extraction.

### 3. MCP for Tool Interface — ⚠️ only partly held
**Why**: Already integrated. Standard protocol for LLM tool use. Easy to add new tools. Supports multiple LLM backends.

**What actually happened**: MCP ended up carrying graph access only. DM tools grew inside
the app as a plain Python class (`DMTools`) because they mutate in-process combat and shop
state that an out-of-process MCP server has no handle on. The result is three overlapping
tool surfaces — `DMTools`, REST, and MCP. Consolidating them is on the Next Steps list.

### 4. Separate Vector and Graph DBs
**Why**: Each optimized for its use case. ChromaDB excellent for semantic search. Neo4j excellent for relationship queries. Clean separation of concerns.

### 5. Session-Based Knowledge Growth
**Why**: Knowledge graph grows with each session. Transcript processing adds new entities and relationships. Campaign state evolves naturally.

### 6. One Unified Agent, Not Assistant vs. Autonomous *(revised)*
**Why**: The original two-mode design (Section 5) made the user declare up front how much
help they wanted, but real table use doesn't split that way — a DM asks a rules question,
then asks for a scene description, then hands an NPC over entirely, all within a minute.
The toggle forced a context switch to get capabilities that should always be available.
The two prompts also drifted, since most edits applied to both. Collapsing them into one
prompt removed the toggle, deleted `prompts/autonomous.py`, and dropped the `DMMode`
enum. The freed sidebar slot now holds campaign context.

### 7. Campaign as a Graph Node, Not a Database *(added)*
**Why**: Multi-campaign support could have meant one Neo4j database per campaign. Instead
a campaign is an ordinary node, and campaign-owned entities point at it via `BELONGS_TO`.
This keeps reference data (spells, rules, classes, races) shared across every campaign
instead of duplicated per database, and makes cross-campaign queries possible later.
Cost: every scoped query needs an explicit `campaign_id` filter, and forgetting one leaks
entities between campaigns.

### 8. Review Before Commit for Extracted Entities *(added)*
**Why**: NER over a two-hour session transcript produces plenty of plausible-but-wrong
entities, and a knowledge graph is far easier to keep clean than to clean up. Extraction
therefore stages results for review in the UI (`EntityPreviewGraph`) and only writes to
Neo4j on explicit confirmation. The graph stays trustworthy at the cost of a manual gate
after each session.

---

## Success Metrics

1. **Rules Lookup Accuracy**: Can correctly answer 90%+ of rules questions with proper citations
2. **Entity Recognition**: 85%+ F1 score on D&D entity extraction from transcripts
3. **Campaign State Accuracy**: Correctly tracks party location, inventory, relationships
4. **Response Latency**: < 3s for simple queries, < 10s for complex generation
5. **User Satisfaction**: DM finds tool useful for actual gameplay

---

## Next Steps

As of 2026-08-05, picking back up after a pause since the last commit (2026-02-19).

**Immediate**
1. Verify the Phase 10 multi-campaign work end-to-end (create → select → scope → chat),
   then commit it — roughly 1,850 uncommitted lines across 28 files
2. Re-populate Neo4j. The database is currently empty (0 nodes); source data for a
   reload sits in `data/graph/` (`nodes/`, `edges/`, `csvs/`) with `backend/load_graph.py`
3. Add the campaign `DELETE` endpoint — the only missing verb in campaign CRUD

**Known gaps worth scheduling**
4. **Authentication** — there is none, and CORS is wide open (`allow_origins=["*"]`).
   Blocks any deployment beyond localhost.
5. **Campaign export/import** — still unbuilt, and now more valuable with multi-campaign
6. **Test isolation** — `tests/test_discord/test_combat_manager.py` requires a live Neo4j
   and fails without it. Should use a fixture or a mocked driver.
7. **Fix the docker-compose healthcheck** — it shells out to `curl`, which no longer
   ships in the `neo4j:5-community` image, so the container reports `unhealthy` forever
   despite serving fine. Use `cypher-shell` instead.
8. **Dynamic difficulty adjustment** — the one Phase 4 capability never built

**Larger directions**
9. Fold the `dm-screen` plugin's D&D Beyond access into the app itself, so adventure
   content can populate the campaign graph directly instead of only rendering to PDF
10. Consolidate the tool surface — `DMTools`, REST, and MCP currently expose overlapping
    functionality through three different interfaces (Section 5.2)
11. **Build the canon graph** (spec stages 4–6) on top of the Phase 11 corpus: layered
    extraction into `plane=canon` nodes, the copy-on-write resolver, and campaign overlays
12. **Chunk page attribution** — chunks currently carry their chapter's *first* page, so a
    citation from p180 of Castle Ravenloft resolves to p96. Fixing it means threading page
    boundaries through `Chapter` into chunking.
13. **Batch API for library-scale ingestion** — 50% cheaper, but a separate code path
    (JSONL upload, polling, result mapping). Not worth it for one book at ~$6; worth
    revisiting at ten books (~$64 → ~$32), where the async turnaround also stops mattering.
