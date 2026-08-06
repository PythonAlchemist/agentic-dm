"""Regression tests for how Cypher parameters are passed to the Neo4j driver.

`Session.run`'s own signature is `run(query, parameters=None, **kwparameters)`. Passing a
parameter dict with `**params` therefore collides whenever a key shares a name with one of
those arguments — `query` being the obvious one. That collision raises TypeError before any
Cypher runs, so it fails at runtime rather than at import or in a type check.
"""

from unittest.mock import MagicMock, patch

from backend.graph.operations import CampaignGraphOps


def _session_capture():
    """A neo4j_session() context manager whose .run() records how it was called."""
    session = MagicMock()
    session.run = MagicMock(return_value=iter([]))
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=session)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx, session


class TestSearchParameterPassing:
    def test_search_does_not_collide_with_session_run_query_arg(self):
        """The bug: search() built params={"query": ...} and spread it as **kwargs."""
        ctx, session = _session_capture()

        with patch("backend.graph.operations.neo4j_session", return_value=ctx):
            CampaignGraphOps().search(query="Ireena")

        # Cypher positional, params as the single positional dict — never **kwargs.
        args, kwargs = session.run.call_args
        assert len(args) == 2, f"expected run(cypher, params), got args={args!r}"
        assert isinstance(args[1], dict)
        assert args[1]["query"] == "Ireena"
        assert "query" not in kwargs

    def test_search_with_campaign_scope_passes_scope_params(self):
        ctx, session = _session_capture()

        with patch("backend.graph.operations.neo4j_session", return_value=ctx):
            CampaignGraphOps().search(query="Ireena", campaign_id="campaign_cos")

        params = session.run.call_args[0][1]
        assert params["campaign_id"] == "campaign_cos"
        assert "scoped_types" in params

    def test_list_entities_passes_params_positionally(self):
        ctx, session = _session_capture()

        with patch("backend.graph.operations.neo4j_session", return_value=ctx):
            CampaignGraphOps().list_entities(entity_type="NPC", limit=5)

        args, kwargs = session.run.call_args
        assert len(args) == 2
        assert isinstance(args[1], dict)
        assert kwargs == {}
