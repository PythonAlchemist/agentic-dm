"""Copy the graph to a deployed Neo4j, over bolt.

    uv run python -m backend.scripts.push_graph --to bolt+s://host:7687 --apply

WHY OVER BOLT rather than a dump and restore: a dump needs the database
stopped and a shell on the box, which Railway and Aura both make awkward, and
this graph is 13k nodes -- small enough that streaming it is the simpler
mechanism. It also works against either host without change, and can be run
again after the local graph moves on.

WHY NOT `MERGE` ON `id`: 2,430 nodes carry no `id` at all -- every Alias,
Chapter, Book and the Campaign -- so an id-keyed copy would fold all 2,389
aliases onto one node and quietly lose the graph's whole naming layer. Nodes
are keyed instead by a temporary `_import_id` holding the SOURCE elementId,
which every node has, and which is removed once the relationships are built.

DRY RUN UNLESS `--apply`, and it refuses a target that already holds nodes
unless `--wipe` says otherwise. The target is a remote database somebody may
be reading from; nothing here should be a surprise.
"""

from __future__ import annotations

import argparse
import os
import sys

from neo4j import GraphDatabase

from backend.core.config import settings
from backend.core.database import read_only_session
from backend.graph.schema import GRAPH_SCHEMA

#: Written to every node so relationships can find their endpoints, then
#: removed. Named with a leading underscore because it is scaffolding, and
#: `check_invariants` would rightly complain if it were left behind.
KEY = "_import_id"

#: Rows per write. Small enough to stay inside the default transaction limits
#: on a free-tier host, large enough that 41k relationships is a minute.
BATCH = 500


def _chunks(rows: list, size: int = BATCH):
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


def read_source() -> tuple[list[dict], list[dict]]:
    """Every node and relationship, keyed by source elementId."""
    with read_only_session() as session:
        nodes = [
            {"key": r["key"], "labels": r["labels"], "props": dict(r["props"])}
            for r in session.run(
                f"MATCH (n) RETURN elementId(n) AS key, labels(n) AS labels, "
                f"properties(n) AS props"
            )
        ]
        edges = [
            {
                "a": r["a"],
                "b": r["b"],
                "type": r["type"],
                "props": dict(r["props"]),
            }
            for r in session.run(
                "MATCH (a)-[r]->(b) RETURN elementId(a) AS a, elementId(b) AS b, "
                "type(r) AS type, properties(r) AS props"
            )
        ]
    return nodes, edges


