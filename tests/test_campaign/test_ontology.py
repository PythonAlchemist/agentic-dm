"""What kinds of thing a story is made of, and which may hold which.

The rule is authored in `ontology.py` rather than inferred from whatever the
last caller allowed, so it can be stated exactly here.
"""

from backend.campaign import ontology as o


class TestContainmentIsItsOwnAxis:
    """The running order was a flat list and a story is not one. Every
    insertion went BETWEEN two things at one level, so an encounter that
    happens DURING a scene could only be placed as its sibling — landing
    before the thing it occurs inside."""

    def test_an_encounter_goes_inside_a_scene(self):
        assert o.may_contain(o.SCENE, o.ENCOUNTER)

    def test_an_encounter_does_not_go_inside_an_encounter(self):
        """A nesting a table has no use for. Refused in a sentence, because
        this reaches a person rather than a log."""
        assert not o.may_contain(o.ENCOUNTER, o.ENCOUNTER)
        assert o.refuse(o.ENCOUNTER, o.ENCOUNTER) == (
            "an encounter goes inside a scene or a section or a subsection, "
            "not inside an encounter"
        )

    def test_a_scene_goes_where_a_section_goes(self):
        """Which is what it is: an episode in the run of play, beside the
        book's own."""
        assert o.may_contain(o.CHAPTER, o.SCENE)
        assert o.may_contain(o.SECTION, o.SCENE)

    def test_a_chapter_sits_at_the_top(self):
        assert o.MAY_SIT_INSIDE[o.CHAPTER] == frozenset()
        assert "cannot go inside anything" in o.refuse(o.SECTION, o.CHAPTER)

    def test_the_books_own_depth_maps_to_a_level(self):
        """The harvest recorded depth 1/2/3 and the running order discarded
        it. Both kinds of thing are answered here so no call site has to
        guess."""
        assert o.level_of("", 1) == o.CHAPTER
        assert o.level_of("", 2) == o.SECTION
        assert o.level_of("", 3) == o.SUBSECTION

    def test_a_campaign_kind_answers_for_itself(self):
        assert o.level_of("encounter", None) == o.ENCOUNTER
        assert o.level_of("scene", None) == o.SCENE

    def test_only_scenes_and_encounters_are_positional(self):
        """An npc, an item or a piece of lore is a thing the story CONTAINS,
        not a place in it — giving one a slot would put a rusty key between
        two scenes."""
        for kind in ("npc", "monster", "location", "item", "lore", "quest"):
            assert kind not in o.POSITIONAL
