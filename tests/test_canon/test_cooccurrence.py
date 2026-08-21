"""Which entities the book names in the same sentence.

Pure: sections and mentions in, `(mention, entity)` pairs out. No database, no
model, no cost.

EVERY MENTION HERE COMES FROM `scan_mentions`, never from a hand-written
`offset`. A fixture that states its own offsets can agree with an assertion
while disagreeing with the prose, which is the exact shape of a test that passes
either side of the bug it guards. Here the offsets are what the scanner found in
the text the test wrote, so a pair the plan reports can always be checked by
reading the string above it.

COUNTS ARE ASSERTED ON THE LIST, never on a set of it. The whole quantity under
test is HOW MANY pairs a sentence produces -- eight entities is 8x7 -- and a
`set` comprehension would absorb a duplicated row and report the number the
assertion wanted. `len(planned)` first, membership second.
"""

import pytest

from backend.canon.cooccurrence import (
    CoOccurrence,
    co_occurrence_counts,
    plan_co_occurrences,
    widest_sentence,
)
from backend.canon.spine import EntityNames, WriteSection, scan_mentions

CHAPTER = "test-chapter"


def section(text: str, index: int = 0) -> WriteSection:
    return WriteSection(
        id=f"cos:{CHAPTER}#{index}",
        chapter_slug=CHAPTER,
        heading=f"Section {index}",
        index=index,
        depth=1,
        parent_index=-1,
        text=text,
    )


def entity(name: str) -> EntityNames:
    """An entity whose id is derived from its name, so a pair reads back."""
    return EntityNames(id=name.lower().replace(" ", "-"), name=name)


def plan(*sections: WriteSection, names: list[str]) -> list[CoOccurrence]:
    """The plan for these sections, scanned for these entity names."""
    entities = [entity(n) for n in names]
    mentions = scan_mentions(sections, entities, CHAPTER)
    return plan_co_occurrences(sections, mentions)


def pairs(text: str, *names: str) -> list[tuple[str, str]]:
    """`(the mention's own entity, the entity it co-occurs with)`, by id.

    A list, in the plan's own order. Deliberately NOT a set -- see the module
    docstring.
    """
    only = section(text)
    return [
        (planned.mention_id.split("@")[0], planned.entity_id)
        for planned in plan(only, names=list(names))
    ]


class TestOneSentence:
    def test_two_names_in_one_sentence_co_occur_both_ways(self):
        """Two mentions, so two (mention, entity) pairs -- and the count is the
        point: 2, not 1 and not 4."""
        found = pairs(
            "Donavich prays for Ireena at the altar.", "Donavich", "Ireena"
        )
        assert len(found) == 2
        assert sorted(found) == [("donavich", "ireena"), ("ireena", "donavich")]

    def test_a_mention_never_co_occurs_with_its_own_entity(self):
        """Named twice in one sentence and it is still one entity, so nothing
        is recorded at all."""
        assert pairs("Ireena fears for Ireena's brother.", "Ireena") == []

    def test_three_names_in_one_sentence_produce_three_times_two(self):
        """The number to watch. n names is n(n-1) pairs, and this is the
        smallest case where that is not also n."""
        found = pairs(
            "Strahd rules Barovia from Castle Ravenloft.",
            "Strahd",
            "Barovia",
            "Castle Ravenloft",
        )
        assert len(found) == 6
        assert sorted(found) == [
            ("barovia", "castle-ravenloft"),
            ("barovia", "strahd"),
            ("castle-ravenloft", "barovia"),
            ("castle-ravenloft", "strahd"),
            ("strahd", "barovia"),
            ("strahd", "castle-ravenloft"),
        ]

    def test_four_names_in_one_sentence_produce_four_times_three(self):
        found = pairs(
            "Strahd, Barovia, Madam Eva and the tarokka deck are all named here.",
            "Strahd",
            "Barovia",
            "Madam Eva",
            "tarokka deck",
        )
        assert len(found) == 12

    def test_a_lone_name_co_occurs_with_nothing(self):
        assert pairs("Donavich prays alone.", "Donavich") == []


