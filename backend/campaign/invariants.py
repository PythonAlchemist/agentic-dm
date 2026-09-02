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

THE SEVENTH IS NOT ONE OF THE FOUR. The six below are all that one
sentence, and each assumes the entity on the end of the edge is a thing the
book says. `UNSUPPORTED_ENTITIES` checks the assumption -- a canon entity no
mention names, which does not admit it -- and it is the only rule here that guards the promise the
project is for rather than the plumbing beneath it.

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

#: A CANON ENTITY THE BOOK NEVER NAMES. The six above are all one sentence -- a
#: campaign-plane thing joining nodes the campaign does not own, outliving
#: whatever made it -- and every one of them assumes the entity on the end of
#: the edge is real. This is that assumption, checked. It is also the only
#: shape here that breaks the promise the whole project is for: that a DM can
#: tell what the published book says from what a model invented.
#:
#: A MENTION IS THE WHOLE OF THAT EVIDENCE. The triangle
#: `(:Entity)<-[:REFERS_TO]-(:Mention)-[:IN_SECTION]->(:Section)` is how an
#: entity cites the prose that says it, so an entity holding none cannot be
#: traced to a word of the book -- while reading, in `expand` and every other
#: tool that returns it, exactly like one that can.
#:
#: MEASURED WHEN THIS WAS WRITTEN: 154 of 2,213 canon entities. 144 from
#: `kftgv` against 10 from `cos`, and none of the `cos` ten are chapter-scoped
#: -- so this is not a property of the design but of how one book was
#: extracted. `Closet 1`, `Side Room 2`, eight spell scrolls named by pattern,
#: `Painting by famous artist`, `Potion of Far Realm Surprise`. Descriptions
#: and inventions, carrying aliases and edges.
#:
#: IT FAILS ON THE SILENT ONES, NOT ON ALL OF THEM, and the difference is the
#: whole rule. The first version of this check failed on every unsupported
#: entity, which made it red on 154 nodes the DM then ruled were worth keeping:
#: `Monodrones GUARDS Abacus Car` says something true about a real train car.
#: A check that is red on data everybody has agreed is fine is a check people
#: learn to skip, which is the failure this file opens by warning about.
#:
#: So the rule is not "every canon entity is named by the book". It is that
#: none is UNSUPPORTED AND UNMARKED -- `schema.NAMED_BY_BOOK` records the
#: entity's own admission, `mark_unnamed` writes it, and `lookup` returns it.
#: Keeping such a node is then a decision the graph states out loud rather
#: than a gap a reader has to notice.
#:
#: THE MENTION MUST BE THE BOOK'S OWN. `expand` writes a CAMPAIGN-plane
#: section and a campaign-plane mention pointing at the entity it fleshes out,
#: and that entity is often the book's. Without `{plane:'canon'}` here, a DM
#: writing up `Monodrones` would satisfy this check on their own prose and the
#: node would report that the book names it. The gate would have had a door on
#: one side only.
#:
#: QUEST IS NOT EXEMPT, though twelve rows are quests phrased as objectives
#: rather than named in the text. Exempting them would carve out the class most
#: likely to be read as canon at the table, and whether an authored objective
#: belongs in this plane at all is the question those rows are asking.
#:
#: `canon` IS SPELLED HERE rather than imported. This module is strings and a
#: dataclass; `CANON_PLANE` lives in `canon.writer`, which pulls the gazetteer
#: and the whole schema behind it -- weight a check meant to be safe to point
#: at a live table mid-session should not carry. `test_invariants` asserts the
#: two agree, which is this file's own rule applied to itself.
UNSUPPORTED_ENTITIES = """
MATCH (e:Entity {plane:'canon'})
WHERE NOT (e)<-[:REFERS_TO]-(:Mention {plane:'canon'})
  AND e.named_by_book IS NULL
RETURN e.id AS id, e.campaign AS campaign,
       'no section names ' + coalesce(e.name, e.id) +
       ', and it does not say so' AS why
LIMIT 50
"""


#: HOW MANY ROWS A CHECK RETURNS. Every query above ends `LIMIT ROW_LIMIT`,
#: and the reason it is named here rather than only spelled there is that the
#: runner has to tell a capped result from a complete one: the seventh check
#: found 154 rows the day it was written and reported "50", which reads as the
#: size of the problem and is not. `test_invariants` asserts the queries and
#: this number agree.
#: A MENTION JOINS ONE BOOK. `mint_id` promises entities "merge across the
#: chapters of one book but never across books", and the scan did not keep it:
#: `_known_entities` filtered on `plane` alone, so writing a chapter of one book
#: scanned every entity of the other against its prose. `mention_pattern` folds
#: case for multi-word forms, so common nouns matched, and the graph ended up
#: holding 332 mentions asserting that Keys from the Golden Vault names Curse of
#: Strahd entities -- `cos:key` 82 times, `cos:light` 47.
#:
#: NOTHING SURFACED THEM. The retriever filters passages by book, so a DM never
#: saw one; they simply sat there, and each chapter write grew slower by every
#: entity in every other book. This is the check that would have failed on the
#: first one.
#:
#: THE CANON PLANE ONLY. A campaign mention pointing at a canon entity is the
#: normal, wanted case -- a DM's scene naming the Jolly Pelican -- and there
#: were seven of those the day this was written.
CROSS_BOOK_MENTIONS = """
MATCH (m:Mention {plane:'canon'})-[:REFERS_TO]->(e:Entity)
MATCH (m)-[:IN_SECTION]->(sec:Section)
WITH m, e, sec, split(e.id,':')[0] AS ebook, split(sec.id,':')[0] AS sbook
WHERE ebook <> sbook
RETURN m.id AS id, m.campaign AS campaign,
       ebook + ' entity named by a ' + sbook + ' section' AS why
LIMIT 50
"""

