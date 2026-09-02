"""Keeping caller text out of the query, on the path that had no guard.

`get_neighbors` interpolated a comma-split query parameter straight into the
Cypher -- `"|".join(relationship_types)` -- and every method in that module
runs on the FULL-WRITE session. So a value that closed the pattern ran whatever
followed it: read the whole graph in one request, or delete it. The module
already knew the hazard; `create_relationship` twelve lines below carries a
comment calling the enum coercion "the only thing keeping an arbitrary caller
string out of the query text". This path simply never got it.

The plane pins are the same story one level up. A forged NODE eventually trips
`UNSUPPORTED_ENTITIES`; a forged EDGE trips nothing, and `lookup.EDGES` serves
it to a DM as the book's own derived fact.
"""

import pytest

from backend.campaign.model import CAMPAIGN_PLANE
from backend.graph.operations import _hops, _relationship_tokens
from backend.graph.schema import RelationshipType


class TestOnlyTypesThisGraphWritesReachTheQuery:
    def test_a_real_type_passes(self):
        assert _relationship_tokens(["LOCATED_IN", "CONTAINS"]) == [
            "LOCATED_IN", "CONTAINS"]

    def test_an_enum_member_passes(self):
        assert _relationship_tokens([RelationshipType.LOCATED_IN]) == ["LOCATED_IN"]

    def test_a_pattern_breakout_is_refused(self):
        """The shape that made this exploitable: close the relationship
        pattern, append a statement, comment out the tail."""
        with pytest.raises(ValueError):
            _relationship_tokens(["X*1..1]-() MATCH (n) DETACH DELETE n //"])

    def test_an_unknown_type_is_refused(self):
        with pytest.raises(ValueError):
            _relationship_tokens(["NOT_A_REAL_TYPE"])

    def test_one_bad_type_refuses_the_whole_request(self):
        """Rather than dropping the bad half: a filter that quietly ignored an
        unknown type would answer a question the caller did not ask."""
        with pytest.raises(ValueError):
            _relationship_tokens(["LOCATED_IN", "DROP EVERYTHING"])

    def test_an_empty_filter_is_refused(self):
        with pytest.raises(ValueError):
            _relationship_tokens([])
        with pytest.raises(ValueError):
            _relationship_tokens(["   "])


class TestTheHopBoundIsBounded:
    """Also interpolated, because Cypher cannot parameterise a variable-length
    bound. FastAPI's `int` is what stops an injection; the cap is because an
    unbounded traversal of a 13,000-node graph is its own outage."""

    @pytest.mark.parametrize("hops", [1, 3, 5])
    def test_a_sane_depth_passes(self, hops):
        assert _hops(hops) == hops

    @pytest.mark.parametrize("hops", [0, -1, 6, 999])
    def test_anything_else_is_refused(self, hops):
        with pytest.raises(ValueError):
            _hops(hops)


class TestThePlaneIsPinnedNotDefaulted:
    """It was `setdefault`, so a caller sending `plane: canon` won -- and the
    route hands the properties dict straight through from the request body."""

    def _props(self, fn, sent):
        """What the write would carry, without touching a database."""
        import backend.graph.operations as ops
        captured = {}

        class _Session:
            def run(self, _query, **params):
                captured.update(params.get("properties") or {})
                return _Result()

            def __enter__(self): return self
            def __exit__(self, *_): return False

        class _Result:
            def single(self): return None

        original = ops.neo4j_session
        ops.neo4j_session = lambda: _Session()
        try:
            fn(sent)
        finally:
            ops.neo4j_session = original
        return captured

    def test_a_caller_cannot_write_onto_the_canon_plane(self):
        import backend.graph.operations as ops

        got = self._props(
            lambda sent: ops.CampaignGraphOps.create_relationship(
                object.__new__(ops.CampaignGraphOps),
                source_id="a", target_id="b",
                relationship_type="LOCATED_IN", properties=sent),
            {"plane": "canon", "status": "accepted"},
        )
        assert got["plane"] == CAMPAIGN_PLANE
        assert "status" not in got, "a forged accepted edge reads as the book's"

    def test_other_properties_still_travel(self):
        import backend.graph.operations as ops

        got = self._props(
            lambda sent: ops.CampaignGraphOps.create_relationship(
                object.__new__(ops.CampaignGraphOps),
                source_id="a", target_id="b",
                relationship_type="LOCATED_IN", properties=sent),
            {"note": "kept"},
        )
        assert got["note"] == "kept"