class TestSentenceIsTheBoundary:
    """The whole reason the granularity is a sentence and not a section."""

    def test_a_name_in_the_next_sentence_does_not_co_occur(self):
        assert pairs(
            "Doru is chained below. Donavich prays at the altar.",
            "Doru",
            "Donavich",
        ) == []

    def test_a_name_in_another_paragraph_does_not_co_occur(self):
        assert pairs(
            "Doru is chained below\n\nDonavich prays at the altar",
            "Doru",
            "Donavich",
        ) == []

    def test_a_name_in_another_section_does_not_co_occur(self):
        """Both sentences start at offset 0, so a plan that grouped by offset
        without the section would pair all four names with each other."""
        first = section("Doru calls to Donavich.", 0)
        second = section("Ismark walks with Ireena.", 1)
        found = plan(
            first, second, names=["Doru", "Donavich", "Ismark", "Ireena"]
        )
        # Two pairs inside each section and nothing across them: 4, not 12.
        assert len(found) == 4
        assert sorted((c.mention_id.split("@")[1], c.entity_id) for c in found) == [
            (first.id, "donavich"),
            (first.id, "doru"),
            (second.id, "ireena"),
            (second.id, "ismark"),
        ]

    def test_the_section_is_not_the_unit(self):
        """Three sentences naming three entities is a section they share and
        NOT a sentence, so the pair count is zero rather than six."""
        assert pairs(
            "Strahd broods. Barovia sleeps. Castle Ravenloft waits.",
            "Strahd",
            "Barovia",
            "Castle Ravenloft",
        ) == []


class TestItReusesTheSpanRule:
    """`passage.sentence_bounds` decides what one sentence is, here and in
    `lookup`. These are the cases where a second, naive rule would disagree --
    each one splits under `[.?!]\\s` and must not split here."""

    def test_a_titles_period_does_not_separate_two_entities(self):
        found = pairs(
            "Milivoj digs a grave outside St. Andral's Church while Ireena waits.",
            "St. Andral's Church",
            "Ireena",
        )
        assert len(found) == 2

    def test_a_keyed_area_code_does_not_separate_two_entities(self):
        found = pairs(
            "The Sunsword lies beyond area K42. Strahd guards it.",
            "Sunsword",
            "Strahd",
        )
        assert len(found) == 2

    def test_a_bare_initial_does_not_separate_two_entities(self):
        found = pairs(
            "See appendix D. Ireena travels with Ismark.", "Ireena", "Ismark"
        )
        assert len(found) == 2

    def test_a_newline_still_separates_them(self):
        """A hard boundary in the shared rule, and a table row is why."""
        assert pairs(
            "| Sunsword | 9th |\n| Tome of Strahd | 5th |",
            "Sunsword",
            "Tome of Strahd",
        ) == []

    def test_a_heading_does_not_co_occur_with_the_prose_beneath_it(self):
        assert pairs(
            "### E5f. Chapel\nDonavich prays here.", "Chapel", "Donavich"
        ) == []


class TestSymmetry:
    """The relation is symmetric IN MEANING, so the graph may not record one
    direction of a pair and drop the other."""

    def test_every_pair_is_recorded_from_both_ends(self):
        found = pairs(
            "Strahd rules Barovia from Castle Ravenloft.",
            "Strahd",
            "Barovia",
            "Castle Ravenloft",
        )
        assert sorted(found) == sorted((b, a) for a, b in found)

    def test_a_sentence_over_the_passage_cap_is_still_symmetric(self):
        """`sentence_bounds` falls back to a WINDOW past `PASSAGE_MAX`, and the
        window is placed around the offset it was asked about -- so for a long
        enough sentence, A's window holds B while B's window does not hold A.

        The corpus contains exactly one such pair (`tinderbox` and a book title
        87 characters long, in chapter 3), and under a one-directional read the
        graph would say the tinderbox co-occurs with the book and the book with
        nothing. That is an artefact of a RENDERING cap, so it may not decide
        the direction of a fact.
        """
        filler = "a chest of assorted oddments and curiosities and trinkets, "
        text = (
            "Inside are a tinderbox, "
            + filler * 4
            + "and the Sunsword, wrapped in oilcloth beneath it all."
        )
        found = pairs(text, "tinderbox", "Sunsword")
        assert len(found) == 2
        assert sorted(found) == [("sunsword", "tinderbox"), ("tinderbox", "sunsword")]


class TestNoDuplicates:
    """`assert len(found) == len(set(found))` USED TO BE THE FIRST TEST HERE and
    was deleted: no mutation of the planner could make it fail. A `:Mention`
    carries one offset, so an offset-based planner cannot emit a row twice, and
    the assertion held for every wrong implementation as well as the right one.

    The duplicate guard that CAN fail is in `test_write_canon_neo4j.py`: the
    graph's `CO_OCCURS_WITH` count is compared against `len(plan)`, and the
    write MERGEs, so a plan that emitted a row twice would silently land one
    edge and the two numbers would part. Both tests below discriminate -- each
    dies under a planner that pairs per occurrence or per unordered pair.
    """

    def test_naming_an_entity_twice_in_a_sentence_is_still_one_row(self):
        """`occurrences` counts repetition; the pair does not."""
        found = pairs(
            "Ireena walks with Ismark, and Ismark answers Ireena.",
            "Ireena",
            "Ismark",
        )
        assert len(found) == 2

    def test_two_sentences_naming_the_same_pair_is_still_one_row_each_way(self):
        """One `:Mention` per (entity, section), so a section that pairs the
        same two entities in two sentences has only two mentions to hang edges
        off -- and the plan must not emit four rows for them."""
        found = pairs(
            "Ireena walks with Ismark. Ireena thanks Ismark again.",
            "Ireena",
            "Ismark",
        )
        assert len(found) == 2


