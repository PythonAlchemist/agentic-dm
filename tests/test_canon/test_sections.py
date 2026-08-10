"""Splitting a chapter into extraction units.

Chapters are too big to extract in one pass (chapter 4 is ~36k tokens) and
ChromaDB chunks split mid-topic, so an entity introduced in one and located in
the next becomes two partial extractions. Sections split on the seams the book's
own author chose.
"""

from collections import Counter
from pathlib import Path

import pytest

from backend.canon.models import Chapter
from backend.canon.sections import split_sections, units_from_sections

FIXTURES = Path(__file__).parent / "fixtures"


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


def real_chapter(fixture: str, slug: str, title: str) -> Chapter:
    """A chapter rebuilt from a committed structural skeleton of the real corpus.

    Every heading line in these fixtures is verbatim from the vision transcription
    of Curse of Strahd; the prose between headings is elided (see the banner in
    each file). `split_sections` reads only heading lines, so the skeleton yields
    exactly the section list the full transcript does -- the counts below match
    the live corpus -- without committing the book's text.
    """
    return Chapter(
        slug=slug,
        title=title,
        start_page=1,
        end_page=2,
        markdown=(FIXTURES / fixture).read_text(),
    )


CHAPTER_3 = ("chapter-3-village-of-barovia.md", "chapter-3-the-village-of-barovia",
             "Chapter 3: The Village of Barovia")
CHAPTER_4 = ("chapter-4-castle-ravenloft.md", "chapter-4-castle-ravenloft",
             "Chapter 4: Castle Ravenloft")
APPENDIX_D = ("appendix-d-monsters-and-npcs.md", "appendix-d-monsters-and-npcs",
              "Appendix D: Monsters and NPCs")


class TestRealCorpusSections:
    """Chapter 3 is 11 sections of tidy keyed areas and is the only material this
    splitter had ever been run against. Chapter 4 (84 sections) and Appendix D
    (32 sections of stat blocks) are ~60% of the corpus and the spec's own Known
    Risks section says chapter 3 tells us nothing about them.
    """

    @pytest.mark.parametrize(
        ("fixture", "expected"),
        [(CHAPTER_3, 11), (CHAPTER_4, 84), (APPENDIX_D, 32)],
    )
    def test_section_counts_match_the_real_corpus(self, fixture, expected):
        assert len(split_sections(real_chapter(*fixture))) == expected

    def test_chapter_three_headings(self):
        headings = [s.heading for s in split_sections(real_chapter(*CHAPTER_3))]

        assert headings == [
            "(preamble)",
            "Approaching the Village",
            "House Occupants",
            "E1. Bildrath's Mercantile",
            "E2. Blood of the Vine Tavern",
            "Roleplaying Ireena",
            # E3 (Burgomaster's Mansion) and E4 (Mad Mary's Townhouse) are
            # missing: both were transcribed as H1 and are swallowed by the
            # section above them -- see the last test in this class.
            "E5. Church",
            "E5g. Undercroft",
            "Fortunes of Ravenloft",
            "Special Events",
            "Dream Pastries",
        ]

    def test_a_stat_block_appendix_splits_on_creatures_not_on_stat_block_parts(self):
        """Appendix D writes each creature's "Actions"/"Traits" as an H3 inside
        its section. 37 H3 sub-headings must not become 37 sections."""
        sections = split_sections(real_chapter(*APPENDIX_D))
        headings = [s.heading for s in sections]

        assert headings[:3] == [
            "(preamble)",
            "New Creatures by Challenge Rating",
            "Baba Lysaga's Creeping Hut",
        ]
        assert "Vladimir Horngaard" not in headings, (
            "an H3 stat-block heading must stay inside its own section"
        )

    @pytest.mark.parametrize(
        ("fixture", "heading", "expected"),
        [(CHAPTER_4, "Treasure", 4), (APPENDIX_D, "Actions", 3)],
    )
    def test_duplicate_headings_really_do_occur(self, fixture, heading, expected):
        """`(chapter_slug, heading)` is not a unique key, which is why
        structure.py keys on section_index. This is the real material that
        claim was made about."""
        counts = Counter(s.heading for s in split_sections(real_chapter(*fixture)))

        assert counts[heading] == expected

    def test_every_section_carries_its_own_index_and_provenance(self):
        sections = split_sections(real_chapter(*CHAPTER_4))

        assert [s.index for s in sections] == list(range(len(sections)))
        assert all(s.chapter_slug == "chapter-4-castle-ravenloft" for s in sections)

    def test_units_are_one_per_section_across_the_whole_corpus(self):
        for fixture in (CHAPTER_3, CHAPTER_4, APPENDIX_D):
            sections = split_sections(real_chapter(*fixture))
            units = units_from_sections(sections)

            assert [u.heading for u in units] == [s.heading for s in sections]

    def test_a_keyed_area_transcribed_as_h1_is_swallowed_by_the_section_before_it(self):
        """FINDING, pinned rather than fixed: the vision transcription emits many
        keyed-area headings at H1 rather than H2 -- 59 of them in chapter 4, and
        E3, E4, E6 and E7 in chapter 3. `split_sections` splits on H2 only, so
        each one is absorbed into the preceding section instead of becoming its
        own unit, and `place_of_section` never sees it. Chapter 3's tidy-looking
        11 sections have been hiding four keyed areas all along -- including the
        Burgomaster's Mansion, which the golden set grades against.

        Not repaired here: promoting H1 to a split point changes which units are
        extracted and what the graded run costs, which is a measurement change,
        not a test fix. This test exists so the next person finds it stated.
        """
        sections = split_sections(real_chapter(*CHAPTER_4))
        headings = [s.heading for s in sections]

        assert "K2. Center Court Gate" not in headings
        swallowing = next(s for s in sections if "K2. Center Court Gate" in s.markdown)
        assert swallowing.heading == "Walls of Ravenloft", (
            "the H1 keyed area is buried in whichever H2 section precedes it"
        )

        ch3 = [s.heading for s in split_sections(real_chapter(*CHAPTER_3))]
        for lost in ("E3. Burgomaster's Mansion", "E4. Mad Mary's Townhouse",
                     "E6. Cemetery", "E7. Haunted House"):
            assert lost not in ch3
