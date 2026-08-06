# Canon Ontology and Copy-on-Write Resolver (Stage 1)

**Date**: 2026-08-06
**Status**: Approved, not yet implemented
**Parent**: [2026-08-05-canon-campaign-graph-design.md](2026-08-05-canon-campaign-graph-design.md)

## Context

The parent spec designed a two-axis knowledge graph — layer (spatial / social / narrative)
× plane (canon / campaign) — and sequenced the work as: ontology and resolver, then
extraction, then read-path integration. This spec is **stage 1**.

Two things changed since the parent was written:

1. **The corpus now exists.** 509 pages of Curse of Strahd are transcribed into 25 chapters
   and 521 chunks in ChromaDB, all tagged `plane=canon`. The narrative vocabulary in the
   parent spec was written before a word of the book had been read.
2. **The graph was wiped.** Neo4j holds zero nodes. Every node the resolver will ever see
   carries `plane`, so there is no legacy branch and no migration path to maintain.

The vocabulary revisions below came out of a design consultation and **amend the parent
spec**; see "Amendments to the parent spec" at the end.

## Ontology

### Relationship types

Six added, one removed. `PURSUING` is defined in `RelationshipType` but referenced nowhere
in the codebase, and it overlaps `SEEKS` closely enough that an extractor would emit both
nondeterministically. Total after this change: **37**.

| Type | Direction | Notes |
|---|---|---|
| `SEEKS` | agent → entity/goal | Carries a free-text `motive` property |
| `OPPOSES` | agent → goal/quest | Distinct from `HOSTILE_TO` — see below |
| `IDENTITY_OF` | persona → persona | Carries `nature`: reincarnation / disguise / transformation |
| `RESOLVES_TO` | entity → candidate | **Resolvable**: campaign edges shadow canon fan-out |
| `PREREQUISITE_OF` | entity/goal → goal | Hard gates only; expect ~a dozen in the whole book |
| `THREATENS` | agent → entity/location | Standing danger not reducible to a contested object |

**Why `SEEKS` rather than `MOTIVATES`.** The parent spec proposed `MOTIVATES`, whose
subject is a *reason* — and reasons are prose, not nodes. They do not traverse. `SEEKS`
points from an agent to the thing it wants, which does. It is also far easier to extract
reliably: Curse of Strahd states wants explicitly in its NPC sidebars, whereas `MOTIVATES`
would require the extractor to infer psychology. Nuance lives in the `motive` property,
where nuance belongs; the type carries only traversal semantics.

**Why `OPPOSES` is not `HOSTILE_TO`.** Vladimir Horngaard hates Strahd *and* will fight the
party to stop them destroying him, because for Vladimir, Strahd's death is mercy. That is
`HOSTILE_TO → Strahd` plus `OPPOSES → destroy-strahd`. A social edge between two agents is
structurally incapable of expressing opposition to a *goal*.

### `IDENTITY_OF` and the alias spoiler leak

The parent spec's "one node per entity" would put Rictavio and Van Richten on one node with
`aliases: ["Van Richten"]`. Because the resolver merges properties with `apoc.map.merge`,
the moment a campaign node materializes ("party met Rictavio, session 2") the **table view
carries the alias** — and a recap generator spoils chapter eleven.

The rule becomes **one node per persona the table can know independently**, with a secret
identity modelled as an edge carrying its own `revealed_in_session`. This is ordinary record
linkage: keep the records separate, make the link an assertion with provenance, rather than
collapsing them and losing the ability to say *when* the link became known.

```
Rictavio --IDENTITY_OF{nature: disguise, revealed_in_session: null}--> Van Richten
Ireena   --IDENTITY_OF{nature: reincarnation, revealed_in_session: 4}--> Tatyana
```

The resolver needs **no special case** for it. Truth view traverses the edge; table view
applies the same reveal filter it applies to everything else. If the party has met Rictavio
and separately heard the legend of Van Richten, both nodes are visible and only the link is
hidden — which is correct.

**Extraction rule this implies:** `aliases` holds surface variants of a *single* persona
("Ismark the Lesser" / "Ismark Kolyanovich"). A different persona is a different node plus
an `IDENTITY_OF` edge. Tatyana is not an alias of Ireena; she is a historical figure with
her own lore edges.

