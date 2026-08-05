"""Stage 2: group page transcripts into chapters by H1 headings."""

import re

from backend.canon.models import Chapter, PageTranscript

H1_PATTERN = re.compile(r"^#\s+(?!#)(.+?)\s*$", re.MULTILINE)


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

        if heading is not None:
            if current is not None:
                chapters.append(_finish(current))
            current = {
                "title": heading.group(1).strip(),
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
    """Ensure slugs are unique by suffixing repeats with -2, -3, ..."""
    seen: dict[str, int] = {}
    for chapter in chapters:
        seen[chapter.slug] = seen.get(chapter.slug, 0) + 1
        if seen[chapter.slug] > 1:
            chapter.slug = f"{chapter.slug}-{seen[chapter.slug]}"
    return chapters
