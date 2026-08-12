"""Splitting on the document's own heading depth, with size-driven refinement.

The key-based splitter (`splitter="key"`, still exercised in `test_sections.py`)
starts a section at any heading whose text matches `^[A-Z]\\d+[a-z]?\\.`. That
convention is Curse of Strahd's; Xanathar's Guide and the Monster Manual have no
keyed rooms at all, so nothing resting on it travels to the other 34 books the
user owns. The D&D Beyond corpus renders heading levels properly, so the
structure the key was standing in for is present and can be used directly.

Two derived parameters, both measured on the DDB corpus rather than chosen:

* **the extraction budget, 1000 tokens.** p99 of the 789 authored leaf bodies is
  1017 tokens and p95 of the 974 authored *area* spans (a heading plus at most
  one level of detail sub-headings) is 934. A section larger than that holds
  more than one authored area by construction, so it is subdividable.
* **the area depth, per chapter.** The shallowest heading depth at which at
  least three quarters of the headings' spans already fit the budget. The
  remaining quarter is what refinement exists for.

Refinement only ever makes units *smaller*, and every subsection keeps its own
heading, depth and index. This is not a reversal of Task 7's deletion of
`pack_sections`: that function *combined* sections into one unit, which made
`_parse` stamp every node with the first section's heading and corrupted
provenance. Subdivision moves provenance the other way -- strictly finer.
"""

import pytest

from backend.canon.models import Chapter
from backend.canon.sections import (
    EXTRACTION_BUDGET_TOKENS,
    area_depth,
    split_chapter,
    split_sections,
)


def prose(tokens: int) -> str:
    """Roughly `tokens` tiktoken tokens of filler."""
    return " ".join(["word"] * tokens)


def chapter(markdown: str, slug: str = "ch", title: str = "Chapter 3: A Village") -> Chapter:
    return Chapter(slug=slug, title=title, start_page=1, end_page=2, markdown=markdown)


# A DDB-shaped chapter: h1 title, h2 chapter sections, h3 areas, h4 sub-areas.
# Sized so that the h2 spans blow the 200-token test budget and the h3 spans
# mostly do not -- which is the situation the real corpus is in.
DDB_SHAPED = (
    f"# Chapter 3: A Village\n\n{prose(40)}\n\n"
    f"## Areas of the Village\n\n{prose(20)}\n\n"
    f"### E1. Mercantile\n\n{prose(60)}\n\n"
    f"### E2. Tavern\n\n{prose(60)}\n\n"
    f"### E5. Church\n\n{prose(30)}\n\n"
    f"#### E5a. Hall\n\n{prose(30)}\n\n"
    f"#### E5g. Undercroft\n\n{prose(30)}\n\n"
    f"### E6. Cemetery\n\n{prose(30)}\n"
)

# Coarse enough that every h3 span fits and nothing is refined; fine enough that
# only `E5. Church` -- the one h3 holding sub-areas -- has to be subdivided.
COARSE, FINE = 150, 80

# The same book rendered one level shallower: areas at h2, details at h3. No
# sourcebook is obliged to render like Curse of Strahd, and a rule that assumed
# h3 would silently mis-split this.
SHALLOW_SHAPED = (
    f"# A Chapter\n\n{prose(30)}\n\n"
    f"## E1. Mercantile\n\n{prose(60)}\n\n"
    f"### Wares\n\n{prose(30)}\n\n"
    f"## E2. Tavern\n\n{prose(60)}\n\n"
    f"## E6. Cemetery\n\n{prose(30)}\n"
)


class TestAreaDepth:
    def test_derives_h3_on_a_ddb_shaped_chapter(self):
        """h2 spans hold several areas each and blow the budget; h3 spans do
        not. The rule must land on h3 without being told h3."""
        assert area_depth(DDB_SHAPED, budget=COARSE) == 3

    def test_derives_h2_when_the_book_renders_areas_one_level_shallower(self):
        """The whole point of the change: `h3` is a fact about how Curse of
        Strahd renders, not about sourcebooks."""
        assert area_depth(SHALLOW_SHAPED, budget=COARSE) == 2

    def test_a_chapter_with_one_heading_and_no_nesting_derives_that_depth(self):
        assert area_depth(f"# Foreword\n\n{prose(50)}\n", budget=200) == 1

    def test_falls_back_to_the_deepest_depth_when_nothing_fits(self):
        """The loud failure mode. Foreword and Credits are single-h1 chapters
        whose one span exceeds the budget and cannot be subdivided; the rule
        must not pretend a depth qualified."""
        markdown = f"# Foreword\n\n{prose(500)}\n"

        assert area_depth(markdown, budget=200) == 1
        assert split_chapter(chapter(markdown), budget=200).depth_qualified is False


