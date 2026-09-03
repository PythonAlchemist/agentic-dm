#!/usr/bin/env python3
"""Put the graph's constraints and indexes in place.

    uv run python -m backend.scripts.apply_schema

`GRAPH_SCHEMA` has always held them and only `CampaignGraphOps.__init__`
applied them -- a class the product no longer constructs -- so a fresh database
came up with no uniqueness at all. Several tests exist precisely to prove that
a duplicate id is REFUSED rather than silently doubling a node, and on an
unconstrained instance they would have been asserting nothing.

Idempotent: every statement is `IF NOT EXISTS`, so running it against a
database that already has them is a no-op.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.core.database import neo4j_session
from backend.graph.schema import GRAPH_SCHEMA


def main() -> int:
    applied, failed = 0, []
    with neo4j_session() as session:
        for kind in ("constraints", "indexes"):
            for statement in GRAPH_SCHEMA.get(kind, []):
                try:
                    session.run(statement).consume()
                    applied += 1
                except Exception as bad:  # noqa: BLE001
                    # COUNTED, NEVER SILENT. A full-text index needs a plugin
                    # that may not be installed, and that is worth reporting
                    # rather than swallowing.
                    failed.append((statement.split()[2], str(bad).split("\n")[0]))
    print(f"  applied {applied}")
    for name, why in failed:
        print(f"  skipped {name}: {why[:90]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
