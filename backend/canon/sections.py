"""Split a chapter into units small enough to extract from in one pass.

A whole chapter is too large -- Castle Ravenloft is ~36k tokens, and a single
response enumerating its entities would be unmanageable. ChromaDB chunks are the
wrong unit too: they split mid-topic, so an entity introduced in one chunk and
located in the next becomes two partial extractions that the least-certain part
of the pipeline has to merge. Sections split where the book's own author put a
heading, which mostly keeps related facts together.
"""

import re

import tiktoken

from backend.canon.models import Chapter, ExtractionUnit, Section

# "E1. Bildrath's Mercantile", "E5g. Undercroft", "K18a. High Tower Shaft".
# A letter prefix is required: the book's only bare-number keys are chapter 1's
# Tarokka card list and Appendix B's Death House rooms, neither of which names a
# physical room. `stem`/`suffix` split "E5g" into the parent area "E5" and its
# sub-area letter, which is the containment hierarchy the transcription lost.
#
# Defined here, not in structure.py, because both modules need it and this is
# the lower layer: structure.py consumes Sections, sections.py consumes nothing
# of structure.py's. One definition, imported -- two regexes that must agree is
# a defect waiting to happen.
KEYED_HEADING = re.compile(r"^(?P<stem>[A-Z]\d+)(?P<suffix>[a-z])?\.\s*(?P<name>.+)$")

# Any level from H1 to H4. Level carries no signal in this transcription -- the
# same keyed room appears as H1, H2, H3 and H4 -- so the filter is applied to
# the heading TEXT below, not to its depth.
_HEADING = re.compile(r"^(#{1,4})\s+(?!#)(.+?)\s*$", re.MULTILINE)

PREAMBLE_HEADING = "(preamble)"

_encoder = tiktoken.encoding_for_model("gpt-4")


def _count(text: str) -> int:
    return len(_encoder.encode(text))


def _is_split_point(match: re.Match[str]) -> bool:
    """A heading that starts its own section.

    Two rules, and the first is the one that matters. A heading whose text is
    keyed (`E4. Burgomaster's Mansion`) starts a section **at any level**: the
    vision transcription assigned levels essentially at random, emitting the
    same kind of keyed room as H1, H2, H3 and H4 within one chapter, so an
    H2-only rule lost roughly 60% of the book's keyed areas -- silently, as
    sections that were never proposed rather than as anything a diagnostic
    could show. Second, an unkeyed `##` still starts a prose section, as it
    always has.

    An unkeyed H1 deliberately does NOT split: the assembler finds chapter
    boundaries on chapter-title H1s, and the page's running header is
    transcribed at H1 too, so splitting there would mint sections for neither.
    An unkeyed H3/H4 stays inside its section, which is what keeps Appendix D's
    37 stat-block sub-headings ("Actions", "Reactions") from becoming 37 units.
    """
    return len(match.group(1)) == 2 or KEYED_HEADING.match(match.group(2)) is not None


def split_sections(chapter: Chapter) -> list[Section]:
    """Split a chapter's markdown on its keyed headings and its `##` headings.

    Text before the first heading becomes a `(preamble)` section, since chapter
    introductions carry real content and would otherwise be dropped.
    """
    if not chapter.markdown.strip():
        return []

    matches = [m for m in _HEADING.finditer(chapter.markdown) if _is_split_point(m)]
    pieces: list[tuple[str, str]] = []

    first_start = matches[0].start() if matches else len(chapter.markdown)
    preamble = chapter.markdown[:first_start].strip()
    if preamble:
        pieces.append((PREAMBLE_HEADING, preamble))

    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(chapter.markdown)
        body = chapter.markdown[match.start():end].strip()
        pieces.append((match.group(2).strip(), body))

    return [
        Section(
            chapter_slug=chapter.slug,
            chapter_title=chapter.title,
            heading=heading,
            index=i,
            markdown=body,
        )
        for i, (heading, body) in enumerate(pieces)
    ]


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
