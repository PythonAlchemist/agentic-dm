"""The sentence a mention sits in, derived rather than stored.

A `:Mention` carries `offset`; its `:Section` carries the full `text`. Between
them the passage is already in the graph, so storing a copy of it on the mention
was a second copy of prose the graph had -- and a paragraph naming three
entities stored that paragraph three times. Measured on chapter 3, the
introduction and the foreword: 153 mentions, 35,383 characters of `evidence`, of
which 9,894 were literal duplicates of a string already on a sibling node.

This module is the replacement, and it is deliberately its own module rather
than a function in `spine.py`. Two callers need the SAME span for different
reasons: `lookup.py` renders it for a DM to read, and co-occurrence at span
granularity asks which other mentions' offsets fall inside it. One rule, one
implementation -- two would eventually disagree about one sentence, and the
disagreement would show up as a co-occurrence edge whose passage does not
contain both names.

That is why `sentence_bounds` returns OFFSETS and `derive_passage` returns the
string. The offsets are the shared, load-bearing half; the string is a rendering
of them.

**A rough boundary is the goal, and the errors are not symmetric.** A span that
runs one sentence long costs a reader an extra clause. A span that ends inside a
name costs them the name -- `...outside St.` is not evidence that anything is at
St. Andral's Church. So every rule below is biased toward NOT splitting: a
doubtful period is left alone, the span grows, and the 300-character cap catches
whatever the boundary rule missed.

**Newlines are hard boundaries.** Checked across all 25 chapters of the corpus:
prose is never hard-wrapped, so a single newline is always a table row, a
heading, an image caption or a blockquote gutter, and never the middle of a
sentence. The payoff is that a mention inside a markdown table quotes its own
row -- `| 9th | The Amber Temple | 13 |` -- where the stored evidence quoted 300
characters of pipes.

**Emphasis markers are stripped.** See `MARKERS`.
"""

from __future__ import annotations

import re

#: How much of its section a passage may quote. Long enough for the sentence a
#: name sits in with room to spare -- the longest real sentence in the loaded
#: corpus derives to 296 -- and short enough that a run-on paragraph cannot
#: reintroduce the bulk this module exists to delete.
PASSAGE_MAX = 300

#: What may trail the punctuation and still belong to the sentence it ends:
#: closing quotes, brackets, and markdown emphasis. `“Let me out, father!”` ends
#: at the quote, not before it, and `**Finding Artifacts.**` ends at the stars.
_CLOSERS = "\"')]}_*”’"

#: A CANDIDATE boundary -- terminal punctuation, its closers, and then
#: whitespace or the end of the line. `_closes_a_sentence` decides which
#: candidates are real.
_SENTENCE_END = re.compile(rf"[.?!][{re.escape(_CLOSERS)}]*(?=\s|$)")

#: The word ending immediately before a period, which is the whole of what the
#: abbreviation guard looks at. `[^\W_]` rather than `\w` for the same reason
#: `spine.WORD_CHAR` is: an underscore is emphasis in this corpus, not a letter.
_WORD_BEFORE = re.compile(r"[^\W_]+\Z")

#: A keyed area code -- `E5`, `E5g`, `K42`, `N7`. The book heads every room with
#: one (`### E5f. Chapel`) and cross-references them in running prose (`beyond
#: area K42.`), 578 times across the corpus. The period after the code is part
#: of the label, and splitting there leaves a passage that is only the label.
_KEY_CODE = re.compile(r"[a-z]{1,2}\d+[a-z]?\Z", re.IGNORECASE)

#: Abbreviations this corpus actually writes, lowercased. Small on purpose: an
#: entry costs a real boundary somewhere (`Avg` would, in prose) and buys back
#: only the split it prevents, so nothing goes in here that the text does not
#: contain. `St.` appears 18 times -- `St. Andral's Church` is a location in
#: chapter 5 -- and `Avg.`/`Inc.` head a table column and a publisher.
#:
#: NOT here, and deliberately: `cp`, `sp`, `gp`. They are coins, they end
#: sentences (`A glass of wine costs 1 cp. Arik returns to...`), and adding them
#: would merge two sentences to prevent nothing.
_ABBREVIATIONS = frozenset(
    {"st", "mr", "mrs", "ms", "dr", "mt", "sgt", "lt", "capt", "gen",
     "no", "vs", "etc", "avg", "inc", "fig"}
)

