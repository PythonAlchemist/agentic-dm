"""The filter chain and id minting that decide what reaches Neo4j.

Nothing here touches a database: `plan_write` is a pure function of candidates,
a gazetteer and a chapter slug, which is what makes every drop rule assertable
without a live graph. The transactional half is pinned in
`test_write_canon_neo4j.py`.
"""

import pytest

from backend.canon.gazetteer import Gazetteer, GazetteerEntry
from backend.canon.models import CandidateEdge, CandidateNode
from backend.canon.writer import CANON_PLANE, mint_id, plan_write
from backend.graph.schema import Layer, RelationshipType

SLUG = "the-village-of-barovia"


def gazetteer(*names: str) -> Gazetteer:
    """A gazetteer knowing exactly these names, all typed NPC."""
    return Gazetteer([GazetteerEntry(name=n, entity_type="NPC", wiki_category="c") for n in names])


def node(name: str, entity_type: str = "LOCATION", **kwargs) -> CandidateNode:
    return CandidateNode(name=name, entity_type=entity_type, chapter_slug=SLUG, **kwargs)


def edge(source: str, target: str, rel_type: str = "LOCATED_IN", **kwargs) -> CandidateEdge:
    return CandidateEdge(
        source_name=source, target_name=target, rel_type=rel_type, chapter_slug=SLUG, **kwargs
    )


class TestIdMinting:
    def test_id_is_chapter_scoped(self):
        assert mint_id(SLUG, "LOCATION", "Blood of the Vine Tavern") == (
            "cos:the-village-of-barovia:location:blood-of-the-vine-tavern"
        )

    def test_same_room_in_two_chapters_gets_two_ids(self):
        """Chapter 4's Chapel is not chapter 3's. Nothing merges across chapters."""
        assert mint_id("the-village-of-barovia", "LOCATION", "Chapel") != mint_id(
            "castle-ravenloft", "LOCATION", "Chapel"
        )

    def test_entity_type_is_part_of_the_id(self):
        """A coined QUEST sharing a LOCATION's name is a measured occurrence."""
        assert mint_id(SLUG, "QUEST", "Barovia") != mint_id(SLUG, "LOCATION", "Barovia")

    def test_planned_nodes_carry_the_minted_id(self):
        nodes, _, _ = plan_write([node("Ismark")], [], gazetteer("Ismark"), SLUG)
        assert [n.id for n in nodes] == ["cos:the-village-of-barovia:location:ismark"]


class TestSelfLoops:
    def test_self_loop_is_dropped(self):
        _, edges, report = plan_write(
            [node("Trapdoor"), node("Undercroft")],
            [edge("Trapdoor", "Trapdoor"), edge("Trapdoor", "Undercroft")],
            gazetteer("Trapdoor", "Undercroft"),
            SLUG,
        )
        assert report.self_loops == 1
        assert [(e.source_id, e.target_id) for e in edges] == [
            (mint_id(SLUG, "LOCATION", "Trapdoor"), mint_id(SLUG, "LOCATION", "Undercroft"))
        ]

    def test_self_loop_detection_ignores_case_and_spacing(self):
        _, edges, report = plan_write(
            [node("Undercroft")],
            [edge("Undercroft", " undercroft ")],
            gazetteer("Undercroft"),
            SLUG,
        )
        assert report.self_loops == 1
        assert edges == []


class TestConstraintViolations:
    def test_type_impossible_edge_is_dropped(self):
        """`Chapel LOCATED_IN Donavich` puts a location inside a priest."""
        _, edges, report = plan_write(
            [node("Chapel", "LOCATION"), node("Donavich", "NPC")],
            [edge("Chapel", "Donavich", "LOCATED_IN")],
            gazetteer("Chapel", "Donavich"),
            SLUG,
        )
        assert report.constraint_violations == 1
        assert edges == []

    def test_edge_with_an_untyped_endpoint_is_kept(self):
        """Unknown endpoint type is UNCHECKED, never violating.

        `structure.py` emits edges without emitting nodes, so a derived edge
        whose endpoint has no candidate node is normal -- and those are the most
        reliable edges in the set. This is the case a filter written as
        "reject anything not provably legal" would silently delete.
        """
        _, edges, report = plan_write(
            [node("Church", "LOCATION"), node("Donavich", "NPC")],
            # Donavich has no *typed* node under the name the edge uses, so the
            # endpoint is unknown -- and LOCATION LOCATED_IN NPC would violate.
            [edge("Church", "Donavich the Priest", "LOCATED_IN")],
            gazetteer("Church", "Donavich", "Donavich the Priest"),
            SLUG,
        )
        assert report.constraint_violations == 0
        # The endpoint node itself does not exist, so the edge dangles -- but it
        # was not counted as a violation, which is the distinction under test.
        assert report.dangling_edges == 1
        assert edges == []

    def test_untyped_endpoint_edge_survives_all_the_way_when_both_ends_exist(self):
        """The same rule, with the endpoint present so the edge really is written."""
        nodes, edges, report = plan_write(
            [node("Church", "LOCATION"), node("Bones", "")],
            [edge("Bones", "Church", "LOCATED_IN")],
            gazetteer("Church", "Bones"),
            SLUG,
        )
        assert report.constraint_violations == 0
        assert len(nodes) == 2
        assert len(edges) == 1


