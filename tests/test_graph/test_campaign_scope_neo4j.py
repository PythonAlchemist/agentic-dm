"""Campaign scoping against a graph that holds canon nodes with no `entity_type`.

`CAMPAIGN_SCOPED_TYPES` splits the graph in two: a type on that list belongs to
one table and is only shown to that table, and anything else -- rules, spells,
the SRD -- is shared with every campaign. The share half is written as
`NOT e.entity_type IN $scoped_types`.

That predicate is NULL, not true, when `e.entity_type` is NULL, and Cypher
drops a row whose WHERE is NULL. Canon nodes have carried their type as a
LABEL and no `entity_type` property since entities became globally unique, so
every one of them silently vanished from these three APIs -- not filtered,
not errored, absent. Seven items and monsters measured missing from the live
graph, `Tome of Strahd` and the `Sunsword` among them.

Live Neo4j on purpose: this is Cypher's three-valued logic, and a mocked
session returns whatever the mock was told to. Only a real database can fail
this test.
"""

import pytest

from backend.graph.operations import CampaignGraphOps

pytestmark = pytest.mark.neo4j

CAMPAIGN = "pytest:campaign:scope"
CANON_ITEM = "pytest:item:tome-of-strahd"
CANON_LOCATION = "pytest:location:church"
CAMPAIGN_NPC = "pytest:npc:bob"
OTHER_NPC = "pytest:npc:elsewhere"


@pytest.fixture
def seeded(graph):
    """Canon nodes typed by LABEL alone, beside this campaign's own and another's.

    The canon nodes deliberately carry NO `entity_type` property -- that is
    exactly what `canon.writer` writes, and writing one here would seed the bug
    out of existence.
    """
    graph.run(
        """
        CREATE (c:Entity {id:$campaign, name:'Table A', entity_type:'CAMPAIGN',
                          plane:'campaign'})
        CREATE (:Entity:ITEM {id:$item, name:'Tome of Strahd', plane:'canon',
                              description:"Strahd's own memoir"})
        CREATE (:Entity:LOCATION:SITE {id:$location, name:'Church of Barovia',
                                       plane:'canon', description:'A failing church'})
        CREATE (bob:Entity {id:$bob, name:'Bob the Hireling', entity_type:'NPC',
                            plane:'campaign', description:'hired in Vallaki'})
        CREATE (bob)-[:BELONGS_TO]->(c)
        CREATE (:Entity {id:$other, name:'Someone Elses NPC', entity_type:'NPC',
                         plane:'campaign', description:'another table'})
        """,
        {
            "campaign": CAMPAIGN,
            "item": CANON_ITEM,
            "location": CANON_LOCATION,
            "bob": CAMPAIGN_NPC,
            "other": OTHER_NPC,
        },
    ).consume()
    return graph


#: Big enough that a page cannot exclude the fixture. *Raised 2026-08-17*, when
#: the whole book landed: these assertions are about whether campaign scoping
#: ADMITS a canon node, and `ours()` already filters the answer down to this
#: test's own ids. A limit of 100 additionally required the fixture to sort into
#: the first hundred of 626 canon entities, which is a fact about pagination
#: rather than about scoping, and which broke the moment the graph grew.
PAGE = 5000


def ours(rows: list[dict]) -> set[str]:
    """Ids from this test's own fixture, so a populated database cannot flake it."""
    return {r["id"] for r in rows if str(r.get("id", "")).startswith("pytest:")}


class TestCanonSurvivesCampaignScoping:
    def test_list_entities_returns_a_canon_item(self, seeded):
        rows = CampaignGraphOps().list_entities(campaign_id=CAMPAIGN, limit=PAGE)

        assert CANON_ITEM in ours(rows)

    def test_list_entities_returns_a_canon_location(self, seeded):
        """LOCATION is a campaign-scoped type, and this node's type is a label.

        The share half is the only branch that can admit it: it belongs to no
        campaign, so `BELONGS_TO` cannot, and the type test has to survive NULL.
        """
        rows = CampaignGraphOps().list_entities(campaign_id=CAMPAIGN, limit=PAGE)

        assert CANON_LOCATION in ours(rows)

    def test_search_returns_a_canon_item(self, seeded):
        rows = CampaignGraphOps().search("Tome of Strahd", campaign_id=CAMPAIGN)

        assert CANON_ITEM in ours(rows)

    def test_the_full_graph_returns_canon_nodes(self, seeded):
        data = CampaignGraphOps().get_full_graph(campaign_id=CAMPAIGN, limit=PAGE)

        assert CANON_ITEM in ours(data["nodes"])

    def test_this_campaigns_own_entities_still_come_back(self, seeded):
        """The fix must widen the share half, not disable the scoping."""
        rows = CampaignGraphOps().list_entities(campaign_id=CAMPAIGN, limit=PAGE)

        assert CAMPAIGN_NPC in ours(rows)

    def test_another_campaigns_entities_are_still_hidden(self, seeded):
        """The regression this scoping exists to prevent. A node with a scoped
        type and no `BELONGS_TO` to us is somebody else's game."""
        rows = CampaignGraphOps().list_entities(campaign_id=CAMPAIGN, limit=PAGE)

        assert OTHER_NPC not in ours(rows)

    def test_search_still_hides_another_campaigns_entities(self, seeded):
        rows = CampaignGraphOps().search("Someone Elses", campaign_id=CAMPAIGN)

        assert OTHER_NPC not in ours(rows)
