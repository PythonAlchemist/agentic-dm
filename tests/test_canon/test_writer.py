"""The filter chain and id minting that decide what reaches Neo4j.

Nothing here touches a database: `plan_write` is a pure function of candidates,
a gazetteer and a chapter slug, which is what makes every drop rule assertable
without a live graph. The transactional half is pinned in
`test_write_canon_neo4j.py`.
"""

import logging

import pytest
from neo4j.exceptions import Neo4jError

from backend.canon.gazetteer import Gazetteer, GazetteerEntry
from backend.canon.models import CandidateEdge, CandidateNode
from backend.canon.structure import STRUCTURAL_EVIDENCE
from backend.canon.writer import (
    CANON_PLANE,
    WriteNode,
    _resolve_endpoint,
    ensure_schema,
    mint_id,
    plan_write,
    restrict_to_accepted,
)
from backend.graph.schema import EntityType, Layer, RelationshipType

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
    def test_an_unkeyed_id_carries_no_chapter(self):
        """One Madam Eva for the whole book, whichever chapter names her."""
        assert mint_id(SLUG, "Blood of the Vine Tavern") == "cos:blood-of-the-vine-tavern"

    def test_two_chapters_naming_one_entity_mint_one_id(self):
        assert mint_id("introduction", "Madam Eva") == mint_id(SLUG, "Madam Eva")

    def test_a_keyed_place_stays_chapter_and_key_scoped(self):
        """`K61a. Empty Cell` and `K62a. Empty Cell` are genuinely different rooms."""
        assert mint_id("castle-ravenloft", "Empty Cell", "K61a") == (
            "cos:castle-ravenloft:k61a-empty-cell"
        )

    def test_the_type_is_not_part_of_the_id(self):
        """A disputed type must dissolve into labels on ONE node, not two nodes."""
        assert mint_id(SLUG, "Barovia") == mint_id(SLUG, "Barovia")

    def test_planned_nodes_carry_the_minted_id(self):
        nodes, _, _ = plan_write([node("Ismark")], [], gazetteer("Ismark"), SLUG)
        assert [n.id for n in nodes] == ["cos:ismark"]


class TestDisputedType:
    """Two samples disagreeing about a type made two nodes, and every edge went
    to whichever one the extractor happened to name. One node with both labels
    dissolves the duplicate without picking a winner."""

    def test_a_disputed_type_is_one_node_carrying_both_types(self):
        nodes, _, report = plan_write(
            [node("Tatyana", "NPC"), node("Tatyana", "LORE")],
            [],
            gazetteer("Tatyana"),
            SLUG,
        )
        assert [n.id for n in nodes] == ["cos:tatyana"]
        assert nodes[0].entity_types == ("LORE", "NPC")
        assert report.duplicate_nodes == 1

    def test_both_types_become_labels(self):
        nodes, _, _ = plan_write(
            [node("Barovia", "LOCATION"), node("Barovia", "SETTING")],
            [],
            gazetteer("Barovia"),
            SLUG,
        )
        assert nodes[0].labels == ("LOCATION", "SETTING")

    def test_a_type_outside_the_canon_set_is_not_a_label(self):
        """Labels are interpolated into Cypher, so only CANON_ENTITY_TYPES may
        become one -- and a PC is a campaign-plane type, not a book's canon."""
        nodes, _, _ = plan_write([node("Ismark", "PC")], [], gazetteer("Ismark"), SLUG)
        assert nodes[0].labels == ()
        assert nodes[0].entity_types == ("PC",)

    def test_every_edge_reaches_the_one_node(self):
        nodes, edges, report = plan_write(
            [node("Ireena", "NPC"), node("Tatyana", "NPC"), node("Tatyana", "LORE")],
            [edge("Ireena", "Tatyana", "IDENTITY_OF")],
            gazetteer("Ireena", "Tatyana"),
            SLUG,
        )
        assert report.ambiguous_edges == 0
        assert [e.target_id for e in edges] == ["cos:tatyana"]
        assert sorted(n.id for n in nodes) == ["cos:ireena", "cos:tatyana"]


