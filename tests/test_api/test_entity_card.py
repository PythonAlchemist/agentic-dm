"""The entity card's one load-bearing claim: whether the book names the thing.

154 canon entities cite no prose and are kept on purpose, so the card cannot
go on asserting "The book." over all of them. This covers the field the card
reads, at the endpoint, because a boolean that is right in Neo4j and wrong by
the time it reaches the reader is worth nothing.
"""

import time

import pytest

from backend.api.routes.homebrew import read_entity
from backend.core.database import neo4j_session
from backend.graph.schema import NAMED_BY_BOOK

PREFIX = "pytest-card"


@pytest.fixture
def graph():
    def clean(s):
        s.run(f"MATCH (n) WHERE n.id STARTS WITH '{PREFIX}' DETACH DELETE n")

    with neo4j_session() as session:
        clean(session)
        yield session
        clean(session)


def _await(cypher: str, params: dict, what: str, tries: int = 50) -> None:
    """Block until a NEW session can see this write.

    Not a sleep: it reads the way the code under test reads, so it waits for
    exactly the condition that matters and returns the moment it holds. The
    fixture writes in its own session and `read_entity` opens another, with no
    bookmark tying them, so the read can land on a snapshot from before the
    write -- the same shape `test_retrieval_overlay` documents.
    """
    for _ in range(tries):
        with neo4j_session() as fresh:
            if fresh.run(cypher, params).single()["n"]:
                return
        time.sleep(0.02)
    raise AssertionError(f"{what} never became visible to a new session")


def _entity(session, suffix: str, name: str, **props):
    extra = "".join(f", {k}:{v}" for k, v in props.items())
    session.run(
        f"CREATE (:Entity:NPC {{id:'{PREFIX}:{suffix}', plane:'canon', "
        f"name:$name{extra}}})",
        {"name": name},
    )
    entity_id = f"{PREFIX}:{suffix}"
    _await("MATCH (e:Entity {id:$id}) RETURN count(e) AS n",
           {"id": entity_id}, entity_id)
    return entity_id


class TestTheCardIsToldWhetherTheBookNamesIt:
    def test_an_entity_the_book_names_reports_true(self, graph):
        eid = _entity(graph, "named", "Ireena Kolyana")
        graph.run(
            f"MATCH (e:Entity {{id:$id}}) "
            f"CREATE (s:Section {{id:'{PREFIX}:sec', plane:'canon', "
            "heading:'A Section', text:'Ireena Kolyana waits here.'}) "
            f"CREATE (m:Mention {{id:$id + '@{PREFIX}:sec', plane:'canon', "
            "offsets:[0]}) "
            "CREATE (m)-[:REFERS_TO]->(e) CREATE (m)-[:IN_SECTION]->(s)",
            {"id": eid},
        )
        assert read_entity(eid)["named_by_book"] is True

    def test_an_entity_marked_unnamed_reports_false(self, graph):
        eid = _entity(graph, "quiet", "Side Room 2", **{NAMED_BY_BOOK: "false"})
        assert read_entity(eid)["named_by_book"] is False

    def test_an_unmarked_entity_with_no_mention_still_reports_true(self, graph):
        """ABSENCE IS NOT A CLAIM OF ABSENCE. A node nobody has marked yet is
        reported as the book's, which is the safe default only because the
        seventh invariant fails on exactly that state -- the graph is not
        allowed to sit in it quietly."""
        eid = _entity(graph, "unmarked", "Something")
        assert read_entity(eid)["named_by_book"] is True

    def test_it_is_always_a_bool_never_the_stored_value(self, graph):
        """The reader has no way to tell `null` from `false`, so the endpoint
        does not make them try."""
        eid = _entity(graph, "plain", "A Thing")
        assert isinstance(read_entity(eid)["named_by_book"], bool)