class TestDeterminism:
    def test_the_plan_is_ordered_and_repeatable(self):
        text = "Strahd rules Barovia from Castle Ravenloft."
        names = ["Castle Ravenloft", "Strahd", "Barovia"]
        first = plan(section(text), names=names)
        second = plan(section(text), names=list(reversed(names)))
        assert first == second
        assert first == sorted(first, key=lambda c: (c.mention_id, c.entity_id))


class TestEveryOccurrenceCounts:
    """This was a stated limitation, and the statement understated it.

    A `:Mention` used to store ONE offset -- where the section first says the
    name -- so an entity named in sentences 1 and 5 anchored in sentence 1 and
    its later appearances were invisible. That hid 2,970 of the corpus's 6,966
    spans and left 478 of 907 entities co-occurring with nothing, including
    every entity in "Three Vistani spies named Alenka, Mirabel, and Sorvia" --
    four names in ONE sentence, no pairs, because `Vistani` had been anchored
    3,300 characters earlier.
    """

    def test_a_shared_LATER_sentence_is_seen(self):
        """Ireena is named in both sentences; Ismark only in the second. The
        pairing lives entirely in her second span."""
        assert pairs(
            "Ireena arrives first. Ismark greets Ireena warmly.",
            "Ireena",
            "Ismark",
        ) != []

    def test_the_sentence_rule_itself_did_not_widen(self):
        """The old note was right that a rule swallowing a paragraph would
        square the graph. What widened is what the window may look at."""
        assert pairs(
            "Ireena arrives first. Ismark waits outside.",
            "Ireena",
            "Ismark",
        ) == []

    def test_the_tavern_sentence_pairs_all_four(self):
        """The measured case, in the book's own words."""
        text = (
            "Three Vistani spies (N female humans) named Alenka, Mirabel, and "
            "Sorvia sit at a table near the front door."
        )
        for other in ("Alenka", "Mirabel", "Sorvia"):
            assert pairs(text, "Vistani", other) != [], other


class TestAMentionMustHaveItsSection:
    def test_a_mention_whose_section_is_absent_raises(self):
        """A silent skip is how a chapter acquires fewer edges than it planned
        with nothing appearing to fail."""
        only = section("Donavich prays for Ireena.")
        mentions = scan_mentions(
            [only], [entity("Donavich"), entity("Ireena")], CHAPTER
        )
        with pytest.raises(ValueError, match="no section"):
            plan_co_occurrences([], mentions)


class TestTheCensus:
    """What gets printed on every write, so the count the design says to watch
    is watched at twenty-five chapters and not only at three."""

    DENSE = (
        "Strahd rules Barovia from Castle Ravenloft. "
        "Doru is chained beneath the chapel."
    )
    NAMES = ["Strahd", "Barovia", "Castle Ravenloft", "Doru"]

    def _parts(self):
        only = section(self.DENSE)
        entities = [entity(n) for n in self.NAMES]
        mentions = scan_mentions([only], entities, CHAPTER)
        planned = plan_co_occurrences([only], mentions)
        return [only], mentions, planned, {e.id: e.name for e in entities}

    def test_counts_rank_the_entities_the_most_sentences_reach(self):
        _, _, planned, names = self._parts()
        counts = co_occurrence_counts(planned, names)
        assert counts == [
            ("Barovia", 2),
            ("Castle Ravenloft", 2),
            ("Strahd", 2),
        ]

    def test_the_widest_sentence_is_the_densest_one_and_not_the_section(self):
        sections, mentions, planned, names = self._parts()
        widest = widest_sentence(sections, mentions, planned, names)
        # Three, not four: Doru is in the second sentence.
        assert widest.entities == 3
        assert widest.names == ("Barovia", "Castle Ravenloft", "Strahd")
        assert widest.passage == "Strahd rules Barovia from Castle Ravenloft."

    def test_the_widest_sentence_is_none_when_nothing_paired(self):
        only = section("Donavich prays alone.")
        entities = [entity("Donavich")]
        mentions = scan_mentions([only], entities, CHAPTER)
        assert widest_sentence([only], mentions, [], {}) is None

    def test_the_widest_count_agrees_with_the_pair_count(self):
        """n(n-1) for the densest sentence is a lower bound on the total, and a
        census derived from a second traversal of the span rule could report a
        width the edges do not support."""
        sections, mentions, planned, names = self._parts()
        widest = widest_sentence(sections, mentions, planned, names)
        assert len(planned) == widest.entities * (widest.entities - 1)