class TestWhatLandsOnTheNode:
    def test_the_type_is_not_a_property(self):
        """Labels are the single source of truth for type; a scalar property
        beside them cannot even represent the disputed case."""
        nodes, _, _ = plan_write([node("Ismark", "NPC")], [], gazetteer("Ismark"), SLUG)
        assert "entity_type" not in nodes[0].properties

    def test_the_chapter_is_not_a_property_either(self):
        """A globally unique node has no one chapter -- it has MENTIONED_IN edges."""
        nodes, _, _ = plan_write(
            [node("Ismark", "NPC", section_heading="E1. Mansion", section_index=2)],
            [],
            gazetteer("Ismark"),
            SLUG,
        )
        props = nodes[0].properties
        assert "chapter_slug" not in props
        assert "section_heading" not in props
        assert "section_index" not in props

    def test_the_appearance_carries_the_section(self):
        nodes, _, _ = plan_write(
            [node("Ismark", "NPC", section_heading="E1. Mansion", section_index=2)],
            [],
            gazetteer("Ismark"),
            SLUG,
        )
        assert nodes[0].appearance == {
            "section_heading": "E1. Mansion",
            "section_index": 2,
        }


class TestKeyedIds:
    """A keyed place resolves to (book, chapter, key), never to its name.

    Chapter 4 holds `Closet` x2 and `Empty Cell` x3 as genuinely distinct rooms.
    Chapter scoping does not separate them -- they are in ONE chapter -- so the
    key has to be in the id or the book loses two of the three cells.
    """

    def test_a_keyed_place_carries_its_key_in_its_id(self):
        nodes, _, _ = plan_write(
            [node("Undercroft", section_heading="E5g. Undercroft", section_index=7)],
            [],
            gazetteer(),
            SLUG,
        )
        assert [n.id for n in nodes] == ["cos:the-village-of-barovia:e5g-undercroft"]

    def test_an_entity_the_book_does_not_key_keeps_the_plain_form(self):
        nodes, _, _ = plan_write(
            [node("Ismark Kolyanovich", "NPC", section_heading="(preamble)", section_index=0)],
            [],
            gazetteer("Ismark Kolyanovich"),
            SLUG,
        )
        assert [n.id for n in nodes] == ["cos:ismark-kolyanovich"]

    def test_two_same_named_rooms_in_one_chapter_are_two_nodes(self):
        """`K61a. Empty Cell` and `K62a. Empty Cell` are different rooms."""
        nodes, _, report = plan_write(
            [
                node("Empty Cell", section_heading="K61a. Empty Cell", section_index=1),
                node("Empty Cell", section_heading="K62a. Empty Cell", section_index=3),
            ],
            [],
            gazetteer(),
            SLUG,
        )
        assert report.duplicate_nodes == 0
        assert sorted(n.id for n in nodes) == [
            "cos:the-village-of-barovia:k61a-empty-cell",
            "cos:the-village-of-barovia:k62a-empty-cell",
        ]

    def test_a_mention_from_elsewhere_joins_the_room_the_book_keys(self):
        """A name the chapter keys exactly once is that room wherever it is
        mentioned -- otherwise the mention would mint a second Undercroft."""
        nodes, _, report = plan_write(
            [
                node("Undercroft", section_heading="E5g. Undercroft", section_index=7),
                node("Undercroft", section_heading="E5a. Hall", section_index=3),
            ],
            [],
            gazetteer(),
            SLUG,
        )
        assert report.duplicate_nodes == 1
        assert [n.id for n in nodes] == ["cos:the-village-of-barovia:e5g-undercroft"]

    def test_a_name_two_sections_key_mentioned_from_neither_is_dropped(self):
        """`Empty Cell` in prose could be K61a's or K62a's. Picking invents a room."""
        nodes, _, report = plan_write(
            [
                node("Empty Cell", section_heading="K61a. Empty Cell", section_index=1),
                node("Empty Cell", section_heading="K62a. Empty Cell", section_index=3),
                node("Empty Cell", section_heading="Approaching the Dungeon", section_index=5),
            ],
            [],
            gazetteer(),
            SLUG,
        )
        assert report.undecidable_keyed == 1
        assert len(nodes) == 2
        assert "LOCATION Empty Cell (k61a/k62a)" in report.dropped_undecidable_keyed

    def test_both_dungeons_keep_their_own_cell(self):
        """`North Dungeon CONTAINS Empty Cell` and `South Dungeon CONTAINS Empty
        Cell` are both real within one chapter. The section an edge was derived
        from says which cell it means.

        `Skeleton` sits in K61a alongside the cell, so the section narrowing has
        to select the room the section KEYS rather than everything extracted
        from that section -- a section-wide narrowing would hand `Empty Cell`
        two candidates again and lose the edge to ambiguity.
        """
        _, edges, report = plan_write(
            [
                node("North Dungeon", section_heading="K61. North Dungeon", section_index=0),
                node("Empty Cell", section_heading="K61a. Empty Cell", section_index=1),
                node("Skeleton", "MONSTER", section_heading="K61a. Empty Cell", section_index=1),
                node("South Dungeon", section_heading="K62. South Dungeon", section_index=2),
                node("Empty Cell", section_heading="K62a. Empty Cell", section_index=3),
            ],
            [
                edge("North Dungeon", "Empty Cell", "CONTAINS", section_index=1),
                edge("South Dungeon", "Empty Cell", "CONTAINS", section_index=3),
            ],
            gazetteer("Skeleton"),
            SLUG,
        )
        assert report.ambiguous_edges == 0
        assert [(e.source_id.split(":")[-1], e.target_id.split(":")[-1]) for e in edges] == [
            ("k61-north-dungeon", "k61a-empty-cell"),
            ("k62-south-dungeon", "k62a-empty-cell"),
        ]


