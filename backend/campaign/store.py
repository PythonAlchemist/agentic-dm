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
    PART_OF,
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


def set_parent(tx, slug: str, section_id: str, parent_id: str) -> dict:
    """Record what a campaign section sits INSIDE. `""` puts it at top level.

    ONE PARENT AT A TIME: the edge is deleted before it is written, because two
    would make "what is this inside" a question with two answers, and the
    running order would draw the thing twice.

    Says nothing about ORDER. That is the chain's job, and keeping them apart
    is the whole reason this exists -- re-parenting must not shuffle the new
    neighbours, and reordering must not change what anything is inside.
    """
    tx.run(
        f"MATCH (s:Section {{id:$id}})-[r:{PART_OF}]->() DELETE r", {"id": section_id}
    )
    if not parent_id:
        return {"section_id": section_id, "parent": ""}
    written = tx.run(
        f"""
        MATCH (s:Section {{id:$id, plane:$plane, campaign:$slug}}), (p:Section {{id:$parent}})
        MERGE (s)-[r:{PART_OF}]->(p)
        SET r.campaign = $slug
        RETURN count(r) AS n
        """,
        {"id": section_id, "parent": parent_id, "plane": CAMPAIGN_PLANE, "slug": slug},
    ).single()["n"]
    if not written:
        raise ValueError(f"{section_id} is not this campaign's, or {parent_id} is gone")
    return {"section_id": section_id, "parent": parent_id}


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


def delete_campaign(tx, slug: str) -> dict:
    """Remove a campaign and everything it ever wrote. Counted, never silent.

    THE INVERSE `create` NEVER HAD. A table could be made and not unmade, so
    an abandoned one left its running order on the book forever: 542 `NEXT`
    links between CANON sections, each carrying a slug for a campaign that no
    longer existed. Deleting the `:Campaign` node does not touch them, because
    they join two nodes it does not own -- the same shape that let edges and
    then mentions outlive the prose that made them, one level up.

    CANON IS NEVER MUTATED, which is the invariant that makes this possible at
    all. Everything removed here was created by the campaign: its own entities
    and sections, the mentions it wrote, the edges it asserted, and the chain
    it laid over the book's own order. The book's nodes survive with their
    campaign-plane attachments gone and nothing else changed.

    ORDERED SO NOTHING IS ORPHANED ON THE WAY. Mentions before the sections
    they sit in, aliases after the entities that answer to them, the chain
    before the campaign that owns it -- each step leaving nothing for the next
    to trip over.
    """
    counts: dict[str, int] = {}

    def run(key: str, cypher: str) -> None:
        counts[key] = tx.run(cypher, {"slug": slug, "plane": CAMPAIGN_PLANE}).single()["n"]

    # The mention triangle first: a mention outlives its section otherwise,
    # which is exactly the defect this ordering exists to avoid.
    run("mentions", "MATCH (m:Mention {campaign:$slug}) DETACH DELETE m RETURN count(m) AS n")
    # Every relationship the campaign wrote, wherever it lands. This is the one
    # that catches the chain over canon sections and the edges between canon
    # entities -- neither has an endpoint the campaign owns.
    run("relationships", "MATCH ()-[r]->() WHERE r.campaign = $slug DELETE r RETURN count(r) AS n")
    run("sections",
        "MATCH (s:Section {plane:$plane, campaign:$slug}) DETACH DELETE s RETURN count(s) AS n")
    run("entities",
        "MATCH (e:Entity {plane:$plane, campaign:$slug}) DETACH DELETE e RETURN count(e) AS n")
    # AFTER the entities, since an alias is orphaned by their going and the
    # `:Alias` node is shared -- it goes only when nothing answers to it.
    run("aliases",
        "MATCH (a:Alias {plane:$plane}) WHERE NOT (a)-[:ALIAS_OF]->() "
        "DETACH DELETE a RETURN count(a) AS n")
    run("campaign", "MATCH (c:Campaign {slug:$slug}) DETACH DELETE c RETURN count(c) AS n")
    return counts


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
