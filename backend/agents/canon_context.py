"""Render a `Retrieval` into the block the model is asked to answer from.

A pure function of the retrieval -- no database, no model, no I/O -- so what the
agent grounds on can be tested exactly rather than inferred from an answer.

TWO THINGS THIS MUST GET RIGHT, and they are the same thing twice.

**The passages have to actually be here.** The pipeline this sits beside inserts
a list of source NAMES and tells the model "relevant context has been
retrieved", which grounds nothing: the model is informed that an answer exists
somewhere and then writes from memory. Whatever a DM sees has to be traceable to
prose the book contains, so the prose travels.

**Provenance has to survive the trip.** Retrieval knows things the model cannot
recover from the text alone -- whether a name resolved or a keyword merely
matched, whether a relationship was derived from the book's structure or guessed
by an extractor that is wrong roughly a third of the time. Flattening all of
that into "here is some context" hands the model unverified claims wearing the
same clothes as the book's own words. So each kind is labelled, in the plainest
language available, with what it is worth.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from backend.canon.retrieval import DEFAULT_LIMIT, PATH_TEXT, Retrieval


@dataclass(frozen=True)
class Depth:
    """How much canon reaches the model.

    Every field trades context against tokens, and the point of making them
    adjustable rather than tuned once is that the trade is not the same for
    every question -- a rules lookup needs one passage, a scene needs five.

    `include_proposed` is the one that is not a size knob. Proposed edges are
    extractor guesses, wrong about a third of the time, and excluding them asks
    a different question: not "how much context", but "how much UNVERIFIED
    context". Being able to turn them off and re-ask is how you find out whether
    a bad answer came from the model or from a false edge fed to it.
    """

    #: Defaulted from the retriever's own budget rather than restated, so the
    #: number the evaluation harness measures is the number the agent gets.
    #: These were both 5 and drifted apart the moment one of them moved.
    passages: int = DEFAULT_LIMIT
    max_edges: int = 12
    #: Tokens the working subgraph may occupy before the oldest-touched items
    #: are evicted. Chosen against the measured shape of a turn: passage prose
    #: is about 5,000 tokens and relationship lines about 160, so 400 leaves
    #: the summary an order of magnitude smaller than the book it describes --
    #: which is the right proportion for something that says what the
    #: conversation is ABOUT rather than what the book says.
    subgraph_budget: int = 400
    include_proposed: bool = True
    #: Withhold a guessed edge whose own cited sentence does not support it.
    #:
    #: Every proposed edge carries `evidence_check`, a verdict on whether the
    #: sentence the extractor read says what the edge claims -- 61% supported
    #: in Curse of Strahd, 51% in the heist anthology. This drops the rest.
    #:
    #: OFF BY DEFAULT until it is measured. The verdict is a model grading a
    #: model, and gating what a DM is shown on it is a larger claim than
    #: recording it, which is why the label was written first and used second.
    only_supported_edges: bool = False
    #: `section` sends each passage's whole section; `sentence` sends one
    #: sentence around the mention.
    #:
    #: SECTION IS THE DEFAULT because sentence width answers a narrower question
    #: than DMs ask. "Who owns the Blood of the Vine Tavern" is answered 3,331
    #: characters after the tavern's first mention, in the same section, under a
    #: sub-heading about roleplaying the other NPCs -- no sentence window
    #: anchored on the mention reaches it, however the anchor is chosen. Sections
    #: are cheap enough to send whole: the median is 842 characters, and five of
    #: them run about a thousand tokens.
    passage_width: str = "section"


def apply(retrieval: Retrieval, depth: Depth) -> Retrieval:
    """The retrieval as `depth` allows it to be seen.

    Passage count is applied by the retriever, which knows the ranking. What is
    applied HERE is `include_proposed`, because dropping the guesses is about
    what the model may read, not about what the graph holds -- the retrieval
    keeps reporting what it found either way.
    """
    kept = retrieval.proposed if depth.include_proposed else ()
    if kept and depth.only_supported_edges:
        # `unsupported` and `reversed` go; `unclear` and an UNJUDGED edge stay.
        # An edge nobody judged is not an edge that failed, and dropping it
        # here would make a missing verdict look like a verdict.
        kept = tuple(
            e for e in kept
            if e.get("evidence_check") not in {"unsupported", "reversed"}
        )
    return replace(retrieval, proposed=kept)

#: What the model is told about the whole block, before any of it.
_PREAMBLE = (
    "CANON — passages retrieved from Curse of Strahd for this question.\n"
    "Answer from these passages. Cite the section you used, like [1].\n"
    "If they do not cover what was asked, say so plainly rather than filling "
    "the gap from memory — a DM acting on an invented detail finds out at the "
    "table."
)

#: Reached when no name in the question resolved. The model is told the answer
#: may simply not be here, because the fallback cannot say so itself: any
#: question sharing one word with any section returns that section.
_TEXT_WARNING = (
    "These sections were found by KEYWORD MATCH ONLY — nothing in the question "
    "named anything the canon graph knows. They share words with the question "
    "and may be about something else entirely. Use one only if it plainly "
    "answers what was asked, and say the canon does not cover it otherwise."
)

#: Appended to the heading of a single keyword-matched passage sitting among
#: resolved ones.
#:
#: A result that anchored on a name now also carries text passages, because
#: `TEXT_SLOTS` reserves room for them, and `_TEXT_WARNING` only fires when the
#: WHOLE retrieval was a keyword search. Without this the model would read a
#: Lucene guess under a block that says these passages were retrieved for the
#: question, with nothing to distinguish it from the section that resolved a
#: name -- which is the fact/guess line going quiet exactly where it is most
#: load-bearing.
_KEYWORD_MARK = "  (keyword match — may be about something else)"

#: What the model is told when retrieval came back empty.
#:
#: THE COUNT THAT USED TO BE HERE WENT STALE. This read "only 3 of its 25
#: chapters have been loaded" long after the whole book was written to the
#: graph, so the model was being told the corpus was 12% present when it was
#: complete. A number that describes the state of a database does not belong in
#: a string constant; the instruction that matters -- do not answer from memory
#: -- is true at every stage of loading, and is what this says now.
_NO_CANON = (
    "CANON — nothing retrieved for this question. Say plainly that the canon "
    "graph did not return anything on it. Do not answer from memory of the "
    "published adventure: retrieval missing something is not the same as the "
    "book not containing it, and a DM cannot tell an invented detail from a "
    "real one until it fails at the table."
)

#: Relationship trust, in words a model will act on rather than a status string.
_ACCEPTED_HEADING = (
    "Relationships DERIVED from the book's own structure. These are reliable:"
)
_PROPOSED_HEADING = (
    "Relationships GUESSED by an extractor. Roughly a third are wrong — treat "
    "each as a lead to check, never state one as fact:"
)


def render(retrieval: Retrieval, *, max_edges: int = 12) -> str:
    """The context block, or a statement that there is none.

    `max_edges` bounds each relationship list. A heavily-mentioned anchor such
    as Strahd carries dozens, and a wall of unverified edges buries the passages
    that are actually worth reading. What is cut is counted in the line above
    it, never dropped silently.
    """
    if not retrieval.passages:
        return _NO_CANON

    parts = [_PREAMBLE]
    if retrieval.path == PATH_TEXT:
        parts.append(_TEXT_WARNING)
        if retrieval.terms:
            parts.append(f"Words searched for: {', '.join(retrieval.terms)}.")

    for number, passage in enumerate(retrieval.passages, start=1):
        heading = f"[{number}] {passage.chapter} › {passage.section}"
        # Only when the block has not already said it wholesale, so a pure text
        # retrieval does not repeat the warning on every line.
        if passage.path == PATH_TEXT and retrieval.path != PATH_TEXT:
            heading += _KEYWORD_MARK
        parts.append(f"{heading}\n{passage.text}")

    for heading, edges in (
        (_ACCEPTED_HEADING, retrieval.accepted),
        (_PROPOSED_HEADING, retrieval.proposed),
    ):
        if not edges:
            continue
        shown = edges[:max_edges]
        lines = [_edge_line(e) for e in shown]
        cut = len(edges) - len(shown)
        if cut:
            lines.append(f"  … and {cut} more, not shown")
        parts.append(heading + "\n" + "\n".join(lines))

    return "\n\n".join(parts)


def sources(retrieval: Retrieval) -> list[dict]:
    """Citations for the UI, one per passage, in the order the model saw them.

    `path` rides along so a caller can render a keyword match differently from a
    resolved one. A citation that looks equally authoritative either way would
    undo the labelling the block above works to preserve.

    Taken from the PASSAGE, not from the retrieval. One result now mixes both
    paths, and stamping the question's coarse label on every citation was how a
    Lucene guess came to be presented in the UI as a resolved name.
    """
    return [
        {
            "source": passage.section_id,
            "type": "canon",
            "chapter": passage.chapter,
            "section": passage.section,
            "path": passage.path,
            "citation": f"[{number}]",
        }
        for number, passage in enumerate(retrieval.passages, start=1)
    ]


def _edge_line(edge: dict) -> str:
    """`A -RELATIONSHIP-> B`, in the direction the graph stores it.

    Direction is not cosmetic here. `Strahd SEEKS Ireena` and `Ireena SEEKS
    Strahd` are different claims about the same two nodes, and reversal is one
    of the extractor's four measured failure modes -- so the arrow is written
    out rather than left to a phrasing that might read either way.
    """
    entity = edge.get("entity", "?")
    other = edge.get("other", "?")
    relationship = edge.get("relationship", "?")
    if edge.get("direction") == "in":
        entity, other = other, entity
    return f"  {entity} -{relationship}-> {other}"
