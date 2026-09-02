"""What a player's question may reach.

Every test here is about what is NOT in the result. A retriever that returns
the right passage is easy; one that can never return the wrong one is the whole
point, because there is no post-filter that undoes having told a model a
secret.
"""

import pytest

from backend.core.database import neo4j_session
from backend.player import reader as visibility
from backend.player.retrieval import PlayerRetriever

PREFIX = "pytest-pret"
SLUG = f"{PREFIX}-camp"
COACHMAN = f"{PREFIX}:strahd"
VILLAGE = f"{PREFIX}:the-village"
TWIST = f"{PREFIX}:the-twist"


@pytest.fixture
def graph():
    with neo4j_session() as session:
        def clean(s):
            s.run("MATCH (n) WHERE n.campaign = $c DETACH DELETE n",
                  {"c": SLUG}).consume()
            s.run("MATCH (n) WHERE n.id STARTS WITH $p DETACH DELETE n",
                  {"p": PREFIX}).consume()
            s.run("MATCH (c:Campaign {slug:$c}) DETACH DELETE c",
                  {"c": SLUG}).consume()
            # `:Alias` IS UNIQUE ON `name` ACROSS THE WHOLE GRAPH, so this
            # fixture cannot borrow a real spelling -- "Strahd" already exists
            # and creating it again is a constraint violation, not a duplicate.
            s.run("MATCH (a:Alias {name:'Pytestrand'}) DETACH DELETE a").consume()

        clean(session)
        session.run(
            "CREATE (:Campaign {slug:$slug, name:'Ret', campaign:$slug}) "
            "CREATE (e:Entity:NPC {id:$e, plane:'canon', "
            "  name:'Pytestrand the Grim'}) "
            "CREATE (v:Section {id:$v, heading:'The Village', plane:'canon', "
            "  text:'Mist lies over the village and the coach waits.'}) "
            "CREATE (t:Section {id:$t, heading:'The Twist', plane:'canon', "
            "  text:'Ireena is his lost bride, taken long ago.'}) "
            "CREATE (m1:Mention {id:$m1})-[:REFERS_TO]->(e) "
            "CREATE (m1)-[:IN_SECTION]->(v) "
            "CREATE (m2:Mention {id:$m2})-[:REFERS_TO]->(e) "
            "CREATE (m2)-[:IN_SECTION]->(t) "
            # Nobody types "Strahd von Zarovich". `ALIAS_OF` is where the
            # book's own spellings already live.
            "CREATE (:Alias {name:'Pytestrand'})-[:ALIAS_OF]->(e)",
            {"slug": SLUG, "e": COACHMAN, "v": VILLAGE, "t": TWIST,
             "m1": f"{COACHMAN}@{VILLAGE}", "m2": f"{COACHMAN}@{TWIST}"},
        ).consume()
        yield session
        clean(session)


def _reveal(graph, target, **kw):
    graph.execute_write(lambda tx: visibility.reveal(
        tx, slug=SLUG, target=target, **kw))


def _ask(question: str):
    return PlayerRetriever(campaign=SLUG, book=PREFIX).retrieve(question)


class TestAnUntoldTable:
    def test_a_question_reaches_nothing(self, graph):
        found = _ask("who is Pytestrand?")
        assert found.passages == () and found.anchors == ()

    def test_and_says_so_rather_than_failing_silently(self, graph):
        assert "told about" in _ask("who is Pytestrand?").miss_reason

    def test_the_book_is_not_searched_for_words_either(self, graph):
        """The text fallback is scoped to the grant. Otherwise a player asking
        about "bride" reads chapter nine."""
        assert _ask("tell me about the bride").passages == ()


class TestOnceTheyHaveBeenTold:
    def test_a_revealed_section_answers(self, graph):
        _reveal(graph, COACHMAN)
        _reveal(graph, VILLAGE)
        found = _ask("what happened in the village?")
        assert [p.section == "The Village" for p in found.passages] == [True]

    def test_the_unrevealed_section_is_not_among_them(self, graph):
        """Both grants, or nothing. A revealed entity does not drag its
        secrets along."""
        _reveal(graph, COACHMAN)
        _reveal(graph, VILLAGE)
        found = _ask("tell me about Pytestrand")
        assert "lost bride" not in str(found)
        assert [p.section for p in found.passages] == ["The Village"]

    def test_revealing_the_entity_alone_answers_with_no_prose(self, graph):
        _reveal(graph, COACHMAN)
        found = _ask("tell me about Pytestrand")
        assert found.anchors and found.passages == ()

    def test_concealing_shuts_it_again(self, graph):
        _reveal(graph, COACHMAN)
        _reveal(graph, VILLAGE)
        graph.execute_write(lambda tx: visibility.conceal(
            tx, slug=SLUG, target=VILLAGE))
        assert _ask("what happened in the village?").passages == ()


