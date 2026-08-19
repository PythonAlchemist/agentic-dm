"""Split a chapter into units small enough to extract from in one pass.

A whole chapter is too large -- Castle Ravenloft is ~40k tokens, and a single
response enumerating its entities would be unmanageable. ChromaDB chunks are the
wrong unit too: they split mid-topic, so an entity introduced in one chunk and
located in the next becomes two partial extractions that the least-certain part
of the pipeline has to merge. Sections split where the book's own author put a
heading, which mostly keeps related facts together.

Two splitters live here, chosen by the caller:

* ``depth`` (default) splits on the document's own heading depth and then
  subdivides any section too large for one extraction pass. It is the one that
  travels: it knows nothing about Curse of Strahd.
* ``key`` splits on a keyed heading at any level. It exists for the retired
  vision transcription, whose heading levels were assigned essentially at
  random, and as the A/B baseline. It is Curse of Strahd-specific by
  construction -- Xanathar's Guide and the Monster Manual key nothing.
"""

import logging
import re
from dataclasses import dataclass

import tiktoken

from backend.canon.models import Chapter, ExtractionUnit, Section

logger = logging.getLogger(__name__)

# "E1. Bildrath's Mercantile", "E5g. Undercroft", "K18a. High Tower Shaft",
# "G. Tser Pool Encampment". A letter prefix is required: the book's only
# bare-number keys are chapter 1's Tarokka card list and Appendix B's Death
# House rooms, neither of which names a physical room. `stem`/`suffix` split
# "E5g" into the parent area "E5" and its sub-area letter.
#
# A BARE LETTER IS A KEY TOO, and requiring a digit silently cost a whole
# chapter. This read `[A-Z]\d+`, written to exclude bare NUMBERS -- and it
# excluded bare LETTERS with them. Chapter 2 is the overland map and keys its
# areas `A.` through `Z.`, one per region, because there are fewer than
# twenty-six of them; every other chapter maps an interior and keys
# letter-plus-number. So `the-lands-of-barovia` was the only chapter in the
# book with ZERO keyed places minted, and `G. Tser Pool Encampment` -- where
# Madam Eva reads the cards -- had no entity at all.
#
# The bare-letter branch requires the dot IMMEDIATELY, via lookahead. Without
# it `[A-Z]\d*` also matches `St. Andral's Feast` as stem `S` suffix `t`, which
# is the one false positive in the corpus's 1,063 headings. A sub-area letter
# only makes sense under a numbered parent, and the lookahead says so.
KEYED_HEADING = re.compile(
    r"^(?P<stem>[A-Z]\d+|[A-Z](?=\.))(?P<suffix>[a-z])?\.\s*(?P<name>.+)$"
)

# H1 to H6. The vision transcription emitted exactly one H5 in the whole corpus
# and no H6; D&D Beyond emits H5 in four chapters. Neither is ever a keyed
# heading, so widening this from the old `{1,4}` cannot move the key splitter --
# `_is_key_split_point` only ever answers yes for `##` or for keyed text.
_HEADING = re.compile(r"^(#{1,6})\s+(?!#)(.+?)\s*$", re.MULTILINE)

PREAMBLE_HEADING = "(preamble)"

SPLITTERS = ("depth", "key")

# How much text one extraction unit may hold, in tokens. DERIVED, not chosen:
# measured over the 25-chapter D&D Beyond corpus,
#
#   * p99 of the 789 authored *leaf* bodies (a heading with no sub-headings, so
#     everything under it is one authored body) is 1017 tokens;
#   * p95 of the 974 authored *area* spans (a heading plus at most one level of
#     detail sub-headings -- "K7. Chapel" with its "Treasure") is 934 tokens.
#
# Two independent statistics land on the same round number, so a section larger
# than 1000 tokens is holding more than one authored area's worth of text by the
# book's own measure, and is subdividable by construction.
#
# The 1500 in the deleted `pack_sections` was arbitrary and is not the ancestor
# of this number. Nor is the mechanism the same: `pack_sections` COMBINED
# sections into one unit, which made `_parse` stamp every candidate with the
# first section's heading. Refinement here only ever makes units smaller, and
# every subsection keeps its own heading, depth and index -- provenance gets
# strictly finer, never coarser.
EXTRACTION_BUDGET_TOKENS = 1000

