"""The two verdicts `audit_scope` reaches on its own, and the evidence it shows.

The script reports and never writes, so the thing worth testing is whether the
sentence it prints a DM is the right one. It used to decide by arithmetic --
more mentions at home than abroad -- which was wrong about 13 of the 16 pairs
it called "may be book-wide". These are the rules that replaced it.
"""

from backend.scripts.audit_scope import (
    _heading_name,
    _names_its_own_room,
    _same_noun,
    _spells_another_name,
)


def _seen(surface, key="", heading=""):
    return [{"surface": surface, "key": key, "heading": heading}]


class TestReadingTheKeyOffAHeading:
    def test_the_name_after_the_key(self):
        assert _heading_name("C18: Rooftop", "c18") == "Rooftop"
        assert _heading_name("B15: Erinyes Barracks", "b15") == "Erinyes Barracks"

    def test_a_subarea_key(self):
        assert _heading_name("C7f: Embry's Room", "c7f") == "Embry's Room"

    def test_a_full_stop_separator(self):
        assert _heading_name("E5g. Undercroft", "e5g") == "Undercroft"


class TestAMentionThatNamesTheRoomItSitsIn:
    """The book keys rooms PER ADVENTURE, so the room is one adventure's and a
    foreign mention spelling its name is of the room, not of the entity."""

    def test_it_is_caught(self):
        assert _names_its_own_room(
            _seen("Rooftop", "c18", "C18: Rooftop")
        ) == "C18: Rooftop"

    def test_an_unkeyed_section_decides_nothing(self):
        """A prose heading is not a room, so this rule has nothing to say."""
        assert _names_its_own_room(_seen("Rooftop", "", "Planning the Heist")) == ""

    def test_a_different_name_in_a_keyed_room_is_not_caught(self):
        """THE OVER-REACH THIS RULE MUST NOT MAKE. A book-wide name is entitled
        to appear inside a keyed room -- the Golden Vault is named in plenty --
        and firing on the section's key alone would call every one a bad merge."""
        assert _names_its_own_room(
            _seen("The Golden Vault", "c18", "C18: Rooftop")
        ) == ""

    def test_nothing_seen_decides_nothing(self):
        assert _names_its_own_room(None) == ""
        assert _names_its_own_room([]) == ""


class TestWhetherTheMentionEvenSpellsThisName:
    def test_a_different_name_is_reported(self):
        """Ten `Mayor Broadfoot`s under `Honorary Mayor Jenna Bean` are two
        mayors of two towns."""
        assert _spells_another_name(
            "Honorary Mayor Jenna Bean", _seen("Mayor Broadfoot")
        ) == "Mayor Broadfoot"

    def test_the_same_name_is_not(self):
        assert _spells_another_name("Iron Chests", _seen("Iron chests")) == ""

    def test_a_plural_is_the_same_noun(self):
        """`Stone Golems` holding a `Stone Golem` is a common noun recurring,
        not coreference folding two things together."""
        assert _spells_another_name("Stone Golems", _seen("Stone Golem")) == ""

    def test_a_curly_apostrophe_is_not_a_different_name(self):
        assert _spells_another_name("Gwish’s Trunk", _seen("Gwish's Trunk")) == ""


class TestTheFoldIsNarrow:
    """It exists so the report reads correctly and nowhere else. Anything
    wider would be the fuzz `aliases.normalize` refuses by design."""

    def test_case_and_plural_and_apostrophe_only(self):
        assert _same_noun("Stone Golem", "Stone Golems")
        assert _same_noun("Iron Chests", "iron chests")
        assert _same_noun("Gwish’s Trunk", "Gwish's Trunk")

    def test_it_does_not_fold_two_real_names(self):
        assert not _same_noun("Jenna Bean", "Mayor Broadfoot")
        assert not _same_noun("The Celestial Codex", "Celestial")
        assert not _same_noun("Erinyes Statuette", "Erinyes Barracks")
