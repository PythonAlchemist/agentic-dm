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
        assert result, "fixture produced no table-view entities"
        assert all(e.get("plane") == "campaign" for e in result)

    def test_table_view_entities_never_expose_canon_id(self, graph):
        """A copy-on-write node's canon_id points at a canon id -- and a leaked id
        is leaked content. The table view must strip it, even though truth needs
        it (Critical 2)."""
        seed(graph)
        result = PlaneResolver(CAMPAIGN).entities("table", as_of_session=10)
        ireena = next(e for e in result if e.get("id") == "pytest:npc:ireena@a")
        assert "canon_id" not in ireena
        assert ireena.get("plane") == "campaign"

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

    def test_table_view_edges_never_expose_canon_endpoint(self, graph):
        """The exact leak: a campaign NPC's LOCATED_IN edge to an un-instantiated
        canon location must not surface that location's id in the table view.
        Node ids are human-readable (e.g. cos:location:castle-ravenloft:k37), so a
        leaked id is leaked spoiler content -- constraining only the edge's source
        plane, as the table branch used to, isn't enough.
        """
        graph.run(
            """
            CREATE (c:Entity {id:$campaign, name:'Table A', entity_type:'CAMPAIGN',
                              plane:'campaign'})
            CREATE (n:Entity {id:'pytest:npc:hireling', name:'Hireling',
                              entity_type:'NPC', plane:'campaign'})
            CREATE (n)-[:BELONGS_TO]->(c)
            CREATE (loc:Entity {id:'pytest:loc:secret-lair', name:'Secret Lair',
                                entity_type:'LOCATION', plane:'canon'})
            CREATE (n)-[:LOCATED_IN {layer:'spatial', revealed_in_session:1}]->(loc)
            """,
            {"campaign": CAMPAIGN},
        ).consume()
        result = PlaneResolver(CAMPAIGN).edges("table", as_of_session=10)
        touched_ids = {e["source_id"] for e in result} | {e["target_id"] for e in result}
        assert "pytest:loc:secret-lair" not in touched_ids

    def test_table_view_intersections_never_expose_canon_ids(self, graph):
        """intersections() derives from edges(), so the same canon leak propagates
        unless both endpoints are constrained there too."""
        graph.run(
            """
            CREATE (c:Entity {id:$campaign, name:'Table A', entity_type:'CAMPAIGN',
                              plane:'campaign'})
            CREATE (n:Entity {id:'pytest:npc:hireling2', name:'Hireling',
                              entity_type:'NPC', plane:'campaign'})
            CREATE (other:Entity {id:'pytest:npc:ally', name:'Ally',
                                  entity_type:'NPC', plane:'campaign'})
            CREATE (loc:Entity {id:'pytest:loc:secret-lair2', name:'Secret Lair',
                                entity_type:'LOCATION', plane:'canon'})
            CREATE (n)-[:BELONGS_TO]->(c)
            CREATE (other)-[:BELONGS_TO]->(c)
            CREATE (n)-[:LOCATED_IN {layer:'spatial', revealed_in_session:1}]->(loc)
            CREATE (other)-[:OBJECTIVE_AT {layer:'narrative', revealed_in_session:1}]->(loc)
            """,
            {"campaign": CAMPAIGN},
        ).consume()
        result = PlaneResolver(CAMPAIGN).intersections("table", as_of_session=10)
        ids = {row["id"] for row in result}
        assert "pytest:loc:secret-lair2" not in ids

    def test_table_view_edges_never_expose_unrevealed_endpoint(self, graph):
        """The edge itself can be revealed while an endpoint never is. Endpoint
        reveal state must be checked independently of the edge's (Critical 1)."""
        graph.run(
            """
            CREATE (c:Entity {id:$campaign, name:'Table A', entity_type:'CAMPAIGN',
                              plane:'campaign'})
            CREATE (a:Entity {id:'pytest:npc:ireena4', name:'Ireena',
                              entity_type:'NPC', plane:'campaign',
                              revealed_in_session:1})
            CREATE (secret:Entity {id:'pytest:npc:strahds-secret-consort',
                                   name:'Strahds Secret Consort', entity_type:'NPC',
                                   plane:'campaign'})
            CREATE (a)-[:BELONGS_TO]->(c)
            CREATE (secret)-[:BELONGS_TO]->(c)
            CREATE (a)-[:KNOWS {layer:'social', revealed_in_session:1}]->(secret)
            """,
            {"campaign": CAMPAIGN},
        ).consume()
        result = PlaneResolver(CAMPAIGN).edges("table", as_of_session=1)
        touched_ids = {e["source_id"] for e in result} | {e["target_id"] for e in result}
        assert "pytest:npc:strahds-secret-consort" not in touched_ids

    def test_table_view_edges_never_expose_source_canon_id(self, graph):
        """A copy-on-write node's canon_id is a canon id -- must not surface via
        an edge's source_canon_id in the table view (Critical 2)."""
        seed(graph)
        graph.run(
            """
            MATCH (a:Entity {id:'pytest:npc:ireena@a'})
            MATCH (b:Entity {id:'pytest:npc:bob'})
            CREATE (a)-[:KNOWS {layer:'social', revealed_in_session:5}]->(b)
            """
        ).consume()
        result = PlaneResolver(CAMPAIGN).edges("table", as_of_session=10)
        assert result, "fixture produced no table-view edges"
        for e in result:
            assert e["source_canon_id"] is None

    def test_truth_view_intersections_finds_layer_crossing_nodes(self, graph):
        """Nothing else exercises intersections() at all -- cover the truth path,
        where the canon-endpoint constraint deliberately does NOT apply."""
        graph.run(
            """
            CREATE (a:Entity {id:'pytest:npc:strahd2', plane:'canon', name:'Strahd'})
            CREATE (b:Entity {id:'pytest:npc:ireena3', plane:'canon', name:'Ireena'})
            CREATE (l:Entity {id:'pytest:loc:barovia2', plane:'canon', name:'Barovia'})
            CREATE (a)-[:SEEKS {layer:'narrative', motive:'believes her Tatyana'}]->(b)
            CREATE (b)-[:LOCATED_IN {layer:'spatial'}]->(l)
            """
        ).consume()
        result = PlaneResolver(CAMPAIGN).intersections("truth")
        row = next(r for r in result if r["id"] == "pytest:npc:ireena3")
        assert row["layers"] == ["narrative", "spatial"]


