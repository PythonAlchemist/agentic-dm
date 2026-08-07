"""Splitting a chapter into extraction units.

Chapters are too big to extract in one pass (chapter 4 is ~36k tokens) and
ChromaDB chunks split mid-topic, so an entity introduced in one and located in
the next becomes two partial extractions. Sections split on the seams the book's
own author chose.
"""

from backend.canon.models import Chapter
from backend.canon.sections import split_sections, units_from_sections


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


class TestUnitsFromSections:
    def test_one_unit_per_section(self):
        sections = split_sections(
            chapter("## A\n\nshort.\n\n## B\n\nshort.\n\n## C\n\nshort.")
        )
        units = units_from_sections(sections)

        assert [u.heading for u in units] == ["A", "B", "C"]

    def test_each_unit_carries_its_own_token_count(self):
        units = units_from_sections(split_sections(chapter("## A\n\nsome words here.")))

        assert units[0].token_count > 0

    def test_no_section_is_lost(self):
        sections = split_sections(
            chapter("".join(f"## S{i}\n\nbody {i}.\n\n" for i in range(6)))
        )
        units = units_from_sections(sections)

        assert [u.heading for u in units] == [s.heading for s in sections]

    def test_each_unit_carries_its_own_section_index(self):
        """If a unit's section_index silently defaulted or collapsed to 0,
        structure.py would attribute every candidate from every section but
        the first to section 0 -- a fabricated LOCATED_IN naming the wrong
        room, inside the one module documented as unable to hallucinate."""
        sections = split_sections(
            chapter("".join(f"## S{i}\n\nbody {i}.\n\n" for i in range(4)))
        )
        units = units_from_sections(sections)

        assert [u.section_index for u in units] == [s.index for s in sections]
