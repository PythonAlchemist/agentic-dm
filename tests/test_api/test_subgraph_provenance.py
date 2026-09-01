"""The subgraph panel is where a DM sees what an answer was built on.

Until this, it showed a node the extraction invented exactly like one the book
prints. The entity card had said so since the marking landed; this is the same
fact at the place the reader actually looks.
"""

import pytest

from backend.api.routes.lab import _with_provenance
from backend.core.database import neo4j_session
from backend.graph.schema import NAMED_BY_BOOK

PREFIX = "pytest-sgp"


@pytest.fixture
def graph():
    def clean(s):
        s.run(f"MATCH (n) WHERE n.id STARTS WITH '{PREFIX}' DETACH DELETE n")

    with neo4j_session() as session:
        clean(session)
        session.run(
            f"CREATE (:Entity {{id:'{PREFIX}:quiet', plane:'canon', "
            f"name:'Closet 1', {NAMED_BY_BOOK}:false}}) "
            f"CREATE (:Entity {{id:'{PREFIX}:said', plane:'canon', name:'Strahd'}})"
        )
        yield session
        clean(session)


def _sub(*ids):
    return {"nodes": [{"id": i, "name": i.split(":")[-1]} for i in ids], "edges": []}


class TestMarkingWhatTheBookDoesNotName:
    def test_an_unnamed_node_is_marked(self, graph):
        found = _with_provenance(_sub(f"{PREFIX}:quiet"))
        assert found["nodes"][0]["named_by_book"] is False

    def test_a_node_the_book_names_is_not(self, graph):
        found = _with_provenance(_sub(f"{PREFIX}:said"))
        assert found["nodes"][0]["named_by_book"] is True

    def test_both_in_one_subgraph(self, graph):
        found = _with_provenance(_sub(f"{PREFIX}:quiet", f"{PREFIX}:said"))
        assert [n["named_by_book"] for n in found["nodes"]] == [False, True]

    def test_a_node_the_graph_does_not_hold_is_not_called_unnamed(self, graph):
        """Absent means not marked, never "unknown". Reporting a node this
        cannot find as unnamed would put the badge on anything the panel
        happened to carry."""
        found = _with_provenance(_sub(f"{PREFIX}:nowhere"))
        assert found["nodes"][0]["named_by_book"] is True


class TestItNeverCostsAnAnswer:
    """A panel decoration is not worth a 500 on a reply that already cost money."""

    def test_no_subgraph_passes_through(self):
        assert _with_provenance(None) is None

    def test_an_empty_subgraph_passes_through(self):
        assert _with_provenance({"nodes": []}) == {"nodes": []}

    def test_a_node_with_no_id_does_not_raise(self, graph):
        found = _with_provenance({"nodes": [{"name": "nameless"}], "edges": []})
        assert found["nodes"][0]["named_by_book"] is True
