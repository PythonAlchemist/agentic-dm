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

from backend.canon.retrieval import PATH_TEXT, Retrieval

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

_NO_CANON = (
    "CANON — nothing retrieved for this question. Say that the canon graph "
    "does not cover it. Do not answer from memory of the published adventure; "
    "only 3 of its 25 chapters have been loaded, so silence here means "
    "'not loaded', not 'not in the book'."
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
    """
    return [
        {
            "source": passage.section_id,
            "type": "canon",
            "chapter": passage.chapter,
            "section": passage.section,
            "path": retrieval.path,
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
