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
            f"CREATE (:Entity {{id:'{PREFIX}:said', plane:'canon', name:'Strahd'}}) "
            f"CREATE (:Entity {{id:'{PREFIX}:mine', plane:'campaign', "
            f"campaign:'{PREFIX}', name:'A DM invention'}})"
        # CONSUMED: `_with_provenance` opens its own session, and this
        # auto-commit write is not committed until its result is. This was a
        # polling loop, on the theory that the read needed a bookmark; the
        # actual fault was an uncommitted transaction. See `tests/conftest.py`.
        ).consume()
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

    def test_a_node_the_graph_does_not_hold_gets_no_verdict(self, graph):
        """It used to be answered `true` -- "the book names this" -- about a
        node the query could not find at all. Now it is left alone, and the
        frontend badges only an explicit `false`."""
        found = _with_provenance(_sub(f"{PREFIX}:nowhere"))
        assert "named_by_book" not in found["nodes"][0]


class TestItNeverCostsAnAnswer:
    """A panel decoration is not worth a 500 on a reply that already cost money."""

    def test_no_subgraph_passes_through(self):
        assert _with_provenance(None) is None

    def test_an_empty_subgraph_passes_through(self):
        assert _with_provenance({"nodes": []}) == {"nodes": []}

    def test_a_node_with_no_id_does_not_raise(self, graph):
        found = _with_provenance({"nodes": [{"name": "nameless"}], "edges": []})
        assert "named_by_book" not in found["nodes"][0]


class TestACampaignNodeIsNotAnsweredFor:
    """The bug this had. It stamped every node, so a campaign session -- whose
    subgraph holds the DM's own invented NPCs -- got `named_by_book: true` on
    them: "the book names this", asserted over an invention, in the panel built
    to prevent exactly that."""

    def test_a_campaign_entity_gets_no_verdict(self, graph):
        found = _with_provenance(_sub(f"{PREFIX}:mine"))
        assert "named_by_book" not in found["nodes"][0]

    def test_canon_nodes_beside_it_are_still_answered(self, graph):
        found = _with_provenance(_sub(f"{PREFIX}:mine", f"{PREFIX}:quiet"))
        assert "named_by_book" not in found["nodes"][0]
        assert found["nodes"][1]["named_by_book"] is False
