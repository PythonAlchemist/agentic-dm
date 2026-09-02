"""Retrieval for somebody who is not the DM.

SEEDED, NOT FILTERED, and that is the entire design. A model handed the book
and told not to mention the twist has already been handed the twist: it shapes
the prose around it, declines in a way that confirms it, or gives it up under
mild rephrasing. There is no post-filter that undoes having been told, so the
only safe answer is that the unrevealed material never enters the context.

A SEPARATE RETRIEVER, NOT A FLAG ON `CanonRetriever`. That class is 1,600 lines
with four `return Retrieval(...)` sites -- its own docstring records that
stamping each was four chances to forget -- and a `visible=` argument would
have to be honoured in every query inside it. One missed clause is a leak
nobody would see. This one CANNOT return an unrevealed row because every query
it has begins at the grant, the same shape `PINS_PLAYER` and `ENTITY_PLAYER`
take.

IT IS DELIBERATELY WORSE AT ITS JOB. No Lucene fallback over the whole book, no
chapter neighbours riding along, no anthology rules -- those all reach for
prose by position or by score rather than by permission, and each would be a
way for an unrevealed section to arrive. A player's assistant that sometimes
says "you have not heard about that" is correct; one that occasionally recites
chapter nine is not a lesser bug, it is the only bug that matters here.

WHAT IT KEEPS is the shape: it returns the same `Retrieval` the DM's does, so
the agent, the prompt builder and the citation renderer are unchanged. The
difference is which rows exist.
"""

from __future__ import annotations

from backend.player.reader import PUBLIC as _PUBLIC
from backend.canon.retrieval import (
    PATH_GRAPH,
    PATH_NONE,
    Anchor,
    CanonRetriever,
    Passage,
    Retrieval,
    find_names,
)

#: Reused from `player/reader.py` so the retriever and the reads cannot
#: disagree about what a rulebook is.
PUBLIC_CLAUSE = _PUBLIC


#: Every entity this table may reach: what it was told, plus whatever a
#: rulebook says. A player owns the Player's Handbook, and making a DM reveal
#: `Fireball` to their own party is a rule whose only effect is busywork.
#:
#: A GRANTED ALIAS REPLACES THE FORMS, IT DOES NOT JOIN THEM. A player who only
#: knows "the coachman" types "the coachman", and letting "Strahd" anchor as
#: well would confirm, in the retrieval report, that the two are the same
#: person -- which is precisely the fact the alias was hiding. So a grant with
#: an `as_name` matches on that and nothing else.
#:
#: WITHOUT ONE, THE BOOK'S OWN ALIASES COUNT. Nobody types "Strahd von
#: Zarovich"; they type "Strahd", and `ALIAS_OF` is where the book's spellings
#: already live. Reusing them keeps one record of what a thing may be called.
GRANTED_ENTITIES = """
MATCH (c:Campaign {slug:$slug}), (e:Entity)
WHERE (c)-[:REVEALED]->(e) OR """ + PUBLIC_CLAUSE % "e.id" + """
WITH c, e, [(c)-[r:REVEALED]->(e) | r][0] AS g
OPTIONAL MATCH (a:Alias)-[:ALIAS_OF]->(e)
WITH e, g, [x IN collect(a.name) WHERE x IS NOT NULL] AS aliases
RETURN e.id AS id,
       CASE WHEN coalesce(g.as_name, '') <> '' THEN g.as_name ELSE e.name END
         AS name,
       CASE WHEN coalesce(g.as_name, '') <> ''
            THEN [g.as_name]
            ELSE [e.name] + aliases END AS forms,
       [l IN labels(e) WHERE l <> 'Entity'] AS labels
ORDER BY name
"""

#: Revealed sections that name one of the anchors.
#:
#: BOTH ENDS GRANTED. The section must be revealed AND the entity must be, so a
#: revealed section cannot be reached through an unrevealed name and an
#: unrevealed section cannot be reached through a revealed one.
GRANTED_PASSAGES = """
MATCH (c:Campaign {slug:$slug}), (s:Section)
WHERE (c)-[:REVEALED]->(s) OR """ + PUBLIC_CLAUSE % "s.id" + """
MATCH (e:Entity)<-[:REFERS_TO]-(m:Mention)-[:IN_SECTION]->(s)
WHERE e.id IN $ids
  AND ((c)-[:REVEALED]->(e) OR """ + PUBLIC_CLAUSE % "e.id" + """)
WITH s, collect(DISTINCT e.id) AS entity_ids, sum(m.occurrences) AS hits
RETURN s.id AS section_id, s.heading AS heading, s.text AS text,
       s.plane AS plane, entity_ids, hits
ORDER BY hits DESC, s.id
LIMIT $limit
"""