class TestFilterOrder:
    def test_endpoint_types_are_read_before_the_gazetteer_removes_them(self):
        """Constraints run on the FULL candidate set, gazetteer afterwards.

        `wooden bed GUARDS Donavich` has a bed standing watch: impossible by
        type. Run the gazetteer first and the bed is gone, its endpoint becomes
        untyped, the edge is merely dangling -- and a real type failure is filed
        as a bookkeeping one. The counts are what this project reads to decide
        whether the constraint table is worth trusting, so which bucket a drop
        lands in is not cosmetic.
        """
        _, edges, report = plan_write(
            [node("wooden bed", "ITEM"), node("Donavich", "NPC")],
            [edge("wooden bed", "Donavich", "GUARDS")],
            gazetteer("Donavich"),
            SLUG,
        )
        assert report.constraint_violations == 1
        assert report.dangling_edges == 0
        assert edges == []


class TestGazetteerFilter:
    def test_bare_generic_noun_is_dropped(self):
        nodes, _, report = plan_write(
            [node("Ismark Kolyanovich", "NPC"), node("wooden bed", "ITEM")],
            [],
            gazetteer("Ismark Kolyanovich"),
            SLUG,
        )
        assert report.gazetteer_dropped == 1
        assert [n.name for n in nodes] == ["Ismark Kolyanovich"]

    def test_keyed_place_absent_from_the_gazetteer_is_kept(self):
        """The wiki indexes 38 locations against the book's 414 keyed areas.

        A keyed room missing from the gazetteer is EXPECTED, not evidence
        against the room. Filtering keyed places by gazetteer membership would
        delete most of the book.
        """
        nodes, _, report = plan_write(
            [
                node(
                    "Bildrath's Mercantile",
                    "LOCATION",
                    section_heading="E1. Bildrath's Mercantile",
                )
            ],
            [],
            gazetteer(),  # knows nothing at all
            SLUG,
        )
        assert report.gazetteer_dropped == 0
        assert [n.name for n in nodes] == ["Bildrath's Mercantile"]

    def test_keyed_place_is_kept_whatever_type_the_extractor_gave_it(self):
        """Chapter 4 has 18 keyed areas the extractor happened to type ITEM."""
        nodes, _, _ = plan_write(
            [node("Trapdoor", "ITEM", section_heading="E5d. Trapdoor")],
            [],
            gazetteer(),
            SLUG,
        )
        assert [n.name for n in nodes] == ["Trapdoor"]

    def test_a_keyed_place_named_in_one_section_is_kept_in_every_section(self):
        """`Church` is keyed at E5; a mention of it from E5g is the same room."""
        nodes, _, _ = plan_write(
            [
                node("Undercroft", "LOCATION", section_heading="E5g. Undercroft"),
                node("Church", "LOCATION", section_heading="E5. Church"),
                node("church", "LOCATION", section_heading="E5g. Undercroft"),
            ],
            [],
            gazetteer(),
            SLUG,
        )
        # "Church" and "church" collapse onto one id, so two nodes survive.
        assert sorted(n.name for n in nodes) == ["Church", "Undercroft"]

    def test_an_unkeyed_heading_confers_nothing(self):
        """`Approaching the Village` is prose, not a keyed area."""
        nodes, _, report = plan_write(
            [
                node(
                    "Approaching the Village",
                    "LOCATION",
                    section_heading="Approaching the Village",
                )
            ],
            [],
            gazetteer(),
            SLUG,
        )
        assert report.gazetteer_dropped == 1
        assert nodes == []