class TestKeyedProvenance:
    """`section_heading` must name the section the book KEYS a room under.

    First-candidate-wins alone records whichever section first mentioned it, so
    a reader looking up the Chapel is sent to the Hall.
    """

    def test_the_keying_section_wins_over_an_earlier_mention(self):
        nodes, _, _ = plan_write(
            [
                node("Chapel", section_heading="E5a. Hall", section_index=3),
                node("Chapel", section_heading="E5f. Chapel", section_index=8),
            ],
            [],
            gazetteer(),
            SLUG,
        )
        assert [n.section_heading for n in nodes] == ["E5f. Chapel"]
        assert [n.section_index for n in nodes] == [8]

    def test_the_keying_section_still_wins_when_it_comes_first(self):
        nodes, _, _ = plan_write(
            [
                node("Chapel", section_heading="E5f. Chapel", section_index=8),
                node("Chapel", section_heading="E5a. Hall", section_index=3),
            ],
            [],
            gazetteer(),
            SLUG,
        )
        assert [n.section_heading for n in nodes] == ["E5f. Chapel"]

    def test_the_heading_spelling_wins_over_a_prose_mention(self):
        """The lowercase `burgomaster's mansion` in the graph came from prose
        beating the `E4.` heading. Canon should carry the book's own casing."""
        nodes, _, _ = plan_write(
            [
                node(
                    "burgomaster's mansion",
                    section_heading="Approaching the Village",
                    section_index=1,
                ),
                node(
                    "Burgomaster's Mansion",
                    section_heading="E4. Burgomaster's Mansion",
                    section_index=6,
                ),
            ],
            [],
            gazetteer(),
            SLUG,
        )
        assert [n.name for n in nodes] == ["Burgomaster's Mansion"]
        assert [n.section_heading for n in nodes] == ["E4. Burgomaster's Mansion"]

    def test_an_apostrophe_variant_joins_the_room_rather_than_minting_one(self):
        """Found in the graph, not in a fixture.

        The DDB corpus keeps the book's U+2019 while the extractor sometimes
        emits an ASCII quote. Matching keyed places on folded TEXT let the ASCII
        spelling miss its own heading, take the unkeyed id, and stand in the
        graph as a second Bildrath's Mercantile. Keyed places match on the slug,
        which is what the id is minted from, so anything that would mint one id
        is one place.
        """
        nodes, _, report = plan_write(
            [
                node(
                    "Bildrath's Mercantile",  # ASCII quote, from the extractor
                    section_heading="E1. Bildrath’s Mercantile",
                    section_index=2,
                ),
                node(
                    "Bildrath’s Mercantile",  # U+2019, as the book spells it
                    section_heading="E1. Bildrath’s Mercantile",
                    section_index=2,
                ),
            ],
            [],
            gazetteer(),
            SLUG,
        )
        assert report.duplicate_nodes == 1
        assert [n.id for n in nodes] == [
            "cos:the-village-of-barovia:e1-bildrath-s-mercantile"
        ]
        # ...and canon carries the book's typography, not the extractor's.
        assert nodes[0].name == "Bildrath’s Mercantile"

    def test_an_unkeyed_entity_keeps_first_candidate_wins(self):
        """Nothing keys an NPC, so the earliest mention stays the provenance."""
        nodes, _, _ = plan_write(
            [
                node("Ismark", "NPC", section_heading="(preamble)", section_index=0),
                node("Ismark", "NPC", section_heading="E2. Blood of the Vine", section_index=4),
            ],
            [],
            gazetteer("Ismark"),
            SLUG,
        )
        assert [n.section_heading for n in nodes] == ["(preamble)"]


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
            (mint_id(SLUG, "Trapdoor"), mint_id(SLUG, "Undercroft"))
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


def cell(entity_type: str, key: str) -> CandidateNode:
    """One of the chapter's two same-named keyed rooms."""
    section = {"K61a": 1, "K62a": 3}[key]
    return node(
        "Empty Cell", entity_type, section_heading=f"{key}. Empty Cell", section_index=section
    )


