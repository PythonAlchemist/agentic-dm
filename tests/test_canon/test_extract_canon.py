"""Tests for the extract_canon CLI script's chapter_place heuristic.

A chapter's title is not by itself evidence that it describes a place: chapter
1 keys Tarokka card results ("1. The Tome of Strahd"), not rooms, and treating
its title as a containing place would invent one for cards and people. Only a
chapter with at least one letter-keyed section -- a genuine keyed room -- is
trusted to be about a physical place.

There is deliberately NO end-to-end "a card-style chapter yields no CONTAINS
edges" case here. `chapter_place` returns None exactly when no section is keyed,
and `structural_edges` emits a CONTAINS only for a keyed section, so the two
guards are logically coupled: any fixture that reaches structural_edges with a
None place is a fixture where the per-section guard already suppresses CONTAINS
on its own. The test that used to sit here asserted that composition and passed
with the `chapter_place` guard deleted, whichever fixture it was given. The
guard is covered by the two `is None` cases below (both fail when it is deleted)
and structural_edges' own handling of a None place by
test_structure.py::TestStructuralEdges::test_no_chapter_place_means_no_contains_edges.
"""

from backend.canon.models import Chapter
from backend.canon.sections import split_sections
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
