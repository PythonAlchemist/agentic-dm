"""Carry newly authored aliases into a graph whose chapters are already written.

    uv run python -m backend.scripts.sync_authored_aliases --dry-run
    uv run python -m backend.scripts.sync_authored_aliases

An alias is written by `write_chapter`, so a spelling added to the seed after a
chapter landed reaches the graph only on a re-write. Re-writing is not a free
operation here -- the pipeline has moved since the live chapters were written,
so a replay changes CANON, not just aliases -- and gate G6 owns that decision.

So this adds the alias nodes and their `ALIAS_OF` edges and NOTHING else. No
entity is created or changed, no mention is touched, no canon claim is
re-derived. It is the same discipline as `backfill_display_names.py`.

WHAT THIS DELIBERATELY DOES NOT DO, and it matters for reading the numbers.
A new spelling can make the SCAN find mentions it previously missed -- a section
that only ever said "Bildrath" has no mention of Bildrath Cantemir today, and
this script does not create one, because creating mentions means re-scanning,
and re-scanning changes occurrence counts, co-occurrence edges and passages.
What it does fix immediately is RESOLUTION: a question or a lookup naming
"Bildrath" now reaches the entity, and reaches every mention already recorded
under his full name. The remaining mentions arrive with the next full write.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

from backend.canon.aliases import plan_aliases
from backend.canon.seed_loader import load_aliases
from backend.canon.writer import CANON_PLANE

ENTITIES = """
MATCH (e:Entity {plane:$plane})
WHERE e.name IS NOT NULL AND trim(e.name) <> ''
RETURN e.id AS id, e.name AS name
"""

#: MERGE on the surface form, exactly as `_write_alias` does, so running this
#: and then re-writing the chapter converge on one node rather than two.
WRITE = """
MATCH (e:Entity {id:$entity_id})
MERGE (a:Alias {name:$name})
SET a.normalized = $normalized, a.display_name = $name
MERGE (a)-[r:ALIAS_OF]->(e)
SET r.plane = $plane
RETURN count(a) AS c
"""

EXISTING = """
MATCH (a:Alias)-[:ALIAS_OF]->(e:Entity {plane:$plane})
RETURN a.name AS name, e.id AS id
"""


def sync(session, *, dry_run: bool = False) -> list[tuple[str, str]]:
    """Write every authored (entity, spelling) pair the graph is missing.

    Returns the pairs that were missing, so a caller can print them. A silent
    count would not let anyone check that the new spellings are the intended
    ones -- and an alias is a hand-written claim about what something is called,
    which is exactly the kind of thing that should be read rather than trusted.
    """
    authored = load_aliases()
    entities = [(row["id"], row["name"]) for row in session.run(ENTITIES, plane=CANON_PLANE)]
    planned = plan_aliases(entities, authored)

    have = {(row["id"], row["name"]) for row in session.run(EXISTING, plane=CANON_PLANE)}
    missing = [a for a in planned if (a.entity_id, a.name) not in have]

    if not dry_run:
        for alias in missing:
            session.run(
                WRITE,
                {
                    "entity_id": alias.entity_id,
                    "name": alias.name,
                    "normalized": alias.normalized,
                    "plane": CANON_PLANE,
                },
            )
    return [(a.name, a.entity_id) for a in missing]


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
            missing = sync(session, dry_run=args.dry_run)
    finally:
        driver.close()

    verb = "would add" if args.dry_run else "added"
    for name, entity_id in sorted(missing):
        print(f"  {verb}: {name!r} -> {entity_id}")
    tail = "missing" if args.dry_run else "added"
    print(f"  {len(missing)} alias{'' if len(missing) == 1 else 'es'} {tail}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
