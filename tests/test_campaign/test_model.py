"""The campaign's own rules, checked without a graph."""

import pytest

from backend.campaign.model import (
    AUTHORED,
    CAMPAIGN_PLANE,
    Campaign,
    authored_is_never_canon,
    campaign_prefix,
    every_section_placed,
    is_campaign_id,
    mint_id,
    start_matches_chain,
)
from backend.canon.writer import ACCEPTED, CANON_PLANE, PROPOSED


class TestIds:
    def test_a_campaign_id_carries_its_origin(self):
        assert mint_id("prisoner-13-home", "sea-battle") == "hb:prisoner-13-home:sea-battle"

    def test_campaign_ids_are_self_identifying(self):
        """A citation must say which world it came from without a lookup."""
        assert is_campaign_id("hb:prisoner-13-home:sea-battle")
        assert not is_campaign_id("kftgv:prisoner-13#7")
        assert not is_campaign_id("cos:the-village-of-barovia")

    def test_a_campaign_slug_cannot_collide_with_a_book_prefix(self):
        """`books.BookScheme` owns bare prefixes; campaigns are always under
        `hb:`. A campaign called `cos` must not mint `cos:` ids."""
        assert campaign_prefix("cos") == "hb:cos:"
        assert not campaign_prefix("cos").startswith("cos:")


class TestCampaign:
    def test_a_campaign_needs_a_slug(self):
        with pytest.raises(ValueError):
            Campaign(slug="", name="nameless")

    def test_a_campaign_with_no_book_is_legal(self):
        """The wholly-invented world. Not an error state."""
        assert Campaign(slug="my-world", name="My World").is_pure_homebrew

    def test_drawing_on_a_book_is_not_pure_homebrew(self):
        assert not Campaign(slug="p13", name="P13", books=("kftgv",)).is_pure_homebrew


class TestInvariants:
    def test_a_started_chain_has_sections_and_an_empty_one_does_not(self):
        assert start_matches_chain(True, 543)
        assert start_matches_chain(False, 0)

    def test_a_start_pointing_at_an_empty_chain_is_broken(self):
        assert not start_matches_chain(True, 0)

    def test_a_non_empty_chain_with_no_start_is_unreachable(self):
        """The failure that loses a whole running order silently."""
        assert not start_matches_chain(False, 543)

    def test_every_section_is_in_the_chain_or_skipped(self):
        spine = frozenset({"a", "b", "c"})
        assert every_section_placed(spine, frozenset({"a", "b"}), frozenset({"c"})) == frozenset()

    def test_a_section_harvested_after_seeding_is_reported(self):
        """The real case: a chapter added to the book after a campaign was
        seeded is in neither set, and must be found rather than assumed cut."""
        spine = frozenset({"a", "b", "c"})
        assert every_section_placed(spine, frozenset({"a"}), frozenset({"b"})) == frozenset({"c"})

    def test_authored_may_not_sit_on_the_canon_plane(self):
        assert not authored_is_never_canon(AUTHORED, CANON_PLANE)

    def test_authored_on_the_campaign_plane_is_fine(self):
        assert authored_is_never_canon(AUTHORED, CAMPAIGN_PLANE)

    def test_the_book_s_own_statuses_are_unaffected(self):
        for status in (ACCEPTED, PROPOSED):
            assert authored_is_never_canon(status, CANON_PLANE)


class TestAuthoredIsItsOwnStatus:
    def test_it_is_neither_accepted_nor_proposed(self):
        """The distinction the model reads to decide how far to trust a line.
        Collapsing it into either existing value tells the model something
        false in one of two directions -- that the book said it, or that it is
        probably wrong."""
        assert AUTHORED not in {ACCEPTED, PROPOSED}
