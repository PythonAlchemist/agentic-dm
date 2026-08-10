"""The seed is hand-authored canon and doubles as stage 2's golden set, so its
integrity is worth asserting rather than assuming."""

import pytest
import yaml

from backend.canon.seed_loader import (
    SEED_DIR,
    extractable_subset,
    load_seed,
    validate_seed,
)

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


class TestExtractionProvenance:
    """The seed is a golden set, so it must distinguish what chapter 3 states from
    what it merely assumes. Grading a chapter-3 run against the whole file penalises
    a correct extractor and rewards one that invents facts it never saw."""

    def test_markers_are_from_the_known_set(self, seed_data):
        from backend.canon.seed_loader import EXTRACTABLE_FROM, EXTRACTABLE_SOURCES

        for entry in [*seed_data["nodes"], *seed_data["edges"]]:
            marker = entry.get(EXTRACTABLE_FROM)
            assert marker is None or marker in EXTRACTABLE_SOURCES, entry

    def test_chapter_three_subset_excludes_other_chapters(self, seed_data):
        subset = extractable_subset(seed_data)
        ids = {n["id"] for n in subset["nodes"]}

        assert "cos:item:tome-of-strahd" not in ids, "the Tome's sites are chapter 1"
        assert "cos:npc:ireena-kolyana" in ids
        assert "cos:npc:kolyan-indirovich" in ids

        types = {e["type"] for e in subset["edges"]}
        assert "RESOLVES_TO" not in types, "the Tarokka fan-out is chapter 1"
        assert "GAVE_QUEST" in types
        assert "IDENTITY_OF" in types, (
            "chapter 3 states that Ireena carries Tatyana's soul, in its opening "
            "paragraph -- this edge must stay in the chapter-3 key"
        )

    def test_subset_is_a_strict_subset(self, seed_data):
        subset = extractable_subset(seed_data)
        assert len(subset["nodes"]) < len(seed_data["nodes"])
        assert len(subset["edges"]) < len(seed_data["edges"])

    def test_requesting_a_marked_source_returns_only_that_source(self, seed_data):
        """Only ch1-marked entries, plus the endpoints its own edges reach for --
        the three sites the Tarokka reading can place the Tome in are chapter-3
        locations, and a RESOLVES_TO edge that named one of them without offering
        it as a node could never be matched."""
        ch1 = extractable_subset(seed_data, source="ch1")
        marked = {n["id"] for n in ch1["nodes"] if n.get("extractable_from") == "ch1"}

        assert marked == {"cos:item:tome-of-strahd", "cos:npc:tatyana"}
        assert all(e["type"] == "RESOLVES_TO" for e in ch1["edges"])
        assert len(ch1["edges"]) == 3
        assert {n["id"] for n in ch1["nodes"]} - marked == {
            "cos:location:church-of-barovia",
            "cos:location:burgomasters-mansion",
            "cos:location:blood-on-the-vine",
        }

    def test_no_subset_emits_an_edge_whose_endpoint_it_omits(self, seed_data):
        """An edge whose endpoint is not in the same subset is unmatchable at any
        looseness -- `by_id.get()` returns an empty name set, so `any(...)` is
        unconditionally False. Measured: `ireena-kolyana IDENTITY_OF tatyana` was
        a permanent 4-point floor on chapter-3 edge recall, read for four review
        rounds as an extraction failure.
        """
        from backend.canon.seed_loader import DEFAULT_SOURCE, EXTRACTABLE_SOURCES

        for source in (DEFAULT_SOURCE, *sorted(EXTRACTABLE_SOURCES)):
            subset = extractable_subset(seed_data, source)
            ids = {n["id"] for n in subset["nodes"]}
            for e in subset["edges"]:
                assert e["source"] in ids, f"{source}: unmatchable source in {e}"
                assert e["target"] in ids, f"{source}: unmatchable target in {e}"

    def test_the_identity_edges_endpoint_is_pulled_into_the_chapter_three_subset(
        self, seed_data
    ):
        """Chapter 3 states that Ireena carries Tatyana's soul, so the edge stays
        in the key -- and an extractor that is asked for the edge is being asked
        to name both of its ends."""
        subset = extractable_subset(seed_data)

        assert "cos:npc:tatyana" in {n["id"] for n in subset["nodes"]}

    def test_an_endpoint_is_pulled_in_only_when_an_edge_needs_it(self, seed_data):
        """The Tome is marked ch1 and no chapter-3 edge touches it, so it stays
        out. Pulling in must not degrade into ignoring the markers."""
        subset = extractable_subset(seed_data)

        assert "cos:item:tome-of-strahd" not in {n["id"] for n in subset["nodes"]}

    def test_pulled_in_endpoints_keep_the_seeds_order(self):
        data = {
            "nodes": [
                {"id": "cos:npc:a", "name": "A", "entity_type": "NPC"},
                {"id": "cos:npc:b", "name": "B", "entity_type": "NPC",
                 "extractable_from": "ch1"},
                {"id": "cos:npc:c", "name": "C", "entity_type": "NPC"},
            ],
            "edges": [{"source": "cos:npc:a", "target": "cos:npc:b", "type": "KNOWS"}],
        }

        subset = extractable_subset(data)

        assert [n["id"] for n in subset["nodes"]] == ["cos:npc:a", "cos:npc:b", "cos:npc:c"]

    def test_unknown_marker_is_reported(self):
        problems = validate_seed(
            {
                "nodes": [
                    {
                        "id": "cos:npc:a",
                        "name": "A",
                        "entity_type": "NPC",
                        "extractable_from": "chapter_seventeen",
                    }
                ],
                "edges": [],
            }
        )
        assert any("chapter_seventeen" in p for p in problems)

    @pytest.mark.neo4j
    def test_marker_is_not_written_to_the_graph(self, graph, tmp_path):
        """The marker describes the answer key, not the world."""
        doc = {
            "nodes": [
                {
                    "id": "pytest:npc:marked",
                    "name": "Marked",
                    "entity_type": "NPC",
                    "extractable_from": "ch1",
                }
            ],
            "edges": [],
        }
        path = tmp_path / "marked.yaml"
        path.write_text(yaml.safe_dump(doc))
        load_seed(path, graph)

        row = graph.run(
            "MATCH (e:Entity {id:'pytest:npc:marked'}) RETURN e.extractable_from AS m"
        ).single()
        assert row["m"] is None
