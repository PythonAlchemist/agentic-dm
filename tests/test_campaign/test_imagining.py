"""The prompt an imagined portrait is asked for, and recorded as."""

from backend.campaign import imagining


class TestItIsBuiltFromTheBook:
    def test_the_source_sentences_are_in_it(self):
        """Handed only a name, a model draws its idea of a D&D NPC."""
        found = imagining.prompt_for(
            name="Ismark", labels=["NPC"],
            says=["Ismark Kolyanovich is the burgomaster's son."])
        assert "burgomaster's son" in found

    def test_it_says_which_words_are_the_book_s(self):
        """The stored prompt is evidence, so it has to be readable as such."""
        found = imagining.prompt_for(
            name="Ismark", labels=["NPC"], says=["He carries a longsword."])
        assert "The source text says: He carries a longsword." in found

    def test_it_stops_at_three_sentences(self):
        """A whole chapter drowns the subject -- the model starts drawing the
        tavern the person is standing in."""
        found = imagining.prompt_for(
            name="Ismark", labels=["NPC"],
            says=[f"Sentence {i}." for i in range(6)])
        assert found.count("The source text says:") == 3

    def test_the_dm_s_note_comes_last(self):
        """It refines the book rather than replacing it."""
        found = imagining.prompt_for(
            name="Ismark", labels=["NPC"], says=["He is weary."],
            note="older than the art suggests")
        assert found.index("source text") < found.index("DM adds")

    def test_a_name_alone_is_allowed_and_is_visibly_thin(self):
        """An entity with no prose gets a prompt so short the result is
        visibly invented, which is the honest outcome."""
        found = imagining.prompt_for(name="Nobody", labels=[])
        assert "Nobody" in found and "source text" not in found


class TestTheFrame:
    def test_a_place_is_not_a_head_and_shoulders(self):
        assert "place" in imagining.prompt_for(name="Barovia",
                                               labels=["LOCATION"])

    def test_a_person_is(self):
        assert "Head and shoulders" in imagining.prompt_for(name="Ismark",
                                                            labels=["NPC"])

    def test_a_monster_takes_the_portrait_frame(self):
        """Splitting further would invent distinctions the graph does not
        draw."""
        assert imagining.frame_for(["MONSTER"]) == imagining.FRAME


class TestItIsNotAStyleEngine:
    def test_no_lighting_lens_or_artist(self):
        """Those are how a prompt stops describing the subject and starts
        describing a picture. This one has to stay readable as evidence."""
        found = imagining.prompt_for(
            name="Ismark", labels=["NPC"], says=["He is weary."]).lower()
        for word in ("cinematic", "8k", "trending", "artstation", "bokeh",
                     "lighting", "octane", "in the style of"):
            assert word not in found
