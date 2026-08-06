"""The seed is hand-authored canon and doubles as stage 2's golden set, so its
integrity is worth asserting rather than assuming."""

import pytest
import yaml

from backend.canon.seed_loader import SEED_DIR, load_seed, validate_seed

BAROVIA = SEED_DIR / "village-of-barovia.yaml"


@pytest.fixture
def seed_data():
    return yaml.safe_load(BAROVIA.read_text())


class TestSeedIntegrity:
    def test_seed_file_exists(self):
        assert BAROVIA.exists()

    def test_seed_validates(self, seed_data):
        assert validate_seed(seed_data) == []

    def test_every_node_has_required_fields(self, seed_data):
        for node in seed_data["nodes"]:
            assert node["id"].startswith("cos:"), node
            for field in ("name", "entity_type"):
                assert field in node, node

    def test_edges_reference_declared_nodes(self, seed_data):
        ids = {n["id"] for n in seed_data["nodes"]}
        for e in seed_data["edges"]:
            assert e["source"] in ids, f"dangling source: {e}"
            assert e["target"] in ids, f"dangling target: {e}"

    def test_exercises_every_narrative_type(self, seed_data):
        """The seed's job is to put the new vocabulary under real material."""
        used = {e["type"] for e in seed_data["edges"]}
        for required in ("SEEKS", "IDENTITY_OF", "GAVE_QUEST", "OBJECTIVE_AT",
                         "RESOLVES_TO"):
            assert required in used, f"seed never exercises {required}"

    def test_identity_edge_is_unrevealed(self, seed_data):
        """Ireena being Tatyana is the reveal the design exists to protect."""
        identity = [e for e in seed_data["edges"] if e["type"] == "IDENTITY_OF"]
        assert identity, "no IDENTITY_OF edge in seed"
        assert all(e.get("revealed_in_session") is None for e in identity)


class TestValidation:
    def test_unknown_relationship_type_is_reported(self):
        problems = validate_seed(
            {
                "nodes": [{"id": "cos:npc:a", "name": "A", "entity_type": "NPC"}],
                "edges": [{"source": "cos:npc:a", "target": "cos:npc:a",
                           "type": "NOT_A_REAL_TYPE"}],
            }
        )
        assert any("NOT_A_REAL_TYPE" in p for p in problems)

    def test_dangling_edge_is_reported(self):
        problems = validate_seed(
            {
                "nodes": [{"id": "cos:npc:a", "name": "A", "entity_type": "NPC"}],
                "edges": [{"source": "cos:npc:a", "target": "cos:npc:missing",
                           "type": "KNOWS"}],
            }
        )
        assert any("missing" in p for p in problems)

    def test_unknown_entity_type_is_reported(self):
        """entity_type: LOCATON (typo) must not load silently -- the seed is a
        grading answer key, and a bad entity_type there is grade-inverting."""
        problems = validate_seed(
            {
                "nodes": [{"id": "cos:loc:a", "name": "A", "entity_type": "LOCATON"}],
                "edges": [],
            }
        )
        assert any("LOCATON" in p for p in problems)

    def test_duplicate_node_id_is_reported(self):
        """A duplicated id silently MERGEs two authored nodes into one."""
        problems = validate_seed(
            {
                "nodes": [
                    {"id": "cos:npc:a", "name": "A", "entity_type": "NPC"},
                    {"id": "cos:npc:a", "name": "A Duplicate", "entity_type": "NPC"},
                ],
                "edges": [],
            }
        )
        assert any("cos:npc:a" in p for p in problems)


@pytest.mark.neo4j
class TestLoad:
    def test_load_creates_nodes_and_edges(self, graph, tmp_path):
        doc = {
            "nodes": [
                {"id": "pytest:npc:a", "name": "A", "entity_type": "NPC"},
                {"id": "pytest:npc:b", "name": "B", "entity_type": "NPC"},
            ],
            "edges": [{"source": "pytest:npc:a", "target": "pytest:npc:b",
                       "type": "KNOWS"}],
        }
        path = tmp_path / "mini.yaml"
        path.write_text(yaml.safe_dump(doc))

        counts = load_seed(path, graph)

        assert counts == {"nodes": 2, "edges": 1}
        stored = graph.run(
            "MATCH (a:Entity {id:'pytest:npc:a'})-[r:KNOWS]->(b) "
            "RETURN r.layer AS layer, a.plane AS plane"
        ).single()
        assert stored["layer"] == "social"
        assert stored["plane"] == "canon"

    def test_load_is_idempotent(self, graph, tmp_path):
        doc = {"nodes": [{"id": "pytest:npc:a", "name": "A", "entity_type": "NPC"}],
               "edges": []}
        path = tmp_path / "mini.yaml"
        path.write_text(yaml.safe_dump(doc))

        load_seed(path, graph)
        load_seed(path, graph)

        n = graph.run("MATCH (e:Entity {id:'pytest:npc:a'}) RETURN count(e) AS n").single()
        assert n["n"] == 1

    def test_load_edge_is_idempotent(self, graph, tmp_path):
        """Loading a doc with one edge twice must not duplicate the relationship.

        Node-side idempotency alone doesn't prove this: a loader that MERGEs nodes
        but CREATEs relationships would still pass test_load_is_idempotent above.
        """
        doc = {
            "nodes": [
                {"id": "pytest:npc:a", "name": "A", "entity_type": "NPC"},
                {"id": "pytest:npc:b", "name": "B", "entity_type": "NPC"},
            ],
            "edges": [{"source": "pytest:npc:a", "target": "pytest:npc:b", "type": "KNOWS"}],
        }
        path = tmp_path / "mini.yaml"
        path.write_text(yaml.safe_dump(doc))

        load_seed(path, graph)
        load_seed(path, graph)

        n = graph.run(
            "MATCH (:Entity {id:'pytest:npc:a'})-[r:KNOWS]->(:Entity {id:'pytest:npc:b'}) "
            "RETURN count(r) AS n"
        ).single()
        assert n["n"] == 1

    def test_structural_edge_gets_no_layer(self, graph, tmp_path):
        """A relationship type with LAYER_MAP value None (e.g. BELONGS_TO) must not
        get a layer property written onto it."""
        doc = {
            "nodes": [
                {"id": "pytest:pc:a", "name": "A", "entity_type": "PC"},
                {"id": "pytest:campaign:b", "name": "B", "entity_type": "CAMPAIGN"},
            ],
            "edges": [{"source": "pytest:pc:a", "target": "pytest:campaign:b",
                       "type": "BELONGS_TO"}],
        }
        path = tmp_path / "mini.yaml"
        path.write_text(yaml.safe_dump(doc))

        load_seed(path, graph)

        stored = graph.run(
            "MATCH (:Entity {id:'pytest:pc:a'})-[r:BELONGS_TO]->(:Entity {id:'pytest:campaign:b'}) "
            "RETURN r.layer AS layer"
        ).single()
        assert stored["layer"] is None
