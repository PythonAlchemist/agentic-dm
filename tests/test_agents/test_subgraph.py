"""What a conversation holds between turns.

Pure: no database, no model. The whole object exists so that a follow-up like
"what makes him special" resolves through an entity id rather than searching
Lucene for `him, makes, special` -- which is what it did, returning the heading
`Special Events` eight times from eight chapters.
"""

import pytest

from backend.agents.subgraph import (
    EXPANDED,
    NAMED,
    SEEDED,
    Subgraph,
    note_named,
    seed,
)


def held(graph: Subgraph) -> list[str]:
    return [h.name for h in graph.subjects(limit=99)]


class TestHoldingEntities:
    def test_an_entity_is_held_with_its_labels(self):
        graph = Subgraph()
        graph.touch_node("cos:rictavio", "Rictavio", ["NPC"])
        assert graph.subjects()[0].line == "Rictavio (NPC)"

    def test_the_most_recently_touched_comes_first(self):
        """A pronoun resolves through this, so recency is the ordering that
        matters rather than insertion."""
        graph = Subgraph()
        graph.touch_node("a", "Strahd", ["NPC"])
        graph.turn = 1
        graph.touch_node("b", "Rictavio", ["NPC"])
        assert held(graph) == ["Rictavio", "Strahd"]

    def test_touching_an_entity_again_brings_it_forward(self):
        graph = Subgraph()
        graph.touch_node("a", "Strahd", ["NPC"])
        graph.turn = 1
        graph.touch_node("b", "Rictavio", ["NPC"])
        graph.turn = 2
        graph.touch_node("a", "Strahd", ["NPC"])
        assert held(graph) == ["Strahd", "Rictavio"]

    def test_a_seeded_entity_does_not_become_a_guess_when_expanded_into(self):
        """`how` records how it FIRST arrived. A name a question resolved is
        stronger evidence than a traversal reaching the same node, and letting
        the later one win would overstate nothing and understate that."""
        graph = Subgraph()
        graph.touch_node("a", "Rictavio", ["NPC"], how=SEEDED)
        graph.turn = 1
        graph.touch_node("a", "Rictavio", ["NPC"], how=EXPANDED)
        assert graph.nodes["a"].how == SEEDED

    def test_ties_break_by_name_rather_than_by_dict_order(self):
        graph = Subgraph()
        graph.touch_node("b", "Zuleika", ["NPC"])
        graph.touch_node("a", "Arabelle", ["NPC"])
        assert held(graph) == ["Arabelle", "Zuleika"]

    def test_subjects_is_capped(self):
        graph = Subgraph()
        for i in range(10):
            graph.touch_node(str(i), f"NPC{i}", ["NPC"])
        assert len(graph.subjects(limit=4)) == 4


class TestHoldingEdges:
    def test_an_edge_keeps_the_status_it_had_in_the_graph(self):
        """A proposed edge is a guess and about a third are false. One that
        arrived here without its status would be a guess in a fact's clothes."""
        graph = Subgraph()
        graph.touch_edge("Strahd", "SEEKS", "Ireena", "proposed")
        assert graph.edges[("Strahd", "SEEKS", "Ireena")].status == "proposed"

    def test_the_same_edge_twice_is_held_once(self):
        graph = Subgraph()
        graph.touch_edge("A", "OWNS", "B", "accepted")
        graph.turn = 1
        graph.touch_edge("A", "OWNS", "B", "accepted")
        assert len(graph.edges) == 1

    def test_opposite_claims_between_one_pair_are_both_held(self):
        """`A SEEKS B` and `B SEEKS A` are different claims about two nodes."""
        graph = Subgraph()
        graph.touch_edge("A", "SEEKS", "B", "proposed")
        graph.touch_edge("B", "SEEKS", "A", "proposed")
        assert len(graph.edges) == 2


