"""Spatial containment lives in the document hierarchy, not the prose.

A section headed "E5. Church" describes Donavich without ever saying he is in
the church -- that is encoded by which section he appears in. Deriving those
edges is deterministic and free; asking an LLM to infer them from prose that
does not state them is neither.
"""

from backend.canon.models import CandidateNode, Section
from backend.canon.structure import STRUCTURAL_EVIDENCE, place_of_section, structural_edges


def contains(edges) -> set[tuple[str, str]]:
    return {(e.source_name, e.target_name) for e in edges if e.rel_type == "CONTAINS"}


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

    def test_a_node_naming_its_own_section_is_not_located_in_itself(self):
        """The entity_type guard above is not enough, and the real chapter-3 run
        proves it: the extractor typed `Trapdoor` -- from section
        `E5d. Trapdoor` -- as an ITEM, and the derived set shipped
        `Trapdoor -LOCATED_IN-> Trapdoor`. A self-loop out of the one module
        documented as unable to fabricate. Casing varies in the transcription
        (`undercroft` beside `Undercroft`), so the comparison ignores it.
        """
        sections = [section("E5d. Trapdoor"), section("E5g. Undercroft", 1)]
        nodes = [
            node("Trapdoor", entity_type="ITEM", heading="E5d. Trapdoor"),
            node("undercroft", entity_type="ITEM", heading="E5g. Undercroft", section_index=1),
        ]

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

    def test_derived_edges_carry_their_section_provenance(self):
        """The section a derived edge came from is mechanically known -- it
        must not ship the -1 sentinel that means "unknown"; stage 2b needs
        this exactly where §7's section_index fix was meant to help."""
        sections = [section("E5. Church", index=2)]
        nodes = [node("Donavich", heading="E5. Church", section_index=2)]
        edges = structural_edges(sections, nodes, "Village of Barovia")

        contains = next(e for e in edges if e.rel_type == "CONTAINS")
        assert contains.section_index == 2
        assert contains.section_heading == "E5. Church"

        located = next(e for e in edges if e.rel_type == "LOCATED_IN")
        assert located.section_index == 2
        assert located.section_heading == "E5. Church"

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
        assert len(located) == 2, (
            "the repeated Donavich mention must collapse to one edge -- these "
            "duplicates share a section_index, which is what separates them "
            "from two same-named rooms in DIFFERENT sections"
        )
        assert {(e.source_name, e.target_name) for e in located} == {
            ("Donavich", "Church"),
            ("Doru", "Church"),
        }
        seen = [(e.source_name, e.target_name, e.rel_type) for e in edges]
        assert len(seen) == len(set(seen))


