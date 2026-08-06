"""Adversarial coverage for the table perspective's whole payload surface.

Named-field assertions (e.g. "entity.get('plane') == 'campaign'") only catch a
leak in the field they check. This test instead seeds every leak vector the
resolver has had -- an unrevealed node, a future-revealed node, a canon node, a
copy-on-write node whose canon_id is itself a spoilery canon id, and another
campaign's node -- wires them all onto one revealed anchor entity, and then
scans the *serialized* table-perspective payload (entities + edges +
intersections together) for any of those ids as a raw string. Scanning the
whole blob rather than named keys means it keeps catching the leak even if a
new field starts carrying one of these ids tomorrow.
"""

import json

import pytest

from backend.graph.resolver import PlaneResolver

pytestmark = pytest.mark.neo4j

CAMPAIGN = "pytest:campaign:adversary"
OTHER = "pytest:campaign:adversary-other"

FORBIDDEN = {
    "pytest:npc:unrevealed-secret",
    "pytest:npc:future-secret",
    "pytest:loc:canon-spoiler",
    "pytest:npc:other-campaigns-npc",
    "cos:location:spoilery-canon-id",
}


@pytest.fixture
def seeded(graph):
    graph.run(
        """
        CREATE (c:Entity {id:$campaign, name:'Table Adversary',
                          entity_type:'CAMPAIGN', plane:'campaign'})
        CREATE (other:Entity {id:$other, name:'Other Table',
                              entity_type:'CAMPAIGN', plane:'campaign'})

        // Revealed anchor, so it can legitimately carry an edge to every vector.
        CREATE (anchor:Entity {id:'pytest:npc:anchor', name:'Anchor',
                               entity_type:'NPC', plane:'campaign',
                               revealed_in_session:1})
        CREATE (anchor)-[:BELONGS_TO]->(c)

        // Never revealed
        CREATE (unrevealed:Entity {id:'pytest:npc:unrevealed-secret',
                                   name:'Unrevealed Secret', entity_type:'NPC',
                                   plane:'campaign'})
        CREATE (unrevealed)-[:BELONGS_TO]->(c)
        CREATE (anchor)-[:KNOWS {layer:'social', revealed_in_session:1}]->(unrevealed)

        // Revealed, but not until session 100
        CREATE (future:Entity {id:'pytest:npc:future-secret', name:'Future Secret',
                               entity_type:'NPC', plane:'campaign',
                               revealed_in_session:100})
        CREATE (future)-[:BELONGS_TO]->(c)
        CREATE (anchor)-[:KNOWS {layer:'social', revealed_in_session:1}]->(future)

        // Canon, never instantiated by this table
        CREATE (canon:Entity {id:'pytest:loc:canon-spoiler', name:'Canon Spoiler',
                              entity_type:'LOCATION', plane:'canon'})
        CREATE (anchor)-[:LOCATED_IN {layer:'spatial', revealed_in_session:1}]->(canon)

        // Another campaign's node
        CREATE (theirs:Entity {id:'pytest:npc:other-campaigns-npc', name:'Theirs',
                               entity_type:'NPC', plane:'campaign',
                               revealed_in_session:1})
        CREATE (theirs)-[:BELONGS_TO]->(other)
        CREATE (anchor)-[:ALLIED_WITH {layer:'social', revealed_in_session:1}]->(theirs)

        // Copy-on-write node whose canon_id is itself a spoilery canon id.
        // Wired as BOTH source and target of a revealed edge, so both the
        // entity property (Critical 2, entities) and source_canon_id (Critical
        // 2, edges) are exercised.
        CREATE (cow:Entity {id:'pytest:npc:cow', name:'Copy On Write',
                            entity_type:'NPC', plane:'campaign',
                            canon_id:'cos:location:spoilery-canon-id',
                            revealed_in_session:1})
        CREATE (cow)-[:BELONGS_TO]->(c)
        CREATE (anchor)-[:KNOWS {layer:'social', revealed_in_session:1}]->(cow)
        CREATE (cow)-[:KNOWS {layer:'social', revealed_in_session:1}]->(anchor)
        """,
        {"campaign": CAMPAIGN, "other": OTHER},
    ).consume()
    yield graph


class TestTablePerspectiveNeverLeaksForbiddenStrings:
    def test_no_forbidden_id_appears_anywhere_in_the_table_payload(self, seeded):
        resolver = PlaneResolver(CAMPAIGN)
        entities = resolver.entities("table", as_of_session=1)
        edges = resolver.edges("table", as_of_session=1)
        intersections = resolver.intersections("table", as_of_session=1)

        assert entities, "fixture produced no table-view entities"
        assert edges, "fixture produced no table-view edges"

        blob = json.dumps(entities + edges + intersections)
        for forbidden in FORBIDDEN:
            assert forbidden not in blob, f"leaked: {forbidden}"
