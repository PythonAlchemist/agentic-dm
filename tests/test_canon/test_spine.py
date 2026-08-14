"""The narrative spine and the mention scan, without a database.

Everything here is pure: sections in, spine and mentions out. The scan is the
part that decides what the graph knows about where an entity appears, and it is
deterministic by construction -- no model, no cost, and therefore assertable to
the exact node.
"""

import re

import pytest

from backend.canon.models import Section
from backend.canon.spine import (
    EVIDENCE_MAX,
    ChapterSpine,
    WriteMention,
    evidence_span,
    fold_apostrophe,
    mention_id,
    mention_pattern,
    plan_spine,
    scan_mentions,
    section_id,
)
from backend.canon.writer import CANON_PLANE, mint_id

CHAPTER = "the-village-of-barovia"


def sec(
    heading: str,
    index: int,
    markdown: str,
    *,
    depth: int = 3,
    parent_index: int = -1,
) -> Section:
    return Section(
        chapter_slug=CHAPTER,
        chapter_title="Chapter 3: The Village of Barovia",
        heading=heading,
        index=index,
        markdown=markdown,
        depth=depth,
        parent_index=parent_index,
    )


def spine_of(sections: list[Section], locations: set[str] | None = None) -> ChapterSpine:
    return plan_spine(
        book_slug="cos",
        book_title="Curse of Strahd",
        chapter_slug=CHAPTER,
        chapter_title="Chapter 3: The Village of Barovia",
        chapter_index=4,
        sections=sections,
        location_ids=locations if locations is not None else set(),
    )


class TestTheSpine:
    def test_a_section_carries_its_own_text(self):
        """A mention quotes its section, so the section has to hold the text."""
        spine = spine_of([sec("E5f. Chapel", 14, "## E5f. Chapel\n\nDonavich prays here.")])
        assert spine.sections[0].text == "## E5f. Chapel\n\nDonavich prays here."

    def test_section_ids_are_stable_and_chapter_scoped(self):
        spine = spine_of([sec("E5f. Chapel", 14, "x"), sec("E5g. Undercroft", 15, "y")])
        assert [s.id for s in spine.sections] == [
            f"cos:{CHAPTER}#14",
            f"cos:{CHAPTER}#15",
        ]

    def test_the_section_keeps_its_index_depth_and_parent(self):
        """`(chapter.index, section.index)` is the order the book reveals things,
        so a section that lost its index would make progression unorderable."""
        spine = spine_of([sec("E5a. Hall", 9, "x", depth=4, parent_index=8)])
        written = spine.sections[0]
        assert (written.index, written.depth, written.parent_index) == (9, 4, 8)

    def test_the_chapter_carries_its_index(self):
        assert spine_of([sec("x", 0, "y")]).chapter_index == 4

    def test_a_keyed_section_describes_the_place_it_names(self):
        """`E5f. Chapel` IS the chapel -- the correspondence `structure.py`
        already computes, reused rather than re-derived."""
        chapel = mint_id(CHAPTER, "Chapel", "e5f")
        spine = spine_of([sec("E5f. Chapel", 14, "x")], locations={chapel})
        assert spine.describes == ((f"cos:{CHAPTER}#14", chapel),)

    def test_a_prose_heading_describes_nothing(self):
        """"Approaching the Village" is not a place, and treating it as one
        would invent a room the book never keys.

        The would-be id is IN `location_ids`, so a spine that read a heading
        rather than asking `place_of_section` whether it keys anything would
        emit the edge and fail here.
        """
        spine = spine_of(
            [sec("Approaching the Village", 1, "x")],
            locations={mint_id(CHAPTER, "Approaching the Village")},
        )
        assert spine.describes == ()

    def test_a_keyed_section_naming_a_non_location_describes_nothing(self):
        """`E5d. Trapdoor` is keyed, and the extractor typed it an ITEM. The
        edge's range is :LOCATION, so an item keyed as an area gets none --
        while the chapel beside it, which IS a location, still does."""
        chapel = mint_id(CHAPTER, "Chapel", "e5f")
        spine = spine_of(
            [sec("E5d. Trapdoor", 12, "x"), sec("E5f. Chapel", 14, "y")],
            locations={chapel},
        )
        assert spine.describes == ((f"cos:{CHAPTER}#14", chapel),)


