"""The seed under the resolver: the ontology exercised on real material."""

from pathlib import Path

import pytest
import yaml

from backend.canon.seed_loader import SEED_DIR, load_seed
from backend.graph.resolver import PlaneResolver

pytestmark = pytest.mark.neo4j

CAMPAIGN = "pytest:campaign:barovia"

SEED_PATH = SEED_DIR / "village-of-barovia.yaml"


def _declared_node_ids(path: Path) -> list[str]:
    """The ids this seed declares, so teardown can delete exactly those.

    Bulk-deleting by namespace prefix (WHERE e.id STARTS WITH 'cos:') would
    delete real canon if this ever ran against a populated database -- the
    same mistake the pytest: prefix exists to avoid for campaign nodes. Canon
    has no such prefix, so the seed's own declared ids are the only safe scope.
    """
    data = yaml.safe_load(path.read_text())
    return [node["id"] for node in data["nodes"]]


@pytest.fixture
def seeded(graph):
    # Captured before load_seed runs (and deleted in `finally` below) so that a
    # load_seed failure partway through -- which can leave partially-written
    # canon nodes -- still gets cleaned up rather than persisting and polluting
    # every subsequent truth view, since canon is global.
    node_ids = _declared_node_ids(SEED_PATH)
    try:
        _seed_and_build_fixture(graph)
        yield graph
    finally:
        graph.run(
            "MATCH (e:Entity) WHERE e.id IN $ids DETACH DELETE e", {"ids": node_ids}
        ).consume()


