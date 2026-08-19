"""Splitting a chapter into extraction units.

Chapters are too big to extract in one pass (chapter 4 is ~36k tokens) and
ChromaDB chunks split mid-topic, so an entity introduced in one and located in
the next becomes two partial extractions. Sections split on the seams the book's
own author chose.

**The real-corpus section counts changed in Task 11 and the change is
deliberate.** They were 11 (chapter 3), 84 (chapter 4) and 32 (Appendix D) while
`split_sections` split on `##` only. The vision transcription assigns heading
levels essentially at random -- the same keyed area appears as H1, H2, H3 or H4
with no pattern (chapter 3: 2/4/8, chapter 4: 39/40/23/1) -- so an H2-only rule
silently lost roughly 60% of the book's keyed areas, including
`E4. Burgomaster's Mansion`, which the golden set grades against. A heading at
any level whose text matches the keyed pattern now starts a section, so the
counts are 21 / 147 / 32. Appendix D is unchanged at 32 because not one of its
88 headings is keyed -- stat-block sub-headings still stay inside their creature.

**Task 12 note: these counts are deliberately UNCHANGED at 21 / 147 / 32.** The
default splitter is now `depth`, and the corpus is now D&D Beyond's text rather
than the vision transcription -- but these three fixtures are skeletons of the
*transcription*, and the transcription is only ever read by the `key` splitter.
Re-baselining them against the depth splitter would be measuring a rule that
reads heading levels against a corpus whose heading levels are noise, which
would pin nonsense. The depth splitter's own behaviour is pinned in
`test_depth_sections.py` against synthetic fixtures; its counts on the real DDB
corpus are reported in the task report, because pinning them here would require
committing the book's text.
"""

import re
from collections import Counter
from pathlib import Path

import pytest

from backend.canon.models import Chapter
from backend.canon.sections import KEYED_HEADING, units_from_sections
from backend.canon.sections import split_sections as _split_sections

FIXTURES = Path(__file__).parent / "fixtures"


