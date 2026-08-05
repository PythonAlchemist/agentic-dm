"""Stage 2: group page transcripts into chapters by H1 headings."""

import re

from backend.canon.models import Chapter, PageTranscript

H1_PATTERN = re.compile(r"^#\s+(?!#)(.+?)\s*$", re.MULTILINE)

CHAPTER_HEADING_PATTERN = re.compile(
    r"^(?:chapter\s+\d+|appendix\s+[a-z]\b|introduction|prologue|epilogue|foreword)",
    re.IGNORECASE,
)


def _is_chapter_heading(title: str) -> bool:
    """True if an H1 names a real chapter rather than a section or map label.

    Transcribed pages emit H1s for things that are not chapters — location keys,
    area names, running headers. Only titles matching a book's chapter vocabulary
    start a new chapter.
    """
    return CHAPTER_HEADING_PATTERN.match(title.strip()) is not None


def slugify(title: str) -> str:
    """Turn a chapter title into a URL-safe slug."""
    slug = title.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")


def assemble_chapters(transcripts: list[PageTranscript]) -> list[Chapter]:
    """Group consecutive pages into chapters, splitting at each H1 heading.

    Pages appearing before the first heading are collected as "front-matter".
    Failed transcripts are skipped; their text is simply absent.
    """
    usable = [t for t in transcripts if t.status == "ok" and t.markdown.strip()]
    if not usable:
        return []

    chapters: list[Chapter] = []
    current: dict | None = None

    for transcript in usable:
        heading = H1_PATTERN.search(transcript.markdown)
        title = heading.group(1).strip() if heading is not None else None
        starts_new_chapter = (
            title is not None
            and _is_chapter_heading(title)
            and (current is None or current["title"] != title)
        )

        if starts_new_chapter:
            if current is not None:
                chapters.append(_finish(current))
            current = {
                "title": title,
                "start_page": transcript.page_number,
                "end_page": transcript.page_number,
                "parts": [transcript.markdown.strip()],
            }
            continue

        if current is None:
            current = {
                "title": "Front Matter",
                "start_page": transcript.page_number,
                "end_page": transcript.page_number,
                "parts": [transcript.markdown.strip()],
            }
            continue

        current["parts"].append(transcript.markdown.strip())
        current["end_page"] = transcript.page_number

    if current is not None:
        chapters.append(_finish(current))

    return _disambiguate(chapters)


def _finish(pending: dict) -> Chapter:
    return Chapter(
        slug=slugify(pending["title"]),
        title=pending["title"],
        start_page=pending["start_page"],
        end_page=pending["end_page"],
        markdown="\n\n".join(pending["parts"]),
    )


def _disambiguate(chapters: list[Chapter]) -> list[Chapter]:
    """Ensure slugs are unique, tracking the slugs actually emitted."""
    used: set[str] = set()
    for chapter in chapters:
        base = chapter.slug
        candidate = base
        suffix = 1
        while candidate in used:
            suffix += 1
            candidate = f"{base}-{suffix}"
        used.add(candidate)
        chapter.slug = candidate
    return chapters