class TestDanglingEdges:
    def test_edge_whose_endpoint_was_dropped_is_dropped(self):
        """The edge is legal by type -- `NPC OWNS ITEM` satisfies the table --
        so only the gazetteer's removal of its target can account for it."""
        _, edges, report = plan_write(
            [node("Ismark Kolyanovich", "NPC"), node("wooden bed", "ITEM")],
            [edge("Ismark Kolyanovich", "wooden bed", "OWNS")],
            gazetteer("Ismark Kolyanovich"),
            SLUG,
        )
        assert report.constraint_violations == 0
        assert report.gazetteer_dropped == 1
        assert report.dangling_edges == 1
        assert edges == []

    def test_edge_naming_an_entity_that_never_had_a_node_is_dropped(self):
        _, edges, report = plan_write(
            [node("Church", "LOCATION")],
            [edge("Church", "Castle Ravenloft", "CONNECTED_TO")],
            gazetteer("Church"),
            SLUG,
        )
        assert report.dangling_edges == 1
        assert edges == []


class TestAmbiguousEndpoints:
    def test_edge_whose_endpoint_name_has_two_types_is_dropped(self):
        """Tatyana is typed NPC by one sample and LORE by four.

        Both nodes are written -- the type is part of the id, and node
        consensus cannot tell "unsupported entity" from "disputed type" -- but
        an edge naming `Tatyana` cannot say which of the two it means. Picking
        one would manufacture an assertion the extractor never made, so the
        edge is dropped and counted, the same way a reversal is detected and
        never performed.
        """
        nodes, edges, report = plan_write(
            [node("Tatyana", "NPC"), node("Tatyana", "LORE"), node("Ireena", "NPC")],
            [edge("Ireena", "Tatyana", "IDENTITY_OF")],
            gazetteer("Tatyana", "Ireena"),
            SLUG,
        )
        assert len(nodes) == 3
        assert report.ambiguous_edges == 1
        assert edges == []
        assert "Ireena -IDENTITY_OF-> Tatyana" in report.dropped_ambiguous


class TestDeduplication:
    def test_two_candidates_for_one_id_become_one_node(self):
        nodes, _, report = plan_write(
            [
                node("Castle Ravenloft", "LOCATION", section_index=0),
                node("Castle Ravenloft", "LOCATION", section_index=4),
            ],
            [],
            gazetteer("Castle Ravenloft"),
            SLUG,
        )
        assert len(nodes) == 1
        assert report.duplicate_nodes == 1
        # First occurrence wins, so provenance is the earliest section.
        assert nodes[0].section_index == 0

    def test_one_relationship_per_source_type_target(self):
        _, edges, report = plan_write(
            [node("Church"), node("Undercroft")],
            [
                edge("Undercroft", "Church", "LOCATED_IN", section_index=1),
                edge("Undercroft", "Church", "LOCATED_IN", section_index=2),
            ],
            gazetteer("Church", "Undercroft"),
            SLUG,
        )
        assert len(edges) == 1
        assert report.duplicate_edges == 1