class TestPassages:
    def test_a_section_read_is_remembered(self):
        graph = Subgraph()
        graph.touch_passage("cos:x#1")
        assert graph.already_read("cos:x#1")
        assert not graph.already_read("cos:x#2")

    def test_the_prose_itself_is_not_held(self):
        """The model has no memory between calls, so the text is re-sent from
        retrieval regardless. A second copy here would be the 35,383-character
        duplication `WriteMention` exists to refuse."""
        graph = Subgraph()
        graph.touch_passage("cos:x#1")
        assert graph.passages["cos:x#1"] == graph.turn


class TestRendering:
    def test_an_empty_subgraph_renders_to_nothing(self):
        """Not a heading with nothing under it -- turn one would then open with
        a promise the conversation has not made yet."""
        assert Subgraph().render() == ""

    def test_it_names_what_the_conversation_is_about(self):
        graph = Subgraph()
        graph.touch_node("cos:rictavio", "Rictavio", ["NPC"])
        assert "Rictavio (NPC)" in graph.render()

    def test_guesses_are_rendered_apart_from_facts(self):
        graph = Subgraph()
        graph.touch_node("a", "Strahd", ["NPC"])
        graph.touch_edge("Ismark", "OWNS", "Tavern", "accepted")
        graph.touch_edge("Strahd", "SEEKS", "Yester Hill", "proposed")
        block = graph.render()
        assert "Established relationships:" in block
        assert "third are wrong" in block
        assert block.index("Ismark -OWNS-> Tavern") < block.index("Strahd -SEEKS->")

    def test_the_prose_of_a_passage_never_appears(self):
        """Retrieval sends the sections. Duplicating them here would double the
        largest part of the input for nothing."""
        graph = Subgraph()
        graph.touch_node("a", "Rictavio", ["NPC"])
        graph.touch_passage("cos:the-town-of-vallaki#16")
        assert "cos:the-town-of-vallaki#16" not in graph.render()


class TestEviction:
    """Required, not optional: with the transcript gone this is the only thing
    between a long campaign and an unbounded working set."""

    @staticmethod
    def _one_token_per_line(text: str) -> int:
        return len(text.splitlines())

    def test_it_drops_the_oldest_touched_first(self):
        graph = Subgraph()
        graph.touch_node("a", "Oldest", ["NPC"])
        graph.turn = 1
        graph.touch_node("b", "Middle", ["NPC"])
        graph.turn = 2
        graph.touch_node("c", "Newest", ["NPC"])
        graph.evict(budget=3, estimate=self._one_token_per_line)
        assert held(graph) == ["Newest", "Middle"]

    def test_it_reports_what_it_dropped(self):
        graph = Subgraph()
        graph.touch_node("a", "Old", ["NPC"])
        graph.turn = 1
        graph.touch_node("b", "New", ["NPC"])
        assert graph.evict(budget=2, estimate=self._one_token_per_line) == 1

    def test_this_turn_is_pinned_so_eviction_terminates(self):
        """Evicting what the conversation is talking about right now, to make
        room for what it is talking about right now, is a loop. A hostile budget
        must stop rather than empty the subgraph."""
        graph = Subgraph()
        graph.touch_node("a", "Current", ["NPC"])
        graph.touch_node("b", "AlsoCurrent", ["NPC"])
        graph.evict(budget=0, estimate=self._one_token_per_line)
        assert sorted(held(graph)) == ["AlsoCurrent", "Current"]

    def test_a_generous_budget_drops_nothing(self):
        graph = Subgraph()
        graph.touch_node("a", "Kept", ["NPC"])
        graph.turn = 1
        assert graph.evict(budget=10_000) == 0
        assert held(graph) == ["Kept"]

    def test_an_edge_loses_its_endpoint_and_goes_with_it(self):
        """An edge whose endpoint was evicted would render as a claim about a
        name nothing else in the block explains."""
        graph = Subgraph()
        graph.touch_node("a", "Strahd", ["NPC"])
        graph.touch_edge("Strahd", "SEEKS", "Ireena", "proposed")
        graph.turn = 5
        graph.touch_node("b", "Rictavio", ["NPC"])
        graph.evict(budget=2, estimate=self._one_token_per_line)
        assert graph.edges == {}
        assert held(graph) == ["Rictavio"]

    def test_eviction_is_not_deletion_from_the_graph(self):
        """Recorded as an assertion about intent: what is lost is that THIS
        conversation held it. The node is still in Neo4j and the graph agent
        can fetch it again.

        Two entities, because the most recent SUBJECT is pinned whatever the
        budget -- a subgraph evicted to empty is a conversation with total
        amnesia, and that is never the better trade."""
        graph = Subgraph()
        graph.touch_node("cos:strahd", "Strahd", ["NPC"])
        graph.turn = 1
        graph.touch_node("cos:rictavio", "Rictavio", ["NPC"])
        graph.turn = 2
        graph.evict(budget=0, estimate=self._one_token_per_line)
        assert "cos:strahd" not in graph.nodes
        assert "cos:rictavio" in graph.nodes

    def test_it_never_evicts_itself_to_empty(self):
        """The subgraph is the only memory now that the transcript is gone."""
        graph = Subgraph()
        graph.touch_node("cos:rictavio", "Rictavio", ["NPC"])
        graph.turn = 9
        graph.evict(budget=0, estimate=self._one_token_per_line)
        assert list(graph.nodes) == ["cos:rictavio"]


