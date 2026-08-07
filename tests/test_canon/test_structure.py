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


def node(
    name: str, entity_type: str = "NPC", heading: str = "", section_index: int = 0
) -> CandidateNode:
    return CandidateNode(
        name=name,
        entity_type=entity_type,
        chapter_slug="chapter-3-the-village-of-barovia",
        section_heading=heading,
        section_index=section_index,
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
        """Appendix D has no containing place; inventing one would be a fabrication.

        The section below IS keyed (unlike the old fixture's "Baba Lysaga"),
        so the per-section None in `by_index` cannot be what blocks CONTAINS
        here -- only the `chapter_place` guard itself can be. This is the
        anti-fabrication property Task 6 exists for.
        """
        sections = [section("D1. Baba Lysaga's Hut")]
        edges = structural_edges(sections, [], None)

        assert [e for e in edges if e.rel_type == "CONTAINS"] == []

    def test_derived_edges_are_marked_as_structural(self):
        sections = [section("E5. Church")]
        edges = structural_edges(sections, [], "Village of Barovia")

        assert all(e.layer == "spatial" for e in edges)
        assert all("structure" in e.evidence for e in edges)

    def test_edges_are_deduplicated(self):
        """The same node name can appear more than once in the same section --
        on the real chapter-3 run, three layer passes extract the same node
        name from the same section repeatedly, and 41 raw candidates dedup to
        19. Two DISTINCT node names (the old fixture) can never exercise this:
        three distinct edges are trivially already unique."""
        sections = [section("E5. Church")]
        nodes = [
            node("Donavich", heading="E5. Church"),
            node("Donavich", heading="E5. Church"),
            node("Doru", heading="E5. Church"),
        ]
        edges = structural_edges(sections, nodes, "Village of Barovia")

        located = [e for e in edges if e.rel_type == "LOCATED_IN"]
        assert len(located) == 2, "the repeated Donavich mention must collapse to one edge"
        assert {(e.source_name, e.target_name) for e in located} == {
            ("Donavich", "Church"),
            ("Doru", "Church"),
        }
        seen = [(e.source_name, e.target_name, e.rel_type) for e in edges]
        assert len(seen) == len(set(seen))


class TestSectionIndexIsTheKey:
    def test_duplicate_headings_in_one_chapter_do_not_merge_their_entities(self):
        """Chapter 4 has four sections headed "Treasure"; Appendix D has three
        headed "Actions" -- `(chapter_slug, heading)` is not a unique key.
        Keying on section_index (not heading text) means a node from one
        "Treasure" section is never resolved against a different "Treasure"
        section's identity, even when they share a heading."""
        sections = [
            section("T1. Treasure", index=0),
            section("Interlude", index=1),
            section("T1. Treasure", index=2),
        ]
        nodes = [
            node("Gold Coins", heading="T1. Treasure", section_index=0),
            node("Silver Chalice", heading="T1. Treasure", section_index=2),
        ]
        edges = structural_edges(sections, nodes, "Death House")

        located = [e for e in edges if e.rel_type == "LOCATED_IN"]
        assert {(e.source_name, e.target_name) for e in located} == {
            ("Gold Coins", "Treasure"),
            ("Silver Chalice", "Treasure"),
        }, "both nodes must be independently located, not merged into one"
