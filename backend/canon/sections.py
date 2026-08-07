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

# H2 only. An H3 sub-heading belongs with its section rather than beside it.
_H2 = re.compile(r"^##\s+(?!#)(.+?)\s*$", re.MULTILINE)

PREAMBLE_HEADING = "(preamble)"
DEFAULT_MAX_TOKENS = 1500

_encoder = tiktoken.encoding_for_model("gpt-4")


def _count(text: str) -> int:
    return len(_encoder.encode(text))


def split_sections(chapter: Chapter) -> list[Section]:
    """Split a chapter's markdown on its `##` headings.

    Text before the first heading becomes a `(preamble)` section, since chapter
    introductions carry real content and would otherwise be dropped.
    """
    if not chapter.markdown.strip():
        return []

    matches = list(_H2.finditer(chapter.markdown))
    pieces: list[tuple[str, str]] = []

    first_start = matches[0].start() if matches else len(chapter.markdown)
    preamble = chapter.markdown[:first_start].strip()
    if preamble:
        pieces.append((PREAMBLE_HEADING, preamble))

    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(chapter.markdown)
        body = chapter.markdown[match.start():end].strip()
        pieces.append((match.group(1).strip(), body))

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
            headings=[s.heading],
            markdown=s.markdown,
            token_count=_count(s.markdown),
        )
        for s in sections
    ]


def pack_sections(
    sections: list[Section],
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> list[ExtractionUnit]:
    """Group contiguous sections into units under a token budget.

    Section sizes vary by two orders of magnitude, so one-call-per-section would
    waste calls on 14-token stubs. A section larger than the budget stands alone
    rather than being split -- splitting mid-section is what this design avoids.
    """
    units: list[ExtractionUnit] = []
    batch: list[Section] = []
    batch_tokens = 0

    def flush() -> None:
        nonlocal batch, batch_tokens
        if not batch:
            return
        units.append(
            ExtractionUnit(
                chapter_slug=batch[0].chapter_slug,
                chapter_title=batch[0].chapter_title,
                headings=[s.heading for s in batch],
                markdown="\n\n".join(s.markdown for s in batch),
                token_count=batch_tokens,
            )
        )
        batch = []
        batch_tokens = 0

    for section in sections:
        tokens = _count(section.markdown)
        if batch and batch_tokens + tokens > max_tokens:
            flush()
        batch.append(section)
        batch_tokens += tokens
        if batch_tokens >= max_tokens:
            flush()

    flush()
    return units