class TestTheNameTheyKnowItBy:
    def test_the_alias_is_what_anchors(self, graph):
        """A player who only knows "the coachman" types that."""
        _reveal(graph, COACHMAN, as_name="the coachman")
        _reveal(graph, VILLAGE)
        found = _ask("where did the coachman take us?")
        assert [a.name for a in found.anchors] == ["the coachman"]

    def test_the_true_name_does_not_anchor_and_does_not_appear(self, graph):
        """Matching the true name would both fail the player and reveal, in
        the retrieval report, that the two are the same."""
        _reveal(graph, COACHMAN, as_name="the coachman")
        _reveal(graph, VILLAGE)
        found = _ask("tell me about Pytestrand the Grim")
        assert found.anchors == ()
        assert "Pytestrand" not in str(found.anchors)


class TestTheDoorsItDoesNotOpen:
    def test_focus_is_ignored(self, graph):
        """What the DM has open is not checked against a grant, so honouring
        it would be a second door into the same room."""
        _reveal(graph, COACHMAN)
        found = PlayerRetriever(campaign=SLUG, book=PREFIX).retrieve(
            "anything", focus=TWIST)
        assert "lost bride" not in str(found)

    def test_carry_is_ignored(self, graph):
        found = PlayerRetriever(campaign=SLUG, book=PREFIX).retrieve(
            "anything", carry=[TWIST])
        assert found.passages == ()

    def test_it_proposes_no_guessed_edges(self, graph):
        """A guessed edge is the extractor's opinion, which is a DM's material
        to weigh -- not something to put in front of somebody with no way to
        check it."""
        _reveal(graph, COACHMAN)
        _reveal(graph, VILLAGE)
        assert _ask("tell me about Pytestrand").proposed == ()

    def test_a_citation_does_not_say_how_far_through_the_book_it_sits(self, graph):
        """A chapter name is a small map of what is left."""
        _reveal(graph, COACHMAN)
        _reveal(graph, VILLAGE)
        assert all(p.chapter == "" for p in _ask("the village").passages)


class TestTheShapeThatKeepsItTrue:
    def test_every_query_gates_before_it_returns(self):
        """The same sweep the gated routes get, in the same stronger form.

        A leak here is a query that selects prose before it checks whether the
        table may have it -- so everything before the first RETURN must carry
        both legitimate branches, the grant and the rulebook. A third branch
        added later fails this until somebody writes it down.
        """
        from backend.player import retrieval

        for name in ("GRANTED_ENTITIES", "GRANTED_PASSAGES", "GRANTED_TEXT"):
            selection = getattr(retrieval, name).split("RETURN")[0]
            assert "REVEALED" in selection, f"{name} does not check a grant"
            assert "b.reference = true" in selection, (
                f"{name} does not check for a rulebook")


class TestPeopleSaySurnames:
    """"What do we know about Saltmarrow" is the question a player asks.
    Matching only the full name answers it with silence, which reads as "your
    DM has told you nothing"."""

    def test_part_of_a_name_anchors(self, graph):
        _reveal(graph, COACHMAN)
        assert [a.name for a in _ask("what about Pytestrand?").anchors] == [
            "Pytestrand the Grim"]

    def test_a_title_alone_does_not(self, graph):
        """A title is not an identity, and matching one would anchor "who is
        the captain" to whichever captain the table has met."""
        _reveal(graph, COACHMAN, as_name="the Captain of the Guard")
        assert _ask("who is the captain?").anchors == ()

    def test_a_loose_match_still_cannot_reach_an_ungranted_name(self, graph):
        """Generous, and only among things already revealed."""
        assert _ask("what about Pytestrand?").anchors == ()

    def test_knowing_of_somebody_reads_differently_from_never_hearing_of_them(
            self, graph):
        """Two empty answers that lead to different next questions."""
        _reveal(graph, COACHMAN)
        known = _ask("what about Pytestrand?")
        unknown = _ask("what about the archmage?")
        assert "but nothing your table has been shown" in known.miss_reason
        assert "nothing your table has been told about" in unknown.miss_reason
