"""Question in, grounded canon out. No model anywhere in the path.

`CanonLookup` answers three questions about a NAME the caller already has.
This answers a question in a DM's own words, which needs one thing the lookup
does not: finding the names inside it. That step -- and only that step -- is
what this module adds. Everything downstream is the lookup's queries.

WHY NO EMBEDDINGS. A similarity score cannot be argued with. When a graph-native
retrieval misses, the miss points at a specific missing thing -- an alias that
was never recorded, a section the scan skipped, an edge nobody wrote -- and that
is a repairable defect. A vector miss points at a number. The graph's mentions,
aliases and hierarchy already encode what a text index would have to guess, and
at 36 sections there is nothing for an index to do that a scan cannot.

WHY NO ANSWER GENERATION. Retrieval returns passages; it never writes prose. A
model asked to answer will paper over a retrieval hole with something plausible,
and the entire point of this module is to make the holes countable. Generation
belongs to whatever calls this, after the numbers say retrieval works.

THE MATCHER IS THE SCAN'S MATCHER. `spine.mention_pattern` finds names in a
question exactly as it finds them in a section -- whole-word, apostrophe-folded.
Writing a second "find a name in some text" here would be the same mistake as a
second definition of "the same sentence", which `passage.py` exists to prevent.

The one rule that differs is case, and it differs because the TEXT differs. The
scan's single-word case rule reads a capital as evidence of a proper noun, which
is true of prose and false of a typed question. So retrieval runs the scan's
rule first and falls back to a case-folded pass ONLY when the first finds
nothing at all -- and marks the result `loose` when it does, so a weaker match
is never invisible. Measured: the fallback is what rescues "the trapdoor in the
church", while a question that names anything properly never reaches it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.canon.aliases import normalize
from backend.canon.lookup import (
    CANON_PLANE,
    EDGES,
    MENTIONS,
    rung_of,
    split_by_status,
    type_labels,
)
from backend.canon.passage import derive_passage
from backend.canon.questions import content_terms, lucene_query
from backend.canon.spine import mention_pattern

#: Every recorded surface form in the plane, longest first. Length ordering is
#: what makes "Ireena Kolyana" win over "Ireena" in a question containing both:
#: the longer form is the more specific claim, and a question that spells a name
#: out in full should not resolve as though it had not.
ALL_ALIASES = """
MATCH (a:Alias)-[:ALIAS_OF]->(e:Entity {plane:$plane})
RETURN DISTINCT a.name AS name
"""

#: Which entities a surface form names. Several is a legitimate answer --
#: `Barovia` is a region and a village -- and the ambiguity travels rather than
#: being resolved by a coin flip.
BY_ALIAS = """
MATCH (a:Alias)-[:ALIAS_OF]->(e:Entity {plane:$plane})
WHERE a.normalized = $normalized
RETURN DISTINCT e.id AS id, e.name AS name, labels(e) AS labels, e.status AS node_status
ORDER BY e.id
"""

#: The prose fallback, over the full-text index `GRAPH_SCHEMA` declares. Reached
#: ONLY when nothing in the question resolves to an entity.
#:
#: `db.index.fulltext.queryNodes` returns a Lucene score, and that score is
#: deliberately not merged into the graph path's ranking. A name resolved
#: through `:Alias` is a fact about the book; a score is a guess about a
#: question. Blending them produces one ordering in which nobody can tell which
#: answered, and this project's whole method is being able to tell.
SEARCH_SECTIONS = """
CALL db.index.fulltext.queryNodes('section_text', $query) YIELD node AS s, score
MATCH (c:Chapter {plane:$plane})-[:HAS_SECTION]->(s)
RETURN s.id AS section_id, s.heading AS section, s.index AS section_index,
       s.text AS text, c.slug AS chapter, c.index AS chapter_index, score
