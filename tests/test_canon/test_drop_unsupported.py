"""The two judgements that decide whether canon gets deleted.

This script removes entities from the book's own plane, so the interesting
tests are the ones that keep it from removing the wrong thing. Both cases here
are real rows it was pointed at: `Gunther Arasek`, who the book names only as
half of "Gunther and Yelena Arasek", and `Spellbook`, which the book writes
only in lowercase and which the scan is right to refuse.
"""

from backend.scripts.drop_unsupported import (
    _book_may_name_it,
    _distinctive,
    _held_by_a_campaign,
)


class TestTheBookMayStillBeSayingIt:
    """The same inference `spine.mention_pattern` makes: a capitalised word in
    running prose is a proper noun, a lowercase one is not."""

    def test_a_person_named_only_as_half_of_a_pair_is_held_back(self):
        """`Gunther Arasek` holds no mention because his name is never one run
        of text. Dropping him would delete correct canon."""
        prose = ("It is owned by a middle-aged married couple, Gunther and "
                 "Yelena Arasek (LG male and female commoners).")
        assert _book_may_name_it("Gunther Arasek", prose) == "Gunther"

    def test_a_declined_surname_is_held_back(self):
        """The node dropped the feminine ending the book uses. `Krezkov` is
        correctly NOT found inside `Krezkova` -- whole-word means whole word --
        and the given name carries the holdback instead, which is the outcome
        that matters: a real person is not deleted."""
        prose = "Anna Krezkova praises the Abbot and Saint Markovia."
        assert _book_may_name_it("Anna Krezkov", prose) == "Anna"

    def test_a_surname_is_not_matched_inside_a_longer_one(self):
        assert _book_may_name_it("Krezkov", "Anna Krezkova praises him") == ""

    def test_a_lowercase_common_noun_is_not(self):
        """`Spellbook` is the defect: title-cased by the extractor, written by
        the book only as a common noun, so no mention can ever be minted."""
        prose = "The desk holds a spellbook and a cabinet of potions."
        assert _book_may_name_it("Spellbook", prose) == ""
        assert _book_may_name_it("Cabinet", prose) == ""

    def test_a_name_the_book_never_prints_is_not(self):
        prose = "The vault holds a diadem and a silvered dagger."
        assert _book_may_name_it("Potion of Far Realm Surprise", prose) == ""

    def test_it_matches_whole_words_only(self):
        """`Golem` must not be found inside `Golemsburg`, or a name would be
        held back on a coincidence of letters."""
        assert _book_may_name_it("Iron Golem", "The road to Golemsburg") == ""
        assert _book_may_name_it("Iron Golem", "an amber Golem stirs") == "Golem"

    def test_empty_words_carry_no_identity(self):
        assert _distinctive("the room of area") == []
        assert "Arasek" in _distinctive("Gunther Arasek")


class TestItRefusesAnythingACampaignTouches:
    """The one thing worse than a node the book never said is a session's prep
    deleted to remove it."""

    def test_an_edge_naming_a_campaign_refuses(self):
        row = {"edges": [{"type": "KNOWS", "campaign": "p13-home", "plane": "canon"}]}
        assert _held_by_a_campaign(row)

    def test_a_campaign_plane_neighbour_refuses(self):
        row = {"edges": [{"type": "KNOWS", "campaign": None, "plane": "campaign"}]}
        assert _held_by_a_campaign(row)

    def test_a_plain_canon_edge_does_not(self):
        row = {"edges": [{"type": "GUARDS", "campaign": None, "plane": "canon"}]}
        assert not _held_by_a_campaign(row)

    def test_no_edges_does_not(self):
        assert not _held_by_a_campaign({"edges": []})