class TestAmbiguousEndpoints:
    """A name answered by two surviving nodes of different types.

    A DISPUTED TYPE NO LONGER PRODUCES THIS. `Tatyana` typed NPC by one sample
    and LORE by four is now one node wearing both labels, because the type left
    the id. What remains is the case the key exists for: the chapter keys `Empty
    Cell` at both K61a and K62a, they are genuinely two rooms, and an edge
    naming `Empty Cell` from a third section has two nodes it could mean. The
    domain/range table settles it when it admits exactly one of them, and
    nothing settles it otherwise.
    """

    def test_the_only_reading_the_ontology_permits_is_taken(self):
        """`KNOWS` admits only animates, so the cell typed LOCATION cannot
        stand there. This is the edge the whole reveal-filter design rests on."""
        nodes, edges, report = plan_write(
            [cell("LOCATION", "K61a"), cell("MONSTER", "K62a"), node("Ireena", "NPC")],
            [edge("Ireena", "Empty Cell", "KNOWS", section_index=9)],
            gazetteer("Ireena"),
            SLUG,
        )
        assert len(nodes) == 3
        assert report.ambiguous_edges == 0
        assert report.endpoint_resolved == 1
        assert [e.target_id for e in edges] == [mint_id(SLUG, "Empty Cell", "K62a")]

    def test_a_resolved_edge_is_stamped(self):
        """An edge whose endpoint was CHOSEN to satisfy the constraint table
        will always satisfy it afterwards, so the check is vacuous on exactly
        these. Acceptable -- but it must be visible, not silent."""
        _, edges, _ = plan_write(
            [cell("LOCATION", "K61a"), cell("MONSTER", "K62a"), node("Ireena", "NPC")],
            [edge("Ireena", "Empty Cell", "KNOWS", section_index=9)],
            gazetteer("Ireena"),
            SLUG,
        )
        assert edges[0].endpoint_resolved == "constraint"
        assert edges[0].properties["endpoint_resolved"] == "constraint"

    def test_an_unambiguous_edge_carries_no_resolution_stamp(self):
        """Otherwise every edge would look like one the table had to rescue."""
        _, edges, report = plan_write(
            [node("Ireena", "NPC"), node("Ismark", "NPC")],
            [edge("Ismark", "Ireena", "RELATED_TO")],
            gazetteer("Ireena", "Ismark"),
            SLUG,
        )
        assert report.endpoint_resolved == 0
        assert edges[0].endpoint_resolved == ""
        assert "endpoint_resolved" not in edges[0].properties

    def test_the_source_side_resolves_too(self):
        """`GUARDS`'s domain is agents only, so the cell typed LOCATION cannot
        be the one standing watch."""
        _, edges, report = plan_write(
            [cell("LOCATION", "K61a"), cell("MONSTER", "K62a"), node("Ireena", "NPC")],
            [edge("Empty Cell", "Ireena", "GUARDS", section_index=9)],
            gazetteer("Ireena"),
            SLUG,
        )
        assert report.endpoint_resolved == 1
        assert [e.source_id for e in edges] == [mint_id(SLUG, "Empty Cell", "K62a")]

    def test_two_candidates_that_both_satisfy_settle_nothing(self):
        """`KNOWS` admits both cells alike, so the table cannot say which one
        Ireena is acquainted with."""
        _, edges, report = plan_write(
            [cell("MONSTER", "K61a"), cell("MONSTER", "K62a"), node("Ireena", "NPC")],
            [edge("Ireena", "Empty Cell", "KNOWS", section_index=9)],
            gazetteer("Ireena"),
            SLUG,
        )
        assert report.endpoint_resolved == 0
        assert report.ambiguous_edges == 1
        assert edges == []
        assert "Ireena -KNOWS-> Empty Cell" in report.dropped_ambiguous

    def test_no_candidate_satisfying_settles_nothing(self):
        """Tested on the helper, because `plan_write` cannot reach it.

        An edge only arrives here having already passed `check_edges`, and that
        passes only if at least one of the name's types fits -- so for a
        constrained relationship the zero case is unreachable from above. The
        branch is kept because zero and two-or-more must behave identically,
        and a reader should not have to prove the unreachability to trust it.
        """
        by_id = {
            "a": WriteNode(id="a", name="Barovia", entity_types=("LOCATION",), chapter_slug=SLUG),
            "b": WriteNode(id="b", name="Barovia", entity_types=("SETTING",), chapter_slug=SLUG),
        }
        assert _resolve_endpoint({"a", "b"}, by_id, frozenset({EntityType.FACTION})) == (
            None,
            False,
        )

    def test_a_relationship_with_no_domain_range_entry_settles_nothing(self):
        """`OCCURRED_AT` is a runtime edge with no row in the table, so there
        is nothing to resolve WITH -- and a resolution rule that guessed in its
        absence would be back to manufacturing assertions."""
        _, edges, report = plan_write(
            [cell("LOCATION", "K61a"), cell("MONSTER", "K62a"), node("Ismark", "NPC")],
            [edge("Ismark", "Empty Cell", "OCCURRED_AT", section_index=9)],
            gazetteer("Ismark"),
            SLUG,
        )
        assert report.endpoint_resolved == 0
        assert report.ambiguous_edges == 1
        assert edges == []

    def test_an_untyped_candidate_is_never_the_unique_answer(self):
        """`check_edges` treats an unknown type as unchecked, which is right for
        "is this legal" and wrong for "which of these two is meant"."""
        _, edges, report = plan_write(
            [cell("MONSTER", "K61a"), cell("BESTIARY", "K62a"), node("Ireena", "NPC")],
            [edge("Ireena", "Empty Cell", "KNOWS", section_index=9)],
            gazetteer("Ireena"),
            SLUG,
        )
        # K61a is the one satisfying candidate; the unknown type is not a rival.
        assert report.endpoint_resolved == 1
        assert [e.target_id for e in edges] == [mint_id(SLUG, "Empty Cell", "K61a")]

    def test_two_identical_resolved_candidates_are_counted_once(self):
        """The resolved list is what downstream reads to know where the
        constraint check is vacuous. A duplicate candidate that collapses into
        one written edge must not leave a phantom entry naming an edge that
        exists once."""
        _, edges, report = plan_write(
            [cell("LOCATION", "K61a"), cell("MONSTER", "K62a"), node("Ireena", "NPC")],
            [
                edge("Ireena", "Empty Cell", "KNOWS", section_index=9),
                edge("Ireena", "Empty Cell", "KNOWS", section_index=11),
            ],
            gazetteer("Ireena"),
            SLUG,
        )
        assert report.duplicate_edges == 1
        assert len(edges) == 1
        assert report.endpoint_resolved == 1
        assert len(report.resolved_endpoints) == 1

    def test_resolutions_are_counted_apart_from_drops(self):
        nodes, edges, report = plan_write(
            [
                cell("LOCATION", "K61a"),
                cell("MONSTER", "K62a"),
                node("Ireena", "NPC"),
                node("Closet", "LOCATION", section_heading="K60a. Closet", section_index=0),
                node("Closet", "LOCATION", section_heading="K60b. Closet", section_index=2),
            ],
            [
                edge("Ireena", "Empty Cell", "KNOWS", section_index=9),
                edge("Ireena", "Closet", "TRAVELED_TO", section_index=9),
            ],
            gazetteer("Ireena"),
            SLUG,
        )
        assert report.endpoint_resolved == 1
        assert report.ambiguous_edges == 1
        assert report.written_edges == 1
        assert len(edges) == 1


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
            "plane": CANON_PLANE,
            "votes": 5,
            "description": "The burgomaster's son.",
            # An unkeyed NPC with no accepted edge attached: nothing
            # deterministic vouches for it.
            "status": "proposed",
        }
        # The type is a LABEL and the chapter is an EDGE; neither is a property.
        assert nodes[0].labels == ("NPC",)
        assert nodes[0].appearance == {"section_heading": "(preamble)", "section_index": 0}

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
            name="Church",
            entity_type="LOCATION",
            chapter_slug="chapter-3-the-village-of-barovia",
            section_heading="E5. Church",
            section_index=1,
        )
        nodes, _, _ = plan_write([candidate], [], gazetteer("Church"), SLUG)
        # A keyed place is scoped to a chapter, and it is the caller's slug in
        # the id -- and the caller's chapter that the appearance will point at.
        assert nodes[0].id == f"cos:{SLUG}:e5-church"
        assert nodes[0].chapter_slug == SLUG