#: A CANON CLAIM CARRIES ITS EVIDENCE. Every edge the canon writer makes between
#: two book entities carries `evidence` -- the sentence it was read from -- and
#: `chapter_slug`. An edge minted any other way carries neither.
#:
#: WHY THAT IS WORTH A CHECK. `CampaignGraphOps.create_relationship` MERGEs an
#: edge between any two entities and applies the caller's own properties, and
#: `POST /api/campaign/relationships` hands the request body straight to it. A
#: forged NODE is caught by `UNSUPPORTED_ENTITIES`, which fails on a canon
#: entity no mention names; a forged EDGE was caught by nothing, and
#: `lookup.EDGES` serves it to a DM as the book's own derived fact. The write
#: path now pins `plane` and drops `status`, and this is the check that says so
#: rather than the fix being remembered.
UNSOURCED_CANON_CLAIMS = """
MATCH (a:Entity {plane:'canon'})-[r]->(b:Entity {plane:'canon'})
WHERE r.plane = 'canon'
  AND NOT type(r) IN ['REFERS_TO','IN_SECTION','ALIAS_OF','CO_OCCURS_WITH']
  AND r.evidence IS NULL
RETURN a.id AS id, r.campaign AS campaign,
       type(r) + ' to ' + b.id + ' cites no sentence' AS why
LIMIT 50
"""

#: AN ASSET SAYS WHERE IT CAME FROM. `origin` is `plane` for pixels: a portrait
#: the book printed, one a DM uploaded and one a model imagined are three
#: different things, and the moment they render alike the promise this project
#: makes is broken in the most persuasive medium it has.
#:
#: SO IT IS PINNED AT ONE WRITER PER ORIGIN, and this is the check that says so
#: rather than the discipline being remembered -- the same shape as
#: `UNSOURCED_CANON_CLAIMS`, which exists because a forged edge read to a DM
#: exactly like the book's own.
#:
#: A GENERATED ASSET MUST NAME ITS GENERATOR, for the reason a canon claim must
#: cite its sentence. An image with no record of what produced it is a claim
#: nobody can check.
UNSOURCED_ASSETS = """
MATCH (a:Asset)
WHERE a.origin IS NULL
   OR NOT a.origin IN ['book', 'uploaded', 'generated']
   OR (a.origin = 'generated' AND coalesce(a.generator, '') = '')
RETURN a.id AS id, a.campaign AS campaign,
       'origin ' + coalesce(a.origin, 'unset') + ' does not say where it came from'
       AS why
LIMIT 50
"""

#: A pin whose coordinates are not fractions of its image.
#:
#: THE FAILURE IS SILENT, WHICH IS WHY IT IS CHECKED. `maps.pin` refuses
#: anything outside 0..1, but a hand-written Cypher or an import does not go
#: through it, and a pixel coordinate that escaped conversion stores cleanly.
#: Nobody notices until the tavern is in the lake -- or worse, until a pin sits
#: off the edge of the map where no click can reach it to be deleted.
#:
#: NULL COUNTS AS BROKEN. A pin with no `x` renders at the origin, which looks
#: like a decision somebody made rather than a value nobody wrote.
STRAY_PINS = """
MATCH (e:Entity)-[p:PINNED_ON]->(m:Map)
WHERE p.x IS NULL OR p.y IS NULL
   OR p.x < 0.0 OR p.x > 1.0 OR p.y < 0.0 OR p.y > 1.0
RETURN e.id AS id, m.id AS map, p.x AS x, p.y AS y,
       'a pin is a fraction of the image, not a pixel' AS why
LIMIT 50
"""

ROW_LIMIT = 50


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
    Check("an asset says where it came from", UNSOURCED_ASSETS,
          "delete it, or restore the origin its writer should have pinned; a "
          "picture whose provenance is unknown reads as the book's"),
    Check("a mention joins one book", CROSS_BOOK_MENTIONS,
          "delete them; the scan that made them read every book's entities "
          "against one book's prose, and `_known_entities` now filters"),
    Check("a canon claim carries its evidence", UNSOURCED_CANON_CLAIMS,
          "delete them -- a canon edge citing no sentence was not written by "
          "the canon writer, and reads to a DM exactly like one that was"),
    Check("a pin is a fraction of its image", STRAY_PINS,
          "re-pin it through `maps.pin`, which divides by the image dimensions; "
          "a pin off the edge cannot be clicked, so it cannot be removed by "
          "the DM who put it there"),
    Check("a canon entity says whether the book names it", UNSUPPORTED_ENTITIES,
          "`mark_unnamed --apply` records it on the node, which is what makes "
          "keeping one a stated decision rather than a gap a reader must spot"),
)


def run(session) -> list[tuple[Check, list[dict]]]:
    """Every check, with the rows that break it. Empty rows means it holds."""
    found = []
    for check in CHECKS:
        rows = [dict(r) for r in session.run(check.cypher)]
        found.append((check, rows))
    return found