class TestWithholdingGuesses:
    """`include_proposed` is a depth knob about what the model may READ. The
    subgraph goes on holding what it knows, so turning it back on needs no
    re-fetch -- the same rule `canon_context.apply` states."""

    @staticmethod
    def _mixed() -> Subgraph:
        graph = Subgraph()
        graph.touch_node("a", "Arik", ["NPC"])
        graph.touch_edge("Ismark", "OWNS", "Tavern", "accepted")
        graph.touch_edge("Arik", "SEEKS", "Ireena", "proposed")
        return graph

    def test_guesses_are_withheld_when_asked(self):
        block = self._mixed().render(include_proposed=False)
        assert "Ismark -OWNS-> Tavern" in block
        assert "Arik -SEEKS-> Ireena" not in block

    def test_the_subgraph_still_holds_them(self):
        """Withheld is not discarded. Otherwise the knob would be one-way."""
        graph = self._mixed()
        graph.render(include_proposed=False)
        assert ("Arik", "SEEKS", "Ireena") in graph.edges

    def test_they_come_back_when_the_knob_does(self):
        assert "Arik -SEEKS-> Ireena" in self._mixed().render(include_proposed=True)


@pytest.mark.neo4j
@pytest.mark.corpus
class TestTheFollowUpThatMotivatedThis:
    """Two real turns against the real graph.

    Asked "who is rictavio" and then "what about him makes him special", the
    second turn used to anchor NOTHING: it searched Lucene for `him, makes,
    special` and returned the heading `Special Events` eight times from eight
    chapters, with 93 relationships harvested from them.

    Nothing measures multi-turn behaviour anywhere else -- all 96 retrieval
    questions and all 10 answer questions are single-turn, and the answer
    harness builds a fresh agent per question precisely so history cannot
    bleed. So this is the only thing standing between the subgraph and a silent
    regression.
    """

    @staticmethod
    def _two_turns() -> Subgraph:
        from backend.canon.retrieval import CanonRetriever

        retriever = CanonRetriever(book="cos")
        graph = Subgraph()
        graph.turn = 1
        seed(graph, retriever.retrieve("Who is Rictavio?"))
        graph.turn = 2
        seed(graph, retriever.retrieve("what about him makes him special"))
        return graph

    def test_the_conversation_still_knows_who_he_is(self):
        graph = self._two_turns()
        assert "cos:rictavio" in graph.nodes
        assert "Rictavio" in graph.render()

    def test_he_is_reachable_as_a_subject_after_the_follow_up(self):
        """What a pronoun resolves through. Present even though turn two
        anchored nothing of its own."""
        assert any(h.id == "cos:rictavio" for h in self._two_turns().subjects())

    def test_the_junk_the_follow_up_retrieved_became_no_subjects(self):
        """Turn two returns eight `Special Events` sections. Only ANCHORS
        become nodes, so none of them is now something the conversation
        believes itself to be about."""
        names = {h.name for h in self._two_turns().subjects(limit=99)}
        assert "Special Events" not in names