def split_sections(chapter: Chapter):
    """Every test in this module is about the `key` splitter, so it says so.

    `split_sections` now defaults to `splitter="depth"`. These tests and these
    fixtures are the *transcription* corpus, and the depth splitter must never
    be pointed at it: its heading levels were assigned essentially at random by
    a vision model, so deriving anything from them would be deriving from noise.
    Naming the splitter here keeps that separation visible at every call site
    rather than resting on whichever default happens to be current.
    """
    return _split_sections(chapter, splitter="key")


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

    def test_an_unkeyed_h3_does_not_split(self):
        """Sub-headings belong with their section, not beside it."""
        sections = split_sections(
            chapter("## Area E1\n\nShop.\n\n### Wares\n\nOverpriced.\n\n## Area E2\n\nTavern.")
        )

        assert len(sections) == 2
        assert "Overpriced." in sections[0].markdown

    def test_a_keyed_heading_splits_at_any_level(self):
        """Heading *level* carries no signal in this transcription -- the same
        kind of thing (a keyed room) is emitted as H1, H2, H3 and H4 with no
        pattern -- so the key, not the level, is what starts a section."""
        sections = split_sections(
            chapter(
                "## Prose\n\ntext.\n\n"
                "# E6. Cemetery\n\nGraves.\n\n"
                "### E4. Burgomaster's Mansion\n\nMansion.\n\n"
                "#### K18a. High Tower Shaft\n\nShaft."
            )
        )

        assert [s.heading for s in sections] == [
            "Prose",
            "E6. Cemetery",
            "E4. Burgomaster's Mansion",
            "K18a. High Tower Shaft",
        ]

    def test_an_unkeyed_h1_does_not_split(self):
        """The assembler finds chapter boundaries on chapter-title H1s and the
        page's running header is transcribed at H1 too, so an unkeyed H1 is not
        a section boundary -- "Areas of the Village" is a divider, not a room."""
        sections = split_sections(
            chapter("## Prose\n\ntext.\n\n# Areas of the Village\n\nmore text.")
        )

        assert [s.heading for s in sections] == ["Prose"]
        assert "Areas of the Village" in sections[0].markdown

    def test_an_unkeyed_h4_does_not_split(self):
        sections = split_sections(
            chapter("## Prose\n\ntext.\n\n#### Actions\n\nMultiattack.")
        )

        assert [s.heading for s in sections] == ["Prose"]
        assert "Multiattack." in sections[0].markdown

    def test_a_bare_number_heading_does_not_split(self):
        """Task 6's ruling, now load-bearing at a second call site: the book's
        bare-number keys are chapter 1's Tarokka card *results* -- items and
        people, not rooms -- and splitting on them mints sections for
        "1. The Tome of Strahd" that a fabricated place would then contain."""
        sections = split_sections(
            chapter(
                "## Fortunes of Ravenloft\n\ntext.\n\n"
                "### 1. The Tome of Strahd\n\nA card.\n\n"
                "# 5. Strahd\n\nAnother card."
            )
        )

        assert [s.heading for s in sections] == ["Fortunes of Ravenloft"]

    def test_a_bare_letter_is_a_key_too(self):
        """Chapter 2 is the overland map and keys its regions `A.` to `Z.`,
        because there are fewer than twenty-six. The pattern used to require a
        digit -- written to exclude bare NUMBERS, and excluding bare letters
        with them -- so `the-lands-of-barovia` was the only chapter in the book
        with zero keyed places, and Madam Eva's camp had no entity."""
        assert KEYED_HEADING.match("G. Tser Pool Encampment").group("name") == (
            "Tser Pool Encampment"
        )
        assert KEYED_HEADING.match("G. Tser Pool Encampment").group("stem") == "G"

    def test_a_sub_area_letter_needs_a_numbered_parent(self):
        """`[A-Z]\d*[a-z]?` also matches `St. Andral's Feast` as stem `S`
        suffix `t` -- the one false positive in the corpus's 1,063 headings.
        A sub-area letter only means anything under a numbered area."""
        assert KEYED_HEADING.match("St. Andral's Feast") is None
        assert KEYED_HEADING.match("Mr. Smith") is None
        assert KEYED_HEADING.match("E5g. Undercroft").group("suffix") == "g"

    def test_a_keyed_heading_ends_the_section_before_it(self):
        """A split point that did not terminate the previous body would leave
        the same prose in two extraction units and double-bill for it."""
        sections = split_sections(
            chapter("## E2. Tavern\n\nAle.\n\n### E3. Townhouse\n\nMary weeps.")
        )

        assert "Mary weeps." not in sections[0].markdown
        assert "Mary weeps." in sections[1].markdown

    def test_a_keyed_heading_ends_the_preamble(self):
        sections = split_sections(
            chapter("# Chapter 3\n\nIntro prose.\n\n### E1. Bildrath's Mercantile\n\nShop.")
        )

        assert [s.heading for s in sections] == ["(preamble)", "E1. Bildrath's Mercantile"]
        assert "Intro prose." in sections[0].markdown
        assert "Shop." in sections[1].markdown

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
    """Chapter 3 is the only material this splitter had ever been run against.
    Chapter 4 and Appendix D are ~60% of the corpus and the spec's own Known
    Risks section says chapter 3 tells us nothing about them.

    Counts were 11 / 84 / 32 under the H2-only rule; see the module docstring
    for why they are now 21 / 147 / 32.
    """

    @pytest.mark.parametrize(
        ("fixture", "expected"),
        [(CHAPTER_3, 21), (CHAPTER_4, 147), (APPENDIX_D, 32)],
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
            # E3 and E4 are transcribed as H3 and E6/E7 as H1; all four were
            # invisible to the H2-only rule and never became extraction units.
            "E3. Mad Mary's Townhouse",
            "E4. Burgomaster's Mansion",
            "Roleplaying Ireena",
            "E5. Church",
            "E5a. Hall",
            "E5b. Doru’s Bedroom",
            "E5c. Donavich’s Bedroom",
            "E5d. Trapdoor",
            "E5e. Office",
            "E5f. Chapel",
            "E5g. Undercroft",
            "Fortunes of Ravenloft",
            "E6. Cemetery",
            "E7. Haunted House",
            "Special Events",
            "Dream Pastries",
        ]

    def test_the_keyed_areas_the_h2_rule_lost_are_now_their_own_sections(self):
        """The four chapter-3 areas this task exists to recover. `E4.
        Burgomaster's Mansion` is the one the golden edge
        `kolyan-indirovich LOCATED_IN burgomasters-mansion` grades against; it
        had been in the miss list since the first classification because the
        section describing it was never extracted as a unit."""
        sections = split_sections(real_chapter(*CHAPTER_3))
        by_heading = {s.heading: s for s in sections}

        for recovered in ("E3. Mad Mary's Townhouse", "E4. Burgomaster's Mansion",
                          "E6. Cemetery", "E7. Haunted House"):
            assert recovered in by_heading, f"{recovered} must be its own section"
            assert by_heading[recovered].markdown.startswith("#")

    def test_a_keyed_h1_in_chapter_four_is_its_own_section(self):
        """Was pinned as a FINDING in Task 10: `K2. Center Court Gate` is
        transcribed at H1 and was swallowed by "Walls of Ravenloft" above it.
        59 of chapter 4's keyed areas were lost this way."""
        headings = [s.heading for s in split_sections(real_chapter(*CHAPTER_4))]

        assert "K2. Center Court Gate" in headings
        assert "Walls of Ravenloft" in headings

    def test_a_stat_block_appendix_splits_on_creatures_not_on_stat_block_parts(self):
        """Appendix D writes stat-block parts as H3 sub-headings inside a
        creature's section -- "The Abbot's Traits", "Antimagic Susceptibility",
        "Reactions". All 37 of them must stay inside their sections rather than
        becoming 37 more sections. None of its 88 headings is keyed, so
        splitting on the key leaves this appendix untouched at 32 sections."""
        sections = split_sections(real_chapter(*APPENDIX_D))
        headings = [s.heading for s in sections]

        assert headings[:3] == [
            "(preamble)",
            "New Creatures by Challenge Rating",
            "Baba Lysaga's Creeping Hut",
        ]
        for h3 in ("The Abbot's Traits", "Antimagic Susceptibility", "Reactions"):
            assert h3 not in headings, "an H3 stat-block heading must not split"

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

    def test_every_keyed_heading_in_the_corpus_becomes_a_section(self):
        """The census this task was written from: 14 keyed headings in chapter
        3 (2 at H1, 4 at H2, 8 at H3) and 103 in chapter 4 (39/40/23/1). Every
        one must now be a section heading -- that is the whole recall claim, and
        a level-based rule can only ever satisfy part of it."""
        for fixture, expected_keyed in ((CHAPTER_3, 14), (CHAPTER_4, 103)):
            markdown = real_chapter(*fixture).markdown
            keyed_headings = [
                text
                for level, text in re.findall(r"^(#{1,6})\s+(.+?)\s*$", markdown, re.MULTILINE)
                if KEYED_HEADING.match(text)
            ]
            headings = {s.heading for s in split_sections(real_chapter(*fixture))}

            assert len(keyed_headings) == expected_keyed
            assert set(keyed_headings) <= headings

    def test_an_unkeyed_h1_in_the_real_corpus_still_does_not_split(self):
        """Chapter 3's "Areas of the Village" is an H1 divider, not a room, and
        the running headers the transcription emits appear at H1 as well."""
        headings = [s.heading for s in split_sections(real_chapter(*CHAPTER_3))]

        assert "Areas of the Village" not in headings
        assert "Chapter 3: The Village of Barovia" not in headings
