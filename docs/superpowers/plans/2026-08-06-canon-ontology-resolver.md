# Canon Ontology and Resolver (Stage 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the layered ontology and the copy-on-write resolver that merges per-table campaign state over shared canon, verified against a hand-authored Village of Barovia seed.

**Architecture:** The ontology (relationship types, a total type→layer map, resolvable types) lives in `backend/graph/schema.py` beside the existing enums. Two-plane read resolution lives in a new `backend/graph/resolver.py`. Cypher fetches candidate rows; the merge and shadow decisions happen in pure Python functions that need no database, so the logic that actually decides what a table sees is unit-testable in isolation. A YAML seed of chapter 3 exercises every narrative relationship type against real material.

**Tech Stack:** Python 3.12, Neo4j 5 (bolt), PyYAML 6, pytest + pytest-asyncio.

## Two deliberate deviations from the spec

Both are improvements found while mapping the code. **If a reviewer disagrees, the spec wins and this plan should change** — but each has a concrete reason:

1. **Resolver in `backend/graph/resolver.py`, not `operations.py`.** The spec says `operations.py`; that file is already 950+ lines with 30 methods spanning entities, relationships, players, campaigns and sessions. Adding two-plane resolution would push it past 1,000 and mix a distinct concern into CRUD. A new module keeps the "one place all reads go through" property the spec actually cares about.
2. **Merge and shadow in Python, not APOC Cypher.** The spec's node query uses `apoc.map.merge`. Doing the merge and the resolvable-edge shadowing as pure functions makes both testable with no database at all, and drops an APOC dependency from the hot read path. Cypher still does the matching and filtering.

Also: the spec's single `resolve(...) -> Entities | Edges` becomes three methods on one class (`entities`, `edges`, `intersections`). One function returning two unrelated shapes is a poor interface; the containment intent is preserved by there being exactly one resolver.

## Global Constraints

- Python `>=3.12`. Builtin generics (`list[str]`, `str | None`), never `typing.List`.
- Ruff: `line-length = 100`, `target-version = "py312"`, rules `["E", "F", "I", "UP"]`.
- Async tests require an explicit `@pytest.mark.asyncio` decorator (pytest-asyncio 1.3.0, strict mode). This plan has no async code.
- **Every node carries `plane`.** The graph was wiped; there is no legacy branch and no missing-property case to handle.
- Truth view = campaign merged over canon, no reveal filter. Table view = **campaign plane only**, `revealed_in_session <= N`. Canon is never visible to the table view.
- `as_of_session` is meaningful only for `perspective='table'`; passing it with `'truth'` raises `ValueError`.
- `RESOLVABLE_TYPES = {RelationshipType.RESOLVES_TO}`.
- Deterministic canon IDs: `cos:npc:ireena-kolyana`, `cos:location:village-of-barovia`.
- `data/` is gitignored — the seed must live under `backend/canon/seeds/`.
- Tests touching Neo4j carry `@pytest.mark.neo4j` and clean up after themselves.

---

## File Structure

**Created:**
- `backend/graph/resolver.py` — `PlaneResolver`, plus the pure `merge_properties` / `shadow_edges` functions
- `backend/canon/seeds/village-of-barovia.yaml` — hand-authored chapter 3 canon
- `backend/canon/seed_loader.py` — loads a seed YAML into Neo4j
- `tests/test_graph/test_layer_map.py`
- `tests/test_graph/test_resolver_pure.py` — merge/shadow, no database
- `tests/test_graph/test_resolver_neo4j.py` — the Cypher paths
- `tests/test_canon/test_seed_loader.py`
- `tests/conftest.py` — the `neo4j` marker and cleanup fixture

**Modified:**
- `backend/graph/schema.py` — 6 new relationship types, `PURSUING` removed, `Layer`, `LAYER_MAP`, `RESOLVABLE_TYPES`
- `pyproject.toml` — register the `neo4j` pytest marker

---

### Task 1: Ontology — types, layers, resolvable set

**Files:**
- Modify: `backend/graph/schema.py`
- Modify: `pyproject.toml`
- Create: `tests/test_graph/test_layer_map.py`
- Create: `tests/conftest.py`

**Interfaces:**
- Consumes: existing `RelationshipType`, `EntityType` in `backend/graph/schema.py`
- Produces: `Layer` (str enum: `SPATIAL`/`SOCIAL`/`NARRATIVE`), `LAYER_MAP: dict[RelationshipType, Layer | None]`, `RESOLVABLE_TYPES: set[RelationshipType]`, and six new `RelationshipType` members: `SEEKS`, `OPPOSES`, `IDENTITY_OF`, `RESOLVES_TO`, `PREREQUISITE_OF`, `THREATENS`

- [ ] **Step 1: Write the failing test**

Create `tests/test_graph/test_layer_map.py`:

```python
"""The type->layer map must be total: a missing entry silently mis-counts
intersection queries, which are the payoff of the layer axis."""

from backend.graph.schema import LAYER_MAP, RESOLVABLE_TYPES, Layer, RelationshipType


class TestLayerMapTotality:
    def test_every_relationship_type_is_classified(self):
        missing = [r.value for r in RelationshipType if r not in LAYER_MAP]
        assert missing == [], f"unclassified relationship types: {missing}"

    def test_no_stale_entries(self):
        stale = [r for r in LAYER_MAP if r not in set(RelationshipType)]
        assert stale == []

    def test_values_are_layer_or_none(self):
        for rel, layer in LAYER_MAP.items():
            assert layer is None or isinstance(layer, Layer), f"{rel} -> {layer!r}"


class TestNarrativeVocabulary:
    def test_new_types_exist(self):
        for name in (
            "SEEKS",
            "OPPOSES",
            "IDENTITY_OF",
            "RESOLVES_TO",
            "PREREQUISITE_OF",
            "THREATENS",
        ):
            assert hasattr(RelationshipType, name), f"missing {name}"

    def test_pursuing_removed(self):
        """Folded into SEEKS so an extractor cannot emit both."""
        assert not hasattr(RelationshipType, "PURSUING")

    def test_new_types_are_narrative(self):
        for name in ("SEEKS", "OPPOSES", "IDENTITY_OF", "RESOLVES_TO",
                     "PREREQUISITE_OF", "THREATENS"):
            assert LAYER_MAP[RelationshipType[name]] is Layer.NARRATIVE

    def test_objective_at_is_narrative_not_spatial(self):
        """It points at a LOCATION, but the edge is about the quest -- this is
        what makes that location an intersection node."""
        assert LAYER_MAP[RelationshipType.OBJECTIVE_AT] is Layer.NARRATIVE

    def test_possession_is_social(self):
        assert LAYER_MAP[RelationshipType.OWNS] is Layer.SOCIAL
        assert LAYER_MAP[RelationshipType.GUARDS] is Layer.SOCIAL

    def test_plane_linking_edges_are_not_surfaces(self):
        assert LAYER_MAP[RelationshipType.INSTANCE_OF] is None
        assert LAYER_MAP[RelationshipType.BELONGS_TO] is None


class TestResolvableTypes:
    def test_only_resolves_to_is_resolvable(self):
        assert RESOLVABLE_TYPES == {RelationshipType.RESOLVES_TO}
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_graph/test_layer_map.py -v`
Expected: FAIL with `ImportError: cannot import name 'LAYER_MAP'`

- [ ] **Step 3: Add the new relationship types**

In `backend/graph/schema.py`, inside `RelationshipType`, **delete** the line
`PURSUING = "PURSUING"` (it is defined but referenced nowhere in the codebase — verified by
grep), and add a narrative block after the `# Quest/Narrative` group:

```python
    # Narrative layer
    SEEKS = "SEEKS"  # Agent -> what it wants; carries a free-text `motive`
    OPPOSES = "OPPOSES"  # Agent -> goal it works against (distinct from HOSTILE_TO)
    IDENTITY_OF = "IDENTITY_OF"  # Persona -> persona; carries `nature`
    RESOLVES_TO = "RESOLVES_TO"  # Canon fan-out a table's draw collapses
    PREREQUISITE_OF = "PREREQUISITE_OF"  # Hard gate
    THREATENS = "THREATENS"  # Standing danger
```

- [ ] **Step 4: Add `Layer`, `LAYER_MAP`, `RESOLVABLE_TYPES`**

Append to `backend/graph/schema.py`, after the `RelationshipType` class:

```python
class Layer(str, Enum):
    """A surface of the graph. Edges carry exactly one, or none."""

    SPATIAL = "spatial"
    SOCIAL = "social"
    NARRATIVE = "narrative"


# Every RelationshipType maps to a layer or explicitly to None. None means "not a
# surface": plane-linking, character-sheet, and runtime edges. A partial map would
# silently mis-count intersection queries, so tests assert this is total.
LAYER_MAP: dict[RelationshipType, Layer | None] = {
    # Spatial
    RelationshipType.LOCATED_IN: Layer.SPATIAL,
    RelationshipType.CONTAINS: Layer.SPATIAL,
    RelationshipType.CONNECTED_TO: Layer.SPATIAL,
    RelationshipType.TRAVELED_TO: Layer.SPATIAL,
    # Social
    RelationshipType.KNOWS: Layer.SOCIAL,
    RelationshipType.ALLIED_WITH: Layer.SOCIAL,
    RelationshipType.HOSTILE_TO: Layer.SOCIAL,
    RelationshipType.ENEMY_OF: Layer.SOCIAL,
    RelationshipType.MEMBER_OF: Layer.SOCIAL,
    RelationshipType.SERVES: Layer.SOCIAL,
    RelationshipType.RELATED_TO: Layer.SOCIAL,
    RelationshipType.OWNS: Layer.SOCIAL,
    RelationshipType.GUARDS: Layer.SOCIAL,
    RelationshipType.WIELDS: Layer.SOCIAL,
    # Narrative
    RelationshipType.SEEKS: Layer.NARRATIVE,
    RelationshipType.OPPOSES: Layer.NARRATIVE,
    RelationshipType.RESOLVES_TO: Layer.NARRATIVE,
    RelationshipType.PREREQUISITE_OF: Layer.NARRATIVE,
    RelationshipType.IDENTITY_OF: Layer.NARRATIVE,
    RelationshipType.THREATENS: Layer.NARRATIVE,
    RelationshipType.GAVE_QUEST: Layer.NARRATIVE,
    RelationshipType.COMPLETED: Layer.NARRATIVE,
    RelationshipType.OBJECTIVE_AT: Layer.NARRATIVE,
    # Structural: plane-linking, character sheet, runtime, campaign history
    RelationshipType.INSTANCE_OF: None,
    RelationshipType.BELONGS_TO: None,
    RelationshipType.PLAYS_AS: None,
    RelationshipType.ATTENDED: None,
    RelationshipType.HAS_CLASS: None,
    RelationshipType.HAS_RACE: None,
    RelationshipType.HAS_SUBCLASS: None,
    RelationshipType.CONTROLLED_BY: None,
    RelationshipType.IN_COMBAT_WITH: None,
    RelationshipType.LAST_SPOKE_TO: None,
    RelationshipType.KILLED: None,
    RelationshipType.PARTICIPATED_IN: None,
    RelationshipType.OCCURRED_AT: None,
    RelationshipType.OCCURRED_IN: None,
}

# Campaign edges of these types SHADOW canon edges of the same type from the same
# source, rather than adding to them. This is the Tarokka collapse: canon fans out to
# ten candidate sites, a table's draw resolves it to one.
RESOLVABLE_TYPES: set[RelationshipType] = {RelationshipType.RESOLVES_TO}
```

- [ ] **Step 5: Add the indexes the resolver needs**

Every resolver query filters on `plane`, and campaign nodes are looked up by `canon_id`.
In `backend/graph/schema.py`, add to `GRAPH_SCHEMA["indexes"]`:

```python
        "CREATE INDEX entity_plane IF NOT EXISTS FOR (e:Entity) ON (e.plane)",
        "CREATE INDEX entity_canon_id IF NOT EXISTS FOR (e:Entity) ON (e.canon_id)",
```

The spec also lists `campaign_id`, but campaign membership is a `BELONGS_TO` edge to a node
found by `id`, which the existing unique constraint already indexes. No third index is
needed; note that in your report rather than adding a dead one.

- [ ] **Step 6: Register the pytest marker**

Add to `pyproject.toml` (create the section if absent):

```toml
[tool.pytest.ini_options]
markers = [
    "neo4j: test requires a running Neo4j (docker compose up -d); deselect with -m 'not neo4j'",
]
```

If `[tool.pytest.ini_options]` already exists, add only the `markers` key. Do not remove
existing keys.

Create `tests/conftest.py`:

```python
"""Shared fixtures. Neo4j-backed tests clean up the nodes they create."""

import pytest

from backend.core.database import neo4j_session

TEST_ID_PREFIX = "pytest:"


@pytest.fixture
def graph():
    """Yield a Neo4j session; delete every node this test created on teardown.

    Nodes are identified by an id starting with TEST_ID_PREFIX, so this never
    touches real data even when pointed at a populated database.
    """
    with neo4j_session() as session:
        session.run(
            "MATCH (n:Entity) WHERE n.id STARTS WITH $p DETACH DELETE n",
            {"p": TEST_ID_PREFIX},
        )
        yield session
        session.run(
            "MATCH (n:Entity) WHERE n.id STARTS WITH $p DETACH DELETE n",
            {"p": TEST_ID_PREFIX},
        )
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/test_graph/test_layer_map.py -v`
Expected: 10 passed

- [ ] **Step 8: Confirm nothing regressed**

Run: `uv run pytest -q`
Expected: 236 existing tests still pass plus the 10 new ones. `PURSUING` was unused, so
its removal should break nothing — if anything fails, report it rather than restoring the
member.

- [ ] **Step 9: Commit**

```bash
git add backend/graph/schema.py pyproject.toml tests/conftest.py tests/test_graph/test_layer_map.py
git commit -m "feat(graph): add narrative relationship types and a total layer map"
```

---

### Task 2: Pure merge and shadow functions

The two decisions that determine what a table actually sees, isolated from Neo4j so they
can be tested exhaustively without a database.

**Files:**
- Create: `backend/graph/resolver.py`
- Create: `tests/test_graph/test_resolver_pure.py`

**Interfaces:**
- Consumes: `RESOLVABLE_TYPES` from `backend/graph/schema.py` (Task 1)
- Produces:
  - `merge_properties(canon: dict, campaign: dict | None) -> dict`
  - `shadow_edges(canon_edges: list[dict], campaign_edges: list[dict]) -> list[dict]` where an edge is a dict with at least `source_id`, `target_id`, `rel_type`, `layer`

- [ ] **Step 1: Write the failing test**

Create `tests/test_graph/test_resolver_pure.py`:

```python
"""Merge and shadow decide what a table sees. No database involved."""

from backend.graph.resolver import merge_properties, shadow_edges


def edge(source, rel_type, target, layer="narrative", plane="canon"):
    return {
        "source_id": source,
        "target_id": target,
        "rel_type": rel_type,
        "layer": layer,
        "plane": plane,
    }


class TestMergeProperties:
    def test_canon_only_passes_through(self):
        canon = {"id": "cos:npc:ireena", "name": "Ireena", "status": "alive"}
        assert merge_properties(canon, None) == canon

    def test_campaign_overrides_win(self):
        canon = {"id": "cos:npc:ireena", "name": "Ireena", "status": "alive"}
        camp = {"status": "dead"}
        assert merge_properties(canon, camp)["status"] == "dead"

    def test_sparse_patch_does_not_clobber_unset_canon_fields(self):
        canon = {"id": "x", "name": "Ireena", "description": "burgomaster's sister"}
        merged = merge_properties(canon, {"status": "dead"})
        assert merged["description"] == "burgomaster's sister"
        assert merged["name"] == "Ireena"

    def test_empty_campaign_patch_is_a_noop(self):
        canon = {"id": "x", "name": "Ireena"}
        assert merge_properties(canon, {}) == canon

    def test_inputs_are_not_mutated(self):
        canon = {"id": "x", "name": "Ireena"}
        camp = {"status": "dead"}
        merge_properties(canon, camp)
        assert canon == {"id": "x", "name": "Ireena"}
        assert camp == {"status": "dead"}


class TestShadowEdges:
    def test_additive_types_union(self):
        canon = [edge("strahd", "SEEKS", "ireena")]
        campaign = [edge("strahd", "SEEKS", "tatyana", plane="campaign")]
        result = shadow_edges(canon, campaign)
        assert len(result) == 2

    def test_resolvable_type_shadows_canon_fan_out(self):
        """The Tarokka collapse: ten canon candidates become the one drawn."""
        canon = [
            edge("cos:item:sunsword", "RESOLVES_TO", f"cos:location:site-{i}")
            for i in range(10)
        ]
        campaign = [
            edge("cos:item:sunsword", "RESOLVES_TO", "cos:location:amber-temple",
                 plane="campaign")
        ]
        result = shadow_edges(canon, campaign)
        assert len(result) == 1
        assert result[0]["target_id"] == "cos:location:amber-temple"

    def test_shadowing_is_scoped_to_the_same_source(self):
        """A draw for the Sunsword must not blank the Holy Symbol's candidates."""
        canon = [
            edge("cos:item:sunsword", "RESOLVES_TO", "cos:location:a"),
            edge("cos:item:holy-symbol", "RESOLVES_TO", "cos:location:b"),
        ]
        campaign = [
            edge("cos:item:sunsword", "RESOLVES_TO", "cos:location:c", plane="campaign")
        ]
        result = shadow_edges(canon, campaign)
        targets = sorted(e["target_id"] for e in result)
        assert targets == ["cos:location:b", "cos:location:c"]

    def test_shadowing_is_scoped_to_the_same_type(self):
        canon = [
            edge("cos:item:sunsword", "RESOLVES_TO", "cos:location:a"),
            edge("cos:item:sunsword", "SEEKS", "cos:npc:someone"),
        ]
        campaign = [
            edge("cos:item:sunsword", "RESOLVES_TO", "cos:location:c", plane="campaign")
        ]
        result = shadow_edges(canon, campaign)
        types = sorted(e["rel_type"] for e in result)
        assert types == ["RESOLVES_TO", "SEEKS"]

    def test_no_campaign_edges_leaves_canon_intact(self):
        canon = [edge("a", "RESOLVES_TO", "b")]
        assert shadow_edges(canon, []) == canon

    def test_campaign_only_edges_survive(self):
        campaign = [edge("a", "SEEKS", "b", plane="campaign")]
        assert shadow_edges([], campaign) == campaign
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_graph/test_resolver_pure.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.graph.resolver'`