class TestSeedingIsSelective:
    """A turn that resolved no name contributes nothing to what the
    conversation is about. Found live rather than in a unit test: the
    follow-up's 93 incidental edges were seeded, pinned as current-turn, and
    eviction dropped Rictavio to make room for them."""

    @staticmethod
    def _text_path_retrieval():
        from backend.canon.retrieval import PATH_TEXT, Passage, Retrieval

        return Retrieval(
            question="what about him makes him special",
            anchors=(),
            passages=(Passage("cos:x#1", "ch", 0, "Special Events", 1, "t", 0, ()),),
            proposed=({"entity": "Someone", "relationship": "KNOWS",
                       "other": "Else", "direction": "out"},),
            path=PATH_TEXT,
        )

    def test_an_unanchored_turn_seeds_no_edges(self):
        graph = Subgraph()
        seed(graph, self._text_path_retrieval())
        assert graph.edges == {}

    def test_it_still_records_the_sections_read(self):
        """Reading is a fact about the conversation even when the retrieval was
        a guess; only the CLAIMS are refused."""
        graph = Subgraph()
        seed(graph, self._text_path_retrieval())
        assert graph.already_read("cos:x#1")

    def test_an_unanchored_turn_cannot_evict_the_subject(self):
        """The bug, as the property it broke."""
        graph = Subgraph()
        graph.turn = 1
        graph.touch_node("cos:rictavio", "Rictavio", ["NPC"])
        graph.turn = 2
        seed(graph, self._text_path_retrieval())
        graph.evict(budget=1, estimate=lambda text: len(text.splitlines()))
        assert "cos:rictavio" in graph.nodes


class TestWhatTheAnswerNamed:
    """The third way in, and the one the other two cannot cover.

    Asked "who owns the tavern", retrieval anchors NOTHING -- `tavern` is a
    common noun and refused, and the question never spells out "Blood of the
    Vine Tavern". The text path answers it correctly anyway. Then "describe it"
    had nothing to resolve through and searched Lucene for `describe`, getting
    sections headed `Details`, `Age`, `Light`, `Humor` and `The Unknown`.
    """

    @staticmethod
    def _resolver(pairs):
        return lambda text: [p for p in pairs if p[1] in text]

    def test_an_entity_the_answer_named_becomes_a_subject(self):
        graph = Subgraph()
        note_named(
            graph,
            "The Blood of the Vine Tavern is owned by three Vistani.",
            self._resolver([("cos:tavern", "Blood of the Vine Tavern", ("LOCATION",))]),
        )
        assert [h.name for h in graph.subjects()] == ["Blood of the Vine Tavern"]

    def test_it_is_marked_as_named_rather_than_seeded(self):
        """Weaker evidence than a question resolving a name, and a reader of
        the subgraph should be able to tell which."""
        graph = Subgraph()
        note_named(graph, "Rictavio smiles.",
                   self._resolver([("cos:rictavio", "Rictavio", ("NPC",))]))
        assert graph.nodes["cos:rictavio"].how == NAMED

    def test_it_does_not_demote_something_the_question_resolved(self):
        graph = Subgraph()
        graph.touch_node("cos:rictavio", "Rictavio", ("NPC",), how=SEEDED)
        note_named(graph, "Rictavio smiles.",
                   self._resolver([("cos:rictavio", "Rictavio", ("NPC",))]))
        assert graph.nodes["cos:rictavio"].how == SEEDED

    def test_an_answer_naming_nothing_adds_nothing(self):
        graph = Subgraph()
        note_named(graph, "The canon does not cover that.", self._resolver([]))
        assert graph.nodes == {}


