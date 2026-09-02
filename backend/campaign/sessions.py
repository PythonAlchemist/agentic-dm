"""A night of play, and the two lists that make it worth recording.

THE REFERENT EVERYTHING TIME-INDEXED NEEDS. "Who held the Sunsword in session
three", "what the party knew by session five", "which scenes we actually
reached" are all functions of a session, and every one of them is a dangling
pointer until sessions exist as nodes. This is why it is built before inventory
and before player visibility rather than after them.

PLANNED AND COVERED ARE TWO EDGES, NOT A STATUS. What a DM meant to run and
what the table actually reached are different claims about the same scene, and
a single `status` on the section would make one of them overwrite the other --
losing exactly the comparison the roadmap is asking for. `PLANNED` is the DM's
intention and is DM-only; `COVERED` is what happened.

TIME IS A PROPERTY, NOT AN AXIS. `since_session` on an inventory edge and
`at_session` on a reveal carry when, without the graph becoming versioned. The
graph stays current-state-plus-history: what is true now, and enough stamps to
say when it became true.

`:Session` IS APPARATUS. A session is a container for an evening, not an
assertion about the world, so it carries no `plane` -- see
`schema.APPARATUS_LABELS`. It carries `campaign`, so `delete_campaign` sweeps
it from `CAMPAIGN_OWNED_LABELS` along with everything else a table minted.
"""

from __future__ import annotations

PLANNED = "planned"
PLAYED = "played"

#: `hb:<campaign>:session-<n>`, the same self-identifying shape every campaign
#: node uses. `transcript/processor.py` minted `session_<uuid4>` ids carrying no
#: campaign at all, which made its debris invisible even to `ORPHANED_NODES` --
#: that check filters on `n.campaign IS NOT NULL`.
def session_id(slug: str, number: int) -> str:
    return f"hb:{slug}:session-{number}"


NEXT_NUMBER = """
MATCH (:Campaign {slug:$slug})-[:HAS_SESSION]->(s:Session)
RETURN coalesce(max(s.number), 0) + 1 AS number
"""

OPEN = """
MATCH (c:Campaign {slug:$slug})
MERGE (s:Session {id:$id})
ON CREATE SET s.number = $number, s.campaign = $slug, s.status = $status,
              s.title = $title, s.held_on = $held_on
MERGE (c)-[:HAS_SESSION]->(s)
RETURN s.id AS id, s.number AS number, s.status AS status
"""

LIST = """
MATCH (:Campaign {slug:$slug})-[:HAS_SESSION]->(s:Session)
OPTIONAL MATCH (s)-[:PLANNED]->(p:Section)
OPTIONAL MATCH (s)-[:COVERED]->(c:Section)
RETURN s.id AS id, s.number AS number, s.title AS title,
       s.status AS status, s.held_on AS held_on,
       count(DISTINCT p) AS planned, count(DISTINCT c) AS covered
ORDER BY s.number DESC
"""

PLAN = """
MATCH (s:Session {id:$id, campaign:$slug}), (sec:Section {id:$section})
MERGE (s)-[r:PLANNED]->(sec)
SET r.campaign = $slug, r.rank = $rank
RETURN count(r) AS n
"""

UNPLAN = """
MATCH (:Session {id:$id, campaign:$slug})-[r:PLANNED]->(:Section {id:$section})
DELETE r RETURN count(r) AS n
"""

COVER = """
MATCH (s:Session {id:$id, campaign:$slug}), (sec:Section {id:$section})
MERGE (s)-[r:COVERED]->(sec)
SET r.campaign = $slug
RETURN count(r) AS n
"""

#: What was meant against what was reached, for one session.
#:
#: A DERIVED DIFF, NOT A SECOND LEDGER. Both lists already exist as edges, so
#: "planned but not covered" is a set difference computed on read. A stored
#: `outcome` field would be the second copy that drifts -- the defect this
#: codebase names at every level.
DIFF = """
MATCH (s:Session {id:$id, campaign:$slug})
OPTIONAL MATCH (s)-[:PLANNED]->(p:Section)
WITH s, collect(DISTINCT {id: p.id, heading: p.heading}) AS planned
OPTIONAL MATCH (s)-[:COVERED]->(c:Section)
RETURN planned,
       collect(DISTINCT {id: c.id, heading: c.heading}) AS covered
"""


def open_session(tx, *, slug: str, title: str = "", held_on: str = "",
                 number: int | None = None) -> dict:
    """Start the next session, or re-open one by number.

    NUMBERED FROM WHAT EXISTS rather than counted by the caller: two clients
    opening a session at once would otherwise both call it the fifth.
    """
    if number is None:
        number = tx.run(NEXT_NUMBER, {"slug": slug}).single()["number"]
    row = tx.run(OPEN, {
        "slug": slug, "id": session_id(slug, number), "number": number,
        "status": PLANNED, "title": title, "held_on": held_on,
    }).single()
    if row is None:
        raise ValueError(f"no campaign {slug!r} to hold a session")
    return dict(row)


def sessions(tx, *, slug: str) -> list[dict]:
    """Every session, newest first, with how much was meant and reached."""
    return [dict(r) for r in tx.run(LIST, {"slug": slug})]


def plan(tx, *, slug: str, session: str, section: str, rank: int = 0) -> int:
    """Mean to run this scene tonight."""
    return tx.run(PLAN, {"slug": slug, "id": session,
                         "section": section, "rank": rank}).single()["n"]


def unplan(tx, *, slug: str, session: str, section: str) -> int:
    return tx.run(UNPLAN, {"slug": slug, "id": session,
                           "section": section}).single()["n"]


def cover(tx, *, slug: str, session: str, section: str) -> int:
    """Record that the table actually reached this scene."""
    return tx.run(COVER, {"slug": slug, "id": session,
                          "section": section}).single()["n"]


def diff(tx, *, slug: str, session: str) -> dict:
    """`{planned, covered, missed, unplanned}` -- computed, never stored."""
    row = tx.run(DIFF, {"slug": slug, "id": session}).single()
    if row is None:
        return {"planned": [], "covered": [], "missed": [], "unplanned": []}
    planned = [p for p in (row["planned"] or []) if p.get("id")]
    covered = [c for c in (row["covered"] or []) if c.get("id")]
    covered_ids = {c["id"] for c in covered}
    planned_ids = {p["id"] for p in planned}
    return {
        "planned": planned,
        "covered": covered,
        # THE TWO INTERESTING LISTS, and the reason this exists at all. A DM
        # asking "what did we not get to" is asking for the first; "what did we
        # end up doing that I never planned" is the second, and it is where a
        # campaign actually diverges from the book.
        "missed": [p for p in planned if p["id"] not in covered_ids],
        "unplanned": [c for c in covered if c["id"] not in planned_ids],
    }