- [ ] **Step 3: Implement**

Create `backend/graph/resolver.py`:

```python
"""Two-plane read resolution: per-table campaign state merged over shared canon.

The Cypher in this module only matches and filters. Every decision about what a
caller actually sees -- which properties win, which canon edges a table's choices
shadow -- happens in the pure functions below, so those decisions can be tested
exhaustively without a database.
"""

from backend.graph.schema import RESOLVABLE_TYPES


def merge_properties(canon: dict, campaign: dict | None) -> dict:
    """Overlay a campaign node's sparse patch on its canon node.

    Campaign nodes store only what they override, so absent keys must fall
    through to canon rather than blanking it. Neither input is mutated.
    """
    if not campaign:
        return dict(canon)
    return {**canon, **campaign}


def shadow_edges(canon_edges: list[dict], campaign_edges: list[dict]) -> list[dict]:
    """Combine canon and campaign edges, honouring resolvable types.

    Additive types (the default) union. Resolvable types -- currently only
    RESOLVES_TO -- are replaced: if the campaign plane has any edge of that type
    out of a given source, every canon edge of that type from that source is
    dropped. That is the Tarokka collapse, where a table's card draw turns ten
    candidate sites into the one that is true for them.

    Shadowing is scoped to (source_id, rel_type), so resolving the Sunsword's
    location leaves the Holy Symbol's candidates untouched.
    """
    resolvable = {r.value for r in RESOLVABLE_TYPES}
    shadowed = {
        (e["source_id"], e["rel_type"])
        for e in campaign_edges
        if e["rel_type"] in resolvable
    }
    kept = [
        e for e in canon_edges if (e["source_id"], e["rel_type"]) not in shadowed
    ]
    return kept + list(campaign_edges)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_graph/test_resolver_pure.py -v`
Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
git add backend/graph/resolver.py tests/test_graph/test_resolver_pure.py
git commit -m "feat(graph): add pure property-merge and edge-shadow resolution"
```

---

### Task 3: `PlaneResolver` — the Cypher paths

**Files:**
- Modify: `backend/graph/resolver.py`
- Create: `tests/test_graph/test_resolver_neo4j.py`

**Interfaces:**
- Consumes: `merge_properties`, `shadow_edges` (Task 2); `Layer`, `LAYER_MAP` (Task 1); `neo4j_session` from `backend.core.database`; the `graph` fixture from `tests/conftest.py`
- Produces: `PlaneResolver(campaign_id: str)` with
  - `.entities(perspective, entity_type=None, source_book=None, as_of_session=None) -> list[dict]`
  - `.edges(perspective, layers=None, as_of_session=None) -> list[dict]`
  - `.intersections(perspective, min_layers=2, as_of_session=None) -> list[dict]`

- [ ] **Step 1: Write the failing test**

Create `tests/test_graph/test_resolver_neo4j.py`:

```python
"""Cypher paths for two-plane resolution. Requires a running Neo4j."""

import pytest

from backend.graph.resolver import PlaneResolver

pytestmark = pytest.mark.neo4j

CAMPAIGN = "pytest:campaign:a"
OTHER = "pytest:campaign:b"


def seed(session):
    """Canon Ireena, a campaign override marking her dead, and a table-invented NPC."""
    session.run(
        """
        CREATE (c:Entity {id:$campaign, name:'Table A', entity_type:'CAMPAIGN',
                          plane:'campaign'})
        CREATE (canon:Entity {id:'pytest:npc:ireena', name:'Ireena Kolyana',
                              entity_type:'NPC', plane:'canon', source_book:'cos',
                              description:"burgomaster's sister", status:'alive'})
        CREATE (camp:Entity {id:'pytest:npc:ireena@a', entity_type:'NPC',
                             plane:'campaign', status:'dead',
                             canon_id:'pytest:npc:ireena', revealed_in_session:3})
        CREATE (camp)-[:INSTANCE_OF]->(canon)
        CREATE (camp)-[:BELONGS_TO]->(c)
        CREATE (invented:Entity {id:'pytest:npc:bob', name:'Bob the Hireling',
                                 entity_type:'NPC', plane:'campaign',
                                 revealed_in_session:5})
        CREATE (invented)-[:BELONGS_TO]->(c)
        """,
        {"campaign": CAMPAIGN},
    )


class TestEntityResolution:
    def test_truth_view_merges_campaign_over_canon(self, graph):
        seed(graph)
        result = PlaneResolver(CAMPAIGN).entities("truth", entity_type="NPC")
        ireena = next(e for e in result if e.get("canon_id") == "pytest:npc:ireena"
                      or e.get("id") == "pytest:npc:ireena")
        assert ireena["status"] == "dead"
        assert ireena["description"] == "burgomaster's sister"

    def test_truth_view_includes_table_invented_entities(self, graph):
        """A canon-rooted query alone silently drops everything a table made up."""
        seed(graph)
        names = {
            e.get("name") for e in PlaneResolver(CAMPAIGN).entities("truth",
                                                                    entity_type="NPC")
        }
        assert "Bob the Hireling" in names

    def test_another_campaign_sees_unmodified_canon(self, graph):
        seed(graph)
        result = PlaneResolver(OTHER).entities("truth", entity_type="NPC")
        ireena = next(e for e in result if e.get("id") == "pytest:npc:ireena")
        assert ireena["status"] == "alive"

    def test_table_view_never_returns_canon_plane(self, graph):
        seed(graph)
        result = PlaneResolver(CAMPAIGN).entities("table", as_of_session=10)
        assert all(e.get("plane") == "campaign" for e in result)

    def test_table_view_respects_as_of_session(self, graph):
        seed(graph)
        result = PlaneResolver(CAMPAIGN).entities("table", as_of_session=4)
        names = {e.get("name") for e in result}
        assert "Bob the Hireling" not in names  # revealed in session 5

    def test_as_of_session_with_truth_is_an_error(self):
        with pytest.raises(ValueError):
            PlaneResolver(CAMPAIGN).entities("truth", as_of_session=3)


class TestEdgeResolution:
    def test_layer_filter_narrows_traversal(self, graph):
        graph.run(
            """
            CREATE (a:Entity {id:'pytest:npc:strahd', plane:'canon', name:'Strahd'})
            CREATE (b:Entity {id:'pytest:npc:ireena2', plane:'canon', name:'Ireena'})
            CREATE (l:Entity {id:'pytest:loc:barovia', plane:'canon', name:'Barovia'})
            CREATE (a)-[:SEEKS {layer:'narrative', motive:'believes her Tatyana'}]->(b)
            CREATE (b)-[:LOCATED_IN {layer:'spatial'}]->(l)
            """
        )
        social_only = PlaneResolver(CAMPAIGN).edges("truth", layers=["narrative"])
        assert all(e["layer"] == "narrative" for e in social_only)
        assert any(e["rel_type"] == "SEEKS" for e in social_only)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_graph/test_resolver_neo4j.py -v`
Expected: FAIL with `ImportError: cannot import name 'PlaneResolver'`

If instead you see a Neo4j connection error, start it: `docker compose up -d`. Note the
container reports `unhealthy` even when working (its healthcheck shells out to `curl`,
which the image no longer ships) — check `docker logs dnd-neo4j` for
`Bolt enabled on 0.0.0.0:7687` instead.

- [ ] **Step 3: Implement `PlaneResolver`**

Append to `backend/graph/resolver.py`:

```python
from typing import Literal

from backend.core.database import neo4j_session
from backend.graph.schema import LAYER_MAP, Layer

Perspective = Literal["truth", "table"]

_ENTITY_CANON_BRANCH = """
MATCH (canon:Entity {plane:'canon'})
WHERE ($entity_type IS NULL OR canon.entity_type = $entity_type)
  AND ($source_book IS NULL OR canon.source_book = $source_book)
OPTIONAL MATCH (camp:Entity {plane:'campaign'})-[:INSTANCE_OF]->(canon)
  WHERE (camp)-[:BELONGS_TO]->(:Entity {id:$campaign_id})
RETURN properties(canon) AS canon_props, properties(camp) AS camp_props
"""

_ENTITY_CAMPAIGN_ONLY_BRANCH = """
MATCH (camp:Entity {plane:'campaign'})-[:BELONGS_TO]->(:Entity {id:$campaign_id})
WHERE NOT (camp)-[:INSTANCE_OF]->(:Entity)
  AND ($entity_type IS NULL OR camp.entity_type = $entity_type)
RETURN properties(camp) AS camp_props
"""

_ENTITY_TABLE_VIEW = """
MATCH (camp:Entity {plane:'campaign'})-[:BELONGS_TO]->(:Entity {id:$campaign_id})
WHERE ($entity_type IS NULL OR camp.entity_type = $entity_type)
  AND camp.revealed_in_session IS NOT NULL
  AND camp.revealed_in_session <= $as_of_session
RETURN properties(camp) AS camp_props
"""

_EDGES = """
MATCH (a:Entity)-[r]->(b:Entity)
WHERE r.layer IS NOT NULL
  AND ($layers IS NULL OR r.layer IN $layers)
  AND ($plane IS NULL OR a.plane = $plane)
RETURN a.id AS source_id, b.id AS target_id, type(r) AS rel_type,
       r.layer AS layer, a.plane AS plane, properties(r) AS props
"""


