"""Load hand-authored canon YAML into Neo4j.

Seeds live in this package rather than under data/ because data/ is gitignored and
a seed is source: it is committed, reviewed, and doubles as the golden set that
stage 2's extractor is graded against.
"""

from collections import Counter
from pathlib import Path

import yaml

from backend.graph.schema import LAYER_MAP, EntityType, RelationshipType

SEED_DIR = Path(__file__).parent / "seeds"

# Grading metadata, not graph data. A marked entry is a fact the seed asserts but the
# seed's own chapter does not state, so a run over that chapter must not be scored
# against it. Stripped before writing -- see `_GRADING_KEYS`.
#
# The axis is chapter numbers rather than a stated/implied/external scheme, because
# per-chapter golden subsets are what `extractable_subset` exists to produce.
EXTRACTABLE_FROM = "extractable_from"
EXTRACTABLE_SOURCES = {"ch1", "ch2"}

# The chapter this seed's unmarked entries are expected to come from.
DEFAULT_SOURCE = "ch3"

_GRADING_KEYS = {EXTRACTABLE_FROM}
RESERVED_EDGE_KEYS = {"source", "target", "type"} | _GRADING_KEYS


def validate_seed(data: dict) -> list[str]:
    """Return human-readable problems with a seed document. Empty means valid."""
    problems: list[str] = []
    known_types = {r.value for r in RelationshipType}
    known_entity_types = {t.value for t in EntityType}
    ids = {n.get("id") for n in data.get("nodes", [])}

    id_counts = Counter(n.get("id") for n in data.get("nodes", []))
    for dup_id, count in id_counts.items():
        if dup_id is not None and count > 1:
            problems.append(f"duplicate node id {dup_id!r} declared {count} times")

    for node in data.get("nodes", []):
        for field in ("id", "name", "entity_type"):
            if not node.get(field):
                problems.append(f"node missing {field}: {node}")
        entity_type = node.get("entity_type")
        if entity_type is not None and entity_type not in known_entity_types:
            problems.append(f"unknown entity_type {entity_type!r} in {node}")

    for e in data.get("edges", []):
        if e.get("type") not in known_types:
            problems.append(f"unknown relationship type {e.get('type')!r} in {e}")
        for end in ("source", "target"):
            if e.get(end) not in ids:
                problems.append(f"edge {end} not declared as a node: {e.get(end)!r}")

    for entry in [*data.get("nodes", []), *data.get("edges", [])]:
        marker = entry.get(EXTRACTABLE_FROM)
        if marker is not None and marker not in EXTRACTABLE_SOURCES:
            problems.append(
                f"unknown {EXTRACTABLE_FROM} {marker!r} "
                f"(expected one of {sorted(EXTRACTABLE_SOURCES)}) in {entry}"
            )

    return problems


def extractable_subset(data: dict, source: str = DEFAULT_SOURCE) -> dict:
    """The nodes and edges an extraction run over `source` should be graded against.

    Entries carrying an `extractable_from` marker name a different chapter, so a run
    over this seed's own chapter cannot be expected to produce them.
    Grading against the whole seed penalises an extractor for correctly reading only
    what its input actually says, and rewards one that invents the rest.

    Unmarked entries belong to DEFAULT_SOURCE. Asking for a marked source returns only
    entries carrying that marker -- NOT that chapter plus everything before it.

    Whether a later chapter's expected set should be cumulative depends on how stage 2
    feeds its extractor: strict-per-source is right if each run sees one chapter's text,
    and under-grades every later run if runs see cumulative text. Deliberately left
    strict until that consumer exists, rather than guessing the semantics here.

    ONE exception to the strictness, and it is not a guess: a node referenced by a kept
    edge is kept too, whatever its own marker says. A subset that emits an edge but not
    its endpoint emits an edge nothing can ever match -- `grade` resolves an endpoint id
    to the names of a node in the same subset, so a missing endpoint yields an empty name
    set and the edge fails at every looseness. Measured: `ireena-kolyana IDENTITY_OF
    tatyana` sat in the chapter-3 edge subset while Tatyana (marked ch1) sat outside the
    node subset, a permanent 4-point floor on edge recall that was read as an extraction
    failure for four review rounds.

    Keeping the edge and pulling its endpoint in, rather than dropping the edge, because
    an edge IS the joint assertion that both its ends exist: asking an extractor for
    `Ireena IDENTITY_OF Tatyana` is asking it to name Tatyana. Dropping the edge instead
    would silently shrink the key on chapter 3's most plot-central fact -- and would
    empty the ch1 subset of the entire Tarokka fan-out, which is the only thing that
    subset grades.
    """
    if source == DEFAULT_SOURCE:
        keep = lambda entry: entry.get(EXTRACTABLE_FROM) is None  # noqa: E731
    else:
        keep = lambda entry: entry.get(EXTRACTABLE_FROM) == source  # noqa: E731

    edges = [e for e in data.get("edges", []) if keep(e)]
    needed = {n.get("id") for n in data.get("nodes", []) if keep(n)}
    needed.update(e.get(end) for e in edges for end in ("source", "target"))

    # Filtered from the seed rather than appended, so pulled-in endpoints keep the
    # order the seed author wrote them in.
    return {
        "nodes": [n for n in data.get("nodes", []) if n.get("id") in needed],
        "edges": edges,
    }


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
        props = {
            k: v
            for k, v in node.items()
            if k != "id" and k != "entity_type" and k not in _GRADING_KEYS
        }
        props.setdefault("plane", "canon")
        props.setdefault("source_book", "cos")
        # The type is a LABEL, as it is on every node `canon.writer` writes --
        # `MATCH (n:NPC)`, not `MATCH (n:Entity {entity_type:'NPC'})`. Coerced
        # through the enum first because a label cannot be parameterized in
        # Cypher and is interpolated into the statement; `validate_seed` has
        # already refused anything the enum does not know, and this is the
        # second lock on the same door.
        raw_type = node.get("entity_type")
        label = f":{EntityType(raw_type).value}" if raw_type else ""
        session.run(
            f"MERGE (e:Entity {{id:$id}}) {f'SET e{label} ' if label else ''}SET e += $props",
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
