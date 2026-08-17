"""The narrative spine and the mention scan, without a database.

Everything here is pure: sections in, spine and mentions out. The scan is the
part that decides what the graph knows about where an entity appears, and it is
deterministic by construction -- no model, no cost, and therefore assertable to
the exact node.
"""

import re

import pytest

from backend.canon.models import Section
from backend.canon.passage import PASSAGE_MAX, derive_passage
from backend.canon.spine import (
    AliasUse,
    ChapterSpine,
    EntityNames,
    WriteMention,
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


class TestEmphasisIsABoundary:
    """Markdown emphasis delimits a name; it does not become part of it.

    `_` is a word character to Python's `\\w`, so the lookarounds that make
    matching whole-word also made the book's own italics opaque: `_Tome of
    Strahd_` is how this book sets an item name, and the artifact the whole
    campaign turns on had ZERO mentions because of it.

    Every test below fixes WHICH CHARACTERS COUNT AS A BOUNDARY. None of them
    relaxes HOW STRICT the boundary is, and the second half of this class
    exists to make that failure mode loud: swap the lookarounds for `\\b`, or
    drop them, and those tests fail.
    """

    def test_an_emphasised_multi_word_name_is_still_the_name(self):
        """The defect, exactly. `_Tome of Strahd_` is the book's own setting."""
        assert mention_pattern("Tome of Strahd").search("he reads the _Tome of Strahd_ aloud")

    def test_an_emphasised_single_word_name_is_still_the_name(self):
        assert mention_pattern("Sunsword").search("the _Sunsword_ blazes")

    def test_the_match_is_the_name_and_not_its_delimiters(self):
        """Offsets index the section's own text, so a span that swallowed the
        underscores would put them in the evidence and in `offset`."""
        match = mention_pattern("Sunsword").search("the _Sunsword_ blazes")
        assert match.group() == "Sunsword"
        assert match.span() == (5, 13)

    def test_emphasis_on_one_side_only_is_still_a_boundary(self):
        """Bold-inside-italic and the book's `_**Name.** _` run-in headings put
        a delimiter on one side and ordinary punctuation on the other."""
        assert mention_pattern("Ismark").search("_Ismark, _ he said")
        assert mention_pattern("Ismark").search("said _Ismark_")

    def test_stars_are_a_boundary_too(self):
        """PINNED, NOT FIXED: `*` was never a `\\w` character, so bold and
        star-italic already matched and this test passed before the change.
        It is here because the fix redefines the boundary class, and a class
        that forgot `*` would silently break the emphasis the book uses most."""
        assert mention_pattern("Sunsword").search("the *Sunsword* blazes")
        assert mention_pattern("Sunsword").search("the **Sunsword** blazes")
        assert mention_pattern("Tome of Strahd").search("the _**Tome of Strahd**_")

    def test_emphasis_does_not_relax_the_case_rule(self):
        """PINNED. `Light` is a real LORE entity; italicised prose is still
        prose, and `_light_` is not a proper noun. Fails if the fix reaches for
        `re.IGNORECASE` instead of for the character class."""
        assert not mention_pattern("Light").search("a shaft of _light_ thrusts")

    def test_emphasis_does_not_relax_whole_word_at_the_end(self):
        """PINNED. Fails if the fix drops the trailing lookaround rather than
        redefining it: `Strah` must not find `Strahd`, emphasised or not."""
        assert not mention_pattern("Strah").search("_Strahd_ waits above")
        assert not mention_pattern("Ismar").search("_Ismark_ waits below")

    def test_emphasis_does_not_relax_whole_word_at_the_start(self):
        """PINNED. Fails if the fix drops the leading lookaround."""
        assert not mention_pattern("Doru").search("_Kodoru_ stood in the doorway")

    def test_emphasis_does_not_make_a_plural_the_singular(self):
        """PINNED. The one liberty is the delimiter, not the suffix."""
        assert not mention_pattern("Trapdoor").search("two _trapdoors_ here")

    def test_the_scan_finds_an_emphasised_name_and_anchors_on_it(self):
        """End to end, in the shape the corpus actually has it: the sentence
        `data/ddb/cos/introduction.md` writes, and the mention it never made.

        The offset indexes the section's own text and not a stripped copy, which
        is what lets the passage be derived from the pair later."""
        body = "Strahd's own words are recorded in the _Tome of Strahd_."
        spine = spine_of([sec("Adventure Overview", 3, body)])
        mentions = scan_mentions(
            spine.sections,
            [EntityNames("cos:tome-of-strahd", "Tome of Strahd")],
            CHAPTER,
        )
        assert [m.entity_id for m in mentions] == ["cos:tome-of-strahd"]
        assert mentions[0].occurrences == 1
        assert mentions[0].offset == body.index("Tome of Strahd")
        assert mentions[0].uses == (AliasUse(name="Tome of Strahd", occurrences=1),)
        assert derive_passage(body, mentions[0].offset) == (
            "Strahd's own words are recorded in the Tome of Strahd."
        )

    def test_the_scan_counts_an_emphasised_and_a_plain_naming_once_each(self):
        """PARTLY PINNED: the plain naming already counted, the emphasised one
        did not, so this asserts the arithmetic the fix changes -- one
        occurrence becomes two, and the mention is still one node."""
        body = "The _Tome of Strahd_ lies here. Ireena has read the Tome of Strahd."
        spine = spine_of([sec("Adventure Overview", 3, body)])
        mentions = scan_mentions(
            spine.sections,
            [EntityNames("cos:tome-of-strahd", "Tome of Strahd")],
            CHAPTER,
        )
        assert len(mentions) == 1
        assert mentions[0].occurrences == 2


class TestTheScan:
    def test_an_entity_named_in_a_section_gets_a_mention(self):
        spine = spine_of([sec("E5f. Chapel", 14, "Donavich prays in the chapel.")])
        mentions = scan_mentions(spine.sections, [EntityNames("cos:donavich", "Donavich")], CHAPTER)
        assert [(m.entity_id, m.section_id) for m in mentions] == [
            ("cos:donavich", f"cos:{CHAPTER}#14")
        ]

    def test_an_entity_absent_from_a_section_gets_none(self):
        spine = spine_of([sec("E5f. Chapel", 14, "An empty chapel.")])
        assert (
            scan_mentions(spine.sections, [EntityNames("cos:donavich", "Donavich")], CHAPTER)
            == []
        )

    def test_two_sentences_about_one_entity_in_one_section_are_ONE_mention(self):
        """One node per (entity, section) pair, not per occurrence."""
        spine = spine_of([sec("E5f. Chapel", 14, "Donavich weeps. Donavich prays.")])
        mentions = scan_mentions(spine.sections, [EntityNames("cos:donavich", "Donavich")], CHAPTER)
        assert len(mentions) == 1
        assert mentions[0].occurrences == 2

    def test_two_sections_naming_one_entity_are_two_mentions(self):
        spine = spine_of(
            [
                sec("E5f. Chapel", 14, "Donavich prays."),
                sec("E5g. Undercroft", 15, "Donavich's son is chained here."),
            ]
        )
        mentions = scan_mentions(spine.sections, [EntityNames("cos:donavich", "Donavich")], CHAPTER)
        assert len(mentions) == 2
        assert {m.section_id for m in mentions} == {
            f"cos:{CHAPTER}#14",
            f"cos:{CHAPTER}#15",
        }

    def test_the_mention_id_is_the_pair(self):
        """Re-running the scan must MERGE onto the same node rather than
        doubling it, so identity is the pair and nothing else."""
        spine = spine_of([sec("E5f. Chapel", 14, "Donavich prays.")])
        mentions = scan_mentions(spine.sections, [EntityNames("cos:donavich", "Donavich")], CHAPTER)
        assert mentions[0].id == mention_id("cos:donavich", f"cos:{CHAPTER}#14")
        assert mentions[0].id == f"cos:donavich@cos:{CHAPTER}#14"

    def test_a_mention_stores_no_copy_of_the_prose(self):
        """THE DELETION. A mention is `offset` and `occurrences`; the words are
        the section's, and storing them again put 35,383 characters into the
        graph that were already in it -- 9,894 of them literal duplicates,
        because a paragraph naming three entities stored itself three times."""
        spine = spine_of([sec("E5f. Chapel", 14, "Donavich prays before the altar.")])
        mentions = scan_mentions(spine.sections, [EntityNames("cos:donavich", "Donavich")], CHAPTER)
        assert "evidence" not in mentions[0].properties
        assert not hasattr(mentions[0], "evidence")

    def test_the_facts_about_the_mention_survive_the_deletion(self):
        """`occurrences` and `offset` are NOT copies -- they are what the scan
        learned, and `offset` is what the passage is derived from."""
        spine = spine_of([sec("E5f. Chapel", 14, "Donavich prays. Donavich weeps.")])
        mentions = scan_mentions(spine.sections, [EntityNames("cos:donavich", "Donavich")], CHAPTER)
        assert mentions[0].properties["occurrences"] == 2
        assert mentions[0].properties["offset"] == 0

    def test_the_offset_and_the_section_together_still_give_a_passage(self):
        """The replacement, end to end: nothing is stored, and a reader still
        gets the sentence."""
        body = "A far paragraph about nobody.\n\nDonavich prays before the altar.\n"
        spine = spine_of([sec("E5f. Chapel", 14, body)])
        mentions = scan_mentions(spine.sections, [EntityNames("cos:donavich", "Donavich")], CHAPTER)
        assert derive_passage(body, mentions[0].offset) == "Donavich prays before the altar."

    def test_the_derived_passage_holds_the_name_when_the_paragraph_is_huge(self):
        """A window, not a truncation from the left: a passage that cut the very
        name it is evidence for would be worse than none."""
        body = "filler word " * 400 + "Donavich prays. " + "more filler " * 400
        spine = spine_of([sec("E5f. Chapel", 14, body)])
        mentions = scan_mentions(spine.sections, [EntityNames("cos:donavich", "Donavich")], CHAPTER)
        passage = derive_passage(body, mentions[0].offset)
        assert "Donavich" in passage
        assert passage in body
        assert len(passage) <= PASSAGE_MAX

    def test_a_straight_apostrophe_in_a_name_finds_the_books_curly_one(self):
        """The end-to-end form of the folding: an ASCII name out of the
        extractor against the book's own U+2019. Without it this is zero."""
        body = "You step into Bildrath’s Mercantile."
        spine = spine_of([sec("E1. Bildrath’s Mercantile", 4, body)])
        mentions = scan_mentions(
            spine.sections,
            [EntityNames("cos:bildraths-mercantile", "Bildrath's Mercantile")],
            CHAPTER,
        )
        assert len(mentions) == 1

    def test_the_passage_quotes_the_book_not_the_folded_text(self):
        """Folding U+2019 is a one-for-one character substitution, so match
        offsets index the original exactly and the derived passage keeps the
        book's own typography."""
        body = "You step into Bildrath’s Mercantile."
        spine = spine_of([sec("E1. Bildrath’s Mercantile", 4, body)])
        mentions = scan_mentions(
            spine.sections,
            [EntityNames("cos:bildraths-mercantile", "Bildrath's Mercantile")],
            CHAPTER,
        )
        assert "’" in derive_passage(body, mentions[0].offset)

    def test_the_offset_points_at_the_first_occurrence(self):
        """FIRST, with a second one present to prove it. A section that names
        someone three times is read from where the section first says so."""
        body = "Nobody here. Donavich prays. Later, Donavich weeps."
        spine = spine_of([sec("E5f. Chapel", 14, body)])
        mentions = scan_mentions(spine.sections, [EntityNames("cos:donavich", "Donavich")], CHAPTER)
        assert mentions[0].occurrences == 2
        assert mentions[0].offset == body.index("Donavich")

    def test_the_mention_is_stamped_canon_and_its_chapter(self):
        """The replace path scopes on both, the way an edge's do."""
        spine = spine_of([sec("E5f. Chapel", 14, "Donavich prays.")])
        mention = scan_mentions(
            spine.sections, [EntityNames("cos:donavich", "Donavich")], CHAPTER
        )[0]
        assert mention.properties["plane"] == CANON_PLANE
        assert mention.properties["chapter_slug"] == CHAPTER

    def test_the_scan_is_deterministic_in_the_order_it_emits(self):
        """Two entity orders, one output order: a diff of two runs must be a
        diff of the book, not of a dict's iteration."""
        spine = spine_of([sec("E5f. Chapel", 14, "Donavich and Doru.")])
        entities = [EntityNames("cos:donavich", "Donavich"), EntityNames("cos:doru", "Doru")]
        assert scan_mentions(spine.sections, entities, CHAPTER) == scan_mentions(
            spine.sections, list(reversed(entities)), CHAPTER
        )

    def test_junk_is_not_filtered(self):
        """A `Trapdoor` entity matching many sections makes the junk MORE
        visible, not less. Nothing here suppresses it."""
        spine = spine_of(
            [sec("A", i, "There is a Trapdoor here.") for i in range(40)]
        )
        found = scan_mentions(
            spine.sections, [EntityNames("cos:trapdoor", "Trapdoor")], CHAPTER
        )
        assert len(found) == 40

    def test_an_entity_with_an_unusable_name_is_skipped_rather_than_matching_everything(self):
        spine = spine_of([sec("E5f. Chapel", 14, "Donavich prays.")])
        assert scan_mentions(spine.sections, [EntityNames("cos:blank", "   ")], CHAPTER) == []


class TestScanningUnderAnAlias:
    """The scan looks for an entity under every RECORDED name, and records
    which one the section used. Nothing here infers a name from another."""

    def test_an_alias_finds_a_section_the_canonical_name_does_not(self):
        spine = spine_of([sec("E5f. Chapel", 14, "Strahd is watching.")])
        assert scan_mentions(
            spine.sections, [EntityNames("cos:strahd", "Strahd von Zarovich")], CHAPTER
        ) == []
        found = scan_mentions(
            spine.sections,
            [EntityNames("cos:strahd", "Strahd von Zarovich", aliases=("Strahd",))],
            CHAPTER,
        )
        assert len(found) == 1

    def test_the_mention_still_refers_to_the_entity_not_the_alias(self):
        spine = spine_of([sec("E5f. Chapel", 14, "Strahd is watching.")])
        mention = scan_mentions(
            spine.sections,
            [EntityNames("cos:strahd", "Strahd von Zarovich", aliases=("Strahd",))],
            CHAPTER,
        )[0]
        assert mention.entity_id == "cos:strahd"
        assert mention.id == mention_id("cos:strahd", f"cos:{CHAPTER}#14")

    def test_the_surface_form_the_book_used_is_recorded(self):
        spine = spine_of([sec("E5f. Chapel", 14, "Strahd is watching.")])
        mention = scan_mentions(
            spine.sections,
            [EntityNames("cos:strahd", "Strahd von Zarovich", aliases=("Strahd",))],
            CHAPTER,
        )[0]
        assert mention.uses == (AliasUse("Strahd", 1),)

    def test_two_spellings_in_one_section_are_two_uses_of_one_mention(self):
        """A mention is still one node per (entity, section). Which names were
        used is a SET, which is why it is edges rather than a scalar."""
        body = "The devil Strahd. They say Strahd von Zarovich still rules."
        spine = spine_of([sec("E5f. Chapel", 14, body)])
        mention = scan_mentions(
            spine.sections,
            [EntityNames("cos:strahd", "Strahd von Zarovich", aliases=("Strahd",))],
            CHAPTER,
        )[0]
        assert {u.name for u in mention.uses} == {"Strahd", "Strahd von Zarovich"}
        assert mention.occurrences == 2

    def test_a_run_of_text_two_forms_both_match_is_counted_once(self):
        """`Strahd` matches inside `Strahd von Zarovich`. The section named him
        once, and `occurrences` counts appearances rather than aliases."""
        spine = spine_of([sec("E5f. Chapel", 14, "Only Strahd von Zarovich here.")])
        mention = scan_mentions(
            spine.sections,
            [EntityNames("cos:strahd", "Strahd von Zarovich", aliases=("Strahd",))],
            CHAPTER,
        )[0]
        assert mention.occurrences == 1
        assert mention.uses == (AliasUse("Strahd von Zarovich", 1),)

    def test_the_longer_form_wins_the_overlap_whichever_order_it_arrives_in(self):
        spine = spine_of([sec("E5f. Chapel", 14, "Only Strahd von Zarovich here.")])
        for forms in (("Strahd", "Strahd von Zarovich"), ("Strahd von Zarovich", "Strahd")):
            mention = scan_mentions(
                spine.sections,
                [EntityNames("cos:strahd", "Strahd von Zarovich", aliases=forms)],
                CHAPTER,
            )[0]
            assert mention.uses == (AliasUse("Strahd von Zarovich", 1),)

    def test_uses_are_ordered_most_used_first(self):
        body = "Strahd. Strahd again. And Strahd von Zarovich once."
        spine = spine_of([sec("E5f. Chapel", 14, body)])
        mention = scan_mentions(
            spine.sections,
            [EntityNames("cos:strahd", "Strahd von Zarovich", aliases=("Strahd",))],
            CHAPTER,
        )[0]
        assert mention.uses == (
            AliasUse("Strahd", 2),
            AliasUse("Strahd von Zarovich", 1),
        )

    def test_the_curly_spelling_is_recorded_when_the_book_sets_curly(self):
        """Both forms match -- the scan folds -- and only one of them is what
        the section says. Attributing the ASCII one would put a spelling in the
        graph that the book never set."""
        spine = spine_of([sec("E1", 4, "You step into Bildrath’s Mercantile.")])
        mention = scan_mentions(
            spine.sections,
            [
                EntityNames(
                    "cos:e1",
                    "Bildrath's Mercantile",
                    aliases=("Bildrath’s Mercantile",),
                )
            ],
            CHAPTER,
        )[0]
        assert mention.uses == (AliasUse("Bildrath’s Mercantile", 1),)

    def test_the_straight_spelling_is_recorded_when_the_book_sets_straight(self):
        spine = spine_of([sec("E1", 4, "You step into Bildrath's Mercantile.")])
        mention = scan_mentions(
            spine.sections,
            [
                EntityNames(
                    "cos:e1",
                    "Bildrath’s Mercantile",
                    aliases=("Bildrath's Mercantile",),
                )
            ],
            CHAPTER,
        )[0]
        assert mention.uses == (AliasUse("Bildrath's Mercantile", 1),)

    def test_typography_is_a_closer_match_than_casing(self):
        """When the exact spelling is not recorded, the form differing only by
        apostrophe beats the form differing by case.

        U+2019 and `'` are one character substituted for another and nothing
        else -- that is stated as the whole of the folding. Case is a difference
        in what the book actually set. So `Zz’s Q` is a nearer record of
        `Zz's Q` than `Zz’S Q` is, and a rank that could not tell them apart
        would fall back to alphabetical order, which here prefers the wrong one.
        """
        spine = spine_of([sec("E1", 4, "Deep inside Zz's Q it is dark.")])
        mention = scan_mentions(
            spine.sections,
            [EntityNames("cos:q", "Zz’S Q", aliases=("Zz’s Q",))],
            CHAPTER,
        )[0]
        assert mention.uses == (AliasUse("Zz’s Q", 1),)

    def test_a_single_word_alias_keeps_the_case_sensitive_rule(self):
        """`Light` the LORE entity must not claim every lit torch, and an alias
        is not a way around that."""
        spine = spine_of([sec("E5f. Chapel", 14, "a shaft of light")])
        assert scan_mentions(
            spine.sections,
            [EntityNames("cos:radiance", "Radiance", aliases=("Light",))],
            CHAPTER,
        ) == []

    def test_a_multi_word_alias_keeps_the_case_insensitive_rule(self):
        spine = spine_of([sec("E2", 5, "the blood on the vine tavern")])
        found = scan_mentions(
            spine.sections,
            [
                EntityNames(
                    "cos:e2",
                    "Blood of the Vine Tavern",
                    aliases=("Blood on the Vine Tavern",),
                )
            ],
            CHAPTER,
        )
        assert len(found) == 1

    def test_an_alias_is_whole_word_like_every_other_name(self):
        spine = spine_of([sec("E5f. Chapel", 14, "Strahdian rites.")])
        assert scan_mentions(
            spine.sections,
            [EntityNames("cos:strahd", "Strahd von Zarovich", aliases=("Strahd",))],
            CHAPTER,
        ) == []

    def test_an_alias_belongs_to_one_entity_and_does_not_leak(self):
        spine = spine_of([sec("E5f. Chapel", 14, "Strahd is watching.")])
        found = scan_mentions(
            spine.sections,
            [
                EntityNames("cos:strahd", "Strahd von Zarovich", aliases=("Strahd",)),
                EntityNames("cos:doru", "Doru"),
            ],
            CHAPTER,
        )
        assert [m.entity_id for m in found] == ["cos:strahd"]

    def test_the_passage_quotes_the_sentence_the_alias_matched(self):
        body = "Nobody here. Strahd is watching."
        spine = spine_of([sec("E5f. Chapel", 14, body)])
        mention = scan_mentions(
            spine.sections,
            [EntityNames("cos:strahd", "Strahd von Zarovich", aliases=("Strahd",))],
            CHAPTER,
        )[0]
        assert derive_passage(body, mention.offset) == "Strahd is watching."

    def test_the_offset_points_at_the_alias_not_the_canonical_name(self):
        body = "Nobody here. Strahd is watching."
        spine = spine_of([sec("E5f. Chapel", 14, body)])
        mention = scan_mentions(
            spine.sections,
            [EntityNames("cos:strahd", "Strahd von Zarovich", aliases=("Strahd",))],
            CHAPTER,
        )[0]
        assert body[mention.offset:].startswith("Strahd")

    def test_the_offset_points_at_the_first_appearance_whichever_form_it_used(self):
        """The alias comes first and the full name second, and the LONGER span
        is resolved first internally -- so a mention that reported the last span
        it happened to keep would quote the wrong half of the section."""
        body = "Strahd walked here. Later, Strahd von Zarovich returned."
        spine = spine_of([sec("E5f. Chapel", 14, body)])
        mention = scan_mentions(
            spine.sections,
            [EntityNames("cos:strahd", "Strahd von Zarovich", aliases=("Strahd",))],
            CHAPTER,
        )[0]
        assert mention.occurrences == 2
        assert mention.offset == 0

    def test_forms_always_hold_the_canonical_name(self):
        """A caller cannot construct an entity the scan will not look for under
        its own name -- that would be a silent zero by configuration."""
        assert EntityNames("cos:e", "Doru", aliases=("Doru the Spawn",)).forms == (
            "Doru",
            "Doru the Spawn",
        )
        assert EntityNames("cos:e", "Doru", aliases=("Doru",)).forms == ("Doru",)


class TestMentionCounts:
    def test_counts_are_reported_per_entity(self):
        from backend.canon.spine import mention_counts

        spine = spine_of(
            [sec("A", 0, "Donavich and Doru."), sec("B", 1, "Donavich alone.")]
        )
        entities = [EntityNames("cos:donavich", "Donavich"), EntityNames("cos:doru", "Doru")]
        mentions = scan_mentions(spine.sections, entities, CHAPTER)
        assert mention_counts(mentions, {e.id: e.name for e in entities}) == [
            ("Donavich", 2),
            ("Doru", 1),
        ]


SOFT = "­"


class TestTheTypesettersSoftHyphen:
    """U+00AD sits inside seven proper nouns in this corpus -- `Kol<AD>yanovich`,
    `Van Rich<AD>ten's`, `Argyn<AD>vost`. It renders as nothing, so the book is
    spelling ordinary names, and the scan has to see them."""

    def test_a_name_the_book_hyphenated_is_still_found(self):
        text = f"a man named Ismark Kol{SOFT}yanovich sat there"
        assert mention_pattern("Ismark Kolyanovich").search(text)

    def test_folding_the_text_does_not_change_its_length(self):
        """THE CONSTRAINT EVERYTHING ELSE RESTS ON. A mention stores an offset
        into `section.text`; any normalization that changes the text's length
        moves every offset after it and makes the derived passage quote the
        wrong span. So the matcher absorbs the soft hyphen and the text keeps
        it."""
        text = f"Ismark Kol{SOFT}yanovich and Bildrath’s"
        assert len(fold_apostrophe(text)) == len(text)

    def test_the_offset_reported_indexes_the_original_text(self):
        text = f"The priest met Ismark Kol{SOFT}yanovich outside."
        match = mention_pattern("Ismark Kolyanovich").search(text)
        assert text[match.start():match.end()] == f"Ismark Kol{SOFT}yanovich"

    def test_a_name_carrying_one_still_matches_text_without_it(self):
        """The other direction: extraction may hand us the hyphenated spelling."""
        assert mention_pattern(f"Argyn{SOFT}vost").search("the ghost of Argynvost rose")

    def test_it_is_not_a_wildcard_between_words(self):
        """`\\xad*` must not turn into 'any characters here'."""
        assert mention_pattern("Mad Mary").search("Mad Xavier Mary") is None

    def test_a_partial_word_is_still_not_a_match(self):
        assert mention_pattern("Doru").search(f"Dor{SOFT}ugan") is None

    def test_normalize_treats_the_two_spellings_as_one_name(self):
        from backend.canon.aliases import normalize

        assert normalize(f"Ismark Kol{SOFT}yanovich") == normalize("Ismark Kolyanovich")

    def test_a_rendered_passage_does_not_show_it(self):
        from backend.canon.passage import derive_passage

        text = f"The priest met Ismark Kol{SOFT}yanovich outside."
        assert SOFT not in derive_passage(text, 15)


class TestHelpers:
    def test_fold_touches_only_the_right_single_quote(self):
        assert fold_apostrophe("Bildrath’s") == "Bildrath's"
        assert fold_apostrophe("Mad Mary") == "Mad Mary"

    def test_section_id_and_mention_id_round_trip_into_each_other(self):
        sid = section_id(CHAPTER, 14)
        assert mention_id("cos:donavich", sid).endswith(sid)



class TestTheRealChapterThree:
    """The measurement the design is built on, run against the real corpus."""

    def test_strahd_is_named_in_eight_of_the_twenty_two_sections(self):
        """THE HEADLINE NUMBER. Eight, and it arrives through `:Alias`.

        The book writes "Strahd" in 8 of chapter 3's 22 sections and "Strahd von
        Zarovich" in exactly one. Recording `Strahd` as an alias is the entire
        distance between the two figures -- the matcher below is the same
        whole-word, case-sensitive-for-one-word matcher it was, and nothing
        infers that the two strings name one man.
        """
        sections = _real_chapter_three()
        strahd = re.compile(r"(?<!\w)Strahd(?!\w)")
        assert sum(1 for s in sections if strahd.search(s.markdown)) == 8

        spine = spine_of(sections)
        mentions = scan_mentions(
            spine.sections,
            [
                EntityNames(
                    "cos:strahd-von-zarovich",
                    "Strahd von Zarovich",
                    aliases=("Strahd", "Strahd von Zarovich"),
                )
            ],
            CHAPTER,
        )
        assert len(mentions) == 8

    def test_without_the_alias_the_same_scan_finds_one(self):
        """The before, kept beside the after. If this ever also returns 8 the
        matcher has been loosened and the alias node is doing nothing."""
        spine = spine_of(_real_chapter_three())
        mentions = scan_mentions(
            spine.sections,
            [EntityNames("cos:strahd-von-zarovich", "Strahd von Zarovich")],
            CHAPTER,
        )
        assert len(mentions) == 1

    def test_the_preamble_names_him_in_full_and_is_counted_once(self):
        """Section 0 contains "Strahd von Zarovich", so both recorded forms
        match the same run of text. The section names him once."""
        spine = spine_of(_real_chapter_three())
        mentions = scan_mentions(
            spine.sections,
            [
                EntityNames(
                    "cos:strahd-von-zarovich",
                    "Strahd von Zarovich",
                    aliases=("Strahd", "Strahd von Zarovich"),
                )
            ],
            CHAPTER,
        )
        preamble = next(m for m in mentions if m.section_id.endswith("#0"))
        assert "Strahd von Zarovich" in {u.name for u in preamble.uses}

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
        occurrences=1, offset=0, entity_name="Entity",
    )
    b = WriteMention(
        id="x", entity_id="e", section_id="s", chapter_slug=CHAPTER,
        occurrences=1, offset=0, entity_name="Entity",
    )
    assert a == b