class TestDepthSplit:
    def test_a_section_begins_at_the_area_depth_or_shallower(self):
        headings = [s.heading for s in split_sections(chapter(DDB_SHAPED), budget=COARSE)]

        assert "Areas of the Village" in headings
        assert "E1. Mercantile" in headings

    def test_a_heading_deeper_than_the_area_depth_stays_in_the_body(self):
        """`E5a` is deeper than the derived area depth and `E5. Church` fits the
        budget, so it is not subdivided and its sub-areas travel with it."""
        sections = {s.heading: s for s in split_sections(chapter(DDB_SHAPED), budget=COARSE)}

        assert "E5a. Hall" not in sections
        assert "E5a. Hall" in sections["E5. Church"].markdown

    def test_every_section_carries_its_heading_depth(self):
        sections = {s.heading: s for s in split_sections(chapter(DDB_SHAPED), budget=COARSE)}

        assert sections["Areas of the Village"].depth == 2
        assert sections["E1. Mercantile"].depth == 3

    def test_a_section_points_at_its_enclosing_section(self):
        sections = split_sections(chapter(DDB_SHAPED), budget=COARSE)
        by_heading = {s.heading: s for s in sections}
        by_index = {s.index: s for s in sections}

        parent = by_index[by_heading["E1. Mercantile"].parent_index]
        assert parent.heading == "Areas of the Village"

    def test_a_shallower_shaped_chapter_splits_on_its_own_areas(self):
        headings = [s.heading for s in split_sections(chapter(SHALLOW_SHAPED), budget=COARSE)]

        assert "E1. Mercantile" in headings
        assert "E2. Tavern" in headings
        assert "Wares" not in headings


class TestSizeDrivenRefinement:
    def test_an_over_budget_section_is_subdivided_at_its_next_heading_level(self):
        """`E5. Church` plus its seven sub-areas is 1923 tokens in the real
        chapter 3 -- more than one authored area's worth -- so it splits into
        the areas the author actually wrote."""
        sections = [s.heading for s in split_sections(chapter(DDB_SHAPED), budget=FINE)]

        assert "E5. Church" in sections
        assert "E5a. Hall" in sections
        assert "E5g. Undercroft" in sections

    def test_refinement_only_ever_makes_units_smaller(self):
        coarse = split_sections(chapter(DDB_SHAPED), budget=COARSE)
        fine = split_sections(chapter(DDB_SHAPED), budget=FINE)

        assert len(fine) > len(coarse)

    def test_a_subsection_keeps_its_own_heading_depth_and_index(self):
        """The distinction from the deleted `pack_sections`, which combined
        sections and made every node inherit the first heading."""
        sections = split_sections(chapter(DDB_SHAPED), budget=FINE)
        undercroft = next(s for s in sections if s.heading == "E5g. Undercroft")

        assert undercroft.depth == 4
        assert undercroft.index == sections.index(undercroft)
        assert sections[undercroft.parent_index].heading == "E5. Church"

    def test_an_under_budget_section_is_left_whole(self):
        result = split_chapter(chapter(DDB_SHAPED), budget=COARSE)

        assert result.subdivided == 0
        assert result.before_refinement == len(result.sections)

    def test_an_over_budget_section_with_no_deeper_headings_is_left_whole(self):
        """The rule's failure mode, and it must be visible rather than silently
        truncated."""
        markdown = f"# A Chapter\n\n## One Long Room\n\n{prose(600)}\n"
        result = split_chapter(chapter(markdown), budget=200)

        assert result.unsplittable >= 1
        assert any(prose(600) in s.markdown for s in result.sections)

    def test_the_budget_defaults_to_the_measured_value(self):
        assert EXTRACTION_BUDGET_TOKENS == 1000


class TestKeySplitterStillReachable:
    def test_the_key_splitter_is_unchanged_and_selectable(self):
        """Legs A and B of the measurement need it, and it is the fallback while
        the depth path is young."""
        markdown = "## Prose\n\ntext.\n\n# E6. Cemetery\n\nGraves."
        headings = [s.heading for s in split_sections(chapter(markdown), splitter="key")]

        assert headings == ["Prose", "E6. Cemetery"]

    def test_an_unknown_splitter_is_rejected(self):
        with pytest.raises(ValueError, match="splitter"):
            split_sections(chapter("## A\n\ntext."), splitter="nonsense")

    def test_the_key_splitter_leaves_depth_unknown(self):
        """Transcribed heading levels are noise, so a key-split section must not
        advertise a depth that `structure.py` would then trust."""
        sections = split_sections(chapter("## E1. Shop\n\ntext.\n\n### E1a. Cellar\n\ntext."),
                                  splitter="key")

        assert all(s.depth == 0 for s in sections)
        assert all(s.parent_index == -1 for s in sections)