ORDER BY score DESC
LIMIT $limit
"""

#: Retrieval returns at most this many passages unless told otherwise. A DM
#: reading an answer will not read twenty paragraphs, and an unbounded context
#: hides a ranking problem by making every miss a hit.
DEFAULT_LIMIT = 5

#: How a retrieval was answered. Carried on the result and reported by the
#: evaluation harness, because a text hit and a graph hit are not the same
#: quality of answer and an aggregate recall that hides which is which would
#: make the fallback look like an improvement to the graph.
PATH_GRAPH = "graph"
PATH_TEXT = "text"
PATH_NONE = ""


@dataclass(frozen=True)
class Anchor:
    """One entity a question named, and the spelling it used to name it."""

    entity_id: str
    name: str
    labels: tuple[str, ...]
    rung: str | None
    surface: str
    node_status: str | None = None


@dataclass(frozen=True)
class Passage:
    """One section a DM would read, and the sentence that anchors it."""

    section_id: str
    chapter: str
    chapter_index: int
    section: str
    section_index: int
    text: str
    occurrences: int
    entity_ids: tuple[str, ...]
    aliases: tuple[str, ...] = ()
    #: Lucene's score, on a text-path passage only. `None` on a graph passage,
    #: and deliberately not defaulted to 0.0: a name match has no score, and a
    #: zero would read as "scored, badly".
    #:
    #: Carried because the text path CANNOT SAY IT DOES NOT KNOW. Any question
    #: sharing one word with any section returns that section -- "what is the
    #: capital of France?" returns the foreword, which discusses Byron in
    #: Switzerland. The score is the only signal a caller has that an answer is
    #: thin, so it travels rather than being consumed here.
    score: float | None = None


@dataclass(frozen=True)
class Retrieval:
    """What a question retrieved, and what it did not."""

    question: str
    anchors: tuple[Anchor, ...] = ()
    passages: tuple[Passage, ...] = ()
    accepted: tuple[dict, ...] = ()
    proposed: tuple[dict, ...] = ()
    #: Passages the budget cut. Counted rather than discarded: this project has
    #: twice had a defect hide for weeks behind a silent filter.
    dropped: int = 0
    miss_reason: str = ""
    ambiguous: tuple[str, ...] = field(default_factory=tuple)
    #: True when nothing matched under the scan's own case rule and the
    #: case-folded fallback was what anchored the question. Surfaced rather
    #: than swallowed: a fallback nobody can observe becomes the default.
    loose: bool = False
    #: Which path answered: `graph` (a name resolved), `text` (the prose
    #: fallback), or empty (nothing did). Never inferred from whether `anchors`
    #: is empty -- a caller reading a text answer must be able to see that it
    #: is one.
    path: str = PATH_NONE
    #: The terms the text fallback searched on, so a bad text answer can be read
    #: back to the question that produced it.
    terms: tuple[str, ...] = field(default_factory=tuple)

    @property
    def found(self) -> bool:
        return bool(self.passages)

    @property
    def section_ids(self) -> tuple[str, ...]:
        return tuple(p.section_id for p in self.passages)


def find_names(question: str, forms: list[str], *, fold_case: bool = False) -> list[str]:
    """Every recorded form the question contains, longest first, non-overlapping.

    Non-overlapping is the load-bearing word. A question naming `Ireena Kolyana`
    contains `Ireena` too, and returning both would anchor twice on one entity
    and let a single name outvote everything else in the ranking. Longest match
    wins and consumes its span.

    Ordering by length here is what makes that greedy pass correct; the caller
    is not required to sort.
    """
    spans: list[tuple[int, int]] = []
    found: list[str] = []
    for form in sorted(forms, key=lambda f: (-len(f), f)):
        pattern = mention_pattern(form, fold_case=fold_case)
        if pattern is None:
            continue
        for match in pattern.finditer(question):
            start, end = match.span()
            if any(start < taken_end and taken_start < end for taken_start, taken_end in spans):
                continue
            spans.append((start, end))
            found.append(form)
            break  # one anchor per form; a question repeating a name means it once
    return found


class CanonRetriever:
    """Retrieve grounded canon for a question. Read-only, deterministic."""

    def __init__(self, limit: int = DEFAULT_LIMIT) -> None:
        self.limit = limit

    def retrieve(self, question: str, *, limit: int | None = None) -> Retrieval:
        limit = self.limit if limit is None else limit
        with self._session() as session:
            forms = [row["name"] for row in self._rows(session, ALL_ALIASES)]
            # Two passes, and the order is the whole point. The first is the
            # scan's own rule, so a question that spells names the way the book
            # does resolves exactly as the graph was built. Only when that finds
            # NOTHING does the second pass drop the single-word case rule --
            # which is what rescues "the trapdoor in the church" while leaving
            # "who is Ismark, and what about the light?" anchored on Ismark
            # alone rather than dragging in the LORE entity `Light`.
            #
            # `loose` travels on the result so a consumer can see which answers
            # needed the weaker rule. A fallback nobody can observe is how a
            # loose match becomes the default without anyone deciding it should.
            named = find_names(question, forms)
            loose = False
            if not named:
                named = find_names(question, forms, fold_case=True)
                loose = bool(named)
            if not named:
                return self._by_text(session, question, limit)

            anchors: list[Anchor] = []
            ambiguous: list[str] = []
            for surface in named:
                rows = self._rows(session, BY_ALIAS, {"normalized": normalize(surface)})
                if len(rows) > 1:
                    ambiguous.append(surface)
                for row in rows:
                    anchors.append(
                        Anchor(
                            entity_id=row["id"],
                            name=row["name"],
                            labels=tuple(type_labels(row["labels"])),
                            rung=rung_of(row["labels"]),
                            surface=surface,
                            node_status=row["node_status"],
                        )
                    )

            if not anchors:
                # A recorded spelling that names nothing is a broken graph, not
                # a descriptive question, so this does NOT fall through to text.
                # Papering over it would turn a repairable defect into a
                # slightly-worse answer nobody investigates.
                return Retrieval(
                    question=question,
                    miss_reason=(
                        f"{named!r} matched a recorded spelling but resolved to no entity"
                    ),
                    ambiguous=tuple(ambiguous),
                    loose=loose,
                )

            ids = sorted({a.entity_id for a in anchors})
            passages = self._passages(session, ids)
            kept = passages[:limit]
            edges = self._rows(session, EDGES, {"ids": ids})
            accepted, proposed = split_by_status(edges)

            return Retrieval(
                question=question,
                anchors=tuple(anchors),
                passages=tuple(kept),
                accepted=tuple(accepted),
                proposed=tuple(proposed),
                dropped=len(passages) - len(kept),
                ambiguous=tuple(ambiguous),
                loose=loose,
                path=PATH_GRAPH,
                miss_reason="" if kept else "anchored, but no section mentions the anchors",
            )

    # -- internals ---------------------------------------------------------

    def _by_text(self, session, question: str, limit: int) -> Retrieval:
        """The last resort: search the prose for what the question describes.

        Reached only when the question names nothing. It returns passages with
        NO anchors and NO edges, and says `path='text'` -- there is no entity
        here to hang a relationship off, and inventing one from a Lucene hit is
        precisely the inference the graph path exists to avoid.

        The passage is the section's OPENING rather than a sentence around a
        match. A text hit has no offset to anchor on -- Lucene scores the whole
        document -- and picking one of the matched terms to centre on would
        imply the section is about that term when the score came from all of
        them. The first sentences of a section are the book's own topic
        statement, which is the honest thing to show for a whole-section hit.
        """
        terms = content_terms(question)
        if not terms:
            return Retrieval(
                question=question,
                miss_reason=(
                    "the question names nothing and, once its question words are "
                    "removed, says nothing to search for"
                ),
            )
        rows = self._rows(
            session,
            SEARCH_SECTIONS,
            {"query": lucene_query(terms), "limit": limit},
        )
        passages = [
            Passage(
                section_id=row["section_id"],
                chapter=row["chapter"],
                chapter_index=row["chapter_index"],
                section=row["section"],
                section_index=row["section_index"],
                text=derive_passage(row["text"], 0),
                occurrences=0,
                entity_ids=(),
                score=row["score"],
            )
            for row in rows
        ]
        return Retrieval(
            question=question,
            passages=tuple(passages),
            path=PATH_TEXT if passages else PATH_NONE,
            terms=tuple(terms),
            miss_reason=(
                ""
                if passages
                else f"the question names nothing, and no section matches {terms}"
            ),
        )

    def _passages(self, session, ids: list[str]) -> list[Passage]:
        """One passage per SECTION, ranked.

        Per section rather than per mention: two anchors named in one section is
        one thing for a DM to read, and emitting it twice would both waste the
        budget and let a single dense section crowd out every other. The
        occurrence counts add, which is what makes a section naming both anchors
        outrank one naming either.

        RANKING, in order: how loudly the section names the anchors, then how
        many distinct anchors it names, then the book's own order. The first two
        are the signal; the third only breaks ties, so the ordering is total and
        a re-run cannot reshuffle it.
        """
        merged: dict[str, dict] = {}
        for row in self._rows(session, MENTIONS, {"ids": ids}):
            section_id = f"{row['chapter']}#{row['section_index']}"
            slot = merged.setdefault(
                section_id,
                {
                    "chapter": row["chapter"],
                    "chapter_index": row["chapter_index"],
                    "section": row["section"],
                    "section_index": row["section_index"],
                    "text": row["section_text"],
                    "offset": row["offset"],
                    "occurrences": 0,
                    "entity_ids": [],
                    "aliases": [],
                },
            )
            slot["occurrences"] += row["occurrences"] or 0
            slot["entity_ids"].append(row["entity_id"])
            slot["aliases"].extend(row["aliases"] or [])
            # The passage anchors on the EARLIEST mention in the section, so a
            # section naming two anchors quotes wherever the book first raises
            # either of them rather than whichever row the driver returned last.
            slot["offset"] = min(slot["offset"], row["offset"])

        passages = [
            Passage(
                section_id=self._section_id(slot),
                chapter=slot["chapter"],
                chapter_index=slot["chapter_index"],
                section=slot["section"],
                section_index=slot["section_index"],
                text=derive_passage(slot["text"], slot["offset"]),
                occurrences=slot["occurrences"],
                entity_ids=tuple(sorted(set(slot["entity_ids"]))),
                aliases=tuple(sorted(set(slot["aliases"]))),
            )
            for slot in merged.values()
        ]
        passages.sort(
            key=lambda p: (
                -p.occurrences,
                -len(p.entity_ids),
                p.chapter_index,
                p.section_index,
            )
        )
        return passages

    @staticmethod
    def _section_id(slot: dict) -> str:
        """The id the write path minted, rebuilt from its parts.

        `MENTIONS` returns the section's heading and index but not its id, and
        widening that shared query for this module's benefit would change what
        `lookup` reads. The format is the write path's and is pinned by a test
        that reads a real section id out of the graph.
        """
        return f"cos:{slot['chapter']}#{slot['section_index']}"

    def _session(self):
        from backend.core.database import neo4j_session

        return neo4j_session()

    def _rows(self, session, query: str, params: dict | None = None) -> list[dict]:
        merged = {"plane": CANON_PLANE, **(params or {})}
        return [dict(record) for record in session.run(query, merged)]