class TestTheMatchingRule:
    def test_a_single_word_name_is_case_sensitive(self):
        """The LORE entity `Light` must not match every lit torch."""
        assert mention_pattern("Light").search("The Light of Ravenkind")
        assert not mention_pattern("Light").search("a shaft of light thrusts")

    def test_a_multi_word_name_is_case_insensitive(self):
        assert mention_pattern("Blood of the Vine Tavern").search(
            "the blood of the vine tavern is empty"
        )

    def test_matching_is_whole_word_at_the_end(self):
        assert not mention_pattern("Ismark").search("Ismarkovich stood there")

    def test_matching_is_whole_word_at_the_start(self):
        assert not mention_pattern("Doru").search("Kodoru stood in the doorway")

    def test_a_possessive_is_still_the_name(self):
        """`'` is not a word character, so `Doru's` names Doru. Deliberate: the
        book writes half its references possessively."""
        assert mention_pattern("Doru").search("Doru's father wept")

    def test_a_plural_is_not_the_singular(self):
        assert not mention_pattern("Trapdoor").search("two trapdoors")

    def test_nothing_is_fuzzy(self):
        """No token subsets: `Ireena` must not match the quest that names her."""
        assert not mention_pattern("Escort Ireena to Vallaki").search(
            "Ireena travels to Vallaki"
        )

    def test_a_curly_apostrophe_and_a_straight_one_are_one_name(self):
        """The DDB corpus keeps the book's U+2019 while the extractor emits an
        ASCII quote. Without folding, `Bildrath's Mercantile` scores zero
        against its own shop -- a silent zero, which is the failure this whole
        change exists to remove. A single-character substitution, not a
        distance.

        Both the pattern and the haystack are folded; `scan_mentions` folds each
        section once, which is what `TestTheScan` exercises end to end.
        """
        for name in ("Bildrath's Mercantile", "Bildrath’s Mercantile"):
            for text in ("inside Bildrath's Mercantile", "inside Bildrath’s Mercantile"):
                assert mention_pattern(name).search(fold_apostrophe(text)), (name, text)

    def test_an_empty_name_has_no_pattern(self):
        assert mention_pattern("   ") is None


