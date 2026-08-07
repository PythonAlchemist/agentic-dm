"""Spatial containment lives in the document hierarchy, not the prose.

A section headed "E5. Church" describes Donavich without ever saying he is in
the church -- that is encoded by which section he appears in. Deriving those
edges is deterministic and free; asking an LLM to infer them from prose that
does not state them is neither.
"""

from backend.canon.models import CandidateNode, Section
from backend.canon.structure import place_of_section, structural_edges


def section(heading: str, index: int = 0) -> Section:
    return Section(
        chapter_slug="chapter-3-the-village-of-barovia",
        chapter_title="Chapter 3: The Village of Barovia",
        heading=heading,
        index=index,
        markdown=f"## {heading}\n\nBody.",
    )


def node(name: str, entity_type: str = "NPC", heading: str = "") -> CandidateNode:
    return CandidateNode(
        name=name,
        entity_type=entity_type,
        chapter_slug="chapter-3-the-village-of-barovia",
        section_heading=heading,
    )


class TestPlaceOfSection:
    def test_strips_a_keyed_area_prefix(self):
        assert place_of_section(section("E1. Bildrath's Mercantile")) == "Bildrath's Mercantile"
        assert place_of_section(section("E5. Church")) == "Church"

    def test_handles_a_lettered_subarea(self):
        assert place_of_section(section("E5g. Undercroft")) == "Undercroft"

    def test_a_section_without_a_key_is_not_a_place(self):
        """Prose sections like "Approaching the Village" name no location."""
        assert place_of_section(section("Approaching the Village")) is None
        assert place_of_section(section("(preamble)")) is None

    def test_a_bare_number_prefix_is_not_a_keyed_room(self):
        """Chapter 1's Tarokka card list and Appendix B's Death House rooms are
        the book's only bare-number keys, and neither names a physical room --
        a letter prefix is what distinguishes a genuine keyed room."""
        assert place_of_section(section("12. Old Bonegrinder")) is None


class TestStructuralEdges:
    def test_chapter_place_contains_each_keyed_section(self):
        sections = [section("E1. Bildrath's Mercantile"), section("E5. Church", 1)]
        edges = structural_edges(sections, [], "Village of Barovia")

        contains = [e for e in edges if e.rel_type == "CONTAINS"]
        assert {e.target_name for e in contains} == {"Bildrath's Mercantile", "Church"}
        assert all(e.source_name == "Village of Barovia" for e in contains)

    def test_an_npc_is_located_in_its_section_place(self):
        sections = [section("E5. Church")]
        nodes = [node("Donavich", heading="E5. Church")]
        edges = structural_edges(sections, nodes, "Village of Barovia")

        located = [e for e in edges if e.rel_type == "LOCATED_IN"]
        assert len(located) == 1
        assert located[0].source_name == "Donavich"
        assert located[0].target_name == "Church"

    def test_a_location_node_is_not_located_in_itself(self):
        sections = [section("E5. Church")]
        nodes = [node("Church", entity_type="LOCATION", heading="E5. Church")]
        edges = structural_edges(sections, nodes, "Village of Barovia")

        assert [e for e in edges if e.rel_type == "LOCATED_IN"] == []

    def test_nodes_from_unkeyed_sections_get_no_location(self):
        sections = [section("Approaching the Village")]
        nodes = [node("Ismark", heading="Approaching the Village")]
        edges = structural_edges(sections, nodes, "Village of Barovia")

        assert [e for e in edges if e.rel_type == "LOCATED_IN"] == []

    def test_no_chapter_place_means_no_contains_edges(self):
        """Appendix D has no containing place; inventing one would be a fabrication."""
        sections = [section("Baba Lysaga")]
        edges = structural_edges(sections, [], None)

        assert [e for e in edges if e.rel_type == "CONTAINS"] == []

    def test_derived_edges_are_marked_as_structural(self):
        sections = [section("E5. Church")]
        edges = structural_edges(sections, [], "Village of Barovia")

        assert all(e.layer == "spatial" for e in edges)
        assert all("structure" in e.evidence for e in edges)

    def test_edges_are_deduplicated(self):
        """Two NPCs in one section must not produce two identical CONTAINS edges."""
        sections = [section("E5. Church")]
        nodes = [node("Donavich", heading="E5. Church"),
                 node("Doru", heading="E5. Church")]
        edges = structural_edges(sections, nodes, "Village of Barovia")

        seen = [(e.source_name, e.target_name, e.rel_type) for e in edges]
        assert len(seen) == len(set(seen))
