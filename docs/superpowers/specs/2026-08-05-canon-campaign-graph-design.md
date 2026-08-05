# Layered Canon & Campaign Knowledge Graph

**Date**: 2026-08-05
**Status**: Approved, not yet implemented

## Problem

The knowledge graph today has one plane and one undifferentiated edge space. Every
campaign's entities live alongside each other, distinguished only by a `BELONGS_TO` edge,
and every relationship — spatial, social, narrative — is just an edge. Two consequences:

1. **No shared canon.** Published setting material (Curse of Strahd) can only be loaded
   into one campaign at a time, or duplicated per campaign. There is no notion of
   "official" content that many tables draw on.
2. **No structural traversal.** "Who does Ireena know" and "what is north of Vallaki" hit
   the same undifferentiated edge set. Retrieval cannot narrow by the *kind* of question.

## Goal

Model published setting material as a shared canon graph, and each table's play as a
personal graph that inherits from canon and diverges over time — while making the graph
traversable by the kind of structure being asked about.

## The Model: Two Axes

```
                    CANON PLANE                 CAMPAIGN PLANE (per table)
                 ┌──────────────────┐          ┌──────────────────┐
   SPATIAL       │  Barovia         │          │  ...as explored  │
   surface       │  K1..K88, roads  │──────────│  visited, burned │
                 └──────────────────┘          └──────────────────┘
                 ┌──────────────────┐          ┌──────────────────┐
   SOCIAL        │  Strahd, Ireena  │──────────│  ...as met       │
   surface       │  factions        │          │  killed, allied  │
                 └──────────────────┘          └──────────────────┘
                 ┌──────────────────┐          ┌──────────────────┐
   NARRATIVE     │  curse, Tarokka  │──────────│  ...as resolved  │
   surface       │  3 treasures     │          │  cards drawn     │
                 └──────────────────┘          └──────────────────┘
```

- **Layer** (spatial | social | narrative) — what kind of structure an edge expresses.
- **Plane** (canon | campaign) — whose truth a node represents.

The axes are independent. Every layer exists in both planes.

### Intersection points

A node is "on" a surface if it has edges in that layer. Nodes with edges in two or more
layers are intersection points, and they are the load-bearing entities:

| Node | Spatial | Social | Narrative |
|---|:---:|:---:|:---:|
| Ireena Kolyana | in Barovia, moves | Ismark's sister | Tatyana reincarnate |
| Castle Ravenloft | contains K1–K88 | Strahd's seat | the finale |
| Madam Eva | Tser Pool | Vistani leader | delivers the Tarokka reading |
| Sunsword | resolves to 1 of ~10 sites | tied to Argynvost | 1 of 3 treasures |

Intersection points are **derived, never stored**. "Which places matter to the plot" is
the query "which nodes have both spatial and narrative edges."

## Design Decisions

### 1. Shared nodes, layered edges

One node per entity. Every relationship carries a `layer` property. Traversing a surface
means filtering edges by layer.

Rejected: layer-local nodes joined by bridge edges (the textbook multiplex formalism).
It matches the "separate surfaces" metaphor more literally, but costs 2–3× the nodes and
requires keeping identity in sync across them. It only pays off when the same entity needs
*conflicting* properties on different surfaces, which this material does not demand.

### 2. Copy-on-write between planes

The campaign plane starts empty. Reads fall through to canon. The first write to a canon
entity materializes a campaign node holding **only the overridden properties**, linked by
`INSTANCE_OF → canon node`.

- A table-invented entity is a campaign node with no `INSTANCE_OF`. No special case.
- Canon is **append-only from ingestion and never mutated by play**. Destruction is a
  campaign-plane `status` override, not a delete. Canon stays reusable across every table.
- The campaign plane is therefore "diff from canon **plus** discovery log" — not diff
  alone, because recording what a party learned materializes a node even when nothing
  diverged. Accepted deliberately.

Rejected: **eager fork** (clone canon per campaign) — simpler reads, but full duplication
per table, canon corrections never propagate, and divergence stops being queryable.
Rejected: **event-log overlay** — gets time-travel, but needs materialized-state caching
for a benefit `revealed_in_session` already approximates.

