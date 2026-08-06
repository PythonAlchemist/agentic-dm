"""Cypher paths for two-plane resolution. Requires a running Neo4j."""

import pytest

from backend.graph.resolver import PlaneResolver

pytestmark = pytest.mark.neo4j

CAMPAIGN = "pytest:campaign:a"
OTHER = "pytest:campaign:b"


def seed(session):
    """Canon Ireena, a campaign override marking her dead, and a table-invented NPC."""
    session.run(
        """
        CREATE (c:Entity {id:$campaign, name:'Table A', entity_type:'CAMPAIGN',
                          plane:'campaign'})
        CREATE (canon:Entity {id:'pytest:npc:ireena', name:'Ireena Kolyana',
                              entity_type:'NPC', plane:'canon', source_book:'cos',
                              description:"burgomaster's sister", status:'alive'})
        CREATE (camp:Entity {id:'pytest:npc:ireena@a', entity_type:'NPC',
                             plane:'campaign', status:'dead',
                             canon_id:'pytest:npc:ireena', revealed_in_session:3})
        CREATE (camp)-[:INSTANCE_OF]->(canon)
        CREATE (camp)-[:BELONGS_TO]->(c)
        CREATE (invented:Entity {id:'pytest:npc:bob', name:'Bob the Hireling',
                                 entity_type:'NPC', plane:'campaign',
                                 revealed_in_session:5})
        CREATE (invented)-[:BELONGS_TO]->(c)
        """,
        {"campaign": CAMPAIGN},
    ).consume()


class TestEntityResolution:
    def test_truth_view_merges_campaign_over_canon(self, graph):
        seed(graph)
        result = PlaneResolver(CAMPAIGN).entities("truth", entity_type="NPC")
        ireena = next(e for e in result if e.get("canon_id") == "pytest:npc:ireena"
                      or e.get("id") == "pytest:npc:ireena")
        assert ireena["status"] == "dead"
        assert ireena["description"] == "burgomaster's sister"

    def test_truth_view_includes_table_invented_entities(self, graph):
        """A canon-rooted query alone silently drops everything a table made up."""
        seed(graph)
        names = {
            e.get("name") for e in PlaneResolver(CAMPAIGN).entities("truth",
                                                                    entity_type="NPC")
        }
        assert "Bob the Hireling" in names

    def test_another_campaign_sees_unmodified_canon(self, graph):
        seed(graph)
        result = PlaneResolver(OTHER).entities("truth", entity_type="NPC")
        ireena = next(e for e in result if e.get("id") == "pytest:npc:ireena")
        assert ireena["status"] == "alive"

    def test_table_view_never_returns_canon_plane(self, graph):
        seed(graph)
        result = PlaneResolver(CAMPAIGN).entities("table", as_of_session=10)
        assert all(e.get("plane") == "campaign" for e in result)

    def test_table_view_respects_as_of_session(self, graph):
        seed(graph)
        result = PlaneResolver(CAMPAIGN).entities("table", as_of_session=4)
        names = {e.get("name") for e in result}
        assert "Bob the Hireling" not in names  # revealed in session 5

    def test_as_of_session_with_truth_is_an_error(self):
        with pytest.raises(ValueError):
            PlaneResolver(CAMPAIGN).entities("truth", as_of_session=3)


class TestEdgeResolution:
    def test_layer_filter_narrows_traversal(self, graph):
        graph.run(
            """
            CREATE (a:Entity {id:'pytest:npc:strahd', plane:'canon', name:'Strahd'})
            CREATE (b:Entity {id:'pytest:npc:ireena2', plane:'canon', name:'Ireena'})
            CREATE (l:Entity {id:'pytest:loc:barovia', plane:'canon', name:'Barovia'})
            CREATE (a)-[:SEEKS {layer:'narrative', motive:'believes her Tatyana'}]->(b)
            CREATE (b)-[:LOCATED_IN {layer:'spatial'}]->(l)
            """
        ).consume()
        social_only = PlaneResolver(CAMPAIGN).edges("truth", layers=["narrative"])
        assert all(e["layer"] == "narrative" for e in social_only)
        assert any(e["rel_type"] == "SEEKS" for e in social_only)
