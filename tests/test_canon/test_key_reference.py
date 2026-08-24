"""A candidate that points at a keyed area is not a second area."""
from backend.canon.writer import key_reference

HEADINGS = [("V1", "Grand Entrance"), ("V13", "Gemstone Wing"), ("K61a", "Empty Cell")]


class TestResolvingAReference:
    def test_a_prose_cross_reference_resolves(self):
        assert key_reference("area V1", HEADINGS) == "V1"

    def test_capitalised_the_same(self):
        assert key_reference("Area V13", HEADINGS) == "V13"

    def test_a_bare_key_resolves_too(self):
        """`V1` and `area V1` and `V1: Grand Entrance` were three nodes."""
        assert key_reference("V1", HEADINGS) == "V1"

    def test_room_is_the_same_word(self):
        assert key_reference("room K61a", HEADINGS) == "K61a"

    def test_a_real_name_is_left_alone(self):
        assert key_reference("Gemstone Wing", HEADINGS) == ""
        assert key_reference("Dr. Cassee Dannell", HEADINGS) == ""

    def test_a_key_this_chapter_does_not_head_is_left_alone(self):
        """No room is invented. `area 51` in a book with no area 51 stays
        whatever the extractor made of it."""
        assert key_reference("area 51", HEADINGS) == ""

    def test_the_word_area_alone_is_not_a_reference(self):
        assert key_reference("area", HEADINGS) == ""

    def test_an_empty_heading_set_resolves_nothing(self):
        assert key_reference("area V1", []) == ""
