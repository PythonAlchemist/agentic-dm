"""Record a human's decision on proposed canon.

    uv run python -m backend.scripts.accept_edges the-village-of-barovia \
        --accept "Mirabel|OWNS|Blood of the Vine Tavern"
    uv run python -m backend.scripts.accept_edges the-village-of-barovia --reject "..."

`review_queue.py` prints the queue; this is the other half, and without it the
queue was a list nobody could act on. The design has said since the accepted /
proposed split was introduced that unverified edges go to a human -- but there
was no way to record what the human decided, so every reviewed edge stayed
proposed and the agent went on hedging about facts somebody had already checked.

WHAT ACCEPTANCE MEANS, precisely: a person read the edge against the book's own
sentence and found it true. It does not mean a model agreed, or that votes were
unanimous -- `Mirabel OWNS Blood of the Vine Tavern` had five of five votes and
sat proposed beside `Madam Eva LOCATED_IN` the same tavern, which had none and
sat accepted. Vote count is not evidence of truth; it is evidence of agreement.

THE DECISION IS RECORDED, NOT JUST APPLIED. `reviewed_by` and `reviewed_at` land
on the edge, so a later reader can tell an edge a human accepted from one the
pipeline derived -- both end up `accepted`, and without the stamp they would be
indistinguishable. A rejected edge is stamped and left in place rather than
deleted: knowing an edge was examined and refused is worth more than its absence,
which reads identically to never having been proposed.
"""

from __future__ import annotations

import argparse
import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

from backend.canon.writer import CANON_PLANE

ACCEPTED = "accepted"
REJECTED = "rejected"

#: Matched on NAMES rather than ids, because a reviewer is reading the queue's
#: rendered output, which prints names. The chapter scopes it, so two entities
#: sharing a name in different chapters cannot be confused.
SET_STATUS = """
MATCH (a:Entity {plane:$plane})-[r]->(b:Entity {plane:$plane})
WHERE a.name = $source AND b.name = $target AND type(r) = $rel_type
  AND r.chapter_slug = $slug
SET r.status = $status, r.reviewed_by = $who, r.reviewed_at = $when
RETURN count(r) AS c
"""


def parse_spec(spec: str) -> tuple[str, str, str]:
    """`Source|REL_TYPE|Target`.

    Pipe-separated because every one of the book's names contains spaces and
    several contain commas, colons and apostrophes -- `The Blade of Truth: The
    Uses of Logic...` is a real entity. A pipe appears nowhere in the corpus.
    """
    parts = [part.strip() for part in spec.split("|")]
    if len(parts) != 3 or not all(parts):
        raise ValueError(
            f"expected 'Source|REL_TYPE|Target', got {spec!r}"
        )
    return parts[0], parts[1], parts[2]


def set_status(session, slug: str, spec: str, status: str, who: str) -> int:
    source, rel_type, target = parse_spec(spec)
    return session.run(
        SET_STATUS,
        {
            "plane": CANON_PLANE,
            "slug": slug,
            "source": source,
            "target": target,
            "rel_type": rel_type,
            "status": status,
            "who": who,
            "when": date.today().isoformat(),
        },
    ).single()["c"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("chapter", metavar="SLUG")
    parser.add_argument("--accept", action="append", default=[], metavar="SPEC")
    parser.add_argument("--reject", action="append", default=[], metavar="SPEC")
    parser.add_argument(
        "--by",
        default=os.getenv("USER", "unknown"),
        help="Who reviewed it. Recorded on the edge.",
    )
    args = parser.parse_args()

    if not args.accept and not args.reject:
        parser.error("nothing to do: pass --accept or --reject")

    load_dotenv(Path.cwd() / ".env")
    driver = GraphDatabase.driver(
        os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD")),
    )
    missed = 0
    try:
        with driver.session() as session:
            for status, specs in ((ACCEPTED, args.accept), (REJECTED, args.reject)):
                for spec in specs:
                    changed = set_status(session, args.chapter, spec, status, args.by)
                    # A spec that matched NOTHING is reported loudly. Silently
                    # doing nothing is how a reviewer comes to believe they have
                    # cleared a queue they have not touched.
                    mark = "ok" if changed else "NO MATCH"
                    print(f"  {status:<8} {spec}  [{mark}]")
                    if not changed:
                        missed += 1
    finally:
        driver.close()
    return 1 if missed else 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
