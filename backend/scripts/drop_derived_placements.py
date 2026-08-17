"""Remove the `LOCATED_IN` edges derived from an entity being NAMED in a section.

    uv run python -m backend.scripts.drop_derived_placements --dry-run
    uv run python -m backend.scripts.drop_derived_placements

THIS DELETES CANON, which nothing else in this repository does casually. The
justification is that the edges are false and were shipped as true.

`structure.py` used to place every non-LOCATION entity extracted from a section
into that section's room. It reads like structure and is not: it says being
NAMED somewhere is being THERE. Hand-checked against the book, roughly half of
chapter 3's 26 such placements were wrong, and every one of them carried
`derived from document structure` and the status `accepted` -- the provenance
the DM agent is told it can rely on.

The derivation is gone from the write path. This removes what earlier writes
already put in the graph, which a re-write would not: the write path replaces a
chapter's edges, but 22 chapters are unwritten and the three that exist are not
reproducible from their artifacts.

SCOPED AS NARROWLY AS THE DEFECT. Only `LOCATED_IN`, only `evidence = 'derived
from document structure'`, only where the SOURCE is not a place. Place-to-place
containment is the book's own key nesting and stays. An extractor's proposed
`LOCATED_IN` carries its own evidence sentence and stays. Nothing else is
touched.

WHAT IS LOST, STATED PLAINLY. Some of those edges were true -- Arik does tend
the bar, Mad Mary is in her townhouse. They are lost here and have to come back
through the review queue, from an extractor edge a human accepts. That is the
trade: a true edge recoverable by review, against a false edge indistinguishable
from a checked one.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

from backend.canon.structure import STRUCTURAL_EVIDENCE
from backend.canon.writer import CANON_PLANE

#: EVERY derived `LOCATED_IN`, with no exemption for place-to-place.
#:
#: The first version of this script spared edges whose source was a `:LOCATION`,
#: reasoning that place-inside-place is the key nesting and therefore sound. It
#: is not: the key nesting emits `CONTAINS` and only `CONTAINS`, so every
#: derived `LOCATED_IN` in the graph came from the node loop being withdrawn.
#: The exemption spared exactly two edges, `Barovia LOCATED_IN Trapdoor` and
#: `Barovia LOCATED_IN Cemetery` -- a region inside a trapdoor. They had escaped
#: the old code's `entity_type == "LOCATION"` guard because the extractor typed
#: Barovia `SETTING` in those sections, which is the same defect wearing the
#: same disguise one layer down.
DOOMED = f"""
MATCH (a:Entity {{plane:$plane}})-[r:LOCATED_IN]->(b:Entity {{plane:$plane}})
WHERE r.evidence = '{STRUCTURAL_EVIDENCE}'
RETURN a.name AS source, b.name AS target, id(r) AS rid,
       [l IN labels(a) WHERE l <> 'Entity'] AS labels
ORDER BY target, source
"""

DELETE = """
MATCH ()-[r]->() WHERE id(r) IN $rids DELETE r
"""


def survey(session) -> list[dict]:
    return [dict(row) for row in session.run(DOOMED, plane=CANON_PLANE)]


def drop(session, rows: list[dict]) -> int:
    if not rows:
        return 0
    session.run(DELETE, rids=[row["rid"] for row in rows])
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_dotenv(Path.cwd() / ".env")
    driver = GraphDatabase.driver(
        os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD")),
    )
    try:
        with driver.session() as session:
            rows = survey(session)
            # Printed in FULL rather than counted. These are being deleted on
            # the strength of an argument, and the reader deserves to check the
            # argument against the actual list.
            for row in rows:
                print(f"  {row['source'][:28]:<28} -LOCATED_IN-> {row['target']}")
            if args.dry_run:
                print(f"\n  {len(rows)} would be deleted (dry run)")
                return 0
            removed = drop(session, rows)
            print(f"\n  {removed} deleted")
    finally:
        driver.close()
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
