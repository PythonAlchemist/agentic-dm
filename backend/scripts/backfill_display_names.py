"""Give every node already in the graph the `display_name` Browser captions on.

Nodes written from now on get it from the write path. This is for the ones
written before it existed, and it is deliberately the SMALLEST possible change
to a live graph: it SETs one property and does nothing else. No node is
created, no node is deleted, no relationship is touched, and no canon claim is
re-derived.

WHY NOT JUST RE-WRITE THE CHAPTERS. Replaying a chapter through
`write_canon.py` would produce the property as a side effect, and it is the
wrong tool: the pipeline has changed since the live chapters were written, so a
replay of `introduction` writes five edges where the graph holds two. That may
well be an improvement, but it is a change to CANON, and it must be argued for
on its own rather than ridden in on a styling fix.

THE CAPTION RULE LIVES IN ONE PLACE. Every value here comes from the same
dataclass the writer uses, imported rather than reimplemented -- notably the
mention's `x<n>` suffix, which a hand-written Cypher `CASE` would have made a
second definition of. This project has been bitten by second definitions of a
rule (see `passage.py`), so the loop below is slower than one big Cypher
statement on purpose.

    uv run python -m backend.scripts.backfill_display_names --dry-run
    uv run python -m backend.scripts.backfill_display_names
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

from backend.canon.spine import WriteMention

#: One entry per node kind whose caption is a property already on the node.
#: `:Mention` is absent because its caption comes from a NEIGHBOUR, which is
#: what `_MENTION_ROWS` is for.
_SIMPLE = (
    ("Entity", "name"),
    ("Section", "heading"),
    ("Chapter", "title"),
    ("Book", "title"),
    ("Alias", "name"),
)

#: Only rows that would actually change are returned, so a second run reports
#: zero rather than rewriting every node with the value it already has.
_SIMPLE_ROWS = """
MATCH (n:{label})
WHERE n.{source} IS NOT NULL AND trim(n.{source}) <> ''
  AND (n.display_name IS NULL OR n.display_name <> n.{source})
RETURN elementId(n) AS eid, n.{source} AS value
"""

#: A mention's caption names the SECTION it sits in -- see
#: `WriteMention.properties` for why the entity's name was the wrong choice.
#: Both endpoints are required and a mention missing either is SKIPPED rather
#: than captioned blank: it is a broken mention, and this script's job is not to
#: paper over that.
_MENTION_ROWS = """
MATCH (m:Mention)-[:REFERS_TO]->(e:Entity)
MATCH (m)-[:IN_SECTION]->(s:Section)
WHERE e.name IS NOT NULL AND trim(e.name) <> ''
  AND s.heading IS NOT NULL AND trim(s.heading) <> ''
RETURN elementId(m) AS eid, m.id AS id, e.id AS entity_id, e.name AS entity_name,
       s.heading AS section_heading,
       m.chapter_slug AS chapter_slug, m.occurrences AS occurrences,
       m.offsets[0] AS offset, m.display_name AS current
"""

_SET = "MATCH (n) WHERE elementId(n) = $eid SET n.display_name = $value"


def _mention_caption(row) -> str:
    """The writer's own rule, not a copy of it."""
    return WriteMention(
        id=row["id"],
        entity_id=row["entity_id"],
        section_id="",  # not part of the caption; never written by this script
        chapter_slug=row["chapter_slug"] or "",
        occurrences=row["occurrences"] or 1,
        offset=row["offset"] or 0,
        entity_name=row["entity_name"],
        section_heading=row["section_heading"],
    ).properties["display_name"]


def backfill(session, *, dry_run: bool = False) -> dict[str, int]:
    """Set `display_name` wherever it is missing or stale. Returns per-label counts."""
    counts: dict[str, int] = {}

    for label, source in _SIMPLE:
        rows = list(session.run(_SIMPLE_ROWS.format(label=label, source=source)))
        if not dry_run:
            for row in rows:
                session.run(_SET, {"eid": row["eid"], "value": row["value"]})
        counts[label] = len(rows)

    stale = [
        (row["eid"], caption)
        for row in session.run(_MENTION_ROWS)
        if (caption := _mention_caption(row)) != row["current"]
    ]
    if not dry_run:
        for eid, caption in stale:
            session.run(_SET, {"eid": eid, "value": caption})
    counts["Mention"] = len(stale)

    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count what would change and write nothing",
    )
    args = parser.parse_args()

    load_dotenv(Path.cwd() / ".env")
    driver = GraphDatabase.driver(
        os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD")),
    )
    try:
        with driver.session() as session:
            counts = backfill(session, dry_run=args.dry_run)
    finally:
        driver.close()

    verb = "would set" if args.dry_run else "set"
    for label, count in counts.items():
        print(f"  {verb} display_name on {count:>4} :{label}")
    total = sum(counts.values())
    print(f"  {total} node{'' if total == 1 else 's'} {verb.split()[-1]}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
