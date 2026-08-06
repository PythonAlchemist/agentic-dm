"""Merge and shadow decide what a table sees. No database involved."""

from backend.graph.resolver import merge_properties, shadow_edges


def edge(source, rel_type, target, layer="narrative", plane="canon"):
    return {
        "source_id": source,
        "target_id": target,
        "rel_type": rel_type,
        "layer": layer,
        "plane": plane,
    }


class TestMergeProperties:
    def test_canon_only_passes_through(self):
        canon = {"id": "cos:npc:ireena", "name": "Ireena", "status": "alive"}
        assert merge_properties(canon, None) == canon

    def test_campaign_overrides_win(self):
        canon = {"id": "cos:npc:ireena", "name": "Ireena", "status": "alive"}
        camp = {"status": "dead"}
        assert merge_properties(canon, camp)["status"] == "dead"

    def test_sparse_patch_does_not_clobber_unset_canon_fields(self):
        canon = {"id": "x", "name": "Ireena", "description": "burgomaster's sister"}
        merged = merge_properties(canon, {"status": "dead"})
        assert merged["description"] == "burgomaster's sister"
        assert merged["name"] == "Ireena"

    def test_empty_campaign_patch_is_a_noop(self):
        canon = {"id": "x", "name": "Ireena"}
        assert merge_properties(canon, {}) == canon

    def test_inputs_are_not_mutated(self):
        canon = {"id": "x", "name": "Ireena"}
        camp = {"status": "dead"}
        merge_properties(canon, camp)
        assert canon == {"id": "x", "name": "Ireena"}
        assert camp == {"status": "dead"}


class TestShadowEdges:
    def test_additive_types_union(self):
        canon = [edge("strahd", "SEEKS", "ireena")]
        campaign = [edge("strahd", "SEEKS", "tatyana", plane="campaign")]
        result = shadow_edges(canon, campaign)
        assert len(result) == 2

    def test_resolvable_type_shadows_canon_fan_out(self):
        """The Tarokka collapse: ten canon candidates become the one drawn."""
        canon = [
            edge("cos:item:sunsword", "RESOLVES_TO", f"cos:location:site-{i}")
            for i in range(10)
        ]
        campaign = [
            edge("cos:item:sunsword", "RESOLVES_TO", "cos:location:amber-temple",
                 plane="campaign")
        ]
        result = shadow_edges(canon, campaign)
        assert len(result) == 1
        assert result[0]["target_id"] == "cos:location:amber-temple"

    def test_shadowing_is_scoped_to_the_same_source(self):
        """A draw for the Sunsword must not blank the Holy Symbol's candidates."""
        canon = [
            edge("cos:item:sunsword", "RESOLVES_TO", "cos:location:a"),
            edge("cos:item:holy-symbol", "RESOLVES_TO", "cos:location:b"),
        ]
        campaign = [
            edge("cos:item:sunsword", "RESOLVES_TO", "cos:location:c", plane="campaign")
        ]
        result = shadow_edges(canon, campaign)
        targets = sorted(e["target_id"] for e in result)
        assert targets == ["cos:location:b", "cos:location:c"]

    def test_shadowing_is_scoped_to_the_same_type(self):
        canon = [
            edge("cos:item:sunsword", "RESOLVES_TO", "cos:location:a"),
            edge("cos:item:sunsword", "SEEKS", "cos:npc:someone"),
        ]
        campaign = [
            edge("cos:item:sunsword", "RESOLVES_TO", "cos:location:c", plane="campaign")
        ]
        result = shadow_edges(canon, campaign)
        types = sorted(e["rel_type"] for e in result)
        assert types == ["RESOLVES_TO", "SEEKS"]

    def test_no_campaign_edges_leaves_canon_intact(self):
        canon = [edge("a", "RESOLVES_TO", "b")]
        assert shadow_edges(canon, []) == canon

    def test_campaign_only_edges_survive(self):
        campaign = [edge("a", "SEEKS", "b", plane="campaign")]
        assert shadow_edges([], campaign) == campaign
