"""Things that must be true of the graph, checked rather than remembered.

FOUR TIMES IN ONE WEEK the same defect appeared, each instance invisible to
the check written for the one before it:

  * deleting a section left the edges it wrote between two CANON entities,
    because neither endpoint was minted by the campaign and so neither took
    the edge with it;
  * deleting a section left its mentions of canon entities, for the same
    reason one level up -- `DETACH DELETE s` takes the `IN_SECTION` edge and
    `REFERS_TO` keeps the node breathing;
  * deleting a campaign left 542 `NEXT` links lying between canon sections,
    because the `:Campaign` node does not own either end;
  * and the sweep written for the second missed ten more, because it looked
    for mentions missing BOTH edges rather than either.

Every one is the same sentence: a campaign-plane thing joining nodes the
campaign does not own, outliving whatever made it. Each was found by hand,
after the fact, in a graph that already held it.

SO THE RULE IS WRITTEN DOWN INSTEAD. These are cheap queries over shapes that
should never occur, and what they buy is that the FIFTH instance is a failing
check rather than another afternoon of noticing.

EACH RETURNS ROWS, NOT A BOOLEAN. A count says something is wrong; the rows
say what, which is the difference between a check a person can act on and one
they learn to skip.
"""

from __future__ import annotations

from dataclasses import dataclass

#: A mention is a triangle: an entity, a section, and the node joining them.
#: Half of one points at nothing and is invisible to every read that traverses
#: the pair, so it accumulates silently -- 573 of them once, from test fixtures
#: nobody had thought to check.
DANGLING_MENTIONS = """
MATCH (m:Mention)
WHERE NOT (m)-[:REFERS_TO]->(:Entity) OR NOT (m)-[:IN_SECTION]->(:Section)
RETURN m.id AS id, m.campaign AS campaign,
       CASE WHEN NOT (m)-[:REFERS_TO]->(:Entity)
            THEN 'names no entity' ELSE 'sits in no section' END AS why
LIMIT 50
"""

#: One node per (entity, section), which is what `mention_id` means and what
#: makes a re-scan MERGE rather than double. Two of them is not a state the
#: scan can produce.
DOUBLED_MENTIONS = """
MATCH (m:Mention)-[:IN_SECTION]->(sec:Section)
MATCH (m)-[:REFERS_TO]->(e:Entity)
WITH e, sec, count(m) AS held WHERE held > 1
RETURN e.id AS id, sec.id AS campaign, held + ' mentions of one pair' AS why
LIMIT 50
"""

#: A claim outliving the campaign that made it. The relationship carries a
#: slug; if nothing answers to that slug it is an assertion nobody stands
#: behind, sitting on the book.
ORPHANED_CLAIMS = """
MATCH ()-[r]->()
WHERE r.campaign IS NOT NULL
  AND NOT EXISTS { MATCH (c:Campaign {slug: r.campaign}) }
RETURN DISTINCT r.campaign AS campaign, type(r) AS id,
       'relationship of a campaign that does not exist' AS why
LIMIT 50
"""

#: The same for nodes: a section or entity whose table is gone.
ORPHANED_NODES = """
MATCH (n)
WHERE n.campaign IS NOT NULL AND NOT n:Campaign
  AND NOT EXISTS { MATCH (c:Campaign {slug: n.campaign}) }
RETURN n.id AS id, n.campaign AS campaign,
       'node of a campaign that does not exist' AS why
LIMIT 50
"""

#: A claim outliving the PROSE that made it, which is a different thing from
#: outliving its campaign and was the first of the four to appear. The edge
#: still names a live table -- what is gone is the section whose text asserted
#: it. Discarding a draft about Elra left the book holding `Elra Lionheart
#: THREATENS Markos Delphi` with a `from_section` naming a scene that no longer
#: existed, and the campaign check below cannot see it because the campaign is
#: fine.
CLAIMS_WITHOUT_PROSE = """
MATCH ()-[r]->()
WHERE r.from_section IS NOT NULL
  AND NOT EXISTS { MATCH (s:Section {id: r.from_section}) }
RETURN DISTINCT r.from_section AS id, r.campaign AS campaign,
       'asserted by a section that no longer exists' AS why
LIMIT 50
"""

#: The id must spell the pair it joins. Composing it out of both endpoints is
#: what makes a re-ingest MERGE onto the same node; an id naming an entity the
#: mention no longer points at reads fine and re-ingests as a second mention
#: beside the stale one.
MISFILED_MENTIONS = """
MATCH (m:Mention)-[:IN_SECTION]->(sec:Section)
MATCH (m)-[:REFERS_TO]->(e:Entity)
WHERE m.id IS NOT NULL AND m.id <> e.id + '@' + sec.id
RETURN m.id AS id, m.campaign AS campaign,
       'id does not spell ' + e.id + '@' + sec.id AS why
LIMIT 50
"""


@dataclass(frozen=True)
class Check:
    """One thing that must be true, and the query that finds it untrue."""

    name: str
    cypher: str
    #: What a reader should do about it, since a violation nobody can act on
    #: is a check they learn to skip.
    fix: str


CHECKS: tuple[Check, ...] = (
    Check("a mention is a triangle", DANGLING_MENTIONS,
          "delete them -- half a triangle is invisible to every read that "
          "traverses the pair"),
    Check("a mention is one per pair", DOUBLED_MENTIONS,
          "fold them; `mention_id` is the pair, so two is not a state the scan "
          "can produce"),
    Check("a claim outlives no prose", CLAIMS_WITHOUT_PROSE,
          "delete them; the section that asserted them is gone, and `delete` "
          "takes them along now"),
    Check("a claim belongs to a campaign that exists", ORPHANED_CLAIMS,
          "delete them, or recreate the campaign they name"),
    Check("a node belongs to a campaign that exists", ORPHANED_NODES,
          "`delete_campaign` removes these; one run by hand leaves them"),
    Check("a mention's id spells its pair", MISFILED_MENTIONS,
          "rename them -- `merge_duplicates --mention-ids` does exactly this"),
)


def run(session) -> list[tuple[Check, list[dict]]]:
    """Every check, with the rows that break it. Empty rows means it holds."""
    found = []
    for check in CHECKS:
        rows = [dict(r) for r in session.run(check.cypher)]
        found.append((check, rows))
    return found
