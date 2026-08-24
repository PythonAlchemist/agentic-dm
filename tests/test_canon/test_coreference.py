"""Grouping names that are one thing said differently.

Everything here is pure -- blocking, parsing, folding -- so the rules that
decide what a model may propose are stated as tests rather than inferred from
a graph afterwards. The model call itself is one function and is not tested
here; what IS tested is that nothing it returns gets through unchecked.
"""

from backend.canon.coreference import (
    AliasGroup,
    blocks,
    owns_something,
    shares_only_a_surname,
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
        """`Alda’s Office` is deliberately NOT here -- see
        `TestAnOwnerIsNotWhatTheyOwn`. What this asserts is that casing and a
        curly apostrophe inside a name do not stop it blocking."""
        found = dict(blocks(["Alda Arkin", "ALDA", "Curator Alda"]))
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
        folded, runaway = merge_overlapping([
            AliasGroup("Varkenbluff Museum", ("Varkenbluff Museum", "Museum")),
            AliasGroup(
                "Varkenbluff Museum of Natural History",
                ("Varkenbluff Museum of Natural History", "Varkenbluff Museum"),
            ),
        ])
        assert runaway == []
        assert len(folded) == 1
        assert set(folded[0].names) == {
            "Museum", "Varkenbluff Museum", "Varkenbluff Museum of Natural History",
        }

    def test_it_is_transitive(self):
        """A groups with B, B with C, so all three are one thing."""
        folded, _ = merge_overlapping([
            AliasGroup("B", ("A", "B")), AliasGroup("C", ("B", "C")),
        ])
        assert len(folded) == 1
        assert set(folded[0].names) == {"A", "B", "C"}

    def test_unrelated_families_stay_apart(self):
        folded, _ = merge_overlapping([
            AliasGroup("Alda Arkin", ("Alda Arkin", "Alda")),
            AliasGroup("Master Key", ("Master Key", "Key")),
        ])
        assert len(folded) == 2

    def test_the_fullest_name_wins_when_two_answers_disagree(self):
        folded, _ = merge_overlapping([
            AliasGroup("Museum", ("Museum", "Varkenbluff Museum")),
            AliasGroup("Varkenbluff Museum", ("Varkenbluff Museum", "Museum")),
        ])
        assert folded[0].canonical == "Varkenbluff Museum"

    def test_nothing_in_means_nothing_out(self):
        assert merge_overlapping([]) == ([], [])


class TestARunawayFamilyIsNotAnAnswer:
    """Folding is transitive, so one wrong grouping welds two families together
    and the union keeps growing. A single bad link chained Little Lockford,
    Brimstone Hold, Vrakir's Chamber and the Ashen Creatures into one 28-name
    "entity"."""

    @staticmethod
    def _chain(n: int) -> list[AliasGroup]:
        return [AliasGroup(f"n{i+1}", (f"n{i}", f"n{i+1}")) for i in range(n)]

    def test_a_family_over_the_cap_is_refused(self):
        folded, runaway = merge_overlapping(self._chain(10), cap=6)
        assert folded == []
        assert "folded into one family" in runaway[0]

    def test_it_is_refused_WHOLE_rather_than_trimmed(self):
        """Trimming would mean guessing which link was the bad one."""
        folded, _ = merge_overlapping(self._chain(10), cap=6)
        assert folded == []

    def test_a_family_within_the_cap_is_kept(self):
        folded, runaway = merge_overlapping(self._chain(3), cap=6)
        assert len(folded) == 1
        assert runaway == []

    def test_the_refusal_names_what_it_dropped(self):
        """A grouping nobody was told about is indistinguishable from one never
        proposed."""
        _, runaway = merge_overlapping(self._chain(10), cap=6)
        assert "n0" in runaway[0]


class TestATaskIsNeverTheThingItIsAbout:
    KINDS = {
        "Deliver the key to Varrin Axebreaker": frozenset({"QUEST"}),
        "Varrin Axebreaker": frozenset({"NPC"}),
        "Varrin": frozenset({"NPC"}),
    }

    def test_a_quest_is_not_offered_beside_its_object(self):
        """The prompt forbade this and the model did it fourteen times. A
        question that offers them together invites the answer it gets."""
        found = blocks(list(self.KINDS), kinds=self.KINDS)
        for _, group in found:
            has_task = any(self.KINDS[n] == frozenset({"QUEST"}) for n in group)
            has_thing = any(self.KINDS[n] != frozenset({"QUEST"}) for n in group)
            assert not (has_task and has_thing), group

    def test_two_spellings_of_one_quest_are_still_asked_about(self):
        """Splitting must not stop quests grouping with each other."""
        kinds = {
            "Retrieve the key": frozenset({"QUEST"}),
            "Retrieve the key from Prisoner 13": frozenset({"QUEST"}),
        }
        assert blocks(list(kinds), kinds=kinds) != []

    def test_without_types_nothing_is_partitioned(self):
        """The rule is opt-in: a caller with no types gets the old behaviour."""
        assert blocks(list(self.KINDS)) == blocks(list(self.KINDS), kinds=None)


class TestAnOwnerIsNotWhatTheyOwn:
    """`Constantori` and `Constantori's Portrait` share a word, so blocking
    offered them together and the model merged a man with his portrait. It did
    the same to Gwish and his room, his trunk and his raven."""

    def test_the_word_before_a_possessive_is_the_owner(self):
        assert owns_something("Constantori’s Portrait", "constantori")

    def test_a_name_with_no_possessive_owns_nothing(self):
        assert not owns_something("Constantori", "constantori")

    def test_a_word_AFTER_the_possessive_is_the_thing_owned(self):
        """In `Vidorant's Vault` the vault is owned, and whether it is the same
        vault as `Vault` is a real question worth asking."""
        assert not owns_something("Vidorant’s Vault", "vault")
        assert owns_something("Vidorant’s Vault", "vidorant")

    def test_both_apostrophes_count(self):
        """The book sets the curly one, the extractor emits the straight one."""
        assert owns_something("Gwish's raven", "gwish")
        assert owns_something("Gwish’s raven", "gwish")

    def test_an_owner_is_never_offered_beside_what_they_own(self):
        names = ["Constantori", "Constantori’s Portrait"]
        for _, group in blocks(names):
            assert set(group) != set(names), group

    def test_two_things_one_person_owns_are_still_asked_about(self):
        """Splitting must not stop `Gwish's room` grouping with a respelling
        of itself."""
        assert blocks(["Gwish’s Room", "Gwish’s room"]) != []


class TestASurnameMeansRelatedNotIdentical:
    """A campaign has families. Blocking on a shared word assembles them and
    asked which are the same, the model merged `Sergei von Zarovich` with
    `Strahd von Zarovich` -- the two brothers whose quarrel is the campaign --
    along with six Belviews and three Krezkovs."""

    def test_two_given_names_on_one_surname_are_two_people(self):
        assert shares_only_a_surname("Sergei von Zarovich", "Strahd von Zarovich")
        assert shares_only_a_surname("Emil Toranescu", "Zuleika Toranescu")

    def test_a_title_does_not_make_a_second_person(self):
        """`Curator Alda Arkin` and `Alda Arkin` are one woman, and she is the
        family this pipeline was built to find. Handled by asking whether one
        name is the other said longer, which needs no list of titles and so
        cannot be defeated by a title nobody wrote down."""
        assert not shares_only_a_surname("Curator Alda Arkin", "Alda Arkin")
        assert not shares_only_a_surname("Mayor Braith Broadfoot", "Braith Broadfoot")

    def test_a_shared_FIRST_word_is_not_a_surname_case(self):
        assert not shares_only_a_surname(
            "Varkenbluff Museum of Natural History", "Varkenbluff Museum"
        )

    def test_it_reads_places_the_same_way(self):
        """`Old Svalich Road` and `Winding Road` share a kind, not an identity."""
        assert shares_only_a_surname("Old Svalich Road", "Winding Road")

    def test_a_single_word_name_is_never_a_surname_case(self):
        assert not shares_only_a_surname("Strahd", "Strahd von Zarovich")

    def test_a_family_is_never_offered_as_one_block(self):
        family = ["Emil Toranescu", "Zuleika Toranescu", "Arturi Toranescu"]
        for _, group in blocks(family):
            assert len(group) < 2 or not any(
                shares_only_a_surname(a, b) for a in group for b in group if a != b
            ), group

    def test_two_spellings_of_one_person_still_block_together(self):
        found = blocks(["Curator Alda Arkin", "Alda Arkin"])
        assert any(len(g) == 2 for _, g in found), found