class TestEnsureSchema:
    """A schema statement that fails for an unexpected reason must be audible.

    Neo4j is not reachable from these tests, so the session is a stub whose
    `run` raises what the driver would raise. That is the failure under test --
    not the database.
    """

    class Session:
        def __init__(self, error: Exception | None) -> None:
            self.error = error
            self.statements: list[str] = []

        def run(self, statement: str):
            self.statements.append(statement)
            if self.error is not None:
                raise self.error

    class Failure(Neo4jError):
        """A driver error with a chosen code. `Neo4jError.code` is a read-only
        property, so a subclass is the only way to stand one up by hand."""

        def __init__(self, code: str, message: str) -> None:
            super().__init__(message)
            self._code = code
            self._message = message

        @property
        def code(self) -> str:
            return self._code

        @property
        def message(self) -> str:
            return self._message

    def test_already_exists_is_silent(self, caplog):
        session = self.Session(
            self.Failure(
                "Neo.ClientError.Schema.EquivalentSchemaRuleAlreadyExists",
                "An equivalent constraint already exists",
            )
        )
        with caplog.at_level(logging.WARNING):
            ensure_schema(session)
        assert session.statements, "no schema statement was attempted"
        assert caplog.records == []

    def test_an_unexpected_neo4j_error_is_logged_with_its_statement(self, caplog):
        session = self.Session(
            self.Failure("Neo.ClientError.Security.Unauthorized", "Unable to authenticate")
        )
        with caplog.at_level(logging.WARNING):
            ensure_schema(session)
        assert caplog.records, "an unexpected schema failure was swallowed"
        assert "Unable to authenticate" in caplog.text

    def test_a_non_neo4j_error_is_not_swallowed_at_all(self):
        """A bad URI or a typo raises TypeError/AttributeError, not Neo4jError,
        and a bare `except Exception` would hide it until the write failed."""
        session = self.Session(RuntimeError("driver is closed"))
        with pytest.raises(RuntimeError, match="driver is closed"):
            ensure_schema(session)


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
            - report.undecidable_keyed
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