class TestTheViewForAReader:
    """`as_dict` is for the panel, `render` is for the model, and they carry
    different things on purpose."""

    @staticmethod
    def _held() -> Subgraph:
        graph = Subgraph()
        graph.turn = 2
        graph.touch_node("cos:tavern", "Blood of the Vine Tavern", ("LOCATION",))
        graph.touch_node("cos:alenka", "Alenka", ("NPC",), how=NAMED)
        graph.touch_edge("Alenka", "OWNS", "Blood of the Vine Tavern", "accepted")
        graph.touch_passage("cos:x#1")
        return graph

    def test_it_carries_how_each_thing_got_here(self):
        """The model does not need this; a person watching does. A node an
        answer happened to name is weaker than one a question resolved."""
        hows = {n["name"]: n["how"] for n in self._held().as_dict()["nodes"]}
        assert hows["Blood of the Vine Tavern"] == SEEDED
        assert hows["Alenka"] == NAMED

    def test_edges_keep_their_status(self):
        assert self._held().as_dict()["edges"][0]["status"] == "accepted"

    def test_passages_are_counted_not_listed(self):
        """A panel wants the number; the ids would be noise beside a picture."""
        assert self._held().as_dict()["passages"] == 1

    def test_an_empty_conversation_views_as_empty(self):
        view = Subgraph().as_dict()
        assert view["nodes"] == [] and view["edges"] == []

    def test_the_view_and_the_render_do_not_have_to_agree_on_shape(self):
        """One is JSON for a browser, the other is prose for a model. Asserted
        so a later refactor does not quietly make `render` the source of the
        panel and lose `how` from it."""
        view = self._held().as_dict()
        assert "how" in view["nodes"][0]
        assert "how" not in self._held().render()


class TestExpiringNameDrops:
    """A name an ANSWER used is held on a bet about the NEXT question. Once
    that question has come and gone without touching it, the bet is settled.

    Before this, nothing checked. Measured on a three-turn session, the working
    set for "Who owns the Blood of the Vine Tavern?" was the tavern plus seven
    `named` nodes left over from the previous answer's prose -- Ireena carrying
    22 relationships into a question about a pub, and Rahadin, who has nothing
    to do with any of it. All of them rendered into the prompt.
    """

    @staticmethod
    def _with_a_newer_subject(graph: Subgraph) -> None:
        """Something newer, sorting first by name.

        The most recent subject is pinned against expiry, so without this every
        test below would pass on the pin rather than on the rule -- vacuously.
        `subjects` orders by (-turn, name), so `AAA` takes the pin.
        """
        graph.touch_node("aaa", "AAA", ["NPC"])

    def test_it_survives_the_very_next_turn(self):
        """The case the whole mechanism exists for: "who owns the tavern"
        anchors nothing, the answer names the tavern, and "describe it" on the
        very next turn has to find it."""
        graph = Subgraph()
        graph.turn = 1
        graph.touch_node("t", "Blood of the Vine Tavern", ["PLACE"], how=NAMED)
        self._with_a_newer_subject(graph)
        graph.begin_turn()
        assert "Blood of the Vine Tavern" in held(graph)

    def test_it_is_gone_the_turn_after_that(self):
        graph = Subgraph()
        graph.turn = 1
        graph.touch_node("r", "Rahadin", ["NPC"], how=NAMED)
        self._with_a_newer_subject(graph)
        graph.begin_turn()
        graph.begin_turn()
        assert "Rahadin" not in held(graph)

    def test_naming_it_again_renews_the_grace(self):
        """A conversation that keeps returning to something keeps it."""
        graph = Subgraph()
        graph.turn = 1
        graph.touch_node("i", "Ireena", ["NPC"], how=NAMED)
        self._with_a_newer_subject(graph)
        graph.begin_turn()
        graph.touch_node("i", "Ireena", ["NPC"], how=NAMED)
        graph.begin_turn()
        assert "Ireena" in held(graph)

    def test_only_name_drops_expire(self):
        """A resolved name and a deliberate fetch are evidence about what the
        conversation is about. A name the model happened to utter is not, and
        that difference is the whole of `how`."""
        graph = Subgraph()
        graph.turn = 1
        graph.touch_node("s", "Seeded", ["NPC"], how=SEEDED)
        graph.touch_node("e", "Expanded", ["NPC"], how=EXPANDED)
        graph.touch_node("n", "Named", ["NPC"], how=NAMED)
        self._with_a_newer_subject(graph)
        graph.begin_turn()
        graph.begin_turn()
        assert sorted(held(graph)) == ["AAA", "Expanded", "Seeded"]

    def test_the_edges_go_with_it(self):
        """An edge whose endpoint is gone is a dangling claim about a name
        nothing else explains."""
        graph = Subgraph()
        graph.turn = 1
        graph.touch_node("g", "Ghost", ["NPC"], how=NAMED)
        graph.touch_edge("Ghost", "SERVES", "Strahd", "accepted")
        self._with_a_newer_subject(graph)
        graph.begin_turn()
        graph.begin_turn()
        assert "Ghost" not in graph.render()

    def test_the_last_subject_is_never_expired(self):
        """An empty subgraph is total amnesia -- the transcript is gone, so
        this is the only memory. Never the better trade."""
        graph = Subgraph()
        graph.turn = 1
        graph.touch_node("t", "Tavern", ["PLACE"], how=NAMED)
        graph.begin_turn()
        graph.begin_turn()
        graph.begin_turn()
        assert held(graph) == ["Tavern"]

    def test_it_reports_what_it_expired(self):
        graph = Subgraph()
        graph.turn = 1
        graph.touch_node("r", "Rahadin", ["NPC"], how=NAMED)
        self._with_a_newer_subject(graph)
        graph.begin_turn()
        assert graph.begin_turn() == 1

    def test_beginning_a_turn_advances_it(self):
        graph = Subgraph()
        graph.begin_turn()
        assert graph.turn == 1


