"""Grouping names that are one thing said differently.

Everything here is pure -- blocking, parsing, folding -- so the rules that
decide what a model may propose are stated as tests rather than inferred from
a graph afterwards. The model call itself is one function and is not tested
here; what IS tested is that nothing it returns gets through unchecked.
"""

from backend.canon.coreference import (
    AliasGroup,
    blocks,
    weak_words,
    merge_overlapping,
    parse,
    significant_words,
)


class TestWhatCouldBeTheSameThing:
    """Blocking. Not an answer -- a way of asking a few hundred questions
    instead of a million."""

    def test_names_sharing_a_word_are_asked_about_together(self):
        found = dict(blocks(["Varkenbluff Museum", "Museum", "Elra"]))
        assert found["museum"] == ("Museum", "Varkenbluff Museum")

    def test_a_name_appears_in_every_block_its_words_put_it_in(self):
        """So a decision is never lost because blocking picked the wrong word."""
        found = dict(blocks(["Varkenbluff Museum", "Museum", "Varkenbluff"]))
        assert "Varkenbluff Museum" in found["museum"]
        assert "Varkenbluff Museum" in found["varkenbluff"]

    def test_a_word_shared_by_nothing_asks_nothing(self):
        assert blocks(["Elra", "Varrin"]) == []

    def test_articles_do_not_group_names(self):
        """`the` would put half a book in one block and is evidence of nothing."""
        assert dict(blocks(["the Vault", "the Museum"])).get("the") is None

    def test_a_block_too_large_to_ask_about_is_left_out(self):
        names = [f"Vault {i}" for i in range(50)]
        assert dict(blocks(names, cap=40)).get("vault") is None

    def test_the_order_is_total_so_two_runs_ask_the_same_thing(self):
        names = ["Museum", "Varkenbluff Museum", "Varkenbluff"]
        assert blocks(names) == blocks(list(reversed(names)))

    def test_case_and_punctuation_do_not_hide_a_shared_word(self):
        found = dict(blocks(["Alda Arkin", "ALDA", "Alda’s Office"]))
        assert len(found["alda"]) == 3

    def test_significant_words_drop_the_scaffolding(self):
        assert significant_words("The Ruins of Berez") == {"ruins", "berez"}


class TestWhichWordsAreEvidence:
    """A rule about what to ASK, not about what the answer is."""

    def test_a_frequent_common_noun_is_weak(self):
        """`hallway` assembled five different hallways and the model merged
        them -- it was answering the question it was asked."""
        names = [f"{k} hallway" for k in "abcdefg"] + ["Hallway"]
        assert "hallway" in weak_words(names, common=6)

    def test_a_frequent_PROPER_noun_is_still_strong(self):
        """`Vidorant` is in fourteen names of this corpus and is the best
        blocking word it has. Frequency alone would throw it away."""
        names = [f"Vidorant's {k}" for k in "abcdefghij"]
        assert "vidorant" not in weak_words(names, common=6)

    def test_a_rare_common_noun_is_not_weak(self):
        assert weak_words(["a skylight", "Attic Skylight"], common=6) == frozenset()

    def test_a_weak_word_stops_blocking(self):
        names = [f"{k} hallway" for k in "abcdefg"] + ["Hallway"]
        assert dict(blocks(names, common=6)).get("hallway") is None


class TestNothingGetsThroughUnchecked:
    OFFERED = ["Varkenbluff Museum of Natural History", "Varkenbluff Museum", "Museum"]

    def test_a_clean_grouping_is_kept(self):
        groups, refused = parse(
            '{"groups":[{"canonical":"Varkenbluff Museum of Natural History",'
            '"names":["Varkenbluff Museum of Natural History","Museum"]}]}',
            self.OFFERED,
        )
        assert refused == []
        assert groups[0].canonical == "Varkenbluff Museum of Natural History"
        assert groups[0].others == ("Museum",)

    def test_an_invented_name_refuses_the_WHOLE_group(self):
        """A model that invented one name was not reading the list, and keeping
        the rest would be trusting the half that happened to look right."""
        groups, refused = parse(
            '{"groups":[{"canonical":"Museum","names":["Museum","The Louvre"]}]}',
            self.OFFERED,
        )
        assert groups == []
        assert "invented" in refused[0]

    def test_a_canonical_outside_its_own_group_is_refused(self):
        groups, refused = parse(
            '{"groups":[{"canonical":"Varkenbluff Museum",'
            '"names":["Museum","Varkenbluff Museum of Natural History"]}]}',
            self.OFFERED,
        )
        assert groups == []
        assert "canonical" in refused[0]

    def test_a_group_of_one_is_not_a_grouping(self):
        groups, refused = parse(
            '{"groups":[{"canonical":"Museum","names":["Museum"]}]}', self.OFFERED
        )
        assert groups == []
        assert "group of one" in refused[0]

    def test_an_unparseable_response_is_reported_not_raised(self):
        """A bad response is evidence about the prompt. Raising loses the run."""
        groups, refused = parse("not json at all", self.OFFERED)
        assert groups == []
        assert "unparseable" in refused[0]

    def test_no_groups_is_a_valid_and_common_answer(self):
        assert parse('{"groups":[]}', self.OFFERED) == ([], [])

    def test_a_duplicate_name_inside_a_group_is_not_two_names(self):
        groups, _ = parse(
            '{"groups":[{"canonical":"Museum","names":["Museum","Museum"]}]}',
            self.OFFERED,
        )
        assert groups == []


class TestFoldingWhatCameBackInPieces:
    """A name is asked about once per word it contains, so one family can
    arrive as two partial answers."""

    def test_groups_sharing_a_name_become_one(self):
        folded = merge_overlapping([
            AliasGroup("Varkenbluff Museum", ("Varkenbluff Museum", "Museum")),
            AliasGroup(
                "Varkenbluff Museum of Natural History",
                ("Varkenbluff Museum of Natural History", "Varkenbluff Museum"),
            ),
        ])
        assert len(folded) == 1
        assert set(folded[0].names) == {
            "Museum", "Varkenbluff Museum", "Varkenbluff Museum of Natural History",
        }

    def test_it_is_transitive(self):
        """A groups with B, B with C, so all three are one thing."""
        folded = merge_overlapping([
            AliasGroup("B", ("A", "B")), AliasGroup("C", ("B", "C")),
        ])
        assert len(folded) == 1
        assert set(folded[0].names) == {"A", "B", "C"}

    def test_unrelated_families_stay_apart(self):
        folded = merge_overlapping([
            AliasGroup("Alda Arkin", ("Alda Arkin", "Alda")),
            AliasGroup("Master Key", ("Master Key", "Key")),
        ])
        assert len(folded) == 2

    def test_the_fullest_name_wins_when_two_answers_disagree(self):
        folded = merge_overlapping([
            AliasGroup("Museum", ("Museum", "Varkenbluff Museum")),
            AliasGroup("Varkenbluff Museum", ("Varkenbluff Museum", "Museum")),
        ])
        assert folded[0].canonical == "Varkenbluff Museum"

    def test_nothing_in_means_nothing_out(self):
        assert merge_overlapping([]) == []