DERIVED = {"evidence": STRUCTURAL_EVIDENCE}


class TestEdgeStatus:
    """The trust split, which is the whole point of the stage.

    A hand read of all 30 LLM edges in the live chapter-3 graph found about a
    third wrong -- `Ismark OPPOSES Ireena`, who is her brother -- while all 37
    deterministically derived edges were sound. Until this stamp existed, a
    query could not tell the two apart.
    """

    def test_a_derived_edge_is_accepted(self):
        _, edges, _ = plan_write(
            [node("Church"), node("Undercroft")],
            [edge("Undercroft", "Church", "LOCATED_IN", **DERIVED)],
            gazetteer("Church", "Undercroft"),
            SLUG,
        )

        assert [e.status for e in edges] == ["accepted"]
        assert edges[0].properties["status"] == "accepted"

    def test_an_llm_edge_is_proposed(self):
        _, edges, _ = plan_write(
            [node("Ismark", "NPC"), node("Ireena", "NPC")],
            [edge("Ismark", "Ireena", "OPPOSES", evidence="Ismark stands against his sister.")],
            gazetteer("Ismark", "Ireena"),
            SLUG,
        )

        assert [e.status for e in edges] == ["proposed"]
        assert edges[0].properties["status"] == "proposed"

    def test_an_edge_with_no_evidence_at_all_is_proposed(self):
        """Acceptance is EARNED from the structural marker. Absent evidence is
        not evidence of derivation, and defaulting the other way would promote
        every edge that merely lost its provenance."""
        _, edges, _ = plan_write(
            [node("Ismark", "NPC"), node("Ireena", "NPC")],
            [edge("Ismark", "Ireena", "KNOWS")],
            gazetteer("Ismark", "Ireena"),
            SLUG,
        )

        assert [e.status for e in edges] == ["proposed"]

    def test_the_counts_split_and_add_back_up(self):
        _, edges, report = plan_write(
            [node("Church"), node("Undercroft"), node("Ismark", "NPC")],
            [
                edge("Church", "Undercroft", "CONTAINS", **DERIVED),
                edge("Ismark", "Church", "OWNS", evidence="Ismark owns the church."),
            ],
            gazetteer("Church", "Undercroft", "Ismark"),
            SLUG,
        )

        assert report.accepted_edges == 1
        assert report.proposed_edges == 1
        assert report.accepted_edges + report.proposed_edges == len(edges) == report.written_edges


