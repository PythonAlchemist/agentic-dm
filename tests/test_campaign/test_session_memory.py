"""A conversation that survives the process it started in.

The subgraph IS the memory: `dm_agent._trim` bounds the transcript to the
current question and leans on the subgraph to carry who the conversation is
about. It lived in a dict on one uvicorn worker, so every deploy, restart and
LRU eviction was amnesia mid-campaign -- and `/elements` is documented as "THE
FRESH-SESSION ENTRY POINT" precisely because of it.
"""

import json

import pytest

from backend.agents.subgraph import NAMED, SEEDED, Subgraph
from backend.campaign import memory
from backend.core.database import neo4j_session

PREFIX = "pytest-mem"
SESSION = f"{PREFIX}:session-1"


@pytest.fixture
def graph():
    def clean(s):
        s.run("MATCH (m:SessionMemory) WHERE m.id STARTS WITH $p DETACH DELETE m",
              {"p": PREFIX}).consume()

    with neo4j_session() as session:
        clean(session)
        yield session
        clean(session)


def _subgraph():
    found = Subgraph()
    found.begin_turn()
    found.touch_node("cos:strahd", "Strahd", ["NPC"], how=SEEDED)
    found.touch_node("cos:ireena", "Ireena", ["NPC"], how=NAMED)
    found.passages["cos:the-village-of-barovia#3"] = 1
    return found


def _save(graph, sub, *, book="cos", campaign="p13"):
    graph.execute_write(lambda tx: memory.save(
        tx, session_id=SESSION, book=book, campaign=campaign,
        snapshot=sub.snapshot(), updated_at="2026-09-02T00:00:00Z"))


def _load(graph, *, book="cos", campaign="p13"):
    return graph.execute_read(lambda tx: memory.load(
        tx, session_id=SESSION, book=book, campaign=campaign))


class TestItSurvivesTheProcess:
    def test_what_was_saved_comes_back(self, graph):
        _save(graph, _subgraph())
        back = Subgraph.restore(_load(graph))
        assert sorted(back.nodes) == ["cos:ireena", "cos:strahd"]

    def test_the_passages_come_back_too(self, graph):
        """`as_dict` reports a COUNT, so restoring from it would drop which
        sections had been read and the conversation would re-fetch prose it
        had already seen. That is why `snapshot` exists beside it."""
        _save(graph, _subgraph())
        assert Subgraph.restore(_load(graph)).passages == {
            "cos:the-village-of-barovia#3": 1}

    def test_how_a_node_arrived_is_preserved(self, graph):
        """A node an answer happened to name is weaker evidence than one a
        question resolved, and the panel colours them differently."""
        _save(graph, _subgraph())
        back = Subgraph.restore(_load(graph))
        assert back.nodes["cos:strahd"].how == SEEDED
        assert back.nodes["cos:ireena"].how == NAMED

    def test_saving_twice_replaces_rather_than_doubles(self, graph):
        _save(graph, _subgraph())
        later = _subgraph()
        later.touch_node("cos:rahadin", "Rahadin", ["NPC"])
        _save(graph, later)
        rows = graph.run(
            "MATCH (m:SessionMemory {id:$i}) RETURN count(m) AS n",
            {"i": SESSION}).single()["n"]
        assert rows == 1
        assert "cos:rahadin" in Subgraph.restore(_load(graph)).nodes


class TestItRefusesAMemoryOfAnotherWorld:
    """`_agent_for` treats a changed book or campaign as a new thread, because
    the subgraph holds entities by id and carrying one table's cast into
    another is the bleed the scoping exists to stop. The same rule has to hold
    across a restart, or the restore is the hole the live path refuses to be."""

    def test_another_book_gets_nothing(self, graph):
        _save(graph, _subgraph(), book="cos")
        assert _load(graph, book="kftgv") is None

    def test_another_campaign_gets_nothing(self, graph):
        _save(graph, _subgraph(), campaign="p13")
        assert _load(graph, campaign="someone-else") is None

    def test_the_canon_only_session_is_its_own_world(self, graph):
        """`campaign=None` is a real value here, not a wildcard."""
        _save(graph, _subgraph(), campaign=None)
        assert _load(graph, campaign=None) is not None
        assert _load(graph, campaign="p13") is None


class TestItFailsSoftly:
    def test_an_unknown_session_is_none_not_an_error(self, graph):
        assert graph.execute_read(lambda tx: memory.load(
            tx, session_id=f"{PREFIX}:never", book="cos", campaign="p13")) is None

    def test_an_unreadable_snapshot_is_none(self, graph):
        """A DM asking a question should not meet a 500 because a stored blob
        will not parse. They lose the thread, which is what they would have
        lost anyway."""
        graph.run(
            "CREATE (m:SessionMemory {id:$i, book:'cos', campaign:'p13', "
            "snapshot:'not json at all'})", {"i": SESSION}).consume()
        assert _load(graph) is None

    def test_forget_removes_it(self, graph):
        """Reset means the conversation, not just this process's copy."""
        _save(graph, _subgraph())
        assert graph.execute_write(
            lambda tx: memory.forget(tx, session_id=SESSION)) == 1
        assert _load(graph) is None

    def test_forgetting_nothing_is_not_an_error(self, graph):
        assert graph.execute_write(
            lambda tx: memory.forget(tx, session_id=f"{PREFIX}:absent")) == 0


class TestDeletingACampaignTakesItsConversations:
    """A table's memory of a table that no longer exists is exactly the debris
    the invariants hunt: it would restore a subgraph naming entities the delete
    has just removed."""

    def test_the_sweep_reaches_it(self, graph):
        from backend.campaign import store
        from backend.campaign.model import Campaign

        slug = f"{PREFIX}-campaign"
        graph.execute_write(
            lambda tx: store.create(tx, Campaign(slug=slug, name="M", books=())))
        graph.execute_write(lambda tx: memory.save(
            tx, session_id=SESSION, book="cos", campaign=slug,
            snapshot=_subgraph().snapshot(), updated_at="2026-09-02T00:00:00Z"))
        try:
            counted = graph.execute_write(
                lambda tx: store.delete_campaign(tx, slug))
        finally:
            graph.run("MATCH (c:Campaign {slug:$s}) DETACH DELETE c",
                      {"s": slug}).consume()
        # KEYED BY LABEL, since the sweep iterates 
        # rather than a hand-written list of phrases.
        assert counted.get("SessionMemory") == 1
        assert graph.run(
            "MATCH (m:SessionMemory {id:$i}) RETURN count(m) AS n",
            {"i": SESSION}).single()["n"] == 0