def _seed_and_build_fixture(graph):
    load_seed(SEED_PATH, graph)
    graph.run(
        """
        MATCH (ireena_canon:Entity {id:'cos:npc:ireena-kolyana'})
        CREATE (c:Entity {id:$id, name:'Table A', entity_type:'CAMPAIGN',
                          plane:'campaign'})
        // A revealed campaign NPC overriding canon Ireena
        CREATE (ireena:Entity {id:'pytest:npc:ireena@a', entity_type:'NPC',
                               plane:'campaign', name:'Ireena Kolyana',
                               canon_id:'cos:npc:ireena-kolyana', status:'travelling',
                               revealed_in_session:2})
        CREATE (ireena)-[:BELONGS_TO]->(c)
        CREATE (ireena)-[:INSTANCE_OF]->(ireena_canon)
        // A table-invented ally, revealed later
        CREATE (ally:Entity {id:'pytest:npc:hireling', entity_type:'NPC',
                             plane:'campaign', name:'Sasha the Hireling',
                             revealed_in_session:6})
        CREATE (ally)-[:BELONGS_TO]->(c)
        // A layered campaign->campaign edge, revealed early
        CREATE (ireena)-[:KNOWS {layer:'social', revealed_in_session:2}]->(ally)
        // A second early-revealed campaign NPC, so a table edge exists as of
        // session 2 -- both endpoints and the edge itself revealed_in_session:2.
        // Without this, the earliest visible campaign->campaign edge is the one
        // above, which only clears its endpoint check at session 6 (ally's own
        // reveal), leaving the table view genuinely edge-less at sessions 2-5.
        CREATE (scout:Entity {id:'pytest:npc:scout', entity_type:'NPC',
                              plane:'campaign', name:'Scout', revealed_in_session:2})
        CREATE (scout)-[:BELONGS_TO]->(c)
        CREATE (ireena)-[:KNOWS {layer:'social', revealed_in_session:2}]->(scout)
        // A campaign entity that has NEVER been revealed
        CREATE (secret:Entity {id:'pytest:npc:unrevealed', entity_type:'NPC',
                               plane:'campaign', name:'Unrevealed NPC'})
        CREATE (secret)-[:BELONGS_TO]->(c)
        // A campaign-plane IDENTITY_OF edge, revealed to the table in the future.
        // Both endpoints are already-revealed campaign nodes, so only the reveal
        // filter (not the plane filter) can exclude it -- that is what makes
        // test_table_view_hides_the_unrevealed_identity actually test the reveal
        // filter rather than the (already separately-tested) plane filter.
        CREATE (ireena)-[:IDENTITY_OF {layer:'narrative', revealed_in_session:100}]->(ally)
        """,
        {"id": CAMPAIGN},
    ).consume()


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
        """The motive property must survive the resolver, not just the edge.

        Pinned exactly rather than by substring: a source-material review found
        that chapter 3 states the Tatyana identity outright in its opening
        paragraph, so an earlier attempt to trim this motive to "the bites" was
        wrong and was reverted. An exact assertion makes the next such edit
        fail loudly instead of drifting.
        """
        edges = PlaneResolver(CAMPAIGN).edges("truth", layers=["narrative"])
        seeks = next(
            e for e in edges
            if e["rel_type"] == "SEEKS"
            and e["target_id"] == "cos:npc:ireena-kolyana"
        )
        assert seeks["props"]["motive"] == (
            "Believes she is Tatyana reborn and means to make her his bride."
        )

    def test_church_is_an_intersection_of_spatial_and_narrative(self, seeded):
        """Which places matter to the plot, computed rather than authored."""
        hits = PlaneResolver(CAMPAIGN).intersections("truth")
        by_id = {h["id"]: h["layers"] for h in hits}
        assert "spatial" in by_id["cos:location:church-of-barovia"]
        assert "narrative" in by_id["cos:location:church-of-barovia"]

    def test_table_view_hides_the_unrevealed_identity(self, seeded):
        """Ireena is Tatyana. The table must not learn that from the graph.

        The fixture's IDENTITY_OF edge is campaign-plane with both endpoints
        already revealed by session 99 -- only the reveal filter (revealed_in_session
        100, in the future) can exclude it, so this genuinely exercises that filter
        rather than passing vacuously because canon never reaches the table view.
        """
        edges = PlaneResolver(CAMPAIGN).edges("table", as_of_session=99)
        assert edges, "fixture produced no table-view edges"
        assert all(e["rel_type"] != "IDENTITY_OF" for e in edges)

    def test_table_view_returns_nothing_from_canon(self, seeded):
        entities = PlaneResolver(CAMPAIGN).entities("table", as_of_session=99)
        assert entities, "fixture produced no table-view entities"
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

        entities = resolver.entities("table", as_of_session=session_n)
        edges = resolver.edges("table", as_of_session=session_n)
        if session_n >= 2:
            assert entities, f"fixture produced no table-view entities at session {session_n}"
            assert edges, f"fixture produced no table-view edges at session {session_n}"

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

        Shadowing keys on the campaign source's canon_id, so a copy-on-write
        campaign node's edge replaces the canon fan-out it descends from.
        """
        seeded.run(
            """
            MATCH (canon:Entity {id:'cos:item:tome-of-strahd'})
            MATCH (church:Entity {id:'cos:location:church-of-barovia'})
            MATCH (c:Entity {id:$campaign})
            CREATE (camp:Entity {id:'pytest:item:tome@a', plane:'campaign',
                                 entity_type:'ITEM',
                                 canon_id:'cos:item:tome-of-strahd'})
            CREATE (camp)-[:INSTANCE_OF]->(canon)
            CREATE (camp)-[:BELONGS_TO]->(c)
            CREATE (camp)-[:RESOLVES_TO {layer:'narrative'}]->(church)
            """,
            {"campaign": CAMPAIGN},
        ).consume()

        edges = PlaneResolver(CAMPAIGN).edges("truth", layers=["narrative"])
        # Scoped to the TOME's fan-out, which is what shadowing is about.
        # *Corrected 2026-08-17*: this counted every narrative `RESOLVES_TO` in
        # the database and asserted 1, which held only while the graph contained
        # nothing but this fixture. With the whole book loaded, chapter 4
        # contributes `glyph of warding -RESOLVES_TO-> Strahd`, and the test
        # failed on the book being present rather than on shadowing being wrong.
        tome = {"pytest:item:tome@a", "cos:item:tome-of-strahd"}
        resolves = [
            e for e in edges
            if e["rel_type"] == "RESOLVES_TO" and e["source_id"] in tome
        ]

        assert len(resolves) == 1, [e["target_id"] for e in resolves]
        assert resolves[0]["target_id"] == "cos:location:church-of-barovia"
        assert resolves[0]["source_id"] == "pytest:item:tome@a"