class TestNodeStatus:
    def test_a_node_an_accepted_edge_attaches_to_is_accepted(self):
        nodes, _, _ = plan_write(
            [node("Church"), node("Undercroft")],
            [edge("Undercroft", "Church", "LOCATED_IN", **DERIVED)],
            gazetteer("Church", "Undercroft"),
            SLUG,
        )

        assert {n.name: n.status for n in nodes} == {
            "Church": "accepted",
            "Undercroft": "accepted",
        }

    def test_an_orphan_llm_node_is_proposed(self):
        """Nothing deterministic vouches for it: it is a name a model emitted."""
        nodes, _, report = plan_write(
            [node("Mad Mary's Townhouse"), node("Gertruda", "NPC")],
            [
                edge(
                    "Mad Mary's Townhouse",
                    "Gertruda",
                    "CONTAINS",
                    evidence="Mad Mary's daughter is in the townhouse.",
                )
            ],
            gazetteer("Mad Mary's Townhouse", "Gertruda"),
            SLUG,
        )

        # The hook of the chapter is that Gertruda is MISSING; the edge is false
        # and the node it drags in is vouched for by nothing.
        assert {n.status for n in nodes} == {"proposed"}
        assert report.proposed_nodes == 2
        assert report.accepted_nodes == 0

    def test_a_keyed_place_is_accepted_even_with_no_edges_at_all(self):
        """`E5g. Undercroft` is a heading in the book, not a model's opinion."""
        nodes, _, _ = plan_write(
            [node("Undercroft", section_heading="E5g. Undercroft", section_index=7)],
            [],
            gazetteer(),
            SLUG,
        )

        assert [n.status for n in nodes] == ["accepted"]

    def test_acceptance_travels_in_both_directions_along_an_accepted_edge(self):
        """A derived edge is evidence about both endpoints, not only its source.
        The unkeyed endpoint here is accepted because the document's own nesting
        put it there."""
        nodes, _, _ = plan_write(
            [
                node("Church", section_heading="E5. Church", section_index=1),
                node("Undercroft"),
            ],
            [edge("Church", "Undercroft", "CONTAINS", **DERIVED)],
            gazetteer("Undercroft"),
            SLUG,
        )

        assert {n.name: n.status for n in nodes} == {
            "Church": "accepted",
            "Undercroft": "accepted",
        }

    def test_a_node_status_lands_on_the_written_properties(self):
        nodes, _, _ = plan_write(
            [node("Gertruda", "NPC")], [], gazetteer("Gertruda"), SLUG
        )

        assert nodes[0].properties["status"] == "proposed"


class TestMutualExclusion:
    """Contradictions are recorded, never resolved by guessing.

    There is no oracle: recall cannot rank extractors, and a wiki oracle failed
    because 8 of the 13 core NPCs have no page. Human review at gate G3 is the
    only precision gate that exists.
    """

    def ireena_and_tatyana(self, *rel_types: str) -> tuple:
        return plan_write(
            [node("Ireena Kolyana", "NPC"), node("Tatyana", "NPC")],
            [
                edge("Ireena Kolyana", "Tatyana", rel, evidence=f"{rel} evidence")
                for rel in rel_types
            ],
            gazetteer("Ireena Kolyana", "Tatyana"),
            SLUG,
        )

    def test_two_proposed_edges_in_conflict_are_both_written(self):
        """Neither dropped, neither demoted, and the conflict recorded on both."""
        _, edges, report = self.ireena_and_tatyana("IDENTITY_OF", "RELATED_TO")

        assert len(edges) == 2
        assert [e.status for e in edges] == ["proposed", "proposed"]
        assert [e.conflict for e in edges] == ["RELATED_TO", "IDENTITY_OF"]
        assert report.exclusive_conflicts == 1
        assert report.conflicted_edges == 0
        assert report.written_edges == 2

    def test_the_conflict_is_named_in_the_report(self):
        _, _, report = self.ireena_and_tatyana("IDENTITY_OF", "RELATED_TO")

        assert len(report.conflicts) == 1
        assert "IDENTITY_OF|RELATED_TO" in report.conflicts[0]
        assert "ireena-kolyana" in report.conflicts[0]

    def test_the_conflict_lands_on_the_edge_in_the_graph(self):
        """A reviewer filters on this property; recomputing it from a dump is
        not a review queue."""
        _, edges, _ = self.ireena_and_tatyana("IDENTITY_OF", "RELATED_TO")

        assert edges[0].properties["conflict"] == "RELATED_TO"

    def test_an_ordinary_edge_carries_no_conflict_property_at_all(self):
        """An empty string on every edge would bury the handful that matter."""
        _, edges, _ = self.ireena_and_tatyana("KNOWS")

        assert "conflict" not in edges[0].properties

    def test_an_accepted_edge_beats_a_proposed_one(self):
        """The single exception to not choosing: the accepted layer is derived
        from the document's structure and cannot hallucinate."""
        _, edges, report = plan_write(
            [node("Church"), node("Undercroft")],
            [
                edge("Church", "Undercroft", "CONTAINS", **DERIVED),
                edge("Church", "Undercroft", "LOCATED_IN", evidence="the church lies below it"),
            ],
            gazetteer("Church", "Undercroft"),
            SLUG,
        )

        assert [e.status for e in edges] == ["accepted", "conflicted"]
        assert report.conflicted_edges == 1
        assert len(edges) == 2  # demoted, never deleted

    def test_the_inverse_pair_the_deriver_emits_is_not_a_conflict(self):
        """`Church CONTAINS Undercroft` with `Undercroft LOCATED_IN Church` is
        the ordinary inverse pair, and the derived layer emits it in bulk."""
        _, edges, report = plan_write(
            [node("Church"), node("Undercroft")],
            [
                edge("Church", "Undercroft", "CONTAINS", **DERIVED),
                edge("Undercroft", "Church", "LOCATED_IN", **DERIVED),
            ],
            gazetteer("Church", "Undercroft"),
            SLUG,
        )

        assert report.exclusive_conflicts == 0
        assert [e.status for e in edges] == ["accepted", "accepted"]
        assert all(e.conflict == "" for e in edges)

    def test_a_conflict_between_two_proposed_edges_confers_no_acceptance(self):
        """A contradiction is not evidence. Two proposed edges disagreeing about
        the same ordered pair leaves both of them, and both endpoints, unvetted
        -- if anything it is a reason to trust them less."""
        nodes, _, _ = plan_write(
            [node("Ismark", "NPC"), node("Ireena", "NPC"), node("Tatyana", "NPC")],
            [
                edge("Ismark", "Ireena", "IDENTITY_OF", evidence="one and the same"),
                edge("Ismark", "Ireena", "RELATED_TO", evidence="brother and sister"),
            ],
            gazetteer("Ismark", "Ireena", "Tatyana"),
            SLUG,
        )

        assert {n.status for n in nodes} == {"proposed"}

    def test_a_conflicted_edges_endpoints_are_accepted_by_the_edge_that_beat_it(self):
        """Not a contradiction of the rule -- a consequence of it.

        A `conflicted` edge is only ever created by an ACCEPTED edge between the
        SAME ordered endpoints, so those endpoints are always accepted through
        the winner. Whether `_mark_node_status` reads `== ACCEPTED` or
        `!= PROPOSED` is therefore unobservable, and the strict form is written
        because it states the intent rather than because a test can catch it.
        """
        nodes, edges, _ = plan_write(
            [node("Church"), node("Undercroft")],
            [
                edge("Church", "Undercroft", "CONTAINS", **DERIVED),
                edge("Church", "Undercroft", "LOCATED_IN", evidence="the church lies below it"),
            ],
            gazetteer("Church", "Undercroft"),
            SLUG,
        )

        assert [e.status for e in edges] == ["accepted", "conflicted"]
        assert {n.status for n in nodes} == {"accepted"}