class TestWrittenProperties:
    def test_every_node_is_stamped_canon_and_carries_its_provenance(self):
        nodes, _, _ = plan_write(
            [
                node(
                    "Ismark Kolyanovich",
                    "NPC",
                    description="The burgomaster's son.",
                    section_heading="(preamble)",
                    section_index=0,
                    votes=5,
                )
            ],
            [],
            gazetteer("Ismark Kolyanovich"),
            SLUG,
        )
        assert nodes[0].properties == {
            "name": "Ismark Kolyanovich",
            "entity_type": "NPC",
            "plane": CANON_PLANE,
            "chapter_slug": SLUG,
            "section_heading": "(preamble)",
            "section_index": 0,
            "votes": 5,
            "description": "The burgomaster's son.",
        }

    def test_a_node_without_a_description_omits_the_property(self):
        nodes, _, _ = plan_write([node("Church")], [], gazetteer("Church"), SLUG)
        assert "description" not in nodes[0].properties

    def test_edge_layer_is_derived_from_the_layer_map(self):
        _, edges, _ = plan_write(
            [node("Ismark", "NPC"), node("Ireena", "NPC")],
            [edge("Ismark", "Ireena", "RELATED_TO")],
            gazetteer("Ismark", "Ireena"),
            SLUG,
        )
        assert edges[0].properties["layer"] == Layer.SOCIAL.value

    def test_an_edge_type_with_no_layer_carries_none(self):
        """LAYER_MAP maps some types explicitly to None: not a surface."""
        _, edges, _ = plan_write(
            [node("Ismark", "NPC"), node("Church")],
            [edge("Ismark", "Church", "OCCURRED_AT")],
            gazetteer("Ismark", "Church"),
            SLUG,
        )
        assert "layer" not in edges[0].properties

    def test_derived_evidence_survives_to_the_graph(self):
        """`evidence == "derived from document structure"` is the ONLY thing
        distinguishing the deterministic layer from LLM output downstream."""
        _, edges, _ = plan_write(
            [node("Church"), node("Undercroft")],
            [
                edge(
                    "Undercroft",
                    "Church",
                    "LOCATED_IN",
                    evidence="derived from document structure",
                )
            ],
            gazetteer("Church", "Undercroft"),
            SLUG,
        )
        assert edges[0].properties["evidence"] == "derived from document structure"
        assert edges[0].properties["plane"] == CANON_PLANE

    def test_relationship_type_is_coerced_through_the_enum(self):
        _, edges, _ = plan_write(
            [node("Church"), node("Undercroft")],
            [edge("Undercroft", "Church", "LOCATED_IN")],
            gazetteer("Church", "Undercroft"),
            SLUG,
        )
        assert edges[0].rel_type is RelationshipType.LOCATED_IN

    def test_an_unknown_relationship_type_is_refused(self):
        """A rel type cannot be parameterized in Cypher, so an unchecked string
        would be interpolated into the query text. `check_edges` deliberately
        treats an unknown type as unchecked rather than violating, so this is
        the only thing standing between a corrupt artifact and the query."""
        with pytest.raises(ValueError, match="DEFENESTRATES"):
            plan_write(
                [node("Church"), node("Undercroft")],
                [edge("Undercroft", "Church", "DEFENESTRATES")],
                gazetteer("Church", "Undercroft"),
                SLUG,
            )


class TestChapterSlugIsAuthoritative:
    def test_the_requested_slug_overrides_the_artifacts_own(self):
        """The artifact's slug comes from the chapter title the extractor read;
        the loop discovers chapters by the corpus filename. When they disagree
        the caller's slug wins, because that is the one the graph is keyed on."""
        candidate = CandidateNode(
            name="Church", entity_type="LOCATION", chapter_slug="chapter-3-the-village-of-barovia"
        )
        nodes, _, _ = plan_write([candidate], [], gazetteer("Church"), SLUG)
        assert nodes[0].id.startswith(f"cos:{SLUG}:")
        assert nodes[0].properties["chapter_slug"] == SLUG


class TestReportTotals:
    def test_every_candidate_is_accounted_for(self):
        """Silent filtering has twice hidden a defect here for weeks."""
        nodes, edges, report = plan_write(
            [
                node("Ismark Kolyanovich", "NPC"),
                node("wooden bed", "ITEM"),
                node("Church", "LOCATION", section_heading="E5. Church"),
                node("Church", "LOCATION", section_heading="E5g. Undercroft"),
            ],
            [
                edge("Church", "Church"),
                edge("Church", "Ismark Kolyanovich", "LOCATED_IN"),
                edge("wooden bed", "Church", "LOCATED_IN"),
                edge("Ismark Kolyanovich", "Church", "LOCATED_IN"),
                edge("Ismark Kolyanovich", "Church", "LOCATED_IN"),
            ],
            gazetteer("Ismark Kolyanovich"),
            SLUG,
        )
        assert report.candidate_nodes == 4
        assert report.candidate_edges == 5
        assert (
            report.candidate_nodes
            - report.gazetteer_dropped
            - report.duplicate_nodes
            - report.unnameable
            == len(nodes)
            == report.written_nodes
        )
        assert (
            report.candidate_edges
            - report.self_loops
            - report.constraint_violations
            - report.dangling_edges
            - report.ambiguous_edges
            - report.duplicate_edges
            == len(edges)
            == report.written_edges
        )

    def test_a_node_whose_name_slugifies_to_nothing_is_dropped(self):
        nodes, _, report = plan_write([node("---")], [], gazetteer("---"), SLUG)
        assert report.unnameable == 1
        assert nodes == []