class PlaneResolver:
    """The single place two-plane reads go through.

    Truth view merges campaign state over canon with no reveal filter -- what is
    actually true, for generators and NPC behaviour. Table view reads the campaign
    plane ONLY, filtered by reveal; canon is deliberately invisible, because canon
    is the book rather than anything the party knows. That asymmetry is the whole
    spoiler defence.
    """

    def __init__(self, campaign_id: str):
        self.campaign_id = campaign_id

    def entities(
        self,
        perspective: Perspective,
        entity_type: str | None = None,
        source_book: str | None = None,
        as_of_session: int | None = None,
    ) -> list[dict]:
        self._check_perspective(perspective, as_of_session)

        with neo4j_session() as session:
            if perspective == "table":
                rows = session.run(
                    _ENTITY_TABLE_VIEW,
                    {
                        "campaign_id": self.campaign_id,
                        "entity_type": entity_type,
                        "as_of_session": as_of_session,
                    },
                )
                return [dict(r["camp_props"]) for r in rows]

            params = {
                "campaign_id": self.campaign_id,
                "entity_type": entity_type,
                "source_book": source_book,
            }
            merged = [
                merge_properties(dict(r["canon_props"]),
                                 dict(r["camp_props"]) if r["camp_props"] else None)
                for r in session.run(_ENTITY_CANON_BRANCH, params)
            ]
            invented = [
                dict(r["camp_props"])
                for r in session.run(_ENTITY_CAMPAIGN_ONLY_BRANCH, params)
            ]
            return merged + invented

    def edges(
        self,
        perspective: Perspective,
        layers: list[str] | None = None,
        as_of_session: int | None = None,
    ) -> list[dict]:
        self._check_perspective(perspective, as_of_session)

        with neo4j_session() as session:
            if perspective == "table":
                rows = session.run(_EDGES, {"layers": layers, "plane": "campaign"})
                return [
                    self._row_to_edge(r)
                    for r in rows
                    if _revealed(r["props"], as_of_session)
                ]

            canon = [
                self._row_to_edge(r)
                for r in session.run(_EDGES, {"layers": layers, "plane": "canon"})
            ]
            campaign = [
                self._row_to_edge(r)
                for r in session.run(_EDGES, {"layers": layers, "plane": "campaign"})
            ]
        return shadow_edges(canon, campaign)

    def intersections(
        self,
        perspective: Perspective,
        min_layers: int = 2,
        as_of_session: int | None = None,
    ) -> list[dict]:
        """Nodes carrying edges in two or more layers.

        Derived, never stored -- "which places matter to the plot" is the query
        "which nodes have both spatial and narrative edges".
        """
        by_node: dict[str, set[str]] = {}
        for e in self.edges(perspective, as_of_session=as_of_session):
            for node_id in (e["source_id"], e["target_id"]):
                by_node.setdefault(node_id, set()).add(e["layer"])
        return [
            {"id": node_id, "layers": sorted(layers)}
            for node_id, layers in sorted(by_node.items())
            if len(layers) >= min_layers
        ]

    @staticmethod
    def _row_to_edge(row) -> dict:
        return {
            "source_id": row["source_id"],
            "target_id": row["target_id"],
            "rel_type": row["rel_type"],
            "layer": row["layer"],
            "plane": row["plane"],
            "props": dict(row["props"]),
        }

    @staticmethod
    def _check_perspective(perspective: Perspective, as_of_session: int | None) -> None:
        if perspective not in ("truth", "table"):
            raise ValueError(f"unknown perspective: {perspective!r}")
        if perspective == "truth" and as_of_session is not None:
            raise ValueError("as_of_session is meaningful only for perspective='table'")
        if perspective == "table" and as_of_session is None:
            raise ValueError("perspective='table' requires as_of_session")


def _revealed(props: dict, as_of_session: int | None) -> bool:
    revealed = props.get("revealed_in_session")
    return revealed is not None and revealed <= as_of_session
```

Move the `from typing import Literal` and the `backend.core.database` import to the top of
the file with the existing imports rather than leaving them mid-module; ruff's `E402` will
flag them otherwise.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_graph/test_resolver_neo4j.py -v`
Expected: 7 passed

- [ ] **Step 5: Confirm the suite is still green and deselectable**

Run: `uv run pytest -q` then `uv run pytest -q -m "not neo4j"`
Expected: both pass; the second reports fewer tests and requires no database.

- [ ] **Step 6: Commit**

```bash
git add backend/graph/resolver.py tests/test_graph/test_resolver_neo4j.py
git commit -m "feat(graph): add PlaneResolver for two-plane entity and edge reads"
```

---

### Task 4: Village of Barovia seed and loader

**Files:**
- Create: `backend/canon/seeds/village-of-barovia.yaml`
- Create: `backend/canon/seed_loader.py`
- Create: `tests/test_canon/test_seed_loader.py`

**Interfaces:**
- Consumes: `RelationshipType`, `LAYER_MAP` (Task 1)
- Produces: `load_seed(path: str | Path, session) -> dict` returning `{"nodes": int, "edges": int}`, and `validate_seed(data: dict) -> list[str]` returning human-readable problems (empty means valid)

- [ ] **Step 1: Write the failing test**

Create `tests/test_canon/test_seed_loader.py`:

```python
"""The seed is hand-authored canon and doubles as stage 2's golden set, so its
integrity is worth asserting rather than assuming."""

from pathlib import Path

import pytest
import yaml

from backend.canon.seed_loader import SEED_DIR, load_seed, validate_seed

BAROVIA = SEED_DIR / "village-of-barovia.yaml"


@pytest.fixture
def seed_data():
    return yaml.safe_load(BAROVIA.read_text())


class TestSeedIntegrity:
    def test_seed_file_exists(self):
        assert BAROVIA.exists()

    def test_seed_validates(self, seed_data):
        assert validate_seed(seed_data) == []

    def test_every_node_has_required_fields(self, seed_data):
        for node in seed_data["nodes"]:
            assert node["id"].startswith("cos:"), node
            for field in ("name", "entity_type"):
                assert field in node, node

    def test_edges_reference_declared_nodes(self, seed_data):
        ids = {n["id"] for n in seed_data["nodes"]}
        for e in seed_data["edges"]:
            assert e["source"] in ids, f"dangling source: {e}"
            assert e["target"] in ids, f"dangling target: {e}"

    def test_exercises_every_narrative_type(self, seed_data):
        """The seed's job is to put the new vocabulary under real material."""
        used = {e["type"] for e in seed_data["edges"]}
        for required in ("SEEKS", "IDENTITY_OF", "GAVE_QUEST", "OBJECTIVE_AT",
                         "RESOLVES_TO"):
            assert required in used, f"seed never exercises {required}"

    def test_identity_edge_is_unrevealed(self, seed_data):
        """Ireena being Tatyana is the reveal the design exists to protect."""
        identity = [e for e in seed_data["edges"] if e["type"] == "IDENTITY_OF"]
        assert identity, "no IDENTITY_OF edge in seed"
        assert all(e.get("revealed_in_session") is None for e in identity)


class TestValidation:
    def test_unknown_relationship_type_is_reported(self):
        problems = validate_seed(
            {
                "nodes": [{"id": "cos:npc:a", "name": "A", "entity_type": "NPC"}],
                "edges": [{"source": "cos:npc:a", "target": "cos:npc:a",
                           "type": "NOT_A_REAL_TYPE"}],
            }
        )
        assert any("NOT_A_REAL_TYPE" in p for p in problems)

    def test_dangling_edge_is_reported(self):
        problems = validate_seed(
            {
                "nodes": [{"id": "cos:npc:a", "name": "A", "entity_type": "NPC"}],
                "edges": [{"source": "cos:npc:a", "target": "cos:npc:missing",
                           "type": "KNOWS"}],
            }
        )
        assert any("missing" in p for p in problems)


@pytest.mark.neo4j
class TestLoad:
    def test_load_creates_nodes_and_edges(self, graph, tmp_path):
        doc = {
            "nodes": [
                {"id": "pytest:npc:a", "name": "A", "entity_type": "NPC"},
                {"id": "pytest:npc:b", "name": "B", "entity_type": "NPC"},
            ],
            "edges": [{"source": "pytest:npc:a", "target": "pytest:npc:b",
                       "type": "KNOWS"}],
        }
        path = tmp_path / "mini.yaml"
        path.write_text(yaml.safe_dump(doc))

        counts = load_seed(path, graph)

        assert counts == {"nodes": 2, "edges": 1}
        stored = graph.run(
            "MATCH (a:Entity {id:'pytest:npc:a'})-[r:KNOWS]->(b) "
            "RETURN r.layer AS layer, a.plane AS plane"
        ).single()
        assert stored["layer"] == "social"
        assert stored["plane"] == "canon"

    def test_load_is_idempotent(self, graph, tmp_path):
        doc = {"nodes": [{"id": "pytest:npc:a", "name": "A", "entity_type": "NPC"}],
               "edges": []}
        path = tmp_path / "mini.yaml"
        path.write_text(yaml.safe_dump(doc))

        load_seed(path, graph)
        load_seed(path, graph)

        n = graph.run("MATCH (e:Entity {id:'pytest:npc:a'}) RETURN count(e) AS n").single()
        assert n["n"] == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_canon/test_seed_loader.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.canon.seed_loader'`

- [ ] **Step 3: Author the seed**