def push(session, nodes: list[dict], edges: list[dict], wipe: bool) -> None:
    if wipe:
        # IN BATCHES, because one `DETACH DELETE` over a full graph is a single
        # transaction big enough to exhaust a small host's heap.
        while True:
            gone = session.run(
                "MATCH (n) WITH n LIMIT 10000 DETACH DELETE n RETURN count(n) AS c"
            ).single()["c"]
            print(f"  wiped {gone}")
            if gone == 0:
                break

    for ddl in GRAPH_SCHEMA.get("constraints", []) + GRAPH_SCHEMA.get("indexes", []):
        session.run(ddl)
    print(f"  schema: {len(GRAPH_SCHEMA.get('constraints', []))} constraints, "
          f"{len(GRAPH_SCHEMA.get('indexes', []))} indexes")

    # THE INDEX ON `_import_id` IS NOT OPTIONAL. Without it each of the 41k
    # relationships scans all 13k nodes twice to find its endpoints, which is
    # a billion comparisons and turns a one-minute copy into an afternoon.
    session.run(f"CREATE INDEX import_key IF NOT EXISTS FOR (n:_Imported) ON (n.{KEY})")

    # GROUPED BY LABEL SET, because labels cannot be parameterised in Cypher
    # and one statement per node would be 13k round trips.
    by_labels: dict[tuple[str, ...], list[dict]] = {}
    for node in nodes:
        by_labels.setdefault(tuple(sorted(node["labels"])), []).append(node)

    written = 0
    for labels, group in by_labels.items():
        tags = "".join(f":`{label}`" for label in labels)
        for batch in _chunks(group):
            session.run(
                f"UNWIND $rows AS row CREATE (n:_Imported{tags}) "
                f"SET n = row.props, n.{KEY} = row.key",
                rows=batch,
            )
            written += len(batch)
    print(f"  nodes: {written} in {len(by_labels)} label set(s)")

    by_type: dict[str, list[dict]] = {}
    for edge in edges:
        by_type.setdefault(edge["type"], []).append(edge)

    linked = 0
    for rel_type, group in by_type.items():
        for batch in _chunks(group):
            result = session.run(
                f"UNWIND $rows AS row "
                f"MATCH (a:_Imported {{{KEY}: row.a}}), (b:_Imported {{{KEY}: row.b}}) "
                f"CREATE (a)-[r:`{rel_type}`]->(b) SET r = row.props "
                f"RETURN count(r) AS c",
                rows=batch,
            ).single()
            linked += result["c"]
    print(f"  relationships: {linked} in {len(by_type)} type(s)")

    # NEVER SILENT. A relationship whose endpoints did not match is a hole in
    # the copy, and a copy that quietly loses edges is worse than one that
    # fails, because the graph still answers -- just wrongly.
    if linked != len(edges):
        print(f"  WARNING: {len(edges) - linked} relationship(s) found no endpoint")

    # THE SCAFFOLDING COMES OFF. `_Imported` and `_import_id` exist only to
    # join the two passes above; leaving them turns every future query's label
    # scan into a wider one and leaves a property no part of the app knows.
    while True:
        stripped = session.run(
            f"MATCH (n:_Imported) WITH n LIMIT 10000 "
            f"REMOVE n:_Imported, n.{KEY} RETURN count(n) AS c"
        ).single()["c"]
        if stripped == 0:
            break
    session.run("DROP INDEX import_key IF EXISTS")
    print("  scaffolding removed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--to", default=os.environ.get("TARGET_NEO4J_URI", ""),
                        help="Target bolt URI. Or TARGET_NEO4J_URI.")
    parser.add_argument("--to-user", default=os.environ.get("TARGET_NEO4J_USER", "neo4j"))
    parser.add_argument("--to-password",
                        default=os.environ.get("TARGET_NEO4J_PASSWORD", ""))
    parser.add_argument("--apply", action="store_true",
                        help="Actually write. Without this, nothing is sent.")
    parser.add_argument("--wipe", action="store_true",
                        help="Delete everything on the target first.")
    args = parser.parse_args()

    if not args.to or not args.to_password:
        print("need --to and --to-password (or TARGET_NEO4J_*)", file=sys.stderr)
        return 2

    # A TYPO HERE WOULD OVERWRITE THE GRAPH THIS READS FROM, and `--wipe` makes
    # that unrecoverable. Cheap to check, so checked.
    if args.to == settings.neo4j_uri:
        print(f"--to is the SOURCE ({settings.neo4j_uri}); refusing", file=sys.stderr)
        return 2

    nodes, edges = read_source()
    print(f"source: {len(nodes)} nodes, {len(edges)} relationships "
          f"({settings.neo4j_uri})")

    driver = GraphDatabase.driver(args.to, auth=(args.to_user, args.to_password))
    try:
        with driver.session() as session:
            standing = session.run("MATCH (n) RETURN count(n) AS c").single()["c"]
            print(f"target: {standing} nodes ({args.to})")

            if standing and not args.wipe:
                print("\ntarget is not empty. --wipe to replace it, or point "
                      "somewhere else.", file=sys.stderr)
                return 1

            if not args.apply:
                print(f"\ndry run. --apply to write {len(nodes)} nodes and "
                      f"{len(edges)} relationships"
                      + (f", replacing {standing}" if standing else "") + ".")
                return 0

            push(session, nodes, edges, wipe=bool(standing and args.wipe))

            after = session.run("MATCH (n) RETURN count(n) AS c").single()["c"]
            rels = session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
            print(f"\ntarget now holds {after} nodes, {rels} relationships")
            if after != len(nodes) or rels != len(edges):
                print("WARNING: that does not match the source", file=sys.stderr)
                return 1
    finally:
        driver.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
