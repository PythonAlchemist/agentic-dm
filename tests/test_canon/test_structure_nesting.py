"""Containment from the document's nesting, corrected by the key.

`structure.py` used to read containment off the key stem alone (`E5g` is inside
`E5`), because the vision transcription's heading levels were noise. The D&D
Beyond corpus nests properly -- of the 131 sub-area/parent pairs in the book,
115 render deeper than their parent, 0 shallower and 0 orphaned -- so nesting
now carries it, and the key is demoted to a correction for the 16 pairs the book
renders at the *same* depth (6 in Castle Ravenloft, 10 in the Amber Temple).

Depth first, key second, and the key only speaks when depth has no answer. That
ordering is what keeps the `key` splitter's behaviour identical: its sections
all report depth 0 ("unknown"), so no section is anyone's ancestor, and every
keyed area falls through to exactly the stem-or-chapter rule it had before.
"""

from backend.canon.models import CandidateNode, Section
from backend.canon.structure import STRUCTURAL_EVIDENCE, derive_structure, structural_edges

CHAPTER = "The Village of Barovia"


def section(heading: str, index: int, depth: int = 0, parent_index: int = -1) -> Section:
    return Section(
        chapter_slug="ch3",
        chapter_title="Chapter 3: The Village of Barovia",
        heading=heading,
        index=index,
        markdown=f"{'#' * max(depth, 2)} {heading}\n\nBody.",
        depth=depth,
        parent_index=parent_index,
    )


def node(name: str, entity_type: str = "NPC", section_index: int = 0) -> CandidateNode:
    return CandidateNode(
        name=name, entity_type=entity_type, chapter_slug="ch3", section_index=section_index
    )


def contains(edges) -> set[tuple[str, str]]:
    return {(e.source_name, e.target_name) for e in edges if e.rel_type == "CONTAINS"}


def located(edges) -> set[tuple[str, str]]:
    return {(e.source_name, e.target_name) for e in edges if e.rel_type == "LOCATED_IN"}


# A DDB-shaped chapter 3: an unkeyed h2 divider, keyed h3 areas, keyed h4
# sub-areas nested under `E5. Church`.
NESTED = [
    section("Areas of the Village", 0, depth=2),
    section("E1. Bildrath's Mercantile", 1, depth=3, parent_index=0),
    section("E5. Church", 2, depth=3, parent_index=0),
    section("E5a. Hall", 3, depth=4, parent_index=2),
    section("E5g. Undercroft", 4, depth=4, parent_index=2),
]


class TestNestingContainment:
    def test_a_deeper_section_is_contained_by_the_section_it_nests_under(self):
        edges = structural_edges(NESTED, [], CHAPTER)

        assert ("Church", "Undercroft") in contains(edges)
        assert ("Church", "Hall") in contains(edges)

    def test_the_chapter_does_not_also_claim_a_nested_sub_area(self):
        """`E5g. Undercroft` is in the church, not loose in the village. The
        nearest *placed* ancestor wins; the chapter is only the fallback."""
        edges = structural_edges(NESTED, [], CHAPTER)

        assert (CHAPTER, "Undercroft") not in contains(edges)

    def test_a_top_level_area_falls_back_to_the_chapter(self):
        """Its enclosing section is an unkeyed divider, which names no place, so
        the walk continues past it rather than inventing "Areas of the
        Village" as a location."""
        edges = structural_edges(NESTED, [], CHAPTER)

        assert (CHAPTER, "Bildrath's Mercantile") in contains(edges)
        assert ("Areas of the Village", "Bildrath's Mercantile") not in contains(edges)

    def test_containment_is_counted_by_where_it_came_from(self):
        result = derive_structure(NESTED, [], CHAPTER)

        assert result.depth_derived == 2      # Hall, Undercroft
        assert result.chapter_derived == 2    # Mercantile, Church
        assert result.key_derived == 0

    def test_derived_edges_keep_structural_evidence_and_exact_provenance(self):
        edges = [e for e in structural_edges(NESTED, [], CHAPTER) if e.target_name == "Undercroft"]

        assert [e.evidence for e in edges] == [STRUCTURAL_EVIDENCE]
        assert edges[0].section_index == 4
        assert edges[0].section_heading == "E5g. Undercroft"