Create `backend/canon/seeds/village-of-barovia.yaml`. Every node gets `plane: canon` and
`source_book: cos` from the loader, so they are not repeated per node.

```yaml
# Curse of Strahd, chapter 3 -- hand-authored canon.
# Doubles as the golden set for stage 2 extraction: if an extractor cannot recover
# roughly this from the chapter 3 prose, it is not good enough.

nodes:
  # --- Locations ---
  - id: cos:location:village-of-barovia
    name: Village of Barovia
    entity_type: LOCATION
    description: A gloomy village cowed by Strahd, its people numb with despair.
  - id: cos:location:burgomasters-mansion
    name: Burgomaster's Mansion
    entity_type: LOCATION
    description: Home of the late burgomaster Kolyan Indirovich, and his children.
  - id: cos:location:bildraths-mercantile
    name: Bildrath's Mercantile
    entity_type: LOCATION
    description: The only shop, charging ten times fair price.
  - id: cos:location:blood-of-the-vine
    name: Blood of the Vine Tavern
    entity_type: LOCATION
    description: Where the Vistani drink and the villagers do not.
  - id: cos:location:church-of-barovia
    name: Church of Barovia
    entity_type: LOCATION
    description: A failing church whose priest hides something beneath it.
  - id: cos:location:vallaki
    name: Vallaki
    entity_type: LOCATION
    description: The walled town west of the village.

  # --- NPCs ---
  - id: cos:npc:ireena-kolyana
    name: Ireena Kolyana
    entity_type: NPC
    aliases: ["Ireena"]
    description: The burgomaster's adopted daughter, twice bitten by Strahd.
  - id: cos:npc:ismark-kolyanovich
    name: Ismark Kolyanovich
    entity_type: NPC
    aliases: ["Ismark the Lesser"]
    description: Ireena's brother, now the village's reluctant leader.
  - id: cos:npc:donavich
    name: Donavich
    entity_type: NPC
    description: The village priest, starving and half-mad with grief.
  - id: cos:npc:doru
    name: Doru
    entity_type: NPC
    description: Donavich's son, a vampire spawn locked in the church undercroft.
  - id: cos:npc:mad-mary
    name: Mad Mary
    entity_type: NPC
    description: A villager wailing for her vanished daughter.
  - id: cos:npc:bildrath-cantemir
    name: Bildrath Cantemir
    entity_type: NPC
    description: The shopkeeper. Gouges without shame.
  - id: cos:npc:parriwimple
    name: Parriwimple
    entity_type: NPC
    description: Bildrath's simple, immensely strong nephew.
  - id: cos:npc:morgantha
    name: Morgantha
    entity_type: NPC
    description: A night hag peddling dream pastries to the desperate.
  - id: cos:npc:strahd-von-zarovich
    name: Strahd von Zarovich
    entity_type: NPC
    aliases: ["the devil Strahd"]
    description: The vampire lord of Barovia.
  - id: cos:npc:tatyana
    name: Tatyana
    entity_type: NPC
    description: The woman Strahd killed for, centuries dead and endlessly reborn.

  # --- Narrative ---
  - id: cos:quest:escort-ireena-to-vallaki
    name: Escort Ireena to Vallaki
    entity_type: QUEST
    description: Ismark asks the party to take his sister somewhere Strahd cannot reach.
  - id: cos:quest:save-doru
    name: Free Doru from the undercroft
    entity_type: QUEST
    description: Donavich cannot bring himself to end his son, and will not let him out.
  - id: cos:item:tome-of-strahd
    name: Tome of Strahd
    entity_type: ITEM
    description: Strahd's own account of his fall. Location set by the Tarokka reading.

edges:
  # Spatial
  - {source: cos:location:village-of-barovia, target: cos:location:burgomasters-mansion, type: CONTAINS}
  - {source: cos:location:village-of-barovia, target: cos:location:bildraths-mercantile, type: CONTAINS}
  - {source: cos:location:village-of-barovia, target: cos:location:blood-of-the-vine, type: CONTAINS}
  - {source: cos:location:village-of-barovia, target: cos:location:church-of-barovia, type: CONTAINS}
  - {source: cos:location:village-of-barovia, target: cos:location:vallaki, type: CONNECTED_TO}
  - {source: cos:npc:ireena-kolyana, target: cos:location:burgomasters-mansion, type: LOCATED_IN}
  - {source: cos:npc:ismark-kolyanovich, target: cos:location:burgomasters-mansion, type: LOCATED_IN}
  - {source: cos:npc:donavich, target: cos:location:church-of-barovia, type: LOCATED_IN}
  - {source: cos:npc:doru, target: cos:location:church-of-barovia, type: LOCATED_IN}
  - {source: cos:npc:bildrath-cantemir, target: cos:location:bildraths-mercantile, type: LOCATED_IN}
  - {source: cos:npc:parriwimple, target: cos:location:bildraths-mercantile, type: LOCATED_IN}

  # Social
  - {source: cos:npc:ismark-kolyanovich, target: cos:npc:ireena-kolyana, type: RELATED_TO, evidence: "adoptive siblings"}
  - {source: cos:npc:donavich, target: cos:npc:doru, type: RELATED_TO, evidence: "father and son"}
  - {source: cos:npc:bildrath-cantemir, target: cos:npc:parriwimple, type: RELATED_TO, evidence: "uncle and nephew"}
  - {source: cos:npc:bildrath-cantemir, target: cos:location:bildraths-mercantile, type: OWNS}
  - {source: cos:npc:donavich, target: cos:npc:doru, type: GUARDS, evidence: "keeps him sealed in the undercroft"}
  - {source: cos:npc:strahd-von-zarovich, target: cos:npc:ireena-kolyana, type: HOSTILE_TO}

  # Narrative
  - source: cos:npc:strahd-von-zarovich
    target: cos:npc:ireena-kolyana
    type: SEEKS
    motive: Believes she is Tatyana reborn and means to make her his bride.
  - source: cos:npc:ireena-kolyana
    target: cos:npc:tatyana
    type: IDENTITY_OF
    nature: reincarnation
    revealed_in_session: null
  - source: cos:npc:donavich
    target: cos:quest:save-doru
    type: SEEKS
    motive: Prays nightly for a son he cannot kill and will not release.
  - source: cos:npc:ismark-kolyanovich
    target: cos:quest:escort-ireena-to-vallaki
    type: GAVE_QUEST
  - source: cos:quest:escort-ireena-to-vallaki
    target: cos:location:vallaki
    type: OBJECTIVE_AT
  - source: cos:npc:morgantha
    target: cos:location:village-of-barovia
    type: THREATENS
    evidence: Trades dream pastries for the villagers' children.
  # Canon fan-out: the Tarokka reading collapses this to one per table.
  - {source: cos:item:tome-of-strahd, target: cos:location:church-of-barovia, type: RESOLVES_TO}
  - {source: cos:item:tome-of-strahd, target: cos:location:burgomasters-mansion, type: RESOLVES_TO}
  - {source: cos:item:tome-of-strahd, target: cos:location:blood-of-the-vine, type: RESOLVES_TO}
```

- [ ] **Step 4: Implement the loader**

Create `backend/canon/seed_loader.py`:

```python
"""Load hand-authored canon YAML into Neo4j.

Seeds live in this package rather than under data/ because data/ is gitignored and
a seed is source: it is committed, reviewed, and doubles as the golden set that
stage 2's extractor is graded against.
"""

from pathlib import Path

import yaml

from backend.graph.schema import LAYER_MAP, RelationshipType

SEED_DIR = Path(__file__).parent / "seeds"

RESERVED_EDGE_KEYS = {"source", "target", "type"}


def validate_seed(data: dict) -> list[str]:
    """Return human-readable problems with a seed document. Empty means valid."""
    problems: list[str] = []
    known_types = {r.value for r in RelationshipType}
    ids = {n.get("id") for n in data.get("nodes", [])}

    for node in data.get("nodes", []):
        for field in ("id", "name", "entity_type"):
            if not node.get(field):
                problems.append(f"node missing {field}: {node}")

    for e in data.get("edges", []):
        if e.get("type") not in known_types:
            problems.append(f"unknown relationship type {e.get('type')!r} in {e}")
        for end in ("source", "target"):
            if e.get(end) not in ids:
                problems.append(f"edge {end} not declared as a node: {e.get(end)!r}")

    return problems


def load_seed(path: str | Path, session) -> dict:
    """Load a seed into Neo4j, stamping canon provenance and edge layers.

    MERGE on id makes this idempotent, so a seed can be reloaded after editing
    without duplicating nodes.
    """
    data = yaml.safe_load(Path(path).read_text())
    problems = validate_seed(data)
    if problems:
        raise ValueError("invalid seed:\n  " + "\n  ".join(problems))

    for node in data["nodes"]:
        props = {k: v for k, v in node.items() if k != "id"}
        props.setdefault("plane", "canon")
        props.setdefault("source_book", "cos")
        session.run(
            "MERGE (e:Entity {id:$id}) SET e += $props",
            {"id": node["id"], "props": props},
        )

    for e in data["edges"]:
        rel = RelationshipType(e["type"])
        props = {k: v for k, v in e.items() if k not in RESERVED_EDGE_KEYS}
        layer = LAYER_MAP[rel]
        if layer is not None:
            props["layer"] = layer.value
        session.run(
            f"""
            MATCH (a:Entity {{id:$source}}), (b:Entity {{id:$target}})
            MERGE (a)-[r:{rel.value}]->(b)
            SET r += $props
            """,
            {"source": e["source"], "target": e["target"], "props": props},
        )

    return {"nodes": len(data["nodes"]), "edges": len(data["edges"])}
```

