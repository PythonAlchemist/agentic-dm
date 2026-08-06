"""Shared fixtures. Neo4j-backed tests clean up the nodes they create."""

import pytest

from backend.core.database import neo4j_session

TEST_ID_PREFIX = "pytest:"


@pytest.fixture
def graph():
    """Yield a Neo4j session; delete every node this test created on teardown.

    Nodes are identified by an id starting with TEST_ID_PREFIX, so this never
    touches real data even when pointed at a populated database.
    """
    with neo4j_session() as session:
        session.run(
            "MATCH (n:Entity) WHERE n.id STARTS WITH $p DETACH DELETE n",
            {"p": TEST_ID_PREFIX},
        )
        yield session
        session.run(
            "MATCH (n:Entity) WHERE n.id STARTS WITH $p DETACH DELETE n",
            {"p": TEST_ID_PREFIX},
        )