#: Markdown emphasis, stripped from the rendered passage.
#:
#: THE DECISION: markers come out ALWAYS, not only when a span cuts one in half.
#: Stripping only unbalanced markers would render the same paragraph differently
#: depending on where it was cut, which is a worse thing to explain than either
#: consistent choice. Leaving them in litters a DM's passage with underscores --
#: `_**Vistani Owners. **_Three Vistani spies` -- for a typographic distinction
#: that a details panel does not render anyway.
#:
#: This is a rendering of the span, not an edit to it. `sentence_bounds` is
#: untouched by it, so the span remains a literal region of the section and
#: co-occurrence still reasons about the book's own offsets.
_MARKERS = re.compile(r"[_*]+")

_WHITESPACE = re.compile(r"\s")


def _closes_a_sentence(text: str, mark: int) -> bool:
    """Is the punctuation at `mark` a real sentence end?

    `?` and `!` always are -- no abbreviation ends in either. A period is
    judged by the word in front of it, and four kinds of word do not end a
    sentence:

    - a single letter (`in appendix D.`, or an initial);
    - digits alone (`2.` opening a list item, `1978.` a year);
    - a keyed area code (`E5g.`, `K42.`);
    - a recorded abbreviation (`St.`, `Avg.`).

    Every one of them errs long: a period wrongly kept merges two sentences,
    and the cap below bounds the damage. A period wrongly split cuts a name.
    """
    if text[mark] != ".":
        return True
    word = _WORD_BEFORE.search(text, 0, mark)
    if word is None:
        return True
    token = word.group()
    if len(token) == 1 or token.isdigit() or _KEY_CODE.match(token):
        return False
    return token.lower() not in _ABBREVIATIONS


def _snap_forward(text: str, low: int, limit: int) -> int:
    """The next word start at or after `low`, never past `limit`."""
    space = _WHITESPACE.search(text, low, limit)
    return space.end() if space else low


def _snap_back(text: str, high: int, floor: int) -> int:
    """The last word end at or before `high`, never before `floor`."""
    for index in range(high, floor, -1):
        if text[index - 1].isspace():
            return index - 1
    return high


def sentence_bounds(text: str, offset: int) -> tuple[int, int]:
    """`(low, high)` into `text` for the sentence containing `offset`.

    THE SHARED RULE. `derive_passage` renders these bounds for a reader;
    co-occurrence asks which other mention offsets fall inside them. Both get
    the same span because both call this.

    Expands from `offset` to the nearest real boundary in each direction --
    a newline always, terminal punctuation when `_closes_a_sentence` allows --
    then trims whitespace off both ends.

    Over the cap, it falls back to a WINDOW rather than a truncation, placed so
    `offset` keeps roughly a third of the budget behind it and the rest ahead,
    and snapped outward-in to whitespace. Truncating from the left would cut off
    the very name the passage is evidence for; snapping is what keeps the window
    from beginning or ending mid-word. `low <= offset < high` always holds for
    an offset inside the text.
    """
    if not text:
        return 0, 0
    offset = max(0, min(offset, len(text) - 1))

    line_start = text.rfind("\n", 0, offset) + 1
    line_end = text.find("\n", offset)
    line_end = len(text) if line_end < 0 else line_end

    start, end = line_start, line_end
    for match in _SENTENCE_END.finditer(text, line_start, line_end):
        if not _closes_a_sentence(text, match.start()):
            continue
        if match.end() <= offset:
            start = match.end()
        else:
            end = match.end()
            break

    while start < offset and text[start].isspace():
        start += 1
    while end > offset + 1 and text[end - 1].isspace():
        end -= 1

    if end - start <= PASSAGE_MAX:
        return start, end

    low = max(start, offset - PASSAGE_MAX // 3)
    high = min(end, low + PASSAGE_MAX)
    low = max(start, min(low, high - PASSAGE_MAX))
    if low > start:
        low = min(_snap_forward(text, low, offset), offset)
    if high < end:
        high = max(_snap_back(text, high, offset + 1), offset + 1)
    return low, high


def derive_passage(text: str, offset: int) -> str:
    """The passage a reader sees for a mention at `offset`. Never None.

    The span, with emphasis markers removed and the ends trimmed. Empty only
    for empty text -- a mention exists because something matched, so a passage
    that came back blank would mean the offset and the section had come apart.
    """
    low, high = sentence_bounds(text, offset)
    return _MARKERS.sub("", text[low:high]).strip()