### 3. Resolvable relationship types

Overrides must work on edges, not just properties. Curse of Strahd's Tarokka reading is
the proving case: canon fans out to ten candidate locations per treasure, and a table's
card draw collapses that to one.

```python
RESOLVABLE_TYPES = {"RESOLVES_TO"}   # campaign edges shadow canon edges of this type
# all other types are additive: campaign edges union with canon edges
```

Resolvability is declared in the ontology, not inferred.

### 4. Reveal tracking as a property, not a dimension

Campaign nodes and edges carry `revealed_in_session: int | null`. An integer rather than
a boolean, so "what did the party know as of session 4" is free — which is what recaps
and journaling need.

Rejected: a third audience dimension. It triples the surface count to express a filter.

### 5. Two peer read perspectives

| Perspective | Reads | Used by |
|---|---|---|
| `truth` | campaign plane merged over canon, no reveal filter | generators, NPC behavior, encounter building |
| `table` | **campaign plane only**, `revealed_in_session <= N` | journaling, recaps, summarization, player-facing answers |

The asymmetry is the spoiler defense. Canon is invisible to the table view because canon
is the book, not something the party knows. A party learning a fact is what materializes a
campaign node with a reveal stamp.

**Perspective has no default.** Callers state it explicitly. Given generators consume this
graph, an inherited default is a spoiler leak waiting to happen — better to fail loudly.

## Ontology Changes

### Layers

| Layer | Relationship types |
|---|---|
| `spatial` | `CONTAINS`, `CONNECTED_TO`, `LOCATED_IN` |
| `social` | `KNOWS`, `RELATED_TO`, `SERVES`, `MEMBER_OF`, `ALLIED_WITH`, `HOSTILE_TO` |
| `narrative` | `MOTIVATES`, `RESOLVES_TO`, `PREREQUISITE_OF`, `THREATENS` |

### New relationship types

Four, all narrative-layer: `MOTIVATES`, `RESOLVES_TO`, `PREREQUISITE_OF`, `THREATENS`.
Spatial and social are already covered by the existing enum.

### New entity types

None. The existing `EntityType` covers NPC, LOCATION, ITEM, MONSTER, FACTION, QUEST,
EVENT, LORE.

### Node properties

| Property | Applies to | Notes |
|---|---|---|
| `plane` | all | `'canon'` or `'campaign'` |
| `source_book` | canon | e.g. `'dnd/cos'` |
| `canon_id` | campaign | denormalized target of `INSTANCE_OF`, for indexing |
| `revealed_in_session` | campaign | `int` or `null` |
| `source_chunk_ids` | canon | links graph node back to ChromaDB prose |

### Edge properties

| Property | Notes |
|---|---|
| `layer` | `'spatial' \| 'social' \| 'narrative'` |
| `revealed_in_session` | campaign-plane edges only |

`INSTANCE_OF` and `BELONGS_TO` are plane-linking edges and carry no layer.

### What this invalidates

`backend/graph/operations.py:187` currently scopes with:

```cypher
WHERE (e)-[:BELONGS_TO]->(:Entity {id: $campaign_id})
   OR NOT e.entity_type IN $scoped_types
```

A canon NPC is a campaign-scoped type with no `BELONGS_TO`, so this query **excludes** it.
The filter must become plane-aware. This is the one existing behavior the design breaks
rather than extends.

## The Resolver

All reads go through one function:

```python
resolve(campaign_id, perspective='truth'|'table', layers=None,
        as_of_session=None) -> Entities | Edges
```

Node resolution, using APOC (already enabled in `docker-compose.yml`):

```cypher
MATCH (canon:Entity {plane:'canon', source_book:$book})
WHERE canon.entity_type = $type
OPTIONAL MATCH (camp:Entity {plane:'campaign'})-[:INSTANCE_OF]->(canon)
  WHERE (camp)-[:BELONGS_TO]->(:Entity {id:$campaign_id})
RETURN apoc.map.merge(properties(canon), properties(camp)) AS entity
```

