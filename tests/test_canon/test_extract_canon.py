"""Tests for the extract_canon CLI script's chapter_place heuristic.

A chapter's title is not by itself evidence that it describes a place: chapter
1 keys Tarokka card results ("1. The Tome of Strahd"), not rooms, and treating
its title as a containing place would invent one for cards and people. Only a
chapter with at least one letter-keyed section -- a genuine keyed room -- is
trusted to be about a physical place.
"""

from backend.canon.models import Chapter
from backend.canon.sections import split_sections
from backend.canon.structure import structural_edges
from backend.scripts.extract_canon import chapter_place


def chapter(slug: str, title: str, markdown: str) -> Chapter:
    return Chapter(slug=slug, title=title, start_page=1, end_page=2, markdown=markdown)


class TestChapterPlace:
    def test_a_card_style_chapter_yields_no_place(self):
        """Chapter 1's bare-number keys name Tarokka cards, not rooms."""
        ch1 = chapter(
            "chapter-1-into-the-mists",
            "Chapter 1: Into the Mists",
            "## 1. The Tome of Strahd\n\nBody.\n\n"
            "## 2. The Holy Symbol of Ravenkind\n\nBody.\n\n"
            "## 5. Strahd\n\nBody.",
        )
        sections = split_sections(ch1)

        assert chapter_place(ch1, sections) is None

    def test_a_card_style_chapter_yields_no_contains_edges(self):
        """No place means structural_edges must not invent a CONTAINS parent,
        even when the chapter DOES have a keyed section -- otherwise this only
        proves the unrelated by-heading None guard (every section is unkeyed),
        not the chapter_place guard itself. This is the exact anti-fabrication
        property Task 6 exists for."""
        ch1 = chapter(
            "chapter-1-into-the-mists",
            "Chapter 1: Into the Mists",
            "## E1. A Keyed Area\n\nBody.",
        )
        sections = split_sections(ch1)

        edges = structural_edges(sections, [], None)

        assert [e for e in edges if e.rel_type == "CONTAINS"] == []

    def test_a_letter_keyed_chapter_still_has_a_place(self):
        ch3 = chapter(
            "chapter-3-the-village-of-barovia",
            "Chapter 3: The Village of Barovia",
            "## E1. Bildrath's Mercantile\n\nBody.",
        )
        sections = split_sections(ch3)

        assert chapter_place(ch3, sections) == "The Village of Barovia"

    def test_an_appendix_with_no_keyed_sections_yields_none(self):
        appendix = chapter(
            "appendix-d-npcs",
            "Appendix D: NPCs",
            "## Baba Lysaga\n\nBody.",
        )
        sections = split_sections(appendix)

        assert chapter_place(appendix, sections) is None
