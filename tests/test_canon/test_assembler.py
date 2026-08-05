"""Tests for grouping page transcripts into chapters."""

from backend.canon.assembler import assemble_chapters, slugify
from backend.canon.models import PageTranscript


def page(n: int, markdown: str) -> PageTranscript:
    return PageTranscript(page_number=n, markdown=markdown, image_sha256="x" * 64, model="gpt-4o")


class TestSlugify:
    def test_lowercases_and_hyphenates(self):
        assert slugify("Chapter 3: The Village of Barovia") == "chapter-3-the-village-of-barovia"

    def test_strips_punctuation_and_collapses_separators(self):
        result = slugify("Appendix A -- Fortunes  of Ravenloft!")
        assert result == "appendix-a-fortunes-of-ravenloft"


class TestAssembleChapters:
    def test_groups_pages_under_headings(self):
        chapters = assemble_chapters(
            [
                page(1, "# Introduction\n\nIntro text."),
                page(2, "More intro."),
                page(3, "# Chapter 1: Into the Mists\n\nMist text."),
                page(4, "More mist."),
            ]
        )

        assert [c.title for c in chapters] == ["Introduction", "Chapter 1: Into the Mists"]
        assert chapters[0].start_page == 1
        assert chapters[0].end_page == 2
        assert chapters[1].start_page == 3
        assert chapters[1].end_page == 4
        assert "More mist." in chapters[1].markdown

    def test_pages_before_first_heading_become_front_matter(self):
        chapters = assemble_chapters([page(1, "Cover art."), page(2, "# Introduction\n\nText.")])

        assert chapters[0].slug == "front-matter"
        assert chapters[0].start_page == 1
        assert chapters[1].title == "Introduction"

    def test_failed_pages_are_skipped(self):
        bad = page(2, "")
        bad.status = "failed"
        chapters = assemble_chapters([page(1, "# Intro\n\nA."), bad, page(3, "C.")])

        assert len(chapters) == 1
        assert chapters[0].end_page == 3
        assert "C." in chapters[0].markdown

    def test_empty_input_returns_empty_list(self):
        assert assemble_chapters([]) == []

    def test_duplicate_titles_get_distinct_slugs(self):
        """Two non-adjacent chapters sharing a title still get distinct slugs.

        Adjacent same-titled pages now merge (running-header fix), so the duplicate
        must be separated by a different intervening chapter to reach _disambiguate
        as two separate chapters at all.
        """
        chapters = assemble_chapters(
            [
                page(1, "# Chapter 5: Areas of the Keep\n\nA."),
                page(2, "# Chapter 6: The Undercroft\n\nB."),
                page(3, "# Chapter 5: Areas of the Keep\n\nC."),
            ]
        )

        assert [c.slug for c in chapters] == [
            "chapter-5-areas-of-the-keep",
            "chapter-6-the-undercroft",
            "chapter-5-areas-of-the-keep-2",
        ]

    def test_disambiguation_avoids_collision_with_pre_suffixed_title(self):
        """A literal title matching an auto-generated suffix must not collide with it.

        The fourth chapter's own slug ("...-2") equals the suffix _disambiguate will
        already have assigned to the third chapter's duplicate title, so this exercises
        the walk-forward collision avoidance rather than the first-bump case.
        """
        chapters = assemble_chapters(
            [
                page(1, "# Chapter 5: Areas of the Keep\n\nA."),
                page(2, "# Chapter 6: The Undercroft\n\nB."),
                page(3, "# Chapter 5: Areas of the Keep\n\nC."),
                page(4, "# Chapter 5: Areas of the Keep 2\n\nD."),
            ]
        )

        slugs = [c.slug for c in chapters]
        assert len(slugs) >= 3, f"expected the collision scenario to reach 3+ chapters, got {slugs}"
        assert len(slugs) == len(set(slugs)), f"expected distinct slugs, got {slugs}"

    def test_three_identical_titles_get_sequential_slugs(self):
        """Three non-adjacent chapters sharing a title get sequential suffixes."""
        chapters = assemble_chapters(
            [
                page(1, "# Chapter 5: Areas of the Keep\n\nA."),
                page(2, "# Chapter 6: The Undercroft\n\nB."),
                page(3, "# Chapter 5: Areas of the Keep\n\nC."),
                page(4, "# Chapter 7: The Old Barracks\n\nD."),
                page(5, "# Chapter 5: Areas of the Keep\n\nE."),
            ]
        )

        assert [c.slug for c in chapters] == [
            "chapter-5-areas-of-the-keep",
            "chapter-6-the-undercroft",
            "chapter-5-areas-of-the-keep-2",
            "chapter-7-the-old-barracks",
            "chapter-5-areas-of-the-keep-3",
        ]


class TestChapterBoundaryDetection:
    def test_non_chapter_h1_does_not_start_a_chapter(self):
        """A location key or map label is not a chapter boundary."""
        chapters = assemble_chapters(
            [
                page(1, "# Chapter 2: The Lands of Barovia\n\nA."),
                page(2, "# N. Town of Vallaki\n\nB."),
                page(3, "C."),
            ]
        )

        assert len(chapters) == 1
        assert chapters[0].title == "Chapter 2: The Lands of Barovia"
        assert chapters[0].end_page == 3
        assert "N. Town of Vallaki" in chapters[0].markdown

    def test_repeated_chapter_title_is_a_continuation(self):
        """A running header repeating the current chapter must not split it."""
        chapters = assemble_chapters(
            [
                page(80, "# Chapter 3: The Village of Barovia\n\nA."),
                page(81, "# Chapter 3: The Village of Barovia\n\nB."),
                page(82, "C."),
            ]
        )

        assert len(chapters) == 1
        assert chapters[0].start_page == 80
        assert chapters[0].end_page == 82

    def test_different_consecutive_chapters_still_split(self):
        chapters = assemble_chapters(
            [
                page(1, "# Chapter 3: The Village of Barovia\n\nA."),
                page(2, "# Chapter 4: Castle Ravenloft\n\nB."),
            ]
        )

        assert [c.title for c in chapters] == [
            "Chapter 3: The Village of Barovia",
            "Chapter 4: Castle Ravenloft",
        ]

    def test_recognises_appendix_and_introduction(self):
        chapters = assemble_chapters(
            [
                page(1, "# Introduction\n\nA."),
                page(2, "# Appendix A: Fortunes of Ravenloft\n\nB."),
            ]
        )

        assert [c.title for c in chapters] == [
            "Introduction",
            "Appendix A: Fortunes of Ravenloft",
        ]

    def test_pilot_page_shape_yields_two_chapters(self):
        """Regression against the exact shape observed in the 79-82 boundary pilot."""
        chapters = assemble_chapters(
            [
                page(79, "# N. Town of Vallaki\n\nA."),
                page(80, "# Chapter 3: The Village of Barovia\n\nB."),
                page(81, "# Chapter 3: The Village of Barovia\n\nC."),
                page(82, "D."),
            ]
        )

        assert len(chapters) == 2
        assert chapters[0].slug == "front-matter"
        assert chapters[1].title == "Chapter 3: The Village of Barovia"
        assert chapters[1].start_page == 80
        assert chapters[1].end_page == 82