Campaign nodes store only overridden properties, so `properties(camp)` is a sparse patch.

Edge resolution branches on `RESOLVABLE_TYPES`: resolvable types drop all canon edges of
that type when the campaign plane has any; everything else unions.

**Containment matters more than the query text.** The two-hop merge is a real cost, and
the failure mode is it leaking into a dozen call sites. One resolver, called everywhere.

Indexes required: `plane`, `canon_id`, `campaign_id`.

## Canon Extraction

New module, `backend/canon/`. Deliberately **not** an extension of `backend/ner/`: that
pipeline targets transcripts — noisy speech, unknown speakers, coreference, low confidence.
Book extraction is clean prose with headings, a known cast, and a hard precision bar
because generators treat the output as truth. Different problem, different module. The one
piece worth reusing is `ner/resolution/` for cross-chapter dedupe.

**Stage 1 — extract per chapter, per layer.** Three focused passes per chapter, each with
a narrow schema, rather than one general prompt. A spatial pass that only cares about
containment produces markedly cleaner output. ~15 chapters × 3 layers ≈ 45 calls.

**Stage 2 — resolve globally.** Strahd appears in a dozen chapters; candidates collapse to
one node. This is the stage most likely to need iteration.

**Deterministic IDs**, so re-runs update in place rather than duplicating:

```
cos:npc:ireena-kolyana
cos:location:castle-ravenloft:k37
```

Extraction over a 500-page book will be re-run several times before it is right, so this
matters more than it appears.

**Graph ↔ prose link.** Canon nodes store the chunk IDs they were extracted from, so
hybrid RAG can traverse structure and then fetch the actual text.

**Review before commit**, consistent with the existing transcript pipeline. Higher stakes
here, since canon is shared across every table.

### Source risk

`data/cos.pdf` is **unusable as a text source**: 224 MB, 509 pages, every page a single
image with ~100 characters of browser print-header text. It is a print-to-PDF of an
AnyFlip flipbook.

Primary source is the D&D Beyond MCP (`ddb_read_book`, book slug `dnd/cos`, owned).
As of 2026-08-05 it timed out three times at 45s on `networkidle`, on both the TOC and a
chapter. The `dm-screen` plugin uses the same MCP successfully, suggesting a transient
issue. Mitigations, in order: retry; have the MCP wait on `domcontentloaded` instead of
`networkidle`; fall back to vision extraction over the PDF page images — more expensive,
but it handles maps and stat blocks that DDB text renders poorly anyway.

## Read Path Integration

`rag/query_planner.py` already classifies queries; it gains two outputs — layer and
perspective. "Where's the Sunsword" → narrative. "Who does Ireena know" → social. "What's
north of Vallaki" → spatial.

Layer selection is a retrieval win independent of the canon work: today those queries
search every edge in the graph.

**API surface** — canon is read-mostly, so it is small:
- list/get canon entities by book
- a diff endpoint: how far has this table drifted from canon
- `layer` and `perspective` as query params on existing campaign entity routes

## Testing

- **Merge semantics** — canon-only passthrough; campaign property override; sparse patch
  does not clobber unset canon fields; pure-campaign node with no `INSTANCE_OF`; additive
  edges union; resolvable edges shadow.
- **Spoiler containment**, as a property test — *for any campaign and any session N, the
  table view returns nothing with `revealed_in_session > N` and nothing from the canon
  plane.* This is the guarantee the whole design rests on.
- **Idempotent extraction** — ingesting a chapter twice yields the same node count.
- **Extraction quality** — hand-checked golden set for one chapter (Village of Barovia is
  small and self-contained), asserting recall on known entities rather than exact match.

**Ephemeral fixtures, not the live database.** `tests/test_discord/test_combat_manager.py`
connects to a running Neo4j, which is why those 11 tests fail when it is down. Canon tests
seed and tear down a fixture graph per test.

## Out of Scope

- Migrating existing campaign data into the two-plane model
- Canon for books other than Curse of Strahd
- Cross-campaign queries ("how did other tables resolve this Tarokka draw")
- Canon versioning or errata propagation
