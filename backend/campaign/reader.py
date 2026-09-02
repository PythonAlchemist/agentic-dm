"""Shaping what a DM is shown, apart from the routes that fetch it.

WHY IT IS ITS OWN MODULE. These rules lived inside `api/routes/homebrew.py`,
between the session handling and the response dict, so the only way to exercise
one was over HTTP with a live graph behind it. They are not plumbing: they
decide what the reader is told a section says, which of a section's
relationships are about the scene in front of them, and which of the book's
sentences are quoted back. The docstrings there record two bugs that reached a
DM through exactly these rules.

Nothing here touches a database. Rows in, response out.
"""

from __future__ import annotations

import json

#: How much either side of a mention to keep when no sentence end is found --
#: enough to be a claim, short enough to stay a quote.
QUOTE_WINDOW = 220


def sentences_at(text: str, offsets: list[int], limit: int = 3) -> list[str]:
    """The sentences that actually name the thing, quoted exactly.

    A LIST OF HEADINGS IS NOT AN ANSWER. "Named in: Trek to the Prison" tells a
    DM where to go looking; "directs them to report to a ship called the Jolly
    Pelican the following dawn" tells them what it IS. The offsets have been
    stored all along and the difference between the two is one hop.

    QUOTED, NEVER SUMMARISED. Everything else the endpoint returns is the
    graph's own record; this is the book's words, and a paraphrase here would
    be the one kind of sentence a DM has no way to check.

    Sentence bounds by punctuation, falling back to a window when a section has
    none -- headings and table rows often do not. A quote that runs on is worse
    than one that stops early, so the window is small.
    """
    found: list[str] = []
    for offset in offsets[:limit]:
        if not 0 <= offset < len(text):
            continue
        start = text.rfind(".", 0, offset) + 1
        end = text.find(".", offset)
        if end == -1 or end - start > QUOTE_WINDOW * 2:
            start = max(0, offset - QUOTE_WINDOW)
            end = min(len(text), offset + QUOTE_WINDOW)
        quote = " ".join(text[start : end + 1].split()).strip()
        if quote and quote not in found:
            found.append(quote)
    return found


def entity_card(row: dict) -> dict:
    """One entity, as the reader's card wants it.

    THE THREE THINGS THIS DECIDES, each of which reached a DM wrongly once:

      * WHERE ELSE IT IS NAMED, with the sentence rather than the heading.
        A row carrying no `section_id` is a `collect` of nothing -- Cypher's
        answer to "this entity is named nowhere" -- and passing it through
        produced a citation to a section that does not exist.
      * WHAT IT IS: `labels` minus the bare `:Entity`, which every node has and
        which says nothing.
      * WHETHER THE BOOK NAMES IT, as a plain boolean. The property is only
        ever set to false, so absence is the ordinary case, and answering
        `None` would ask a reader to tell "not marked" from "not known" -- a
        distinction they do not have.
    """
    found = dict(row)
    found["invented"] = json.loads(found["invented"]) if found.get("invented") else []
    found["named_in"] = [
        {
            "section_id": where["section_id"],
            "heading": where["heading"],
            "plane": where["plane"],
            "says": sentences_at(where.get("text") or "", where.get("offsets") or []),
        }
        for where in (found.get("named_in") or ())
        if where.get("section_id")
    ]
    found["labels"] = [x for x in (found.get("labels") or []) if x != "Entity"]
    found["named_by_book"] = found.get("named_by_book") is not False
    return found
