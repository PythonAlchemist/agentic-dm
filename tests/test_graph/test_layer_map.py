"""The type->layer map must be total: a missing entry silently mis-counts
intersection queries, which are the payoff of the layer axis."""

from backend.graph.schema import LAYER_MAP, RESOLVABLE_TYPES, Layer, RelationshipType


class TestLayerMapTotality:
    def test_every_relationship_type_is_classified(self):
        missing = [r.value for r in RelationshipType if r not in LAYER_MAP]
        assert missing == [], f"unclassified relationship types: {missing}"

    def test_no_stale_entries(self):
        stale = [r for r in LAYER_MAP if r not in set(RelationshipType)]
        assert stale == []

    def test_values_are_layer_or_none(self):
        for rel, layer in LAYER_MAP.items():
            assert layer is None or isinstance(layer, Layer), f"{rel} -> {layer!r}"


class TestNarrativeVocabulary:
    def test_new_types_exist(self):
        for name in (
            "SEEKS",
            "OPPOSES",
            "IDENTITY_OF",
            "RESOLVES_TO",
            "PREREQUISITE_OF",
            "THREATENS",
        ):
            assert hasattr(RelationshipType, name), f"missing {name}"

    def test_pursuing_removed(self):
        """Folded into SEEKS so an extractor cannot emit both."""
        assert not hasattr(RelationshipType, "PURSUING")

    def test_new_types_are_narrative(self):
        for name in ("SEEKS", "OPPOSES", "IDENTITY_OF", "RESOLVES_TO",
                     "PREREQUISITE_OF", "THREATENS"):
            assert LAYER_MAP[RelationshipType[name]] is Layer.NARRATIVE

    def test_objective_at_is_narrative_not_spatial(self):
        """It points at a LOCATION, but the edge is about the quest -- this is
        what makes that location an intersection node."""
        assert LAYER_MAP[RelationshipType.OBJECTIVE_AT] is Layer.NARRATIVE

    def test_possession_is_social(self):
        assert LAYER_MAP[RelationshipType.OWNS] is Layer.SOCIAL
        assert LAYER_MAP[RelationshipType.GUARDS] is Layer.SOCIAL

    def test_plane_linking_edges_are_not_surfaces(self):
        assert LAYER_MAP[RelationshipType.INSTANCE_OF] is None
        assert LAYER_MAP[RelationshipType.BELONGS_TO] is None


class TestResolvableTypes:
    def test_only_resolves_to_is_resolvable(self):
        assert RESOLVABLE_TYPES == {RelationshipType.RESOLVES_TO}