class TestSubareaContainment:
    """The keys encode the hierarchy the transcription lost.

    `E5g. Undercroft` is inside `E5. Church`, and the letter suffix is the only
    reliable record of that: the transcription put `E5. Church` at H2 and
    `E5a. Hall` at H3 in chapter 3, but `E6. Cemetery` at H1 and
    `E4. Burgomaster's Mansion` at H3, so heading depth says nothing.
    """

    def test_a_suffixed_key_is_contained_by_its_stem_section(self):
        sections = [section("E5. Church"), section("E5g. Undercroft", 1)]

        edges = structural_edges(sections, [], "Village of Barovia")

        assert contains(edges) == {
            ("Village of Barovia", "Church"),
            ("Church", "Undercroft"),
        }, "the Undercroft is in the Church, not loose in the village"

    def test_a_suffixless_key_is_contained_by_the_chapter_place(self):
        sections = [section("E1. Bildrath's Mercantile")]

        edges = structural_edges(sections, [], "Village of Barovia")

        assert contains(edges) == {("Village of Barovia", "Bildrath's Mercantile")}

    def test_a_suffixed_key_falls_back_to_the_chapter_place_with_no_stem_section(self):
        """`K20a` with no `K20` section: dropping the edge would lose a
        containment the chapter place can still state correctly."""
        sections = [section("K18. High Tower"), section("K20a. Study", 1)]

        edges = structural_edges(sections, [], "Castle Ravenloft")

        assert contains(edges) == {
            ("Castle Ravenloft", "High Tower"),
            ("Castle Ravenloft", "Study"),
        }

    def test_only_a_suffixless_section_can_be_a_stem(self):
        """`E5a` is not the parent of `E5b`; both are children of `E5`, and
        with no `E5` section both fall back to the chapter place."""
        sections = [section("E5a. Hall"), section("E5b. Bedroom", 1)]

        edges = structural_edges(sections, [], "Village of Barovia")

        assert contains(edges) == {
            ("Village of Barovia", "Hall"),
            ("Village of Barovia", "Bedroom"),
        }

    def test_a_duplicated_stem_key_keeps_its_first_occurrence(self):
        """The transcription duplicates a heading across a page seam -- the same
        reason the self-containment guard below exists. A second `E5` heading
        naming a different place must not silently reparent every E5* sub-area:
        with last-occurrence-wins, all seven of E5a-E5g would point at `Nave`
        instead of `Church`, and nothing else in this module would notice.
        """
        sections = [
            section("E5. Church"),
            section("E5g. Undercroft", 1),
            section("E5. Nave", 2),
        ]

        edges = structural_edges(sections, [], "Village of Barovia")

        assert ("Church", "Undercroft") in contains(edges)
        assert ("Nave", "Undercroft") not in contains(edges)

    def test_two_distinct_rooms_that_share_a_name_both_keep_containment(self):
        """Keyed rooms repeat names across a castle: chapter 4 has two closets
        (`K44`, `K51`), two forgotten treasures (`K74b`, `K74d`) and three empty
        cells. Deduplicating derived edges on name text alone silently drops one
        of each -- 103 keyed places produced only 100 CONTAINS edges -- and the
        loss is invisible downstream, because the surviving edge's provenance
        names the OTHER room. `section_index` is what distinguishes them, which
        is the same reason `by_index` is keyed on it rather than on heading.
        """
        sections = [section("K44. Closet"), section("K51. Closet", 1)]

        edges = [e for e in structural_edges(sections, [], "Castle Ravenloft")
                 if e.rel_type == "CONTAINS"]

        assert len(edges) == 2, "one room's containment was dropped as a duplicate"
        assert {e.section_heading for e in edges} == {"K44. Closet", "K51. Closet"}
        assert {e.section_index for e in edges} == {0, 1}

    def test_a_place_is_never_contained_by_itself(self):
        """The transcription repeats a heading's name onto its sub-area often
        enough that this is real: `E5. Church` and `E5a. Church` would derive
        `Church CONTAINS Church`, a self-loop in the one module that is
        documented as unable to fabricate."""
        sections = [section("E5. Church"), section("E5a. Church", 1)]

        edges = structural_edges(sections, [], "Village of Barovia")

        assert contains(edges) == {("Village of Barovia", "Church")}

    def test_a_stem_contained_edge_keeps_its_structural_evidence_and_provenance(self):
        sections = [section("E5. Church"), section("E5g. Undercroft", 7)]

        edges = structural_edges(sections, [], "Village of Barovia")

        edge = next(e for e in edges if e.target_name == "Undercroft")
        assert edge.evidence == STRUCTURAL_EVIDENCE
        assert edge.layer == "spatial"
        assert edge.section_index == 7
        assert edge.section_heading == "E5g. Undercroft"

    def test_a_stem_parent_holds_even_with_no_chapter_place(self):
        """A stem parent is a section of the document, not an invented place,
        so the anti-fabrication guard that suppresses chapter-place CONTAINS
        for a place-less chapter does not apply to it. (The two suffix-less
        sections still get nothing -- there is no parent to name.)"""
        sections = [section("E5. Church"), section("E5g. Undercroft", 1)]

        edges = structural_edges(sections, [], None)

        assert contains(edges) == {("Church", "Undercroft")}


class TestSectionIndexIsTheKey:
    def test_duplicate_headings_in_one_chapter_do_not_merge_their_entities(self):
        """Chapter 4 has four sections headed "Treasure"; Appendix D has three
        headed "Actions" -- `(chapter_slug, heading)` is not a unique key.
        Keying on section_index (not heading text) means a node from one
        "Treasure" section is never resolved against a different "Treasure"
        section's identity, even when they share a heading.

        NOTE: `place_of_section` is a pure function of heading text, so this
        specific fixture (both "Treasure" sections keyed and identical)
        computes the same place either way and does not by itself
        discriminate heading-keying from index-keying under mutation -- see
        `test_a_node_resolves_against_its_own_section_index_not_its_heading`
        below for the fixture that does.
        """
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

    def test_a_node_resolves_against_its_own_section_index_not_its_heading(self):
        """A shadowed duplicate heading must not resolve a node to the WRONG
        section's place. Donavich's `section_heading` happens to read "E5.
        Church" (stale/duplicate text), but his real section is index 1,
        "Prose Interlude" -- unkeyed, no place. Keying the lookup on
        `node.section_heading` instead of `node.section_index` would find
        section 0's "Church" via the heading text and wrongly emit
        Donavich -LOCATED_IN-> Church, even though his actual section names
        no place at all. This is the failure the brief describes: a shadowed
        duplicate heading resolving to the wrong section's place.
        """
        sections = [section("E5. Church", index=0), section("Prose Interlude", index=1)]
        nodes = [node("Donavich", heading="E5. Church", section_index=1)]
        edges = structural_edges(sections, nodes, "Village of Barovia")

        assert [e for e in edges if e.rel_type == "LOCATED_IN"] == []