class TestResidueIsSpentFirst:
    """Age alone got eviction backwards."""

    @staticmethod
    def _one_token_per_line(text: str) -> int:
        return len(text.splitlines())

    def _strahd_and_residue(self) -> Subgraph:
        """The shape measured on a real session: an entity whose relationships
        are OLD, and a bare name-drop that is younger."""
        graph = Subgraph()
        graph.touch_node("s", "Strahd", ["NPC"])
        graph.touch_edge("Strahd", "ALLIED_WITH", "Rahadin", "accepted")
        graph.turn = 1
        graph.touch_node("r", "Residue", ["NPC"], how=NAMED)
        graph.turn = 2
        # This turn's own subject, which takes the pin -- otherwise the
        # name-drop would be the most recent subject and pinned itself.
        graph.touch_node("q", "Asked", ["PLACE"])
        return graph

    def test_the_bare_name_goes_before_the_older_relationships(self):
        """Strahd survived a real session as a bare `Strahd von Zarovich
        (LORE/NPC)` line with ZERO edges, because he had been re-named on a
        later turn while the 51 relationships that actually said something
        about him were evicted for being older."""
        graph = self._strahd_and_residue()
        graph.evict(budget=5, estimate=self._one_token_per_line)
        assert "Residue" not in held(graph)
        assert "Strahd -ALLIED_WITH-> Rahadin" in graph.render()

    def test_a_name_drop_with_relationships_is_not_residue(self):
        """`named` is not itself the disqualifier -- carrying no structure is.
        A name-drop the graph has something to say about is ordinary, and ages
        out by turn like everything else."""
        graph = self._strahd_and_residue()
        graph.touch_edge("Residue", "LIVES_IN", "Barovia", "accepted")
        graph.turn = 2
        graph.evict(budget=5, estimate=self._one_token_per_line)
        assert "Residue" in held(graph)