# What fraction of a depth's headings must already fit the budget for that depth
# to be the area depth. Three quarters: "most sections are already the right
# size, and refinement handles the tail". Sensitivity is reported by
# `depth_table` rather than assumed away.
_FIT_FRACTION = 0.75

_encoder = tiktoken.encoding_for_model("gpt-4")


def _count(text: str) -> int:
    return len(_encoder.encode(text))


@dataclass
class _Heading:
    depth: int
    text: str
    start: int
    span_end: int


@dataclass
class SplitResult:
    """Sections plus what the splitter had to do to get them.

    The counts are not decoration. `area_depth` silently landing one level wrong
    on one chapter is the failure this design is most exposed to, and
    `unsplittable` is its other failure mode -- a section over budget with no
    deeper heading to cut at, which is left whole rather than truncated.
    """

    sections: list[Section]
    area_depth: int
    depth_qualified: bool
    before_refinement: int
    subdivided: int
    unsplittable: int


def _headings(markdown: str) -> list[_Heading]:
    """Every heading, with the end of the subtree it encloses.

    `span_end` is the next heading at the same depth or shallower, so a
    heading's span is the heading plus everything nested under it -- which is
    what a section would hold if the split stopped at that depth.
    """
    matches = list(_HEADING.finditer(markdown))
    out: list[_Heading] = []
    for i, match in enumerate(matches):
        depth = len(match.group(1))
        span_end = len(markdown)
        for j in range(i + 1, len(matches)):
            if len(matches[j].group(1)) <= depth:
                span_end = matches[j].start()
                break
        out.append(_Heading(depth, match.group(2).strip(), match.start(), span_end))
    return out


def depth_table(
    markdown: str, budget: int = EXTRACTION_BUDGET_TOKENS
) -> list[tuple[int, int, int]]:
    """`(depth, headings at that depth, how many of their spans fit the budget)`.

    The evidence behind `area_depth`'s answer, so a wrong answer is legible
    rather than a bare integer.
    """
    rows: dict[int, list[int]] = {}
    for heading in _headings(markdown):
        rows.setdefault(heading.depth, []).append(
            _count(markdown[heading.start:heading.span_end])
        )
    return [
        (depth, len(spans), sum(1 for size in spans if size <= budget))
        for depth, spans in sorted(rows.items())
    ]


def area_depth(markdown: str, budget: int = EXTRACTION_BUDGET_TOKENS) -> int:
    """The heading depth at which this chapter's areas sit.

    **The shallowest depth at which at least three quarters of the headings'
    spans already fit one extraction pass.** A chapter-organising heading
    ("Areas of the Village", "Main Floor") encloses every area under it, so its
    span is several areas wide and blows the budget; an area's span is one area
    wide and does not. That is the difference the rule reads, and it is a
    property of documents rather than of Curse of Strahd -- nothing here knows
    what an `E5` is.

    Deriving it beats hardcoding `h3` because `h3` is a fact about how this one
    book renders. Measured across the 25 DDB chapters this rule returns h3 for
    18, and the seven it does not are reported rather than smoothed over.

    Falls back to the deepest depth present when nothing qualifies, and says so
    loudly -- `SplitResult.depth_qualified` is False and a warning is logged.
    Raising instead would take out Foreword and Credits, single-heading chapters
    whose one span exceeds the budget and cannot be cut anywhere.
    """
    table = depth_table(markdown, budget)
    if not table:
        return 1
    for depth, total, fits in table:
        if fits >= total * _FIT_FRACTION:
            return depth
    return table[-1][0]