class TestTheScan:
    def test_an_entity_named_in_a_section_gets_a_mention(self):
        spine = spine_of([sec("E5f. Chapel", 14, "Donavich prays in the chapel.")])
        mentions = scan_mentions(spine.sections, [("cos:donavich", "Donavich")], CHAPTER)
        assert [(m.entity_id, m.section_id) for m in mentions] == [
            ("cos:donavich", f"cos:{CHAPTER}#14")
        ]

    def test_an_entity_absent_from_a_section_gets_none(self):
        spine = spine_of([sec("E5f. Chapel", 14, "An empty chapel.")])
        assert scan_mentions(spine.sections, [("cos:donavich", "Donavich")], CHAPTER) == []

    def test_two_sentences_about_one_entity_in_one_section_are_ONE_mention(self):
        """One node per (entity, section) pair, not per occurrence."""
        spine = spine_of([sec("E5f. Chapel", 14, "Donavich weeps. Donavich prays.")])
        mentions = scan_mentions(spine.sections, [("cos:donavich", "Donavich")], CHAPTER)
        assert len(mentions) == 1
        assert mentions[0].occurrences == 2

    def test_two_sections_naming_one_entity_are_two_mentions(self):
        spine = spine_of(
            [
                sec("E5f. Chapel", 14, "Donavich prays."),
                sec("E5g. Undercroft", 15, "Donavich's son is chained here."),
            ]
        )
        mentions = scan_mentions(spine.sections, [("cos:donavich", "Donavich")], CHAPTER)
        assert len(mentions) == 2
        assert {m.section_id for m in mentions} == {
            f"cos:{CHAPTER}#14",
            f"cos:{CHAPTER}#15",
        }

    def test_the_mention_id_is_the_pair(self):
        """Re-running the scan must MERGE onto the same node rather than
        doubling it, so identity is the pair and nothing else."""
        spine = spine_of([sec("E5f. Chapel", 14, "Donavich prays.")])
        mentions = scan_mentions(spine.sections, [("cos:donavich", "Donavich")], CHAPTER)
        assert mentions[0].id == mention_id("cos:donavich", f"cos:{CHAPTER}#14")
        assert mentions[0].id == f"cos:donavich@cos:{CHAPTER}#14"

    def test_every_mention_carries_a_non_empty_evidence_span(self):
        spine = spine_of([sec("E5f. Chapel", 14, "Donavich prays before the altar.")])
        mentions = scan_mentions(spine.sections, [("cos:donavich", "Donavich")], CHAPTER)
        assert mentions[0].evidence.strip()

    def test_the_evidence_is_a_literal_substring_of_its_section(self):
        """A quote that is not in the section is not evidence. Asserted as an
        exact substring so "quoting its section" is checkable rather than
        merely intended -- which is also why nothing here inserts an ellipsis."""
        body = "The priest is broken.\n\nDonavich prays before the altar, weeping.\n"
        spine = spine_of([sec("E5f. Chapel", 14, body)])
        mentions = scan_mentions(spine.sections, [("cos:donavich", "Donavich")], CHAPTER)
        assert mentions[0].evidence in body

    def test_the_evidence_quotes_the_paragraph_the_match_is_in(self):
        body = "A far paragraph about nobody.\n\nDonavich prays before the altar.\n"
        spine = spine_of([sec("E5f. Chapel", 14, body)])
        mentions = scan_mentions(spine.sections, [("cos:donavich", "Donavich")], CHAPTER)
        assert mentions[0].evidence == "Donavich prays before the altar."

    def test_the_evidence_still_contains_the_name_when_the_paragraph_is_huge(self):
        """A window, not a truncation from the left: an evidence span that cut
        the very name it is evidence for would be worse than none."""
        body = "filler word " * 400 + "Donavich prays. " + "more filler " * 400
        spine = spine_of([sec("E5f. Chapel", 14, body)])
        mentions = scan_mentions(spine.sections, [("cos:donavich", "Donavich")], CHAPTER)
        assert "Donavich" in mentions[0].evidence
        assert mentions[0].evidence in body
        assert len(mentions[0].evidence) <= EVIDENCE_MAX

    def test_a_straight_apostrophe_in_a_name_finds_the_books_curly_one(self):
        """The end-to-end form of the folding: an ASCII name out of the
        extractor against the book's own U+2019. Without it this is zero."""
        body = "You step into Bildrath’s Mercantile."
        spine = spine_of([sec("E1. Bildrath’s Mercantile", 4, body)])
        mentions = scan_mentions(
            spine.sections, [("cos:bildraths-mercantile", "Bildrath's Mercantile")], CHAPTER
        )
        assert len(mentions) == 1

    def test_the_evidence_quotes_the_book_not_the_folded_text(self):
        """Folding U+2019 is a one-for-one character substitution, so match
        offsets index the original exactly and the quote keeps the book's own
        typography."""
        body = "You step into Bildrath’s Mercantile."
        spine = spine_of([sec("E1. Bildrath’s Mercantile", 4, body)])
        mentions = scan_mentions(
            spine.sections, [("cos:bildraths-mercantile", "Bildrath's Mercantile")], CHAPTER
        )
        assert "’" in mentions[0].evidence

    def test_the_offset_points_at_the_first_occurrence(self):
        body = "Nobody here. Donavich prays."
        spine = spine_of([sec("E5f. Chapel", 14, body)])
        mentions = scan_mentions(spine.sections, [("cos:donavich", "Donavich")], CHAPTER)
        assert body[mentions[0].offset:].startswith("Donavich")

    def test_the_mention_is_stamped_canon_and_its_chapter(self):
        """The replace path scopes on both, the way an edge's do."""
        spine = spine_of([sec("E5f. Chapel", 14, "Donavich prays.")])
        mention = scan_mentions(spine.sections, [("cos:donavich", "Donavich")], CHAPTER)[0]
        assert mention.properties["plane"] == CANON_PLANE
        assert mention.properties["chapter_slug"] == CHAPTER

    def test_the_scan_is_deterministic_in_the_order_it_emits(self):
        """Two entity orders, one output order: a diff of two runs must be a
        diff of the book, not of a dict's iteration."""
        spine = spine_of([sec("E5f. Chapel", 14, "Donavich and Doru.")])
        entities = [("cos:donavich", "Donavich"), ("cos:doru", "Doru")]
        assert scan_mentions(spine.sections, entities, CHAPTER) == scan_mentions(
            spine.sections, list(reversed(entities)), CHAPTER
        )

    def test_junk_is_not_filtered(self):
        """A `Trapdoor` entity matching many sections makes the junk MORE
        visible, not less. Nothing here suppresses it."""
        spine = spine_of(
            [sec("A", i, "There is a Trapdoor here.") for i in range(40)]
        )
        assert len(scan_mentions(spine.sections, [("cos:trapdoor", "Trapdoor")], CHAPTER)) == 40

    def test_an_entity_with_an_unusable_name_is_skipped_rather_than_matching_everything(self):
        spine = spine_of([sec("E5f. Chapel", 14, "Donavich prays.")])
        assert scan_mentions(spine.sections, [("cos:blank", "   ")], CHAPTER) == []


