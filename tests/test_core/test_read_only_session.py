"""The one invariant a model's query cannot be trusted to respect itself.

The conversational-subgraph design has a graph agent composing Cypher. Every
other guard in that design is about what a query must PROJECT -- `status` on
each edge, `plane` always filtered -- and those are enforced by wrapping the
query. This one is about what a query may DO, and it has to hold even when the
query is hostile, malformed, or simply wrong.

Marked `neo4j` because a security control asserted against a mock proves that
the mock is read-only.
"""

import pytest

from backend.core.database import ReadOnlySession, read_only_session

pytestmark = pytest.mark.neo4j

#: Namespaced so that a failure to block leaves something findable and
#: deletable rather than a stray node nobody can identify.
PROBE = "__ReadOnlyProbeTest"


@pytest.fixture(autouse=True)
def no_probe_survives():
    """Delete anything a failing test managed to write.

    A test that proves the control is broken must not also leave the graph
    dirty for every test after it.
    """
    yield
    from backend.core.database import neo4j_session

    with neo4j_session() as session:
        session.run(f"MATCH (n:{PROBE}) DETACH DELETE n").consume()


@pytest.mark.corpus
class TestItCanRead:
    def test_a_match_returns_rows(self):
        with read_only_session() as session:
            count = session.run(
                "MATCH (e:Entity {plane:$plane}) RETURN count(e) AS n",
                {"plane": "canon"},
            ).single()["n"]
        assert count > 0

    def test_parameters_are_passed_through(self):
        with read_only_session() as session:
            got = session.run("RETURN $x AS x", {"x": 7}).single()["x"]
        assert got == 7

    def test_a_query_with_no_parameters_works(self):
        """`run` defaults them, so a caller need not pass an empty dict."""
        with read_only_session() as session:
            assert session.run("RETURN 1 AS one").single()["one"] == 1


class TestItCannotWrite:
    """Enforced SERVER-SIDE, by read access mode, not by inspecting the query
    string. A parser that tried to spot writes would be a denylist, and a
    denylist for Cypher is a promise nobody can keep."""

    @pytest.mark.parametrize(
        "query",
        [
            f"CREATE (n:{PROBE}) RETURN n",
            f"MERGE (n:{PROBE} {{id:'x'}}) RETURN n",
            f"MATCH (n:{PROBE}) SET n.touched = true RETURN n",
            f"MATCH (n:{PROBE}) DETACH DELETE n",
            f"CREATE (a:{PROBE})-[:KNOWS]->(b:{PROBE}) RETURN a",
        ],
    )
    def test_every_shape_of_write_is_refused(self, query):
        with read_only_session() as session:
            with pytest.raises(Exception) as raised:
                session.run(query).consume()
        assert "AccessMode" in str(raised.value)

    def test_nothing_was_written_by_the_attempts(self):
        from backend.core.database import neo4j_session

        with read_only_session() as session:
            with pytest.raises(Exception):
                session.run(f"CREATE (n:{PROBE}) RETURN n").consume()
        with neo4j_session() as session:
            left = session.run(f"MATCH (n:{PROBE}) RETURN count(n) AS n").single()["n"]
        assert left == 0


class TestTheBypassIsNotReachable:
    """THE FINDING THIS WRAPPER EXISTS FOR.

    Read access mode is a DEFAULT, and `execute_write` overrides it. Probed on
    the live database: a write inside `execute_read` is blocked, a write run
    directly on a read-mode session is blocked, and a write inside
    `execute_write` on that same read-mode session GOES THROUGH.

    So handing a caller a correctly configured session is a guarantee with a
    documented bypass one method call away. The wrapper exposes `run` and
    nothing else, which is what makes the guarantee hold for a caller who has
    not read the docstring -- or for a model composing a query.
    """

    def test_the_wrapper_does_not_expose_execute_write(self):
        with read_only_session() as session:
            assert not hasattr(session, "execute_write")

    def test_nor_any_other_transaction_entry_point(self):
        """`begin_transaction` inherits read mode and `execute_read` is safe,
        but neither is needed and both widen what a caller can reach."""
        with read_only_session() as session:
            for escape in ("begin_transaction", "execute_read", "execute_write"):
                assert not hasattr(session, escape), escape

    def test_the_raw_session_is_not_handed_out(self):
        with read_only_session() as session:
            assert isinstance(session, ReadOnlySession)


class TestTheSessionCloses:
    def test_it_closes_even_when_the_body_raises(self):
        """A session leaked per failed query would exhaust the pool, and the
        failure mode here is a model sending queries that raise."""
        with pytest.raises(ValueError):
            with read_only_session() as session:
                session.run("RETURN 1").consume()
                raise ValueError("boom")

        with read_only_session() as session:
            assert session.run("RETURN 1 AS one").single()["one"] == 1