def _is_key_split_point(match: re.Match[str]) -> bool:
    """A heading that starts its own section under the `key` splitter.

    A heading whose text is keyed (`E4. Burgomaster's Mansion`) starts a section
    **at any level**: the vision transcription assigned levels essentially at
    random, emitting the same kind of keyed room as H1, H2, H3 and H4 within one
    chapter, so an H2-only rule lost roughly 60% of the book's keyed areas.
    Second, an unkeyed `##` still starts a prose section.

    An unkeyed H1 deliberately does NOT split: the assembler finds chapter
    boundaries on chapter-title H1s, and the page's running header is
    transcribed at H1 too. An unkeyed H3/H4 stays inside its section, which is
    what keeps Appendix D's 37 stat-block sub-headings out of the unit list.
    """
    return len(match.group(1)) == 2 or KEYED_HEADING.match(match.group(2)) is not None


def _key_pieces(markdown: str) -> list[tuple[int, str, str]]:
    """`(depth, heading, body)` for the key splitter.

    Depth is reported as 0 -- *unknown* -- for every section, and that is a
    claim, not a placeholder. Heading level in the transcription this splitter
    serves is noise, so publishing it would invite `structure.py` to derive
    containment from a random number.
    """
    matches = [m for m in _HEADING.finditer(markdown) if _is_key_split_point(m)]
    pieces: list[tuple[int, str, str]] = []

    first_start = matches[0].start() if matches else len(markdown)
    preamble = markdown[:first_start].strip()
    if preamble:
        pieces.append((0, PREAMBLE_HEADING, preamble))

    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(markdown)
        pieces.append((0, match.group(2).strip(), markdown[match.start():end].strip()))
    return pieces


def _refine(
    depth: int, heading: str, body: str, budget: int
) -> tuple[list[tuple[int, str, str]], int, int]:
    """Subdivide one over-budget section at the shallowest heading inside it.

    Recursive, so a section holding three levels of nesting keeps being cut
    until each piece fits or runs out of headings. The head piece -- the
    heading's own prose, before its first sub-heading -- is always emitted even
    when it is bare, because dropping it would orphan its children: a keyed area
    with an empty body is still the place that contains its sub-areas, and
    losing it would silently reattach them to the chapter.

    Returns the pieces, how many sections were subdivided, and how many were
    over budget with nowhere to cut.
    """
    if _count(body) <= budget:
        return [(depth, heading, body)], 0, 0

    inner = [m for m in _HEADING.finditer(body) if m.start() > 0]
    if not inner:
        # The failure mode, surfaced rather than truncated. A unit over budget
        # still extracts; it just does so less reliably than one that fits.
        return [(depth, heading, body)], 0, 1

    next_depth = min(len(m.group(1)) for m in inner)
    cuts = [m for m in inner if len(m.group(1)) == next_depth]

    pieces: list[tuple[int, str, str]] = [(depth, heading, body[:cuts[0].start()].rstrip())]
    subdivided, unsplittable = 1, 0
    for i, match in enumerate(cuts):
        end = cuts[i + 1].start() if i + 1 < len(cuts) else len(body)
        sub, sub_divided, sub_stuck = _refine(
            next_depth, match.group(2).strip(), body[match.start():end].strip(), budget
        )
        pieces.extend(sub)
        subdivided += sub_divided
        unsplittable += sub_stuck
    return pieces, subdivided, unsplittable


def _depth_pieces(
    markdown: str, budget: int
) -> tuple[list[tuple[int, str, str]], int, bool, int, int, int]:
    """`(pieces, area_depth, qualified, before_refinement, subdivided, unsplittable)`."""
    table = depth_table(markdown, budget)
    depth = area_depth(markdown, budget)
    qualified = any(d == depth and fits >= total * _FIT_FRACTION for d, total, fits in table)

    tops = [h for h in _headings(markdown) if h.depth <= depth]
    coarse: list[tuple[int, str, str]] = []

    first_start = tops[0].start if tops else len(markdown)
    preamble = markdown[:first_start].strip()
    if preamble:
        coarse.append((0, PREAMBLE_HEADING, preamble))

    for i, heading in enumerate(tops):
        end = tops[i + 1].start if i + 1 < len(tops) else len(markdown)
        coarse.append((heading.depth, heading.text, markdown[heading.start:end].strip()))

    pieces: list[tuple[int, str, str]] = []
    subdivided = unsplittable = 0
    for piece_depth, heading, body in coarse:
        refined, divided, stuck = _refine(piece_depth, heading, body, budget)
        pieces.extend(refined)
        subdivided += divided
        unsplittable += stuck
    return pieces, depth, qualified, len(coarse), subdivided, unsplittable