class TestKeyCorrection:
    # Castle Ravenloft renders `K20a` as a sibling of `K20`, not beneath it.
    # Nesting alone cannot see the relationship; the key can.
    SAME_DEPTH = [
        section("Court of the Count", 0, depth=2),
        section("K20. King's Bedroom", 1, depth=3, parent_index=0),
        section("K20a. Treasury", 2, depth=3, parent_index=0),
    ]

    def test_the_key_supplies_containment_the_depth_missed(self):
        edges = structural_edges(self.SAME_DEPTH, [], "Castle Ravenloft")

        assert ("King's Bedroom", "Treasury") in contains(edges)

    def test_a_key_supplied_parent_replaces_the_chapter_fallback(self):
        """Two parents for one room would be a fabrication dressed as
        thoroughness: the castle contains the treasury only via the bedroom."""
        edges = structural_edges(self.SAME_DEPTH, [], "Castle Ravenloft")

        assert ("Castle Ravenloft", "Treasury") not in contains(edges)

    def test_the_key_correction_is_counted_separately(self):
        result = derive_structure(self.SAME_DEPTH, [], "Castle Ravenloft")

        assert result.key_derived == 1
        assert result.depth_derived == 0

    def test_the_key_does_not_double_count_what_depth_already_established(self):
        """`E5g` nests under `E5` *and* keys to it. One edge, from depth."""
        result = derive_structure(NESTED, [], CHAPTER)
        undercroft = [e for e in result.edges if e.target_name == "Undercroft"]

        assert len(undercroft) == 1
        assert result.key_derived == 0

    def test_an_orphan_sub_area_still_falls_back_to_the_chapter(self):
        orphan = [section("K99z. Lost Closet", 0, depth=3)]
        edges = structural_edges(orphan, [], "Castle Ravenloft")

        assert ("Castle Ravenloft", "Lost Closet") in contains(edges)


class TestNoFabrication:
    def test_an_appendix_with_no_keyed_areas_derives_no_containment(self):
        """Appendix D nests creatures under `## Creatures (A-H)` three levels
        deep. Nothing there names a place, and a depth rule that read nesting
        without asking whether either end IS a place would mint
        "Creatures (A-H) CONTAINS The Abbot"."""
        appendix = [
            section("Creatures (A-H)", 0, depth=2),
            section("The Abbot", 1, depth=3, parent_index=0),
            section("The Abbot's Traits", 2, depth=4, parent_index=1),
            section("Baba Lysaga", 3, depth=3, parent_index=0),
        ]

        assert contains(structural_edges(appendix, [], None)) == set()

    def test_a_place_never_contains_itself(self):
        repeated = [
            section("E5. Church", 0, depth=3),
            section("E5a. church", 1, depth=4, parent_index=0),
        ]

        assert contains(structural_edges(repeated, [], CHAPTER)) == {(CHAPTER, "Church")}

    def test_a_duplicated_stem_keeps_its_first_occurrence(self):
        duplicated = [
            section("K7. Chapel", 0, depth=3),
            section("K7. Chapel Annexe", 1, depth=3),
            section("K7a. Vestry", 2, depth=3),
        ]
        edges = contains(structural_edges(duplicated, [], "Castle Ravenloft"))

        assert ("Chapel", "Vestry") in edges
        assert ("Chapel Annexe", "Vestry") not in edges


class TestLocatedIn:
    def test_a_node_is_located_in_its_own_keyed_section(self):
        edges = structural_edges(NESTED, [node("Donavich", section_index=2)], CHAPTER)

        assert ("Donavich", "Church") in located(edges)

    def test_a_node_in_an_unkeyed_subsection_inherits_the_enclosing_place(self):
        """The regression this design exists to avoid. Refinement can cut
        `#### Roleplaying Ismark` out of `E2. Blood of the Vine Tavern`, and the
        golden edge `ismark LOCATED_IN blood-of-the-vine` must survive it. The
        sub-section names no place, so the nearest placed ancestor answers --
        which is exactly where the prose sat before it was cut."""
        sections = [
            section("E2. Blood of the Vine Tavern", 0, depth=3),
            section("Roleplaying Ismark", 1, depth=4, parent_index=0),
        ]
        edges = structural_edges(sections, [node("Ismark Kolyanovich", section_index=1)], CHAPTER)

        assert ("Ismark Kolyanovich", "Blood of the Vine Tavern") in located(edges)

    def test_a_location_node_is_not_located_in_anything(self):
        edges = structural_edges(NESTED, [node("Undercroft", "LOCATION", section_index=4)], CHAPTER)

        assert located(edges) == set()

    def test_a_node_in_a_placeless_chapter_is_located_nowhere(self):
        appendix = [section("The Abbot", 0, depth=3)]
        edges = structural_edges(appendix, [node("The Abbot", section_index=0)], None)

        assert located(edges) == set()


class TestKeySplitterBaselineUnchanged:
    """Legs A and B of the measurement run the key splitter, whose sections all
    report depth 0. No section can then be an ancestor, so every keyed area
    falls straight through to the stem-or-chapter rule that shipped on `main`.
    If this drifts, the A/B comparison stops isolating anything.
    """

    FLAT = [
        section("E5. Church", 0),
        section("E5g. Undercroft", 1),
        section("E1. Bildrath's Mercantile", 2),
    ]

    def test_the_stem_still_parents_its_sub_area(self):
        assert ("Church", "Undercroft") in contains(structural_edges(self.FLAT, [], CHAPTER))

    def test_the_chapter_still_parents_a_stemless_area(self):
        edges = contains(structural_edges(self.FLAT, [], CHAPTER))

        assert (CHAPTER, "Bildrath's Mercantile") in edges
        assert (CHAPTER, "Undercroft") not in edges

    def test_nothing_is_attributed_to_depth(self):
        result = derive_structure(self.FLAT, [], CHAPTER)

        assert result.depth_derived == 0
        assert result.key_derived == 1
        assert result.chapter_derived == 2