class TestMentionCounts:
    def test_counts_are_reported_per_entity(self):
        from backend.canon.spine import mention_counts

        spine = spine_of(
            [sec("A", 0, "Donavich and Doru."), sec("B", 1, "Donavich alone.")]
        )
        entities = [("cos:donavich", "Donavich"), ("cos:doru", "Doru")]
        mentions = scan_mentions(spine.sections, entities, CHAPTER)
        assert mention_counts(mentions, dict(entities)) == [
            ("Donavich", 2),
            ("Doru", 1),
        ]


class TestHelpers:
    def test_fold_touches_only_the_right_single_quote(self):
        assert fold_apostrophe("Bildrath’s") == "Bildrath's"
        assert fold_apostrophe("Mad Mary") == "Mad Mary"

    def test_section_id_and_mention_id_round_trip_into_each_other(self):
        sid = section_id(CHAPTER, 14)
        assert mention_id("cos:donavich", sid).endswith(sid)

    @pytest.mark.parametrize("start", [0, 5, 40])
    def test_evidence_never_comes_back_empty(self, start):
        text = "a" * 60
        assert evidence_span(text, start, start + 1)


class TestTheRealChapterThree:
    """The measurement the design is built on, run against the real corpus."""

    def test_strahd_von_zarovich_is_named_in_exactly_one_section_under_his_full_name(self):
        """THE HEADLINE NUMBER, and it is not 8.

        The book writes "Strahd" in 8 of chapter 3's 22 sections and "Strahd
        von Zarovich" in exactly one. The canonical name is the full one, the
        gazetteer rejects the bare `Strahd` candidate, and matching is
        whole-word against the canonical name alone until aliases exist. So 1
        is what a correct scan returns here, and the remaining 7 are what the
        alias work is for. Pinned so that reaching 8 has to arrive through
        `:Alias` rather than through someone loosening this matcher.
        """
        sections = _real_chapter_three()
        strahd = re.compile(r"(?<!\w)Strahd(?!\w)")
        assert sum(1 for s in sections if strahd.search(s.markdown)) == 8

        spine = spine_of(sections)
        mentions = scan_mentions(
            spine.sections, [("cos:strahd-von-zarovich", "Strahd von Zarovich")], CHAPTER
        )
        assert len(mentions) == 1

    def test_the_chapter_splits_into_the_twenty_two_sections_the_design_measured(self):
        assert len(_real_chapter_three()) == 22


def _real_chapter_three() -> list[Section]:
    """Chapter 3, split the way the spine splits it. Skipped without the corpus."""
    from backend.canon.sections import split_chapter
    from backend.core.config import settings

    if not (settings.ddb_dir / "cos" / "manifest.json").exists():
        pytest.skip("harvested DDB corpus not present")

    from backend.scripts.extract_canon import find_chapter, load_chapters

    chapter = find_chapter(load_chapters("ddb"), "Chapter 3")
    return split_chapter(chapter, splitter="depth").sections


def test_a_mention_is_comparable_by_value():
    """`scan_mentions` results are compared in these tests and deduplicated in
    the writer, both of which need value equality rather than identity."""
    a = WriteMention(
        id="x", entity_id="e", section_id="s", chapter_slug=CHAPTER,
        evidence="q", occurrences=1, offset=0,
    )
    b = WriteMention(
        id="x", entity_id="e", section_id="s", chapter_slug=CHAPTER,
        evidence="q", occurrences=1, offset=0,
    )
    assert a == b
