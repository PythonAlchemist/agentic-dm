"""Which scope violations this script acts on, and what it names the result.

It moves mentions BY SCOPE rather than by name, which is why it reaches cases
`split_entity` cannot: that one separates two things by what the section calls
them and gives up when the source already carries the foreign spelling as an
alias. Eight of these did, because `apply_aliases` folded it on.
"""

import pytest

from backend.scripts.unmerge_scoped import (
    label_overrides,
    plan_groups,
    wanted,
)


def _group(source, name="A Thing", found="prisoner-13", surfaces=("Thing",),
           mentions=("m1",), label="ITEM", scope="axe-from-the-grave"):
    return {"source": source, "name": name, "label": label, "scope": scope,
            "found": found, "surfaces": list(surfaces), "mentions": list(mentions)}


class TestWhichViolationsAreActedOn:
    """By default only the rooms the book itself numbered, which need no
    judgement on the book's own terms. `--unkeyed` takes the rest, and it is
    the DM's ruling that makes that safe, not anything in the text."""

    def test_a_keyed_room_is_always_wanted(self):
        assert wanted("kftgv:axe-from-the-grave:c18-rooftop", unkeyed=False)
        assert wanted("kftgv:axe-from-the-grave:c18-rooftop", unkeyed=True)

    def test_an_unkeyed_entity_is_only_wanted_when_asked_for(self):
        eid = "kftgv:axe-from-the-grave:flat-rooftop"
        assert not wanted(eid, unkeyed=False)
        assert wanted(eid, unkeyed=True)

    def test_a_subarea_key_counts(self):
        assert wanted("cos:castle-ravenloft:k61a-closet", unkeyed=False)

    def test_a_name_beginning_with_a_word_is_not_a_key(self):
        """`c18-` is a key; `console-` is a word that happens to start with c."""
        assert not wanted("kftgv:prisoner-13:console", unkeyed=False)


class TestWhatTheNewNodeIsCalled:
    def test_the_longest_spelling_wins(self):
        """`Private Room` and `Private Rooms` are one room said twice; the
        longer is the most specific thing the section called it."""
        plan, _ = plan_groups([_group("kftgv:a:x", surfaces=["Room", "Private Rooms"])])
        assert plan[0]["new_name"] == "Private Rooms"

    def test_the_new_id_is_scoped_to_the_chapter_the_mentions_are_in(self):
        """NOT the source's chapter. Scoping it to the source would mint a
        fresh violation in the act of repairing one."""
        plan, _ = plan_groups([
            _group("kftgv:axe-from-the-grave:flat-rooftop",
                   found="prisoner-13", surfaces=["Rooftop"])])
        assert plan[0]["new_id"] == "kftgv:prisoner-13:rooftop"

    def test_the_book_prefix_is_carried_over(self):
        plan, _ = plan_groups([_group("cos:vallaki:n5-stockyard", found="krezk",
                                      surfaces=["Stockyard"])])
        assert plan[0]["new_id"].startswith("cos:krezk:")

    def test_a_group_with_no_surface_is_skipped_not_guessed(self):
        plan, skipped = plan_groups([_group("kftgv:a:x", surfaces=["", None])])
        assert not plan
        assert skipped and "no surface" in skipped[0]

    def test_the_mentions_travel_with_the_plan(self):
        plan, _ = plan_groups([_group("kftgv:a:x", mentions=["m1", "m2"])])
        assert plan[0]["mentions"] == ["m1", "m2"]


class TestOverridingAnInheritedLabel:
    """The new node copies the label of the entity it is pulled out of, which
    is right when the merge folded two things of a kind and wrong when it did
    not: `Erinyes Statuette` is an ITEM and `Erinyes Barracks` is a room."""

    def test_one_override_is_read(self):
        assert label_overrides(
            ["--unkeyed", "--label", "kftgv:a:b=FACTION"]
        ) == {"kftgv:a:b": "FACTION"}

    def test_several_are_read(self):
        found = label_overrides(
            ["--label", "a=FACTION", "--label", "b=LOCATION", "--apply"])
        assert found == {"a": "FACTION", "b": "LOCATION"}

    def test_none_is_empty(self):
        assert label_overrides(["--unkeyed", "--apply"]) == {}

    def test_a_type_the_graph_does_not_use_is_refused(self):
        """A typo would otherwise become a label no query looks for: the node
        would exist, hold its mentions, and be invisible to every read that
        asks for a kind."""
        with pytest.raises(SystemExit) as raised:
            label_overrides(["--label", "a=FACTON"])
        assert "not a type this graph uses" in str(raised.value)

    def test_a_missing_value_is_refused(self):
        with pytest.raises(SystemExit):
            label_overrides(["--label"])
        with pytest.raises(SystemExit):
            label_overrides(["--label", "no-equals-sign"])
