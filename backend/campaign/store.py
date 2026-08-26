"""Reading and writing a campaign's chain. The only module that runs Cypher for it.

`chain.py` decides what SHOULD change and can be tested without a database;
this applies the decision and re-asserts it. The split is `plan_write`'s, and
the reason is the same: a rule that only exists inside a transaction cannot be
argued with.

EVERY MUTATION RE-ASSERTS INTEGRITY BEFORE COMMITTING, with the membership the
caller intended. A chain is pointers, and a half-applied rewire leaves a
running order that is quietly wrong rather than obviously broken -- so the
check runs inside the same transaction and a violation rolls the whole thing
back. `integrity` is given `expected` for the failure it otherwise cannot see:
a section that fell out of the chain completely leaves the remaining links
perfectly sound.

EVERY APPLIED MUTATION IS LOGGED, one JSON line, `write_log_record`'s pattern.
The log is what makes a linked list survivable: homebrew sections and SKIPPED
records are nodes and edges and outlive any corruption, but the POSITIONS of a
DM's decisions live only in pointers. Re-seed from the spine, replay the log,
and nothing is lost.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from backend.campaign.chain import Link, Rewire, integrity, walk
from backend.campaign.model import (
    CAMPAIGN_PLANE,
    DRAWS_ON,
    NEXT,
    SKIPPED,
    STARTS_AT,
    Campaign,
)
from backend.canon.lookup import CANON_PLANE, write_log_record

logger = logging.getLogger(__name__)

#: Where chain mutations are recorded. Beside `query-log.jsonl` and for the
#: same reason: the interesting history of a system is not in its final state.
DEFAULT_LOG_PATH = Path("data/campaign-log.jsonl")


class ChainCorrupted(Exception):
    """A rewire would have left the running order unsound. Nothing was written."""

    def __init__(self, slug: str, problems: tuple[str, ...]) -> None:
        super().__init__(
            f"refusing to change {slug}'s running order: "
            + "; ".join(problems)
            + " -- nothing was written"
        )
        self.slug = slug
        self.problems = problems


# -- reads ------------------------------------------------------------------

SPINE = """
MATCH (b:Book {slug:$book, plane:$plane})-[:HAS_CHAPTER]->(c:Chapter)-[:HAS_SECTION]->(s:Section)
RETURN s.id AS id
ORDER BY c.index, s.index
"""

CHAIN = f"""
MATCH (a:Section)-[r:{NEXT} {{campaign:$slug}}]->(b:Section)
RETURN a.id AS source, b.id AS target
"""

START = f"""
MATCH (:Campaign {{slug:$slug}})-[:{STARTS_AT}]->(s:Section)
RETURN s.id AS id
"""

SKIPPED_SECTIONS = f"""
MATCH (:Campaign {{slug:$slug}})-[:{SKIPPED}]->(s:Section)
RETURN s.id AS id
"""

CAMPAIGNS = f"""
MATCH (c:Campaign)
OPTIONAL MATCH (c)-[:{DRAWS_ON}]->(b:Book)
RETURN c.slug AS slug, c.name AS name, collect(b.slug) AS books
ORDER BY c.slug
"""


def spine_order(session, book: str) -> list[str]:
    """The book's sections in the order the book prints them.

    `ORDER BY chapter_index, section_index` IS the pre-order walk of the
    document's tree -- `index` was assigned as the headings were read -- so no
    tree traversal happens here or anywhere. See `chain.seed_plan`.
    """
    return [dict(r)["id"] for r in session.run(SPINE, {"book": book, "plane": CANON_PLANE})]


def read_chain(session, slug: str) -> tuple[frozenset[Link], str | None]:
    links = frozenset(
        (dict(r)["source"], dict(r)["target"]) for r in session.run(CHAIN, {"slug": slug})
    )
    row = session.run(START, {"slug": slug}).single()
    return links, (dict(row)["id"] if row else None)


def read_skipped(session, slug: str) -> frozenset[str]:
    return frozenset(dict(r)["id"] for r in session.run(SKIPPED_SECTIONS, {"slug": slug}))


CANON_ALIASES = """
MATCH (b:Book {slug:$book, plane:$plane})-[:HAS_CHAPTER]->(:Chapter)-[:HAS_SECTION]->(s:Section)
MATCH (s)<-[:IN_SECTION]-(:Mention)-[:REFERS_TO]->(e:Entity {plane:$plane})
MATCH (a:Alias)-[:ALIAS_OF]->(e)
RETURN DISTINCT a.normalized AS normalized, e.id AS id
"""


def canon_aliases(session, books) -> frozenset[tuple[str, str]]:
    """Every canon name the drawn books use, folded, with the entity it names.

    Read for the cluster planner's collision scan. `hb:` and `<book>:` are
    different namespaces, so a generated "Varrin Axebreaker" would otherwise
    mint happily and leave two nodes answering to one name through
    `resolve_name` -- exactly the silent duplication the anthology work spent a
    day undoing.

    THE FOLD IS `aliases.normalize`, READ OFF THE STORED PROPERTY, never a
    second normaliser computed here. `a.normalized` is what `BY_ALIAS` matches
    on; a scan folding names its own way would miss precisely the collisions
    that matter -- the curly apostrophe in `Vidorant's Vault` is the standing
    example.
    """
    found: set[tuple[str, str]] = set()
    for book in books:
        for record in session.run(CANON_ALIASES, {"book": book, "plane": CANON_PLANE}):
            row = dict(record)
            if row["normalized"]:
                found.add((row["normalized"], row["id"]))
    return frozenset(found)


def read_campaigns(session) -> list[Campaign]:
    return [
        Campaign(
            slug=dict(r)["slug"],
            name=dict(r)["name"] or dict(r)["slug"],
            books=tuple(b for b in dict(r)["books"] if b),
        )
        for r in session.run(CAMPAIGNS)
    ]


def running_order(session, slug: str) -> list[str]:
    """What this table plays, in order. Derived, never stored twice."""
    links, start = read_chain(session, slug)
    return list(walk(links, start, bound=len(links) + 2).order)


# -- writes -----------------------------------------------------------------


def create(tx, campaign: Campaign) -> None:
    """The Campaign node and what it draws on. No chain yet."""
    tx.run(
        """
        MERGE (c:Campaign {slug:$slug})
        SET c.name = $name, c.plane = $plane
        """,
        {"slug": campaign.slug, "name": campaign.name, "plane": CAMPAIGN_PLANE},
    )
    for book in campaign.books:
        tx.run(
            f"""
            MATCH (c:Campaign {{slug:$slug}}), (b:Book {{slug:$book, plane:$plane}})
            MERGE (c)-[:{DRAWS_ON}]->(b)
            """,
            {"slug": campaign.slug, "book": book, "plane": CANON_PLANE},
        )


def apply_rewire(
    tx, slug: str, rewire: Rewire, expected: frozenset[str], *, log_path: Path | None = None
) -> dict:
    """Apply one plan, assert the result, and record what happened.

    Raises `ChainCorrupted` -- rolling the transaction back -- rather than
    committing a running order that does not hold together.
    """
    if rewire.noop:
        return {"changed": 0, "noop": rewire.noop}

    for source, target in rewire.unlink:
        tx.run(
            f"""
            MATCH (:Section {{id:$a}})-[r:{NEXT} {{campaign:$slug}}]->(:Section {{id:$b}})
            DELETE r
            """,
            {"a": source, "b": target, "slug": slug},
        )
    for source, target in rewire.link:
        tx.run(
            f"""
            MATCH (a:Section {{id:$a}}), (b:Section {{id:$b}})
            MERGE (a)-[r:{NEXT} {{campaign:$slug}}]->(b)
            SET r.plane = $plane
            """,
            {"a": source, "b": target, "slug": slug, "plane": CAMPAIGN_PLANE},
        )
    if rewire.sets_start:
        tx.run(
            f"MATCH (:Campaign {{slug:$slug}})-[r:{STARTS_AT}]->() DELETE r", {"slug": slug}
        )
        if rewire.start is not None:
            tx.run(
                f"""
                MATCH (c:Campaign {{slug:$slug}}), (s:Section {{id:$id}})
                MERGE (c)-[:{STARTS_AT}]->(s)
                """,
                {"slug": slug, "id": rewire.start},
            )

    links, start = read_chain(tx, slug)
    problems = integrity(links, start, expected)
    if problems:
        raise ChainCorrupted(slug, problems)

    record = {
        "campaign": slug,
        "unlink": [list(p) for p in rewire.unlink],
        "link": [list(p) for p in rewire.link],
        "start": rewire.start if rewire.sets_start else None,
        "sets_start": rewire.sets_start,
    }
    write_log_record(log_path or DEFAULT_LOG_PATH, record)
    return {"changed": rewire.changes, "noop": ""}


def mark_skipped(tx, slug: str, section_id: str) -> None:
    """Record that the DM cut this, as a fact and not as an absence.

    Without it, reconciliation cannot tell a section the DM removed from one
    the book gained after seeding -- and those want opposite repairs.
    """
    tx.run(
        f"""
        MATCH (c:Campaign {{slug:$slug}}), (s:Section {{id:$id}})
        MERGE (c)-[r:{SKIPPED}]->(s)
        SET r.plane = $plane
        """,
        {"slug": slug, "id": section_id, "plane": CAMPAIGN_PLANE},
    )


def clear_skipped(tx, slug: str, section_id: str) -> None:
    tx.run(
        f"MATCH (:Campaign {{slug:$slug}})-[r:{SKIPPED}]->(:Section {{id:$id}}) DELETE r",
        {"slug": slug, "id": section_id},
    )


def replay(path: Path) -> list[dict]:
    """Every recorded mutation, in order. The other half of recovery."""
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                logger.warning("skipping unreadable campaign-log line")
    return records