#: Revealed sections whose prose contains a word of the question.
#:
#: SCOPED TO THE GRANT, so this is a search of what the table has been shown
#: rather than of the book. It exists because a player asking "what did the
#: burgomaster say about the coffin" has named nothing the graph can anchor on,
#: and the alternative is answering nothing at all from prose they HAVE read.
#: THE HEADING COUNTS AS PROSE HERE. A player asking about "the twist" is using
#: the words they were shown, and a section's heading is the part of it they are
#: most likely to have remembered -- searching only the body misses the one
#: thing they can actually quote back.
GRANTED_TEXT = """
MATCH (c:Campaign {slug:$slug}), (s:Section)
WHERE (c)-[:REVEALED]->(s) OR EXISTS {
    MATCH (b:Book) WHERE b.reference = true AND s.id STARTS WITH b.slug + ':'
  }
WITH c, s, toLower(coalesce(s.heading, '') + ' ' + coalesce(s.text, '')) AS prose
WITH c, s, size([t IN $terms WHERE prose CONTAINS t]) AS hits,
     EXISTS { (c)-[:REVEALED]->(s) } AS ours
// THE BAR IS HIGHER FOR THE RULEBOOK THAN FOR THIS TABLE'S OWN PROSE.
//
// A table has a handful of granted sections and every one of them is about
// this campaign, so a single word hitting one is a decent guess. The rulebook
// is 889 entries about everything, and there one word is noise: "who is
// Captain Saltmarrow" matched `Bandit Captain` on "captain" and answered a
// question about somebody's campaign with a stat block.
//
// A reference work is looked up by NAME -- which the anchors above already do
// -- so its prose has to earn a hit rather than merely contain a common word.
WHERE hits >= CASE WHEN ours OR size($terms) < 2 THEN 1 ELSE 2 END
RETURN s.id AS section_id, s.heading AS heading, s.text AS text,
       s.plane AS plane, hits
// A TABLE'S OWN MATERIAL OUTRANKS THE RULEBOOK. Both are legitimate answers
// and only one of them is about this campaign.
ORDER BY ours DESC, hits DESC, s.id
LIMIT $limit
"""

#: Words too common to be worth searching prose for. Short and blunt on
#: purpose: this is a fallback over a handful of sections, not a ranker.
STOPWORDS = frozenset({
    "the", "and", "was", "were", "for", "with", "that", "this", "what",
    "who", "how", "why", "did", "does", "are", "you", "your", "our", "their",
    "them", "they", "his", "her", "him", "she", "about", "from", "have",
    "has", "had", "will", "would", "when", "where", "there", "here", "into",
    "out", "off", "any", "all", "can", "could", "should", "been", "being",
})


