"""Stage 2: group page transcripts into chapters by H1 headings."""

import re

from backend.canon.models import Chapter, PageTranscript

H1_PATTERN = re.compile(r"^#\s+(?!#)(.+?)\s*$", re.MULTILINE)

CHAPTER_KEY_PATTERN = re.compile(
    r"^(chapter\s+\d+|appendix\s+[a-z]\b|introduction|prologue|epilogue|foreword)",
    re.IGNORECASE,
)


def _chapter_key(title: str) -> str | None:
    """Normalized identity of the chapter a heading names, or None if not a chapter.

    The same chapter renders differently in body headings and running headers —
    "Chapter 4: Castle Ravenloft" versus "Chapter 4 | Castle Ravenloft" — and
    apostrophes vary between straight and curly. Reducing both to "chapter 4"
    makes those the same chapter rather than two.
    """
    match = CHAPTER_KEY_PATTERN.match(title.strip())
    if match is None:
        return None
    return re.sub(r"\s+", " ", match.group(1).strip().lower())


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
        key = _chapter_key(title) if title is not None else None
        starts_new_chapter = key is not None and (
            current is None or current.get("key") != key
        )

        if starts_new_chapter:
            if current is not None:
                chapters.append(_finish(current))
            current = {
                "title": title,
                "key": key,
                "start_page": transcript.page_number,
                "end_page": transcript.page_number,
                "parts": [transcript.markdown.strip()],
            }
            continue

        if current is None:
            current = {
                "title": "Front Matter",
                "key": None,
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