class TestAcceptedOnly:
    def plan(self) -> tuple:
        return plan_write(
            [
                node("Church", section_heading="E5. Church", section_index=1),
                node("Undercroft"),
                node("Gertruda", "NPC"),
            ],
            [
                edge("Church", "Undercroft", "CONTAINS", **DERIVED),
                edge("Church", "Gertruda", "CONTAINS", evidence="Gertruda is in the church."),
            ],
            gazetteer("Church", "Undercroft", "Gertruda"),
            SLUG,
        )

    def test_proposed_edges_are_omitted(self):
        nodes, edges, _ = self.plan()

        kept_nodes, kept_edges = restrict_to_accepted(nodes, edges)

        assert [e.rel_type for e in kept_edges] == [RelationshipType.CONTAINS]
        assert all(e.status == "accepted" for e in kept_edges)
        assert len(edges) == 2  # the plan itself is untouched

    def test_a_node_left_with_nothing_attached_is_omitted(self):
        nodes, edges, _ = self.plan()

        kept_nodes, _ = restrict_to_accepted(nodes, edges)

        assert sorted(n.name for n in kept_nodes) == ["Church", "Undercroft"]

    def test_a_keyed_node_with_no_accepted_edge_is_omitted_too(self):
        """Accepted in its own right, but writing an isolated node would give
        the loop's node-counting predicate a chapter that looks written."""
        nodes, edges, _ = plan_write(
            [node("Undercroft", section_heading="E5g. Undercroft", section_index=7)],
            [],
            gazetteer(),
            SLUG,
        )

        assert [n.status for n in nodes] == ["accepted"]
        assert restrict_to_accepted(nodes, edges) == ([], [])

    def test_a_conflicted_edge_is_omitted_with_the_rest_of_the_proposed(self):
        nodes, edges, _ = plan_write(
            [node("Church"), node("Undercroft")],
            [
                edge("Church", "Undercroft", "CONTAINS", **DERIVED),
                edge("Church", "Undercroft", "LOCATED_IN", evidence="below it"),
            ],
            gazetteer("Church", "Undercroft"),
            SLUG,
        )

        _, kept_edges = restrict_to_accepted(nodes, edges)

        assert [e.rel_type for e in kept_edges] == [RelationshipType.CONTAINS]
