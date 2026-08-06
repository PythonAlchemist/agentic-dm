"""The seed under the resolver: the ontology exercised on real material."""

import pytest

from backend.canon.seed_loader import SEED_DIR, load_seed
from backend.graph.resolver import PlaneResolver

pytestmark = pytest.mark.neo4j

CAMPAIGN = "pytest:campaign:barovia"


@pytest.fixture
def seeded(graph):
    load_seed(SEED_DIR / "village-of-barovia.yaml", graph)
    graph.run(
        "CREATE (c:Entity {id:$id, name:'Table A', entity_type:'CAMPAIGN', "
        "plane:'campaign'})",
        {"id": CAMPAIGN},
    ).consume()
    yield graph
    graph.run("MATCH (e:Entity) WHERE e.id STARTS WITH 'cos:' DETACH DELETE e").consume()


class TestSeedUnderResolver:
    def test_truth_view_returns_canon_npcs(self, seeded):
        names = {
            e["name"] for e in PlaneResolver(CAMPAIGN).entities("truth",
                                                                entity_type="NPC")
        }
        assert "Ireena Kolyana" in names
        assert "Strahd von Zarovich" in names

    def test_narrative_layer_isolates_plot_edges(self, seeded):
        edges = PlaneResolver(CAMPAIGN).edges("truth", layers=["narrative"])
        types = {e["rel_type"] for e in edges}
        assert "SEEKS" in types
        assert "LOCATED_IN" not in types

    def test_seeks_edge_carries_its_motive(self, seeded):
        edges = PlaneResolver(CAMPAIGN).edges("truth", layers=["narrative"])
        seeks = next(
            e for e in edges
            if e["rel_type"] == "SEEKS"
            and e["target_id"] == "cos:npc:ireena-kolyana"
        )
        assert "Tatyana" in seeks["props"]["motive"]

    def test_church_is_an_intersection_of_spatial_and_narrative(self, seeded):
        """Which places matter to the plot, computed rather than authored."""
        hits = PlaneResolver(CAMPAIGN).intersections("truth")
        by_id = {h["id"]: h["layers"] for h in hits}
        assert "spatial" in by_id["cos:location:church-of-barovia"]
        assert "narrative" in by_id["cos:location:church-of-barovia"]

    def test_table_view_hides_the_unrevealed_identity(self, seeded):
        """Ireena is Tatyana. The table must not learn that from the graph."""
        edges = PlaneResolver(CAMPAIGN).edges("table", as_of_session=99)
        assert all(e["rel_type"] != "IDENTITY_OF" for e in edges)

    def test_table_view_returns_nothing_from_canon(self, seeded):
        entities = PlaneResolver(CAMPAIGN).entities("table", as_of_session=99)
        assert all(e.get("plane") == "campaign" for e in entities)

    @pytest.mark.parametrize("session_n", [0, 1, 2, 5, 12, 99])
    def test_table_view_never_leaks_across_any_session(self, seeded, session_n):
        """The invariant the whole design rests on, checked across the range.

        For any session N: the table view returns nothing from the canon plane and
        nothing whose reveal is later than N. Parametrized rather than
        hypothesis-driven so it needs no new dependency, but the intent is a
        property: this must hold for every N, not one convenient value.
        """
        resolver = PlaneResolver(CAMPAIGN)

        for entity in resolver.entities("table", as_of_session=session_n):
            assert entity.get("plane") == "campaign"
            revealed = entity.get("revealed_in_session")
            assert revealed is not None and revealed <= session_n

        for e in resolver.edges("table", as_of_session=session_n):
            assert e["plane"] == "campaign"
            revealed = e["props"].get("revealed_in_session")
            assert revealed is not None and revealed <= session_n

    def test_campaign_draw_shadows_the_tarokka_fan_out(self, seeded):
        """Canon offers three sites for the Tome; this table drew the church.

        shadow_edges() keys on (source_id, rel_type). A copy-on-write campaign
        node has its own id (pytest:item:tome@a), not the canon node's id
        (cos:item:tome-of-strahd), so a RESOLVES_TO edge originating from the
        *campaign* copy never matches the canon edges' source_id and does not
        shadow them -- the fan-out survives untouched in the truth view. See
        the finding in task-5-report.md for what key would actually collapse it.
        """
        seeded.run(
            """
            MATCH (canon:Entity {id:'cos:item:tome-of-strahd'})
            MATCH (church:Entity {id:'cos:location:church-of-barovia'})
            MATCH (table:Entity {id:$campaign})
            CREATE (camp:Entity {id:'pytest:item:tome@a', plane:'campaign',
                                 entity_type:'ITEM', canon_id:'cos:item:tome-of-strahd'})
            CREATE (camp)-[:INSTANCE_OF]->(canon)
            CREATE (camp)-[:BELONGS_TO]->(table)
            CREATE (camp)-[:RESOLVES_TO {layer:'narrative'}]->(church)
            """,
            {"campaign": CAMPAIGN},
        ).consume()

        edges = PlaneResolver(CAMPAIGN).edges("truth", layers=["narrative"])
        resolves = [e for e in edges if e["rel_type"] == "RESOLVES_TO"]
        targets = {e["target_id"] for e in resolves}

        # The campaign draw is present ...
        assert ("pytest:item:tome@a", "cos:location:church-of-barovia") in {
            (e["source_id"], e["target_id"]) for e in resolves
        }
        # ... but because shadow_edges keys on (source_id, rel_type) and the
        # campaign edge's source is the campaign node's own id rather than the
        # canon id, all three canon candidates survive alongside it: shadowing
        # does not cross the plane boundary as currently keyed.
        assert targets == {
            "cos:location:church-of-barovia",
            "cos:location:burgomasters-mansion",
            "cos:location:blood-on-the-vine",
        }
        assert len(resolves) == 4
