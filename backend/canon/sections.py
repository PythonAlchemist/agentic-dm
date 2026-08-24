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

#: A heading's leading token, whatever shape it has. PERMISSIVE ON PURPOSE: the
#: shape of a key is what varies between books, so this parses and `KeyScheme`
#: decides. It matches `St. Andral's Feast` too, and that is fine -- nothing
#: consults it without a scheme.
#:
#: THE SEPARATOR VARIES TOO, and hardcoding the period cost a whole book.
#: Curse of Strahd heads `K61a. Empty Cell`; Keys from the Golden Vault heads
#: `V1: Grand Entrance`. Against a period-only pattern, ZERO of that book's
#: forty-three sections parsed as keyed, so it derived no containment at all --
#: and containment is the only relationship type this corpus has any DERIVED
#: edges for. An entire book would have been extractor guesswork end to end
#: because of one character.
#:
#: Loosening this cannot loosen what counts as a key: `KeyScheme` still admits
#: only the shapes the book's own `area XX` cross-references attest, so a
#: heading like `Note: something` parses here and is refused there.
KEY_PREFIX = re.compile(r"^(?P<key>[^\s.:]{1,4})[.:]\s+(?P<name>\S.*)$")

#: How the book refers to its own keys. A key exists SO THAT the book can point
#: at it, which is why this is the evidence a scheme is inferred from.
_AREA_REFERENCE = re.compile(
    r"\b(?:area|areas|room|rooms)\s+(?P<key>[A-Za-z][0-9]{0,2}[a-z]?|[0-9]{1,3}[A-Za-z]?)\b"
)

#: A token ending in a letter is a SUB-area of the number before it -- `E5g`
#: under `E5`, `23A` under `23`. A token with no digits has no sub-area to be:
#: `G` is a whole region, not `G` suffixed onto nothing.
_SUBAREA = re.compile(r"^(?P<stem>.*[0-9])(?P<suffix>[A-Za-z])$")


def key_shape(token: str) -> str:
    """`K85` -> `A#`, `E5g` -> `A#a`, `G` -> `A`, `21` -> `#`, `St` -> `Aa`.

    Runs collapse, so `K85` and `K3` are one shape and a book that refers to
    either covers both. This is the whole of what "the same kind of key" means.
    """
    kinds: list[str] = []
    for character in token:
        kind = "#" if character.isdigit() else ("A" if character.isupper() else "a")
        if not kinds or kinds[-1] != kind:
            kinds.append(kind)
    return "".join(kinds)


@dataclass(frozen=True)
class KeyedHeading:
    """A heading parsed under a scheme: `E5g. Undercroft`."""

    key: str
    stem: str
    suffix: str
    name: str


@dataclass(frozen=True)
class KeyScheme:
    r"""Which leading tokens this book treats as area keys.

    INFERRED, NOT SPELLED OUT, and that is the whole point. The regex this
    replaces enumerated Curse of Strahd's three conventions -- `[A-Z]\d+` for
    interior maps, a bare letter for the overland map, bare numbers for Death
    House -- as alternatives in one pattern. Three special cases for one book,
    and every other book brings its own. A heading prefix is a formatting
    choice by an author, and a formatting choice must not decide whether the
    pipeline can see a room.

    What is general is WHY a key exists: so the book can point at it. Every
    keyed map is cross-referenced, or the keys would be decoration. So the book
    says which prefixes are keys, by writing "area E6", "area 21", "room K85",
    and `infer` reads that back.

    Membership is by SHAPE rather than by the literal keys referenced. Testing
    each heading against the referenced set was tried and lost 161 real rooms:
    `Q22. Bathroom` is a room nothing happens to point at. The references are
    evidence about the shape of this chapter's keys, not about which rooms
    matter.
    """

    shapes: frozenset[str]

    def match(self, heading: str) -> KeyedHeading | None:
        """The heading's key and name, or `None` if it carries no key."""
        found = KEY_PREFIX.match(heading.strip())
        if not found or key_shape(found.group("key")) not in self.shapes:
            return None
        token = found.group("key")
        sub = _SUBAREA.match(token)
        stem = sub.group("stem") if sub else token
        suffix = sub.group("suffix") if sub else ""
        return KeyedHeading(
            key=f"{stem}{suffix}".lower(),
            stem=stem,
            suffix=suffix,
            name=found.group("name").strip(),
        )

    @classmethod
    def infer(cls, text: str) -> "KeyScheme":
        """Read a chapter's key shapes out of its own cross-references.

        A chapter that refers to nothing yields an EMPTY scheme and therefore
        no keyed headings, which is the honest answer: a book that never points
        at its rooms has given no evidence that its heading prefixes are keys
        rather than numbering.
        """
        return cls(
            frozenset(
                key_shape(m.group("key")) for m in _AREA_REFERENCE.finditer(text)
            )
        )


#: Curse of Strahd's shapes, as the hand-written regex enumerated them. Kept so
#: a caller with no chapter text in hand behaves exactly as before, and so the
#: equivalence between the two is a test rather than a claim.
LEGACY_SCHEME = KeyScheme(frozenset({"A#", "A#a", "A"}))

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
    return len(match.group(1)) == 2 or LEGACY_SCHEME.match(match.group(2)) is not None


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
