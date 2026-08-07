"""Splitting a chapter into extraction units.

Chapters are too big to extract in one pass (chapter 4 is ~36k tokens) and
ChromaDB chunks split mid-topic, so an entity introduced in one and located in
the next becomes two partial extractions. Sections split on the seams the book's
own author chose.
"""

import pytest

from backend.canon.models import Chapter
from backend.canon.sections import pack_sections, split_sections


def chapter(markdown: str) -> Chapter:
    return Chapter(
        slug="chapter-3-the-village-of-barovia",
        title="Chapter 3: The Village of Barovia",
        start_page=80,
        end_page=94,
        markdown=markdown,
    )


class TestSplitSections:
    def test_splits_on_h2_headings(self):
        sections = split_sections(
            chapter("# Chapter 3\n\nIntro.\n\n## Area E1\n\nShop.\n\n## Area E2\n\nTavern.")
        )

        assert [s.heading for s in sections] == ["(preamble)", "Area E1", "Area E2"]
        assert "Shop." in sections[1].markdown

    def test_preamble_captures_text_before_the_first_heading(self):
        sections = split_sections(chapter("# Chapter 3\n\nIntro prose.\n\n## Area E1\n\nShop."))

        assert sections[0].heading == "(preamble)"
        assert "Intro prose." in sections[0].markdown

    def test_no_preamble_section_when_chapter_opens_on_a_heading(self):
        sections = split_sections(chapter("## Area E1\n\nShop.\n\n## Area E2\n\nTavern."))

        assert [s.heading for s in sections] == ["Area E1", "Area E2"]

    def test_h3_does_not_split(self):
        """Sub-headings belong with their section, not beside it."""
        sections = split_sections(
            chapter("## Area E1\n\nShop.\n\n### Wares\n\nOverpriced.\n\n## Area E2\n\nTavern.")
        )

        assert len(sections) == 2
        assert "Overpriced." in sections[0].markdown

    def test_carries_chapter_provenance(self):
        sections = split_sections(chapter("## Area E1\n\nShop."))

        assert sections[0].chapter_slug == "chapter-3-the-village-of-barovia"
        assert sections[0].chapter_title == "Chapter 3: The Village of Barovia"
        assert sections[0].index == 0

    def test_empty_chapter_yields_nothing(self):
        assert split_sections(chapter("   \n\n  ")) == []


class TestPackSections:
    def test_small_sections_combine(self):
        sections = split_sections(
            chapter("## A\n\nshort.\n\n## B\n\nshort.\n\n## C\n\nshort.")
        )
        units = pack_sections(sections, max_tokens=1500)

        assert len(units) == 1
        assert units[0].headings == ["A", "B", "C"]

    def test_oversized_section_stands_alone(self):
        big = "word " * 3000
        sections = split_sections(chapter(f"## Small\n\ntiny.\n\n## Big\n\n{big}"))
        units = pack_sections(sections, max_tokens=1500)

        assert len(units) == 2
        assert units[0].headings == ["Small"]
        assert units[1].headings == ["Big"]
        assert units[1].token_count > 1500

    def test_packing_loses_no_section(self):
        sections = split_sections(
            chapter("".join(f"## S{i}\n\n{'word ' * 200}\n\n" for i in range(10)))
        )
        units = pack_sections(sections, max_tokens=1500)

        packed = [h for u in units for h in u.headings]
        assert packed == [s.heading for s in sections]

    def test_packing_duplicates_no_section(self):
        sections = split_sections(
            chapter("".join(f"## S{i}\n\n{'word ' * 200}\n\n" for i in range(10)))
        )
        units = pack_sections(sections, max_tokens=1500)

        packed = [h for u in units for h in u.headings]
        assert len(packed) == len(set(packed))

    def test_units_carry_their_token_count(self):
        units = pack_sections(split_sections(chapter("## A\n\nsome words here.")))

        assert units[0].token_count > 0

    def test_empty_input_yields_no_units(self):
        assert pack_sections([]) == []
