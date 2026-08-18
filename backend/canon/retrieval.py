"""Question in, grounded canon out. No model anywhere in the path.

`CanonLookup` answers three questions about a NAME the caller already has.
This answers a question in a DM's own words, which needs one thing the lookup
does not: finding the names inside it. That step -- and only that step -- is
what this module adds. Everything downstream is the lookup's queries.

WHY NO EMBEDDINGS. A similarity score cannot be argued with. When a graph-native
retrieval misses, the miss points at a specific missing thing -- an alias that
was never recorded, a section the scan skipped, an edge nobody wrote -- and that
is a repairable defect. A vector miss points at a number.

*Corrected 2026-08-18.* This paragraph used to continue "the graph's mentions
and aliases already encode what a text index would have to guess, and at 36
sections there is nothing for an index to do that a scan cannot". At 835
sections that is measurably false. Over the 46-question set the BM25 index alone
retrieves the right section 78% of the time against the graph path's 67%, and
seven of the nine questions the graph anchored and then missed were sitting in
the index. The argument against embeddings survives -- a keyword hit can still
be read back to the words that caused it -- but the claim that the graph makes a
text index redundant did not, and `TEXT_SLOTS` is what was done about it.

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
from backend.canon.passage import derive_passage, derive_section
from backend.canon.questions import content_terms, lucene_query, terms_present
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

#: The entities a set of sections names. What the text path anchors on, having
#: no resolved name of its own.
#:
#: WITHOUT THIS, THE TEXT PATH THREW AWAY THE GRAPH. Asked "who owns the
#: tavern", it found section E2 -- exactly the right section -- and returned
#: prose alone, so the three `OWNS` edges a human had accepted about that very
#: room never reached the model, which then said the canon did not cover it.
#: Retrieving a section and ignoring what the graph knows about its occupants is
#: using the book as a text file.
#:
#: The fact/guess line is untouched: these edges keep their own status and are
#: rendered under the same two headings. What is a guess here is WHICH SECTIONS
#: to look at, and that was already labelled.
ENTITIES_IN_SECTIONS = """
MATCH (s:Section)<-[:IN_SECTION]-(:Mention)-[:REFERS_TO]->(e:Entity {plane:$plane})
WHERE s.id IN $section_ids
RETURN DISTINCT e.id AS id
"""

#: Retrieval returns at most this many passages unless told otherwise. A DM
#: reading an answer will not read twenty paragraphs, and an unbounded context
#: hides a ranking problem by making every miss a hit.
DEFAULT_LIMIT = 5

#: How much of a section a passage carries.
WIDTH_SENTENCE = "sentence"
WIDTH_SECTION = "section"

#: A whole-section passage is cut here. The corpus's largest section is 4,621
#: characters and its median 842, so this bounds the worst case without touching
#: the typical one. Truncation is reported on the passage, never silent.
SECTION_MAX = 4000

#: How a retrieval was answered. Carried on the result and reported by the
#: evaluation harness, because a text hit and a graph hit are not the same
#: quality of answer and an aggregate recall that hides which is which would
#: make the fallback look like an improvement to the graph.
PATH_GRAPH = "graph"
PATH_TEXT = "text"
PATH_NONE = ""

#: What one matched question word is worth against one naming of an anchor, when
#: ranking the graph path's candidate sections.
#:
#: CHOSEN FROM A PLATEAU, NOT FITTED TO A PEAK. Swept over the 24-question set:
#:
#:     weight   0     1     2     3     4     5     8    12    20   terms-only
#:     MRR     .690  .784  .787  .801  .801  .796  .796  .769  .759   .664
#:     hits   16/18 17/18 17/18 17/18 17/18 17/18 17/18 17/18 17/18  17/18
#:
#: Everything from 1 to 8 lands within .02 of the best, so what matters is that
#: the term signal is PRESENT, not what it is multiplied by -- and a constant
#: that only works at one value would be a number fitted to eighteen questions.
#: 3 is the middle of the flat region. `terms-only` is worse than either signal
#: combined, which is why occurrences are not simply replaced.
TERM_WEIGHT = 3

#: How many of the budget's passages are held for the text path when a question
#: DID anchor. The rest go to the graph, and any slack the graph does not use
#: goes to text as well.
#:
#: THE FALLBACK USED TO BE ALL-OR-NOTHING, and that was the single largest
#: defect in retrieval. Text ran only when NOTHING anchored, so a question that
#: anchored on the WRONG thing was dead: `coffin` resolved to an extracted prop
#: in Castle Ravenloft, and "who is lying in the coffin in the burgomaster's
#: mansion" went to the tombs. Forced onto the text path, seven of the nine
#: anchored-but-missed questions hit, two of them at rank 1.
#:
#: Swept over the 46-question set at limit 5. `reserve 0` is padding alone --
#: text fills only slots the graph left empty, so it displaces nothing and
#: cannot cost a hit:
#:
#:     reserve      0     1     2     3     4     5   graph only
#:     hits/46     33    35    34    35    35    36    31
#:     recall     72%   76%   74%   76%   76%   78%   67%
#:
#: 1 is chosen over the larger reserves because they buy nothing beyond it
#: while evicting more of the path that resolved a name. The last column is why
#: this constant exists at all; the 5 column is reported because it is
#: uncomfortable and hiding it would be dishonest -- BM25 alone outscores the
#: graph path on SECTION RECALL, which is the only thing this set measures. It
#: does not measure the edges, and the edges are what made the agent right
#: about the tavern's three owners where prose alone said canon did not cover it.
TEXT_SLOTS = 1


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
    #: How many of the question's non-name words this section contains. The
    #: other half of the ranking, carried so a surprising order can be read
    #: rather than guessed at.
    term_hits: int = 0
    #: True when a whole-section passage hit `SECTION_MAX` and lost its tail.
    truncated: bool = False
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
    #: Which path put THIS passage in front of the reader. One result now mixes
    #: both, so the label belongs on the passage rather than only on the
    #: `Retrieval`: a section that resolved a name is a fact about the book, a
    #: section Lucene scored is a guess about the question, and the two now sit
    #: side by side in one list.
    #:
    #: Defaulted rather than required so the callers and fixtures that build a
    #: graph passage by hand keep working. `_text_passages` sets it explicitly,
    #: and a test pins that every text passage carries the label.
    path: str = PATH_GRAPH


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
    #: How the QUESTION was answered: `graph` (a name resolved), `text` (nothing
    #: did and the prose was searched instead), or empty (nothing answered).
    #: Never inferred from whether `anchors` is empty -- a caller reading a text
    #: answer must be able to see that it is one.
    #:
    #: This is now the coarser of two labels. A `graph` result still contains
    #: text passages, because `TEXT_SLOTS` reserves room for them; which one put
    #: any PARTICULAR passage in front of the reader is `Passage.path`. Reading
    #: this field as "every passage below resolved a name" was true before that
    #: reservation existed and is not true now.
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


def dedupe_edges(rows: list[dict]) -> list[dict]:
    """One row per edge, whichever endpoints were asked about.

    `EDGES` deliberately reads both directions, because half of what a DM wants
    about an NPC is written with the NPC as the TARGET. When only ONE endpoint
    is an anchor that yields one row per edge. When BOTH are -- which is now the
    normal case, since the text path anchors on every entity a section names --
    it yields two, and the rendered block showed six lines for the tavern's
    three owners.

    Deduplicated on the edge as the graph stores it, so the surviving row keeps
    its own direction and `_edge_line` still writes the arrow the right way
    round. Order is preserved: the first row seen wins, and the query is already
    ordered.
    """
    seen: set[tuple[str, str, str]] = set()
    unique: list[dict] = []
    for row in rows:
        entity, other = row.get("entity"), row.get("other")
        if row.get("direction") == "in":
            entity, other = other, entity
        key = (str(entity), str(row.get("relationship")), str(other))
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def combine_passages(
    graph: list[Passage],
    text: list[Passage],
    limit: int,
    reserve: int = TEXT_SLOTS,
) -> list[Passage]:
    """One budget, split between the path that resolved a name and the one that
    scored the prose. Concatenation, never a blended score.

    The two orderings are NOT comparable -- `occurrences + 3*terms` and Lucene's
    BM25 are different units -- so nothing here adds, scales or normalises them
    against each other. Each list arrives already ranked by its own rule, and
    this function only decides how many slots each gets. That is what keeps
    `Passage.path` meaningful: a reader can still say which path is responsible
    for any line, which a merged score would destroy.

    `reserve` slots are held for text. The graph takes the rest AND any slack
    text does not use, so the two effects the sweep measured apart are one rule
    here:

      * a graph path returning FEWER than `limit - reserve` candidates is padded
        out of text, displacing nothing -- 11 of the 46 questions
      * a graph path with more candidates than budget gives `reserve` of them up

    Order is graph-first because a resolved name outranks a guess at equal
    standing; `reserve=0` degenerates to padding alone.

    A section reached by both paths appears ONCE, keeping whichever came first
    -- which, for anything inside the graph's kept prefix, is the graph's copy
    with its occurrence count and entity ids intact.

    THE RESERVATION NEVER TAKES THE GRAPH'S LAST SLOT. At `limit=1` the
    arithmetic gave the graph `1 - 1 = 0`, so a question that resolved a name
    got back a single Lucene guess and both of its real candidates counted as
    dropped. A guess may fill what a name left empty and may take the tail of a
    long list; it may not evict the name entirely.
    """
    if graph:
        reserve = min(reserve, limit - 1)
    kept = graph[: max(0, limit - reserve)]
    out: list[Passage] = list(kept)
    seen = {p.section_id for p in kept}
    for passage in [*text, *graph[max(0, limit - reserve) :]]:
        if len(out) >= limit:
            break
        if passage.section_id in seen:
            continue
        seen.add(passage.section_id)
        out.append(passage)
    return out


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

    def __init__(
        self, limit: int = DEFAULT_LIMIT, passage_width: str = WIDTH_SECTION
    ) -> None:
        self.limit = limit
        self.passage_width = passage_width

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
            # The question's words MINUS the anchors' own. A question naming
            # Strahd already counts him through his occurrences; letting
            # `strahd` score again as a content word would count one signal
            # twice and re-favour exactly the broad sections this is meant to
            # demote.
            anchor_words = {word for a in anchors for word in a.surface.lower().split()}
            terms = [t for t in content_terms(question) if t not in anchor_words]
            passages = self._passages(session, ids, terms)

            # The text path runs even though a name resolved, and this is the
            # change that matters most. Anchoring is not the same as anchoring
            # WELL: `coffin` resolves to an extracted prop in Castle Ravenloft,
            # and while text ran only on a total anchoring failure, "who is
            # lying in the coffin in the burgomaster's mansion" had no way back.
            #
            # Searched on the question's OWN terms -- `content_terms(question)`,
            # not `terms` -- because the anchor words are removed only to stop
            # one signal being counted twice inside the graph's ranking. Lucene
            # is a separate ordering that never sees those occurrences, so
            # withholding `strahd` from it would just make it a worse search.
            text_terms = content_terms(question)
            text_passages = self._text_passages(session, text_terms, limit)
            kept = combine_passages(passages, text_passages, limit)

            edges = dedupe_edges(self._rows(session, EDGES, {"ids": ids}))
            accepted, proposed = split_by_status(edges)

            # Edges stay anchored on the RESOLVED names, and deliberately do not
            # follow the text passages the reservation added. The text path
            # gathers entities from the sections it scored because it has no
            # resolved name to work from; here there is one, and pulling in
            # relationships about entities the question never named -- chosen by
            # a Lucene score -- would put guesses under the heading that reads
            # as what the graph knows about what you asked.
            return Retrieval(
                question=question,
                anchors=tuple(anchors),
                passages=tuple(kept),
                accepted=tuple(accepted),
                proposed=tuple(proposed),
                # Graph candidates the budget cut, which is what this has always
                # counted. Text passages are not counted as dropped: the text
                # path is bounded by `limit` at the query, so it has no tail.
                dropped=max(0, len(passages) - sum(1 for p in kept if p.path == PATH_GRAPH)),
                ambiguous=tuple(ambiguous),
                loose=loose,
                path=PATH_GRAPH,
                terms=tuple(text_terms),
                miss_reason="" if kept else "anchored, but no section mentions the anchors",
            )

    # -- internals ---------------------------------------------------------

    def _text_passages(self, session, terms: list[str], limit: int) -> list[Passage]:
        """The prose search itself, with no opinion about why it was called.

        Split out of `_by_text` so the two callers cannot drift: the fallback
        that runs when nothing anchored, and the `TEXT_SLOTS` reservation that
        runs alongside a graph result. A second copy of "search the sections and
        build passages" would be free to disagree with this one about width,
        truncation or the score -- the same duplication `passage.py` exists to
        prevent for "the same sentence".

        The passage is anchored at offset 0, since Lucene scores a whole
        document and picking one matched term to centre on would imply the
        section is about that term. At `section` width that is the whole
        section anyway; at `sentence` width it is the section's opening, which
        is the book's own topic statement.
        """
        if not terms:
            return []
        rows = self._rows(
            session,
            SEARCH_SECTIONS,
            {"query": lucene_query(terms), "limit": limit},
        )
        return [
            Passage(
                section_id=row["section_id"],
                chapter=row["chapter"],
                chapter_index=row["chapter_index"],
                section=row["section"],
                section_index=row["section_index"],
                # Through `_render`, so `passage_width` applies here too. It
                # used to call `derive_passage` directly and always sent one
                # sentence, silently ignoring the setting -- which is how a
                # whole-section search returned 930 tokens of the wrong
                # sentence.
                text=self._render({"text": row["text"], "offset": 0}),
                truncated=self._truncated({"text": row["text"]}),
                occurrences=0,
                entity_ids=(),
                score=row["score"],
                path=PATH_TEXT,
            )
            for row in rows
        ]

    def _by_text(self, session, question: str, limit: int) -> Retrieval:
        """The last resort: search the prose for what the question describes.

        Reached only when the question names nothing. It reports `path='text'`
        and carries NO anchors, because no name resolved -- which sections to
        read is a Lucene score's opinion, and that has to stay visible.

        IT DOES CARRY THE GRAPH'S EDGES, from the entities those sections name.
        It used to carry none, on the reasoning that a text hit has no entity to
        hang a relationship off. That was wrong in a way a real question
        exposed: asked "who owns the tavern", it found section E2 -- exactly the
        right section -- and returned prose alone, so three `OWNS` edges a human
        had accepted about that very room never reached the model, which
        answered that the canon did not cover it. Retrieving a section and
        discarding what the graph knows about its occupants is using the book as
        a text file.

        The passage is anchored at offset 0, since Lucene scores a whole
        document and picking one matched term to centre on would imply the
        section is about that term. At `section` width that is the whole
        section anyway; at `sentence` width it is the section's opening, which
        is the book's own topic statement.
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
        passages = self._text_passages(session, terms, limit)
        section_ids = [p.section_id for p in passages]
        ids = sorted(
            row["id"]
            for row in self._rows(
                session, ENTITIES_IN_SECTIONS, {"section_ids": section_ids}
            )
        ) if section_ids else []
        accepted, proposed = split_by_status(
            dedupe_edges(self._rows(session, EDGES, {"ids": ids})) if ids else []
        )
        return Retrieval(
            question=question,
            accepted=tuple(accepted),
            proposed=tuple(proposed),
            passages=tuple(passages),
            path=PATH_TEXT if passages else PATH_NONE,
            terms=tuple(terms),
            miss_reason=(
                ""
                if passages
                else f"the question names nothing, and no section matches {terms}"
            ),
        )

    def _passages(self, session, ids: list[str], terms: list[str]) -> list[Passage]:
        """One passage per SECTION, ranked.

        Per section rather than per mention: two anchors named in one section is
        one thing for a DM to read, and emitting it twice would both waste the
        budget and let a single dense section crowd out every other. The
        occurrence counts add, which is what makes a section naming both anchors
        outrank one naming either.

        RANKING is `occurrences + TERM_WEIGHT * matched terms`, then the number
        of distinct anchors, then the book's own order. The last only breaks
        ties, so the ordering is total and a re-run cannot reshuffle it.

        THE TERM SIGNAL EXISTS BECAUSE OCCURRENCES ALONE ANSWER THE WRONG
        QUESTION. Counting how loudly a section names the anchors ranks the
        sections that talk about them MOST, which for `Strahd` and `Barovia` is
        the introduction's overview -- while every word of the question that is
        not a name goes unused. "Who are Strahd's undead enemies in Barovia"
        ranked its answer NINTH, and that answer contains the words `undead` and
        `enemies` almost verbatim.

        The candidate set is untouched by this. Every eligible section is one
        that mentions a resolved name; terms only reorder them. So the fact/guess
        line the text fallback respects is respected here too -- a term can move
        a passage up, never conjure one.

        Note what this does NOT fix, because ranking cannot: a section the scan
        never linked is not a candidate at any weight. "What happens at the
        cemetery at midnight" is the example -- the book writes `cemetery` in
        lower case in `March of the Dead`, and the single-word case rule (the
        rule keeping the LORE entity `Light` off every lit torch) means
        `Cemetery` has no mention there.

        That question now hits, and NOT because ranking improved: `TEXT_SLOTS`
        reaches the section through the index instead. The limit stated here is
        real and unchanged. It is worth being precise about which repair worked,
        because a sweep of nine occurrence-saturating and term-weighting
        variants moved this set by at most one question in either direction --
        ranking was measured, repeatedly, and is not where these misses live.
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
                text=self._render(slot),
                truncated=self._truncated(slot),
                occurrences=slot["occurrences"],
                entity_ids=tuple(sorted(set(slot["entity_ids"]))),
                aliases=tuple(sorted(set(slot["aliases"]))),
                term_hits=terms_present(slot["text"], terms),
            )
            for slot in merged.values()
        ]
        passages.sort(
            key=lambda p: (
                -(p.occurrences + TERM_WEIGHT * p.term_hits),
                -len(p.entity_ids),
                p.chapter_index,
                p.section_index,
            )
        )
        return passages

    def _render(self, slot: dict) -> str:
        """The passage text at the configured width."""
        if self.passage_width == WIDTH_SECTION:
            return derive_section(slot["text"], SECTION_MAX)[0]
        return derive_passage(slot["text"], slot["offset"])

    def _truncated(self, slot: dict) -> bool:
        if self.passage_width != WIDTH_SECTION:
            return False
        return derive_section(slot["text"], SECTION_MAX)[1]

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
