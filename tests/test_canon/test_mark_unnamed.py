"""Marking an entity that cites no prose, and un-marking one that has earned it.

The DM ruled that entities the book never names are worth keeping, so the
repair is to record the gap rather than delete the node. These tests cover the
two halves that keep the record true: it is set on the silent ones, and it is
CLEARED from any entity that has since been named -- a stale mark would be the
graph lying, in the direction nobody would check.
"""

import pytest

from backend.core.database import neo4j_session
from backend.graph.schema import NAMED_BY_BOOK
from backend.scripts.mark_unnamed import TO_CLEAR, TO_MARK

PREFIX = "pytest-mark"
PARAMS = {"plane": "canon", "prefix": PREFIX}


@pytest.fixture
def graph():
    def clean(s):
        s.run(f"MATCH (n) WHERE n.id STARTS WITH '{PREFIX}' DETACH DELETE n")

    with neo4j_session() as session:
        clean(session)
        yield session
        clean(session)


def _ids(session, query):
    return {r["id"] for r in session.run(query, PARAMS)}


def _named(session, entity_id: str, section_id: str):
    """The mention triangle: an entity, a section, and the node joining them."""
    session.run(
        f"MATCH (e:Entity {{id:$e}}) "
        f"CREATE (s:Section {{id:$s, plane:'canon'}}) "
        f"CREATE (m:Mention {{id:$e + '@' + $s, plane:'canon'}}) "
        "CREATE (m)-[:REFERS_TO]->(e) CREATE (m)-[:IN_SECTION]->(s)",
        {"e": entity_id, "s": section_id},
    )


class TestItMarksTheSilentOnes:
    def test_an_entity_with_no_mention_is_selected(self, graph):
        graph.run(f"CREATE (:Entity {{id:'{PREFIX}:quiet', plane:'canon', "
                  "name:'Spellbook'})")
        assert f"{PREFIX}:quiet" in _ids(graph, TO_MARK)

    def test_an_entity_a_mention_names_is_not(self, graph):
        graph.run(f"CREATE (:Entity {{id:'{PREFIX}:said', plane:'canon', "
                  "name:'Ireena'})")
        _named(graph, f"{PREFIX}:said", f"{PREFIX}:sec1")
        assert f"{PREFIX}:said" not in _ids(graph, TO_MARK)

    def test_one_that_already_says_so_is_not_marked_again(self, graph):
        graph.run(f"CREATE (:Entity {{id:'{PREFIX}:done', plane:'canon', "
                  f"name:'Closet 1', {NAMED_BY_BOOK}:false}})")
        assert f"{PREFIX}:done" not in _ids(graph, TO_MARK)

    def test_a_campaign_entity_is_never_marked(self, graph):
        """The DM inventing someone is the campaign plane working. This
        property is a statement about the BOOK's plane and nothing else."""
        graph.run(f"CREATE (:Entity {{id:'{PREFIX}:authored', plane:'campaign', "
                  "name:'Someone the DM made up'})")
        assert f"{PREFIX}:authored" not in _ids(graph, TO_MARK)


class TestItClearsTheStaleOnes:
    """The half that keeps it honest. An entity that earns a mention -- from a
    new alias, a re-scan, a chapter written since -- is named by the book now."""

    def test_a_marked_entity_that_gained_a_mention_is_cleared(self, graph):
        graph.run(f"CREATE (:Entity {{id:'{PREFIX}:grew', plane:'canon', "
                  f"name:'Gunther Arasek', {NAMED_BY_BOOK}:false}})")
        _named(graph, f"{PREFIX}:grew", f"{PREFIX}:sec2")
        assert f"{PREFIX}:grew" in _ids(graph, TO_CLEAR)

    def test_a_marked_entity_still_unnamed_is_left_alone(self, graph):
        graph.run(f"CREATE (:Entity {{id:'{PREFIX}:still', plane:'canon', "
                  f"name:'Amethyst', {NAMED_BY_BOOK}:false}})")
        assert f"{PREFIX}:still" not in _ids(graph, TO_CLEAR)

    def test_an_unmarked_named_entity_is_not_touched(self, graph):
        graph.run(f"CREATE (:Entity {{id:'{PREFIX}:fine', plane:'canon', "
                  "name:'Strahd'})")
        _named(graph, f"{PREFIX}:fine", f"{PREFIX}:sec3")
        assert f"{PREFIX}:fine" not in _ids(graph, TO_CLEAR)

    def test_the_two_queries_never_select_the_same_entity(self, graph):
        """Marking and clearing are opposite moves; an entity in both would be
        written twice in one run and the second write would undo the first."""
        graph.run(f"CREATE (:Entity {{id:'{PREFIX}:a', plane:'canon', name:'A'}}) "
                  f"CREATE (:Entity {{id:'{PREFIX}:b', plane:'canon', name:'B', "
                  f"{NAMED_BY_BOOK}:false}})")
        _named(graph, f"{PREFIX}:b", f"{PREFIX}:sec4")
        assert not (_ids(graph, TO_MARK) & _ids(graph, TO_CLEAR))
