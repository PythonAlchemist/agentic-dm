"""Entities and edges created through the ops layer must carry the properties the
resolver filters on, or the resolver cannot see application-created data at all."""

import pytest

from backend.graph.operations import CampaignGraphOps
from backend.graph.schema import RelationshipType

pytestmark = pytest.mark.neo4j


class TestEntityPlaneStamp:
    def test_created_entity_defaults_to_campaign_plane(self, graph):
        ops = CampaignGraphOps()
        created = ops.create_entity(
            name="Test NPC", entity_type="NPC", entity_id="pytest:npc:stamp"
        )
        assert created["plane"] == "campaign"

    def test_a_caller_cannot_ask_for_the_canon_plane(self, graph):
        """This asserted the opposite, on a premise that was not true.

        Its docstring said "the seed loader writes canon; an explicit plane
        must not be overwritten" -- but no seed loader uses this class. Canon is
        written by `canon/writer.py`, which has its own Cypher; every caller of
        `CampaignGraphOps` is campaign-side (the Discord registry, the NER
        linker, the transcript processor, shop, players). What the old
        `setdefault` actually bought was a route -- `POST /api/campaign/entities`
        passes the request body's `properties` straight through -- by which any
        token-holder could mint a node on the book's own plane, which `lookup`
        then serves as the book's.
        """
        ops = CampaignGraphOps()
        created = ops.create_entity(
            name="Canon NPC",
            entity_type="NPC",
            entity_id="pytest:npc:canon-stamp",
            properties={"plane": "canon"},
        )
        assert created["plane"] == "campaign"


class TestRelationshipLayerStamp:
    def test_created_edge_carries_its_layer(self, graph):
        ops = CampaignGraphOps()
        ops.create_entity(name="A", entity_type="NPC", entity_id="pytest:npc:a")
        ops.create_entity(name="B", entity_type="NPC", entity_id="pytest:npc:b")
        ops.create_relationship("pytest:npc:a", "pytest:npc:b", RelationshipType.KNOWS)

        row = graph.run(
            "MATCH (:Entity {id:'pytest:npc:a'})-[r:KNOWS]->() RETURN r.layer AS layer"
        ).single()
        assert row["layer"] == "social"

    def test_structural_edge_gets_no_layer(self, graph):
        """BELONGS_TO is plane-linking, not a surface. It must stay unlayered."""
        ops = CampaignGraphOps()
        ops.create_entity(name="A", entity_type="NPC", entity_id="pytest:npc:c")
        ops.create_entity(name="C", entity_type="CAMPAIGN", entity_id="pytest:camp:x")
        ops.create_relationship(
            "pytest:npc:c", "pytest:camp:x", RelationshipType.BELONGS_TO
        )

        row = graph.run(
            "MATCH (:Entity {id:'pytest:npc:c'})-[r:BELONGS_TO]->() "
            "RETURN r.layer AS layer"
        ).single()
        assert row["layer"] is None

    def test_unknown_relationship_type_is_rejected(self, graph):
        """The type is interpolated into Cypher, so it must be validated first."""
        ops = CampaignGraphOps()
        ops.create_entity(name="A", entity_type="NPC", entity_id="pytest:npc:d")
        ops.create_entity(name="B", entity_type="NPC", entity_id="pytest:npc:e")

        with pytest.raises(ValueError):
            ops.create_relationship(
                "pytest:npc:d", "pytest:npc:e", "NOT_A_TYPE; DROP DATABASE neo4j"
            )
