"""The sentence span, and the passage derived from it.

Pure: text and an offset in, offsets and a string out. No database, no model.

Two properties carry the weight, and they pull in opposite directions. A span
must never cut mid-word -- a passage that ends `Strah` is worse than no passage.
A span may be slightly too long, because the failure mode of a missed boundary
is a reader who gets an extra sentence, and the failure mode of a false one is a
reader who gets half a name. Every abbreviation case below therefore asserts
that the span is NOT split, never that it is.
"""

import pytest

from backend.canon.passage import PASSAGE_MAX, derive_passage, sentence_bounds


def passage_of(text: str, name: str) -> str:
    """The passage the graph would show for a mention of `name` in `text`."""
    return derive_passage(text, text.index(name))


class TestTheContainingSentence:
    def test_it_returns_the_sentence_the_offset_is_in(self):
        text = "Doru is chained below. Donavich prays. Ireena waits outside."
        assert passage_of(text, "Donavich") == "Donavich prays."

    def test_it_does_not_return_the_whole_paragraph(self):
        """The point of the change: a paragraph naming three entities stored
        three copies of itself, and the sentence is what a reader wanted."""
        text = "Doru is chained below. Donavich prays. Ireena waits outside."
        assert "Ireena" not in passage_of(text, "Donavich")
        assert "Doru" not in passage_of(text, "Donavich")

    def test_a_question_mark_ends_a_sentence(self):
        text = "Who weeps below? Donavich does."
        assert passage_of(text, "Donavich") == "Donavich does."

    def test_an_exclamation_mark_ends_a_sentence(self):
        text = "Let me out! Donavich weeps at the trapdoor."
        assert passage_of(text, "Donavich") == "Donavich weeps at the trapdoor."

    def test_a_closing_quote_stays_with_the_sentence_it_closes(self):
        """`.”` is one boundary, not a boundary followed by a stray mark."""
        text = "“Let me out, father!” Donavich weeps at the trapdoor."
        assert passage_of(text, "Donavich") == "Donavich weeps at the trapdoor."

    def test_the_first_sentence_of_a_paragraph_needs_no_boundary_behind_it(self):
        text = "Donavich prays before the altar. Nobody answers."
        assert passage_of(text, "Donavich") == "Donavich prays before the altar."

    def test_the_last_sentence_of_a_paragraph_needs_no_boundary_ahead_of_it(self):
        """No trailing punctuation at all -- the text simply stops."""
        text = "Nobody answers. Donavich prays before the altar"
        assert passage_of(text, "Donavich") == "Donavich prays before the altar"

    def test_a_blank_line_ends_a_passage(self):
        text = "A far paragraph about nobody.\n\nDonavich prays before the altar."
        assert passage_of(text, "Donavich") == "Donavich prays before the altar."


class TestAbbreviationsDoNotEndSentences:
    """Each of these is a period that a naive `[.?!]\\s` split treats as a
    sentence end, and each one would cut a name in half. The corpus supplies
    every case: 578 keyed-area codes, 18 `St. Andral`, three lettered
    appendices."""

    def test_a_titles_period_does_not_split_a_name(self):
        text = "Milivoj is digging a grave outside St. Andral's Church tonight."
        assert passage_of(text, "Andral") == text

    def test_a_keyed_area_code_does_not_end_a_sentence(self):
        text = "The vault lies beyond area K42. The door is barred by iron."
        assert passage_of(text, "K42") == text

    def test_a_keyed_heading_keeps_the_name_it_keys(self):
        """`### E5f. Chapel` is how this book heads a room. Split at the code
        and the passage for the Chapel is the string `### E5f.`"""
        assert passage_of("### E5f. Chapel", "Chapel") == "### E5f. Chapel"

    def test_a_lettered_appendix_does_not_end_a_sentence(self):
        text = "Stat blocks are in appendix D. When a name appears in bold, see it."
        assert passage_of(text, "appendix") == text

    def test_a_numbered_list_marker_does_not_end_a_sentence(self):
        text = "2. The Vistani camp lies east of the village."
        assert passage_of(text, "Vistani") == text

    def test_a_real_boundary_is_still_a_boundary_after_a_short_word(self):
        """The guard must not swallow every short word. `cp` is not an
        abbreviation in this corpus -- it is a coin, and the sentence ends."""
        text = "A glass of wine costs 1 cp. Arik returns to cleaning mugs."
        assert passage_of(text, "Arik") == "Arik returns to cleaning mugs."


class TestTheCap:
    def test_a_run_on_paragraph_is_capped(self):
        text = "word " * 400 + "Donavich prays."
        assert len(derive_passage(text, text.index("Donavich"))) <= PASSAGE_MAX

    def test_the_cap_never_cuts_mid_word(self):
        """A span may be short of a boundary; it may never end inside a word.
        `supercalifragilistic` is one token longer than the cap's stride, so a
        naive slice lands inside it."""
        text = "Donavich prays. " + "antidisestablishmentarianism " * 20
        passage = derive_passage(text, 0)
        for token in passage.split():
            assert token in text.split(), token

    def test_the_capped_span_still_holds_the_name_it_is_evidence_for(self):
        """Truncating from the left would produce a passage that cut off the
        very name it exists to show."""
        text = "filler word " * 400 + "Donavich prays. " + "more filler " * 400
        assert "Donavich" in derive_passage(text, text.index("Donavich"))

    def test_the_bounds_always_contain_the_offset(self):
        text = "filler word " * 400 + "Donavich prays. " + "more filler " * 400
        offset = text.index("Donavich")
        low, high = sentence_bounds(text, offset)
        assert low <= offset < high