The relationship type is interpolated into the Cypher because Neo4j cannot parameterize
a relationship type. It is safe here: `RelationshipType(e["type"])` raises `ValueError`
on anything not in the enum, so only enum values ever reach the f-string.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_canon/test_seed_loader.py -v`
Expected: 10 passed

- [ ] **Step 6: Commit**

```bash
git add backend/canon/seeds/village-of-barovia.yaml backend/canon/seed_loader.py \
        tests/test_canon/test_seed_loader.py
git commit -m "feat(canon): add Village of Barovia seed and loader"
```

---

### Task 5: End-to-end resolution against the seed

Proves the ontology and resolver work on real material rather than fixtures, including the
reveal case the whole design exists to protect.

**Files:**
- Create: `tests/test_graph/test_resolver_integration.py`

**Interfaces:**
- Consumes: `PlaneResolver` (Task 3), `load_seed`, `SEED_DIR` (Task 4), the `graph` fixture (Task 1)
- Produces: nothing — this is the verification task

- [ ] **Step 1: Write the failing test**

Create `tests/test_graph/test_resolver_integration.py`:

```python
"""The seed under the resolver: the ontology exercised on real material."""

import pytest

from backend.canon.seed_loader import SEED_DIR, load_seed
from backend.graph.resolver import PlaneResolver

pytestmark = pytest.mark.neo4j

CAMPAIGN = "pytest:campaign:barovia"


@pytest.fixture
def seeded(graph):
    load_seed(SEED_DIR / "village-of-barovia.yaml", graph)
    graph.run(
        "CREATE (c:Entity {id:$id, name:'Table A', entity_type:'CAMPAIGN', "
        "plane:'campaign'})",
        {"id": CAMPAIGN},
    )
    yield graph
    graph.run("MATCH (e:Entity) WHERE e.id STARTS WITH 'cos:' DETACH DELETE e")


class TestSeedUnderResolver:
    def test_truth_view_returns_canon_npcs(self, seeded):
        names = {
            e["name"] for e in PlaneResolver(CAMPAIGN).entities("truth",
                                                                entity_type="NPC")
        }
        assert "Ireena Kolyana" in names
        assert "Strahd von Zarovich" in names

    def test_narrative_layer_isolates_plot_edges(self, seeded):
        edges = PlaneResolver(CAMPAIGN).edges("truth", layers=["narrative"])
        types = {e["rel_type"] for e in edges}
        assert "SEEKS" in types
        assert "LOCATED_IN" not in types

    def test_seeks_edge_carries_its_motive(self, seeded):
        edges = PlaneResolver(CAMPAIGN).edges("truth", layers=["narrative"])
        seeks = next(
            e for e in edges
            if e["rel_type"] == "SEEKS"
            and e["target_id"] == "cos:npc:ireena-kolyana"
        )
        assert "Tatyana" in seeks["props"]["motive"]

    def test_church_is_an_intersection_of_spatial_and_narrative(self, seeded):
        """Which places matter to the plot, computed rather than authored."""
        hits = PlaneResolver(CAMPAIGN).intersections("truth")
        by_id = {h["id"]: h["layers"] for h in hits}
        assert "spatial" in by_id["cos:location:church-of-barovia"]
        assert "narrative" in by_id["cos:location:church-of-barovia"]

    def test_table_view_hides_the_unrevealed_identity(self, seeded):
        """Ireena is Tatyana. The table must not learn that from the graph."""
        edges = PlaneResolver(CAMPAIGN).edges("table", as_of_session=99)
        assert all(e["rel_type"] != "IDENTITY_OF" for e in edges)

    def test_table_view_returns_nothing_from_canon(self, seeded):
        entities = PlaneResolver(CAMPAIGN).entities("table", as_of_session=99)
        assert all(e.get("plane") == "campaign" for e in entities)

    @pytest.mark.parametrize("session_n", [0, 1, 2, 5, 12, 99])
    def test_table_view_never_leaks_across_any_session(self, seeded, session_n):
        """The invariant the whole design rests on, checked across the range.

        For any session N: the table view returns nothing from the canon plane and
        nothing whose reveal is later than N. Parametrized rather than
        hypothesis-driven so it needs no new dependency, but the intent is a
        property: this must hold for every N, not one convenient value.
        """
        resolver = PlaneResolver(CAMPAIGN)

        for entity in resolver.entities("table", as_of_session=session_n):
            assert entity.get("plane") == "campaign"
            revealed = entity.get("revealed_in_session")
            assert revealed is not None and revealed <= session_n

        for e in resolver.edges("table", as_of_session=session_n):
            assert e["plane"] == "campaign"
            revealed = e["props"].get("revealed_in_session")
            assert revealed is not None and revealed <= session_n

    def test_campaign_draw_shadows_the_tarokka_fan_out(self, seeded):
        """Canon offers three sites for the Tome; this table drew the church."""
        seeded.run(
            """
            MATCH (canon:Entity {id:'cos:item:tome-of-strahd'})
            MATCH (church:Entity {id:'cos:location:church-of-barovia'})
            CREATE (camp:Entity {id:'pytest:item:tome@a', plane:'campaign',
                                 entity_type:'ITEM', canon_id:'cos:item:tome-of-strahd'})
            CREATE (camp)-[:INSTANCE_OF]->(canon)
            CREATE (camp)-[:BELONGS_TO]->(:Entity {id:$campaign})
            CREATE (canon)-[:RESOLVES_TO {layer:'narrative'}]->(church)
            """,
            {"campaign": CAMPAIGN},
        )
        # The campaign edge must originate from the canon id to shadow it.
        seeded.run(
            """
            MATCH (a:Entity {id:'cos:item:tome-of-strahd'})
            MATCH (b:Entity {id:'cos:location:church-of-barovia'})
            MERGE (a)-[r:RESOLVES_TO {layer:'narrative'}]->(b)
            """
        )
        edges = PlaneResolver(CAMPAIGN).edges("truth", layers=["narrative"])
        resolves = [e for e in edges if e["rel_type"] == "RESOLVES_TO"]
        assert len(resolves) >= 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_graph/test_resolver_integration.py -v`
Expected: FAIL — the seed file or resolver behaviour is not yet wired end to end. Capture
the actual output.

If `test_campaign_draw_shadows_the_tarokka_fan_out` proves awkward to express because
shadowing keys on the *canon* source id while campaign nodes have their own ids, **report
that rather than weakening the assertion** — it is a real design question about whether
`shadow_edges` should key on `canon_id`, and it should be answered rather than papered
over.

- [ ] **Step 3: Fix whatever the integration surfaces**

No new module is expected here. If a test fails, the fault is in Task 1–4 code and should
be fixed there, with the fix noted in your report.

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest -q` and `uv run pytest -q -m "not neo4j"`
Expected: both green.

- [ ] **Step 5: Commit**

```bash
git add tests/test_graph/test_resolver_integration.py
git commit -m "test(graph): verify resolver against the Barovia seed"
```

---

### Task 6: Stamp `plane` and `layer` on the write path

**Why this exists.** Added after Task 1's review. The plan's global constraint says *every
node carries `plane`*, but `backend/graph/operations.py` contains **zero** occurrences of
it: an entity created through `POST /api/campaign/entities` lands with no `plane`, and the
resolver — which filters `plane:'campaign'` — silently never sees it. The same hole exists
for edges: `create_relationship` sets no `layer`, and the resolver's edge query filters
`WHERE r.layer IS NOT NULL`, so API-created edges are invisible to every layer traversal.

Without this, the resolver works against the seed and against fixtures and is useless
against anything a running application produced.

A third issue surfaced while reading the same code: `create_relationship` interpolates
`relationship_type` directly into Cypher without validating it against the enum. The seed
loader already guards this by coercing through `RelationshipType(...)`; this method should
too.

**Files:**
- Modify: `backend/graph/operations.py`
- Create: `tests/test_graph/test_write_path_stamps.py`

**Interfaces:**
- Consumes: `LAYER_MAP`, `RelationshipType` from `backend.graph.schema` (Task 1)
- Produces: no new public API. `create_entity` and `create_relationship` keep their exact signatures.

- [ ] **Step 1: Write the failing test**

Create `tests/test_graph/test_write_path_stamps.py`:

```python
"""Entities and edges created through the ops layer must carry the properties the
resolver filters on, or the resolver cannot see application-created data at all."""

import pytest

from backend.graph.operations import CampaignGraphOps
from backend.graph.schema import RelationshipType

pytestmark = pytest.mark.neo4j


class TestEntityPlaneStamp:
    def test_created_entity_defaults_to_campaign_plane(self, graph):
        ops = CampaignGraphOps()
        created = ops.create_entity(
            name="Test NPC", entity_type="NPC", entity_id="pytest:npc:stamp"
        )
        assert created["plane"] == "campaign"

    def test_explicit_plane_is_respected(self, graph):
        """The seed loader writes canon; an explicit plane must not be overwritten."""
        ops = CampaignGraphOps()
        created = ops.create_entity(
            name="Canon NPC",
            entity_type="NPC",
            entity_id="pytest:npc:canon-stamp",
            properties={"plane": "canon"},
        )
        assert created["plane"] == "canon"


class TestRelationshipLayerStamp:
    def test_created_edge_carries_its_layer(self, graph):
        ops = CampaignGraphOps()
        ops.create_entity(name="A", entity_type="NPC", entity_id="pytest:npc:a")
        ops.create_entity(name="B", entity_type="NPC", entity_id="pytest:npc:b")
        ops.create_relationship("pytest:npc:a", "pytest:npc:b", RelationshipType.KNOWS)

        row = graph.run(
            "MATCH (:Entity {id:'pytest:npc:a'})-[r:KNOWS]->() RETURN r.layer AS layer"
        ).single()
        assert row["layer"] == "social"

    def test_structural_edge_gets_no_layer(self, graph):
        """BELONGS_TO is plane-linking, not a surface. It must stay unlayered."""
        ops = CampaignGraphOps()
        ops.create_entity(name="A", entity_type="NPC", entity_id="pytest:npc:c")
        ops.create_entity(name="C", entity_type="CAMPAIGN", entity_id="pytest:camp:x")
        ops.create_relationship(
            "pytest:npc:c", "pytest:camp:x", RelationshipType.BELONGS_TO
        )

        row = graph.run(
            "MATCH (:Entity {id:'pytest:npc:c'})-[r:BELONGS_TO]->() "
            "RETURN r.layer AS layer"
        ).single()
        assert row["layer"] is None

    def test_unknown_relationship_type_is_rejected(self, graph):
        """The type is interpolated into Cypher, so it must be validated first."""
        ops = CampaignGraphOps()
        ops.create_entity(name="A", entity_type="NPC", entity_id="pytest:npc:d")
        ops.create_entity(name="B", entity_type="NPC", entity_id="pytest:npc:e")

        with pytest.raises(ValueError):
            ops.create_relationship(
                "pytest:npc:d", "pytest:npc:e", "NOT_A_TYPE; DROP DATABASE neo4j"
            )
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_graph/test_write_path_stamps.py -v`
Expected: FAIL — `KeyError: 'plane'` or equivalent on the entity tests, `None != 'social'`
on the layer test, and `DID NOT RAISE` on the validation test. Capture the actual output.

- [ ] **Step 3: Stamp `plane` in `create_entity`**

In `backend/graph/operations.py`, in `create_entity` (the `props = properties or {}` line
is currently line 57), change:

```python
        props = properties or {}
```

to:

```python
        # The resolver filters on `plane`; an unstamped node is invisible to it.
        # Default to campaign — canon is written by the seed loader, which passes
        # plane explicitly.
        props = dict(properties or {})
        props.setdefault("plane", "campaign")
```

Copying the dict also stops the method mutating a caller's argument, which the current
code does via `props["created_at"] = ...` in the sibling method.

- [ ] **Step 4: Validate and stamp in `create_relationship`**

In `create_relationship`, replace:

```python
        if isinstance(relationship_type, RelationshipType):
            relationship_type = relationship_type.value

        props = properties or {}
        props["created_at"] = datetime.utcnow().isoformat()
```

with:

```python
        # Coerce through the enum before interpolating into Cypher. A relationship
        # type cannot be parameterized, so this is the only thing keeping an
        # arbitrary caller string out of the query text.
        rel = RelationshipType(
            relationship_type.value
            if isinstance(relationship_type, RelationshipType)
            else relationship_type
        )
        relationship_type = rel.value

        props = dict(properties or {})
        props["created_at"] = datetime.utcnow().isoformat()
        layer = LAYER_MAP[rel]
        if layer is not None:
            props.setdefault("layer", layer.value)
```

Add `LAYER_MAP` to the existing `from backend.graph.schema import ...` line at the top of
the file.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_graph/test_write_path_stamps.py -v`
Expected: 5 passed

- [ ] **Step 6: Confirm nothing regressed**

Run: `uv run pytest -q`
Expected: green. Pay attention to `tests/test_api/` and `tests/test_graph/` — several
suites create entities through this path, and a stamped `plane` now appears in their
returned dicts. If a test asserted an exact dict equality it will now fail; report that
rather than removing the assertion.

- [ ] **Step 7: Commit**

```bash
git add backend/graph/operations.py tests/test_graph/test_write_path_stamps.py
git commit -m "fix(graph): stamp plane and layer on the write path"
```

---

### Task 7: Campaign scoping, cross-plane shadowing, and non-vacuous reveal tests

**Why this exists.** Task 5's integration work and review found three interacting defects,
all originating in this plan's own reference code. They share a module and the third's
tests are what prove the first two, so they are fixed together.

**(A) `edges()` is not campaign-scoped — a cross-campaign leak.** `_EDGES` and
`_EDGES_TABLE` filter on `plane` but never on the campaign, so
`PlaneResolver("campaign_a").edges(...)` returns campaign B's edges. This affects **both**
perspectives. Two tables' private state bleeding together is a worse failure than the canon
leak fixed in Task 3.

**(B) Resolvable shadowing does not work across the plane boundary.** `shadow_edges` keys
on `source_id`, but under copy-on-write a campaign node has its own id
(`pytest:item:tome@a`), never the canon id (`cos:item:tome-of-strahd`) the canon edges use.
Verified live: the truth view returns 4 `RESOLVES_TO` edges (the table's draw plus all 3
canon candidates) instead of 1. The Tarokka collapse — the concrete mechanic resolvable
types exist to serve — has been inert since it was written.

**(C) Three reveal tests pass vacuously.** `test_table_view_hides_the_unrevealed_identity`,
`test_table_view_returns_nothing_from_canon`, and all six parametrized cases of
`test_table_view_never_leaks_across_any_session` loop over **empty** result sets. The
`seeded` fixture creates one campaign node and nothing with `revealed_in_session` set, so
there is no data to filter and a regression deleting the reveal filter entirely would pass.
The parametrized test is the one the plan calls "the invariant the whole design rests on".

**Files:**
- Modify: `backend/graph/resolver.py`
- Modify: `tests/test_graph/test_resolver_integration.py`
- Modify: `tests/test_graph/test_resolver_neo4j.py`

**Interfaces:**
- Consumes: `merge_properties`, `shadow_edges`, `PlaneResolver` (Tasks 2–3); `load_seed`, `SEED_DIR` (Task 4)
- Produces: no signature changes. `shadow_edges` keeps `(canon_edges, campaign_edges) -> list[dict]`; `PlaneResolver`'s three methods keep their signatures.

- [ ] **Step 1: Fix (C) first — give the reveal tests real data**

The vacuity fix comes first because it is what proves (A) and (B) afterwards. In
`tests/test_graph/test_resolver_integration.py`, extend the `seeded` fixture so the
campaign plane actually contains something:

```python
@pytest.fixture
def seeded(graph):
    load_seed(SEED_DIR / "village-of-barovia.yaml", graph).__str__()
    graph.run(
        """
        CREATE (c:Entity {id:$id, name:'Table A', entity_type:'CAMPAIGN',
                          plane:'campaign'})
        // A revealed campaign NPC overriding canon Ireena
        CREATE (ireena:Entity {id:'pytest:npc:ireena@a', entity_type:'NPC',
                               plane:'campaign', name:'Ireena Kolyana',
                               canon_id:'cos:npc:ireena-kolyana', status:'travelling',
                               revealed_in_session:2})
        CREATE (ireena)-[:BELONGS_TO]->(c)
        CREATE (ireena)-[:INSTANCE_OF]->(:Entity {id:'cos:npc:ireena-kolyana'})
        // A table-invented ally, revealed later
        CREATE (ally:Entity {id:'pytest:npc:hireling', entity_type:'NPC',
                             plane:'campaign', name:'Sasha the Hireling',
                             revealed_in_session:6})
        CREATE (ally)-[:BELONGS_TO]->(c)
        // A layered campaign->campaign edge, revealed early
        CREATE (ireena)-[:KNOWS {layer:'social', revealed_in_session:2}]->(ally)
        // A campaign entity that has NEVER been revealed
        CREATE (secret:Entity {id:'pytest:npc:unrevealed', entity_type:'NPC',
                               plane:'campaign', name:'Unrevealed NPC'})
        CREATE (secret)-[:BELONGS_TO]->(c)
        """,
        {"id": CAMPAIGN},
    ).consume()
    yield graph
    graph.run("MATCH (e:Entity) WHERE e.id STARTS WITH 'cos:' DETACH DELETE e").consume()
```

Note the `.consume()` calls — an earlier task established that with `neo4j==6.0.2` an
unconsumed write is not reliably visible to a read on a different session, and the resolver
opens its own.

Then add a guard so vacuity cannot recur silently. Insert at the top of the parametrized
property test, before its loops:

```python
        entities = resolver.entities("table", as_of_session=session_n)
        edges = resolver.edges("table", as_of_session=session_n)
        if session_n >= 2:
            assert entities, f"fixture produced no table-view entities at session {session_n}"
            assert edges, f"fixture produced no table-view edges at session {session_n}"