class PlayerRetriever(CanonRetriever):
    """What a player may be told, and nothing beside it."""

    def retrieve(self, question: str, *, limit: int | None = None,
                 carry=(), focus: str = "") -> Retrieval:
        """Answer out of the revealed closure alone.

        `focus` AND `carry` ARE ACCEPTED AND IGNORED. Both are ways for context
        to arrive from somewhere other than the question -- what the DM has open,
        what was said three turns ago -- and neither is checked against a grant.
        Honouring them would be a second door into the same room. They stay in
        the signature so this can be dropped in where the DM's retriever goes.
        """
        want = limit or self.limit
        with self._session() as session:
            granted = [dict(r) for r in session.run(
                GRANTED_ENTITIES, {"slug": self.campaign or ""})]
            # ONE ENTITY UNDER EVERY FORM IT MAY BE CALLED, the same shape
            # `EntityNames.forms` takes for the mention scan -- a caller cannot
            # construct an entity the matcher will not look for under its own
            # name, which is the silent zero that module exists to remove.
            by_form = {
                form.lower(): g
                for g in granted
                for form in (g["forms"] or [])
                if form
            }
            forms = sorted(
                {form for g in granted for form in (g["forms"] or []) if form},
                key=len, reverse=True,
            )

            named = find_names(question, forms, fold_case=True)
            if not named:
                named = _by_part(question, by_form)
            anchors = tuple(
                Anchor(
                    entity_id=by_form[surface.lower()]["id"],
                    name=by_form[surface.lower()]["name"],
                    labels=tuple(by_form[surface.lower()]["labels"]),
                    rung=None,
                    surface=surface,
                    path=PATH_GRAPH,
                )
                for surface in named
                if surface.lower() in by_form
            )

            rows = []
            if anchors:
                rows = [dict(r) for r in session.run(GRANTED_PASSAGES, {
                    "slug": self.campaign or "",
                    "ids": [a.entity_id for a in anchors],
                    "limit": want,
                })]

            terms = _terms(question)
            if not rows and terms:
                rows = [dict(r) for r in session.run(GRANTED_TEXT, {
                    "slug": self.campaign or "", "terms": terms, "limit": want,
                })]

        passages = tuple(_passage(row) for row in rows)
        return Retrieval(
            question=question,
            anchors=anchors,
            passages=passages,
            # NO `proposed`. A guessed edge is the extractor's opinion about
            # the book, which is a DM's material to weigh -- offering one to a
            # player would put a machine's guess in front of somebody with no
            # way to check it.
            proposed=(),
            path=PATH_GRAPH if passages else PATH_NONE,
            terms=tuple(terms),
            book_title=self.title,
            # TWO DIFFERENT EMPTY ANSWERS, and a player needs to be able to
            # tell them apart. "We have never heard of that" and "we know who
            # they are but have been shown nothing about them" lead to
            # different next questions -- and the second one, rendered as the
            # first, tells a player their DM has said nothing when in fact
            # they have.
            miss_reason=(
                "" if passages else
                f"you know of {anchors[0].name}, but nothing your table has "
                "been shown says any more than that" if anchors else
                "nothing your table has been told about covers that"
            ),
        )


#: Words that name nobody on their own. A title is not an identity, and
#: matching one would anchor "who is the captain" to whichever captain the
#: table happens to have met.
TITLES = frozenset({
    "captain", "lord", "lady", "sir", "baron", "burgomaster", "father",
    "mother", "brother", "sister", "master", "doctor", "professor", "king",
    "queen", "prince", "princess", "count", "countess", "the",
})


def _by_part(question: str, by_form: dict) -> list[str]:
    """Anchor on part of a name when the whole one was not typed.

    PEOPLE SAY SURNAMES. "What do we know about Saltmarrow" is the question a
    player actually asks, and matching only the full "Captain Saltmarrow"
    answers it with silence -- which reads as "your DM has told you nothing".
    The DM's retriever leans on the book's own aliases for this; a player has
    only what they were granted, so the parts of it have to count.

    SAFE TO BE GENEROUS HERE, and only here. Every candidate is already
    revealed, so a loose match can surface the wrong revealed thing but can
    never surface an unrevealed one. That is a usability risk, not a leak.

    LONGEST PART WINS, so "Saltmarrow" beats "Captain" when both are in the
    same name and only one is in the question.
    """
    asked = {
        word for word in
        "".join(c.lower() if c.isalnum() else " " for c in question).split()
        if len(word) > 3 and word not in TITLES
    }
    hits: dict[str, str] = {}
    for form in by_form:
        for part in form.split():
            cleaned = "".join(c for c in part.lower() if c.isalnum())
            if len(cleaned) > 3 and cleaned in asked and cleaned not in TITLES:
                if len(cleaned) > len(hits.get(form, "")):
                    hits[form] = cleaned
    return [by_form[form]["name"] for form in hits
            if by_form[form]["name"].lower() in by_form]


def _terms(question: str) -> list[str]:
    return [
        word for word in
        "".join(c.lower() if c.isalnum() else " " for c in question).split()
        if len(word) > 2 and word not in STOPWORDS
    ]


def _passage(row: dict) -> Passage:
    """A row as the renderer expects it.

    THE CHAPTER IS NOT CARRIED. A chapter name is a fact about the book's
    structure -- "chapter 9: Castle Ravenloft" -- and a citation carrying it
    tells a player how far through the adventure a passage sits, which is a
    small map of what is left. The heading they were shown is enough.
    """
    return Passage(
        section_id=row["section_id"],
        chapter="",
        chapter_index=0,
        section=row.get("heading") or "",
        section_index=0,
        text=row.get("text") or "",
        occurrences=int(row.get("hits") or 0),
        entity_ids=tuple(row.get("entity_ids") or ()),
        origin="campaign" if row.get("plane") == "campaign" else "canon",
        path=PATH_GRAPH,
    )