class TestNewlinesBoundAPassage:
    """This corpus never hard-wraps a prose paragraph -- checked across all 25
    chapters -- so a newline is always a row, a heading or a quote gutter, and
    never the middle of a sentence."""

    def test_a_table_row_is_its_own_passage(self):
        text = (
            "| Avg. Level | Area | Chapter |\n"
            "| --- | --- | --- |\n"
            "| 1st-3rd | Village of Barovia | 3 |\n"
            "| 9th | The Amber Temple | 13 |\n"
        )
        assert passage_of(text, "Amber Temple") == "| 9th | The Amber Temple | 13 |"

    def test_a_heading_does_not_run_into_the_prose_beneath_it(self):
        """The newline rule itself is unchanged: a passage never spans the break.

        What changed is the ANCHOR. *Corrected 2026-08-17.* This test used to
        assert `passage_of(...) == "### E5. Church"` -- that a mention landing in
        a heading yields the heading. The rule was right and the outcome was
        useless: a keyed section names its own place in its title, so the first
        (and only stored) occurrence of `Blood of the Vine Tavern` in section E2
        is at character 8, and the passage a DM got for the tavern was
        32 characters of heading. Measured on the live graph: 20 of 153
        mentions, and not a random 20 -- every keyed room and building.

        So an offset inside the heading now anchors on the body instead. The
        passage still does not cross the newline; it starts on the other side of
        it.
        """
        text = "### E5. Church\nDonavich prays before the altar."
        assert passage_of(text, "Church") == "Donavich prays before the altar."

    def test_an_offset_already_in_the_body_is_left_alone(self):
        text = "### E5. Church\nDonavich prays. Doru screams below."
        assert passage_of(text, "Doru") == "Doru screams below."


class TestMarkdownMarkers:
    """DECISION: emphasis markers are STRIPPED from the derived passage, always,
    not only when a span cuts one in half. A rule that stripped only unbalanced
    markers would render the same paragraph differently depending on where it
    was cut, and a DM reads `Tome of Strahd`, not `_Tome of Strahd_`. The
    offsets `sentence_bounds` returns are untouched by this, so the span itself
    remains a literal region of the section."""

    def test_italics_are_stripped(self):
        text = "Strahd's own words are recorded in the _Tome of Strahd_."
        assert passage_of(text, "Tome") == "Strahd's own words are recorded in the Tome of Strahd."

    def test_a_bold_run_in_header_loses_its_stars(self):
        text = "**Finding Artifacts.** The treasures are hidden across Barovia."
        assert "*" not in passage_of(text, "Artifacts")

    def test_a_span_that_begins_mid_emphasis_leaves_no_stray_marker(self):
        """The failure this decision exists for: the span starts inside an
        italic run, so exactly one delimiter falls inside it."""
        text = "_**Vistani Owners. **_Three Vistani spies sit near the door."
        passage = passage_of(text, "spies")
        assert "_" not in passage
        assert "*" not in passage

    def test_stripping_does_not_eat_an_underscore_bearing_word(self):
        """The strip is a rendering of prose, and this corpus's underscores are
        always emphasis -- but the passage must still read as words."""
        text = "The _Tome of Strahd_ lies here."
        assert passage_of(text, "Tome") == "The Tome of Strahd lies here."


class TestItNeverComesBackEmpty:
    @pytest.mark.parametrize("offset", [0, 5, 40, 59])
    def test_a_passage_is_returned_for_any_offset_in_the_text(self, offset):
        assert derive_passage("a" * 60, offset)

    def test_an_offset_past_the_end_does_not_raise(self):
        """Defensive: `offset` comes off a node, and a section re-split under a
        different splitter would leave one pointing past the end."""
        assert derive_passage("Donavich prays.", 9_999) is not None

    def test_empty_text_yields_an_empty_passage_rather_than_an_error(self):
        assert derive_passage("", 0) == ""

    def test_whitespace_is_trimmed_off_both_ends(self):
        text = "Nobody here.   Donavich prays.   Nobody answers."
        assert passage_of(text, "Donavich") == "Donavich prays."


class TestTheSpanIsReusable:
    """Section 2 of the design computes co-occurrence from THIS span: the other
    entities whose own mention offsets fall inside it. That is why the rule
    returns offsets and not only a string."""

    def test_two_names_in_one_sentence_share_a_span(self):
        text = "Doru is chained below. Donavich prays for Ireena at the altar."
        donavich, ireena = text.index("Donavich"), text.index("Ireena")
        assert sentence_bounds(text, donavich) == sentence_bounds(text, ireena)

    def test_a_name_in_the_next_sentence_falls_outside_the_span(self):
        text = "Doru is chained below. Donavich prays for Ireena at the altar."
        low, high = sentence_bounds(text, text.index("Donavich"))
        assert not low <= text.index("Doru") < high

    def test_the_bounds_index_the_text_they_were_read_from(self):
        """A literal region, so `text[low:high]` is checkable against the
        section rather than merely asserted."""
        text = "Doru is chained below. Donavich prays."
        low, high = sentence_bounds(text, text.index("Donavich"))
        assert text[low:high] == "Donavich prays."