class TestCampaignScoping:
    def test_truth_edges_exclude_other_campaigns(self, graph):
        graph.run(
            """
            CREATE (a:Entity {id:'pytest:campaign:a', plane:'campaign',
                              entity_type:'CAMPAIGN'})
            CREATE (b:Entity {id:'pytest:campaign:b', plane:'campaign',
                              entity_type:'CAMPAIGN'})
            CREATE (mine:Entity {id:'pytest:npc:mine', plane:'campaign'})
            CREATE (theirs:Entity {id:'pytest:npc:theirs', plane:'campaign'})
            CREATE (mine)-[:BELONGS_TO]->(a)
            CREATE (theirs)-[:BELONGS_TO]->(b)
            CREATE (mine)-[:KNOWS {layer:'social'}]->(mine)
            CREATE (theirs)-[:KNOWS {layer:'social'}]->(theirs)
            """
        ).consume()

        ids = {
            e["source_id"]
            for e in PlaneResolver("pytest:campaign:a").edges("truth", layers=["social"])
        }
        assert "pytest:npc:mine" in ids
        assert "pytest:npc:theirs" not in ids

    def test_truth_edges_exclude_other_campaigns_on_the_target(self, graph):
        """Task 7 scoped the source; the target was left unconstrained, so a
        campaign-plane source's edge to ANOTHER campaign's node leaked that
        node's id in the truth view (Critical 3)."""
        graph.run(
            """
            CREATE (a:Entity {id:'pytest:campaign:a', plane:'campaign',
                              entity_type:'CAMPAIGN'})
            CREATE (b:Entity {id:'pytest:campaign:b', plane:'campaign',
                              entity_type:'CAMPAIGN'})
            CREATE (mine:Entity {id:'pytest:npc:mine3', plane:'campaign'})
            CREATE (theirs:Entity {id:'pytest:npc:theirs3', plane:'campaign'})
            CREATE (mine)-[:BELONGS_TO]->(a)
            CREATE (theirs)-[:BELONGS_TO]->(b)
            CREATE (mine)-[:ALLIED_WITH {layer:'social'}]->(theirs)
            """
        ).consume()

        result = PlaneResolver("pytest:campaign:a").edges("truth", layers=["social"])
        target_ids = {e["target_id"] for e in result}
        assert "pytest:npc:theirs3" not in target_ids

    def test_table_edges_exclude_other_campaigns(self, graph):
        graph.run(
            """
            CREATE (a:Entity {id:'pytest:campaign:a', plane:'campaign',
                              entity_type:'CAMPAIGN'})
            CREATE (b:Entity {id:'pytest:campaign:b', plane:'campaign',
                              entity_type:'CAMPAIGN'})
            CREATE (mine:Entity {id:'pytest:npc:mine', plane:'campaign',
                                 revealed_in_session:1})
            CREATE (theirs:Entity {id:'pytest:npc:theirs', plane:'campaign',
                                   revealed_in_session:1})
            CREATE (mine)-[:BELONGS_TO]->(a)
            CREATE (theirs)-[:BELONGS_TO]->(b)
            CREATE (mine)-[:KNOWS {layer:'social', revealed_in_session:1}]->(mine)
            CREATE (theirs)-[:KNOWS {layer:'social', revealed_in_session:1}]->(theirs)
            """
        ).consume()

        ids = {
            e["source_id"]
            for e in PlaneResolver("pytest:campaign:a").edges("table", as_of_session=9)
        }
        assert ids == {"pytest:npc:mine"}
