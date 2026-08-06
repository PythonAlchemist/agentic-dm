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

RESERVED_EDGE_KEYS = {"source", "target", "type"}


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