### `LAYER_MAP` must be total

Every relationship type maps to exactly one layer or to `None`. A partial map silently
mis-counts intersection queries, which are the payoff of the layer axis. `None` is an
explicit value meaning "not a surface" — plane-linking, character-sheet, and runtime edges.

| Layer | Types |
|---|---|
| `spatial` (4) | `LOCATED_IN`, `CONTAINS`, `CONNECTED_TO`, `TRAVELED_TO` |
| `social` (10) | `KNOWS`, `ALLIED_WITH`, `HOSTILE_TO`, `ENEMY_OF`, `MEMBER_OF`, `SERVES`, `RELATED_TO`, `OWNS`, `GUARDS`, `WIELDS` |
| `narrative` (9) | `SEEKS`, `OPPOSES`, `RESOLVES_TO`, `PREREQUISITE_OF`, `IDENTITY_OF`, `THREATENS`, `GAVE_QUEST`, `COMPLETED`, `OBJECTIVE_AT` |
| `None` (14) | `INSTANCE_OF`, `BELONGS_TO`, `PLAYS_AS`, `ATTENDED`, `HAS_CLASS`, `HAS_RACE`, `HAS_SUBCLASS`, `CONTROLLED_BY`, `IN_COMBAT_WITH`, `LAST_SPOKE_TO`, `KILLED`, `PARTICIPATED_IN`, `OCCURRED_AT`, `OCCURRED_IN` |

**`OBJECTIVE_AT` is narrative, not spatial.** It points at a LOCATION, but the edge is about
the quest. That assignment is what turns the location into an intersection node — it gains a
narrative edge alongside its spatial ones — and is therefore what makes "which places matter
to the plot" computable rather than authored.

A test asserts every `RelationshipType` member appears in `LAYER_MAP`, so adding a type
without classifying it fails the suite rather than silently degrading queries.

### Properties

| Property | Applies to | Notes |
|---|---|---|
| `plane` | all nodes | `'canon'` or `'campaign'`; no node may omit it |
| `source_book` | canon nodes | e.g. `'cos'` |
| `canon_id` | campaign nodes | Denormalized `INSTANCE_OF` target, for indexing. The edge is authoritative. |
| `revealed_in_session` | campaign nodes and edges | `int` or `null` |
| `source_chunk_ids` | canon nodes | Links back to ChromaDB prose |
| `layer` | all surface edges | `'spatial'` / `'social'` / `'narrative'` |
| `motive` | `SEEKS` edges | Free text |
| `nature` | `IDENTITY_OF` edges | `reincarnation` / `disguise` / `transformation` |

No new `EntityType` members. The existing 18 cover what canon needs.

## Resolver

One function, in `backend/graph/operations.py`:

```python
resolve(campaign_id, perspective='truth'|'table', layers=None,
        entity_type=None, source_book=None, as_of_session=None)
```

- `layers=None` returns all layers; `layers=['social']` traverses only that surface.
- `as_of_session` is meaningful **only** for `perspective='table'`; passing it with
  `'truth'` raises rather than being silently ignored.
- **Truth view**: campaign plane merged over canon, no reveal filter.
- **Table view**: campaign plane only, filtered to `revealed_in_session <= N`. Canon is
  deliberately invisible — canon is the book, not what the party knows.

Node resolution needs two `UNION` branches: canon entities with campaign overrides merged
over them, and campaign-only entities that have no `INSTANCE_OF` to merge against. A
canon-rooted query alone silently drops everything a table invented.

Edge resolution branches on `RESOLVABLE_TYPES = {"RESOLVES_TO"}`: resolvable types drop all
canon edges of that type when the campaign plane has any; everything else unions.

**No legacy branch.** The graph is empty, so every node carries `plane`. This is a
deliberate simplification bought by wiping rather than migrating.

Indexes required on `plane`, `canon_id`, `campaign_id`.

## Barovia seed

`backend/canon/seeds/village-of-barovia.yaml` — hand-authored, committed (note `data/` is
gitignored, so seeds cannot live there), roughly 25–30 nodes covering chapter 3.

Contents chosen to exercise every narrative type at least once:

- **NPCs**: Ireena Kolyana, Ismark Kolyanovich, Donavich, Doru, Mad Mary, Bildrath,
  Parriwimple, Morgantha
- **Locations**: Village of Barovia, Burgomaster's Mansion, Bildrath's Mercantile, Blood of
  the Vine Tavern, Church of Barovia
- **Narrative**: `Strahd SEEKS Ireena{motive}`, `Ireena IDENTITY_OF Tatyana{reincarnation}`
  unrevealed, `Ismark GAVE_QUEST escort-ireena`, `Donavich SEEKS doru-salvation`,
  `escort-ireena OBJECTIVE_AT Vallaki`, one `RESOLVES_TO` fan-out
- **Spatial**: containment from village down to buildings
- **Social**: the Kolyana sibling relation, Donavich→Doru, dispositions

A loader reads the YAML into Neo4j with deterministic IDs (`cos:npc:ireena-kolyana`).

**This doubles as stage 2's golden set.** The parent spec already calls for a hand-checked
answer key for one chapter; authoring it now means the ontology is exercised against real
material before an extractor is built against it, and when extraction lands the answer key
already exists. Authoring it after extraction risks grading the extractor against its own
output.

## Testing

- **Merge semantics** — canon passthrough; campaign override; sparse patch does not clobber
  unset canon fields; campaign-only node with no `INSTANCE_OF`; additive edges union;
  resolvable edges shadow.
- **Spoiler containment, as a property test** — for any campaign and any session N, the
  table view returns nothing with `revealed_in_session > N` and nothing from the canon
  plane. This now covers identity edges, which is the case that matters most.
- **`LAYER_MAP` totality** — every `RelationshipType` member is classified.
- **Seed integrity** — the YAML loads, produces the expected node and edge counts, and every
  edge type it uses exists in `RelationshipType`.
- **Intersection query** — returns exactly the locations carrying narrative edges.

Ephemeral fixture graph seeded and torn down per test, never the live database.

## Out of scope

- **Extraction** (stage 2) — no LLM extraction of any kind here
- **Read-path integration** (stage 3) — query planner layer/perspective selection
- **The diff endpoint** — "how far has this table drifted from canon" is a demo nobody asks
  mid-session; it should not compete with the resolver for build time
- Migration of pre-existing data — there is none

## Amendments to the parent spec

These supersede the parent where they conflict:

1. **Narrative vocabulary.** `MOTIVATES` is dropped in favour of `SEEKS`. `OPPOSES` and
   `IDENTITY_OF` are added. Final narrative set: `SEEKS`, `OPPOSES`, `RESOLVES_TO`,
   `PREREQUISITE_OF`, `IDENTITY_OF`, `THREATENS` (plus the three pre-existing quest types).
2. **"One node per entity"** becomes **"one node per persona the table can know
   independently."** Secret identities are edges, not aliases.
3. **`OWNS` and `GUARDS` are layered** (social). The parent's layer table omitted them
   despite their being load-bearing narrative facts.
4. **`RESOLVES_TO` covers five fan-outs per table**, not three: the Tarokka reading also
   randomizes the party's ally and the site of the final confrontation.
5. **No legacy/migration branch in the resolver** — the graph was wiped.

## Known risks

**Narrative-layer recall is the load-bearing unknown.** Spatial extraction will be near
perfect because containment is stated typographically (room keys, chapter structure). Social
and narrative depend on inference. The failure mode is asymmetric and nasty: vector search
degrades *visibly*, but a graph query over 80%-recall narrative edges returns a confident,
silently incomplete answer — and a DM burned once stops trusting the system. Stage 2's
review gate must audit narrative-layer recall specifically, not overall entity counts.

**The social layer is the weakest retrieval story.** Social facts cluster locally in prose,
so vector search over one chapter answers "who does Ireena know" perfectly well. The social
layer's real justification is feeding NPC agent behaviour with structured dispositions and
loyalties — a different purpose than lookup. Worth being clear-eyed that it is built for the
agents, not the queries.

**The graph's table-time value concentrates at the canon×campaign seam.** Before any play
happens, it beats vector search only on cross-chapter joins. The compounding returns start
when sessions write against canon — which argues for pointing transcript ingestion at canon
nodes soon after stage 2.