```

Without that guard the test can silently return to asserting nothing. With it, an empty
result set is itself a failure for any session at or after the first reveal.

- [ ] **Step 2: Run to confirm the reveal tests now have data and still pass**

Run: `uv run pytest tests/test_graph/test_resolver_integration.py -v`
Expected: the parametrized cases at `session_n` 0 and 1 pass with empty sets (nothing is
revealed yet, correctly), and 2/5/12/99 pass with real data. If any case at
`session_n >= 2` now FAILS, that is a genuine table-view bug the vacuous test was hiding —
report it before changing anything else.

- [ ] **Step 3: Write the failing tests for (A) — the cross-campaign leak**

Append to `tests/test_graph/test_resolver_neo4j.py`:

```python
class TestCampaignScoping:
    def test_truth_edges_exclude_other_campaigns(self, graph):
        graph.run(
            """
            CREATE (a:Entity {id:'pytest:campaign:a', plane:'campaign',
                              entity_type:'CAMPAIGN'})
            CREATE (b:Entity {id:'pytest:campaign:b', plane:'campaign',
                              entity_type:'CAMPAIGN'})
            CREATE (mine:Entity {id:'pytest:npc:mine', plane:'campaign'})
            CREATE (theirs:Entity {id:'pytest:npc:theirs', plane:'campaign'})
            CREATE (mine)-[:BELONGS_TO]->(a)
            CREATE (theirs)-[:BELONGS_TO]->(b)
            CREATE (mine)-[:KNOWS {layer:'social'}]->(mine)
            CREATE (theirs)-[:KNOWS {layer:'social'}]->(theirs)
            """
        ).consume()

        ids = {
            e["source_id"]
            for e in PlaneResolver("pytest:campaign:a").edges("truth", layers=["social"])
        }
        assert "pytest:npc:mine" in ids
        assert "pytest:npc:theirs" not in ids

    def test_table_edges_exclude_other_campaigns(self, graph):
        graph.run(
            """
            CREATE (a:Entity {id:'pytest:campaign:a', plane:'campaign',
                              entity_type:'CAMPAIGN'})
            CREATE (b:Entity {id:'pytest:campaign:b', plane:'campaign',
                              entity_type:'CAMPAIGN'})
            CREATE (mine:Entity {id:'pytest:npc:mine', plane:'campaign',
                                 revealed_in_session:1})
            CREATE (theirs:Entity {id:'pytest:npc:theirs', plane:'campaign',
                                   revealed_in_session:1})
            CREATE (mine)-[:BELONGS_TO]->(a)
            CREATE (theirs)-[:BELONGS_TO]->(b)
            CREATE (mine)-[:KNOWS {layer:'social', revealed_in_session:1}]->(mine)
            CREATE (theirs)-[:KNOWS {layer:'social', revealed_in_session:1}]->(theirs)
            """
        ).consume()

        ids = {
            e["source_id"]
            for e in PlaneResolver("pytest:campaign:a").edges("table", as_of_session=9)
        }
        assert ids == {"pytest:npc:mine"}
```

- [ ] **Step 4: Run to verify (A) fails**

Run: `uv run pytest tests/test_graph/test_resolver_neo4j.py::TestCampaignScoping -v`
Expected: FAIL — both assert that the other campaign's node is absent, and it is present.
Capture the actual output showing `pytest:npc:theirs` in the result.

- [ ] **Step 5: Fix (A) — scope the edge queries by campaign**

In `backend/graph/resolver.py`, canon edges are shared and must NOT be campaign-filtered;
campaign edges must be. Replace the edge query constants:

```python
_EDGES_CANON = """
MATCH (a:Entity {plane:'canon'})-[r]->(b:Entity)
WHERE r.layer IS NOT NULL
  AND ($layers IS NULL OR r.layer IN $layers)
RETURN a.id AS source_id, coalesce(a.canon_id, a.id) AS source_canon_id,
       b.id AS target_id, type(r) AS rel_type, r.layer AS layer,
       a.plane AS plane, properties(r) AS props
"""

_EDGES_CAMPAIGN = """
MATCH (a:Entity {plane:'campaign'})-[:BELONGS_TO]->(:Entity {id:$campaign_id})
MATCH (a)-[r]->(b:Entity)
WHERE r.layer IS NOT NULL
  AND ($layers IS NULL OR r.layer IN $layers)
RETURN a.id AS source_id, coalesce(a.canon_id, a.id) AS source_canon_id,
       b.id AS target_id, type(r) AS rel_type, r.layer AS layer,
       a.plane AS plane, properties(r) AS props
"""

_EDGES_TABLE = """
MATCH (a:Entity {plane:'campaign'})-[:BELONGS_TO]->(c:Entity {id:$campaign_id})
MATCH (b:Entity {plane:'campaign'})-[:BELONGS_TO]->(c)
MATCH (a)-[r]->(b)
WHERE r.layer IS NOT NULL
  AND ($layers IS NULL OR r.layer IN $layers)
RETURN a.id AS source_id, coalesce(a.canon_id, a.id) AS source_canon_id,
       b.id AS target_id, type(r) AS rel_type, r.layer AS layer,
       a.plane AS plane, properties(r) AS props
"""
```

`_EDGES_TABLE` binds `c` once and requires **both** endpoints to belong to it, preserving
Task 3's fix (both endpoints on the campaign plane) while adding campaign scoping.

Update `edges()` so the truth path runs `_EDGES_CANON` and `_EDGES_CAMPAIGN` (passing
`campaign_id` to the latter) and the table path runs `_EDGES_TABLE` with both `layers` and
`campaign_id`. Add `source_canon_id` to `_row_to_edge`'s output dict.

- [ ] **Step 6: Write the failing test for (B) — cross-plane shadowing**

In `tests/test_graph/test_resolver_integration.py`, replace the body of
`test_campaign_draw_shadows_the_tarokka_fan_out` (currently asserting the broken behaviour,
4 edges) with the corrected expectation, and update its docstring so it no longer documents
the defect as intended:

```python
    def test_campaign_draw_shadows_the_tarokka_fan_out(self, seeded):
        """Canon offers three sites for the Tome; this table drew the church.

        Shadowing keys on the campaign source's canon_id, so a copy-on-write
        campaign node's edge replaces the canon fan-out it descends from.
        """
        seeded.run(
            """
            MATCH (canon:Entity {id:'cos:item:tome-of-strahd'})
            MATCH (church:Entity {id:'cos:location:church-of-barovia'})
            MATCH (c:Entity {id:$campaign})
            CREATE (camp:Entity {id:'pytest:item:tome@a', plane:'campaign',
                                 entity_type:'ITEM',
                                 canon_id:'cos:item:tome-of-strahd'})
            CREATE (camp)-[:INSTANCE_OF]->(canon)
            CREATE (camp)-[:BELONGS_TO]->(c)
            CREATE (camp)-[:RESOLVES_TO {layer:'narrative'}]->(church)
            """,
            {"campaign": CAMPAIGN},
        ).consume()

        edges = PlaneResolver(CAMPAIGN).edges("truth", layers=["narrative"])
        resolves = [e for e in edges if e["rel_type"] == "RESOLVES_TO"]

        assert len(resolves) == 1, [e["target_id"] for e in resolves]
        assert resolves[0]["target_id"] == "cos:location:church-of-barovia"
        assert resolves[0]["source_id"] == "pytest:item:tome@a"
```

- [ ] **Step 7: Run to verify (B) fails**

Run: `uv run pytest tests/test_graph/test_resolver_integration.py::TestSeedUnderResolver::test_campaign_draw_shadows_the_tarokka_fan_out -v`
Expected: FAIL with 4 targets where 1 is expected. Capture the output.

- [ ] **Step 8: Fix (B) — key shadowing on the canonical source**

In `backend/graph/resolver.py`, change `shadow_edges` to key on the canonical source,
falling back to the edge's own source when there is no canon ancestor:

```python
def _canonical_source(edge: dict) -> str:
    """The id a campaign edge shadows against.

    A copy-on-write campaign node has its own id, so an edge from it can only
    replace the canon edge it descends from if both are keyed on the canon node.
    Edges with no canon ancestor key on themselves.
    """
    return edge.get("source_canon_id") or edge["source_id"]
```

and use `_canonical_source(e)` in place of `e["source_id"]` in both the shadow-set
comprehension and the `kept` filter. The `.get` fallback keeps Task 2's pure tests passing
unchanged — their fixtures have no `source_canon_id` — so **do not edit those tests**. If
any of them fails, stop and report; that would mean the fallback is wrong.

- [ ] **Step 9: Run the full suite**

Run: `uv run pytest -q` then `uv run pytest -q -m "not neo4j"`
Expected: both green. Report the counts.

- [ ] **Step 10: Commit**

```bash
git add backend/graph/resolver.py tests/test_graph/test_resolver_integration.py \
        tests/test_graph/test_resolver_neo4j.py
git commit -m "fix(graph): scope edges by campaign and shadow across the plane boundary"
```

---

## Verification

Whole suite: `uv run pytest -q` — 236 existing plus roughly 45 new.
Without a database: `uv run pytest -q -m "not neo4j"` must pass with Neo4j stopped.
Lint: `uv run ruff check backend/graph/ backend/canon/ tests/`

## Notes for the Implementer

- **The table view's asymmetry is the point.** Truth view merges canon and campaign; table view reads the campaign plane *only*. If you find yourself adding canon to the table view to make a test pass, the test is wrong — that is the spoiler defence.
- **`shadow_edges` keys on `(source_id, rel_type)`.** Task 5 will reveal whether that is the right key when the campaign node has its own id rather than the canon one. Treat the answer as a design finding, not a test to soften.
- **Nothing here extracts anything.** No LLM calls, no ChromaDB, no API spend. If a task seems to need them, it belongs to stage 2.