def _parents(depths: list[int]) -> list[int]:
    """For each section, the index of the nearest enclosing section.

    Nesting, and nothing else: the preceding section at a strictly shallower
    depth. Depth 0 means "unknown" (the preamble, and every key-split section),
    and an unknown depth neither has a parent nor can be one -- a splitter that
    cannot vouch for its levels must not have containment derived from them.
    """
    parents: list[int] = []
    stack: list[tuple[int, int]] = []  # (depth, index)
    for index, depth in enumerate(depths):
        if depth <= 0:
            parents.append(-1)
            continue
        while stack and stack[-1][0] >= depth:
            stack.pop()
        parents.append(stack[-1][1] if stack else -1)
        stack.append((depth, index))
    return parents


def split_chapter(
    chapter: Chapter,
    *,
    splitter: str = "depth",
    budget: int = EXTRACTION_BUDGET_TOKENS,
) -> SplitResult:
    """Split a chapter into sections, and report how the split went."""
    if splitter not in SPLITTERS:
        raise ValueError(f"unknown splitter {splitter!r}; expected one of {SPLITTERS}")

    if not chapter.markdown.strip():
        return SplitResult([], 1, True, 0, 0, 0)

    if splitter == "key":
        pieces = _key_pieces(chapter.markdown)
        depth, qualified, before, subdivided, unsplittable = 0, True, len(pieces), 0, 0
    else:
        pieces, depth, qualified, before, subdivided, unsplittable = _depth_pieces(
            chapter.markdown, budget
        )
        if not qualified:
            logger.warning(
                "%s: no heading depth had %.0f%% of its spans inside the %d-token budget; "
                "falling back to the deepest depth present (h%d). Sections may be too large.",
                chapter.slug, _FIT_FRACTION * 100, budget, depth,
            )

    parents = _parents([piece_depth for piece_depth, _, _ in pieces])
    sections = [
        Section(
            chapter_slug=chapter.slug,
            chapter_title=chapter.title,
            heading=heading,
            index=index,
            markdown=body,
            depth=piece_depth,
            parent_index=parents[index],
        )
        for index, (piece_depth, heading, body) in enumerate(pieces)
    ]
    return SplitResult(sections, depth, qualified, before, subdivided, unsplittable)


def split_sections(
    chapter: Chapter,
    *,
    splitter: str = "depth",
    budget: int = EXTRACTION_BUDGET_TOKENS,
) -> list[Section]:
    """Split a chapter's markdown into sections.

    Text before the first heading becomes a `(preamble)` section, since chapter
    introductions carry real content and would otherwise be dropped.
    """
    return split_chapter(chapter, splitter=splitter, budget=budget).sections


def units_from_sections(sections: list[Section]) -> list[ExtractionUnit]:
    """One extraction unit per section, so a candidate's provenance is exact.

    Packing several sections into one call saves a few cents across the corpus
    and costs the ability to say which section a candidate came from -- which
    structural derivation and stage 2b's resolution both depend on. At
    gpt-4o-mini prices that is a bad trade.
    """
    return [
        ExtractionUnit(
            chapter_slug=s.chapter_slug,
            chapter_title=s.chapter_title,
            heading=s.heading,
            section_index=s.index,
            markdown=s.markdown,
            token_count=_count(s.markdown),
        )
        for s in sections
    ]
