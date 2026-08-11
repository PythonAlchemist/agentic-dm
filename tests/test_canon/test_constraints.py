"""Domain/range constraints: reject edges that are impossible by construction.

The pipeline has no automatic precision signal -- recall is monotone in candidate
count, so it cannot rank extractors. But a hand read of 30 chapter-4 edges found
16 false, and nine of those violate a TYPE constraint rather than a factual one
(`Chapel -LOCATED_IN-> Donavich`: a location inside a priest). Every candidate
already carries an `entity_type`, so those nine are free to catch.

Two properties matter more than the catching, and each has its own class here:

- `TestGoldenSet` -- the hand-authored seed is ground truth, so a table that
  rejects any golden edge is wrong about the ontology, not the other way round.
  It asserts `checked` too, because a table that typed nothing would score zero
  violations vacuously.
- `TestUntypedEndpointsAreUnchecked` -- `structure.py` emits edges whose endpoint
  has no node, and those derived edges are the one part of the output a
  fabrication check found clean. A check that treated "we could not type this"
  as "this is wrong" would fire hardest on the most reliable layer, which would
  be worse than no check at all.
"""

import pytest
import yaml

from backend.canon.constraints import (
    ConstraintReport,
    Violation,
    check_edges,
    enforce,
    format_report,
    report_edges,
)
from backend.canon.extract import layer_vocabulary
from backend.canon.models import CandidateEdge, CandidateNode
from backend.canon.seed_loader import SEED_DIR, extractable_subset
from backend.canon.structure import STRUCTURAL_EVIDENCE
from backend.graph.schema import (
    CANON_ENTITY_TYPES,
    RELATIONSHIP_DOMAIN_RANGE,
    EntityType,
    Layer,
    RelationshipType,
)
from backend.scripts.extract_canon import _known_sources, build_parser


def node(name: str, entity_type: str) -> CandidateNode:
    return CandidateNode(name=name, entity_type=entity_type)


def edge(source: str, rel_type: str, target: str, **kwargs) -> CandidateEdge:
    return CandidateEdge(source_name=source, rel_type=rel_type, target_name=target, **kwargs)


class TestTableTotality:
    def test_every_layer_type_has_a_domain_and_range(self):
        """A relationship type added to a layer must fail this until it is
        constrained -- iterates the layers and layer_vocabulary rather than a
        hardcoded list, exactly as the RELATIONSHIP_GLOSS totality test does, so
        this stays true as LAYER_MAP grows."""
        for layer in Layer:
            for value in layer_vocabulary(layer):
                assert RelationshipType(value) in RELATIONSHIP_DOMAIN_RANGE, (
                    f"{value} ({layer.value}) has no entry in RELATIONSHIP_DOMAIN_RANGE"
                )

    def test_no_entry_for_a_type_the_extractor_is_never_offered(self):
        """Structural and runtime edges are never extracted, so constraining
        them would assert an ontology nothing in this pipeline can violate."""
        offered = {RelationshipType(v) for layer in Layer for v in layer_vocabulary(layer)}

        assert set(RELATIONSHIP_DOMAIN_RANGE) == offered

    def test_every_constrained_type_is_a_canon_entity_type(self):
        """A domain naming PC or SPELL could never be satisfied: `_parse` drops
        any candidate outside CANON_ENTITY_TYPES before this check ever runs."""
        for rel, (domain, range_) in RELATIONSHIP_DOMAIN_RANGE.items():
            assert domain <= CANON_ENTITY_TYPES, f"{rel.value} domain"
            assert range_ <= CANON_ENTITY_TYPES, f"{rel.value} range"
            assert domain and range_, f"{rel.value} has an empty side"


def seed() -> dict:
    return yaml.safe_load((SEED_DIR / "village-of-barovia.yaml").read_text())


def as_candidates(data: dict) -> tuple[list[CandidateNode], list[CandidateEdge]]:
    """Seed ids stand in for names: the check resolves endpoints by name, and the
    seed's ids are unique where its names would need aliases to be."""
    return (
        [node(n["id"], n["entity_type"]) for n in data["nodes"]],
        [edge(e["source"], e["type"], e["target"]) for e in data["edges"]],
    )


class TestGoldenSet:
    """The measurement that decides the table. See the module docstring."""

    def test_no_golden_edge_violates_a_constraint(self):
        nodes, edges = as_candidates(seed())

        violations = check_edges(nodes, edges)

        assert [
            f"{v.source_name} -{v.rel_type}-> {v.target_name} ({v.reason})" for v in violations
        ] == []

    def test_every_golden_edge_is_actually_checked(self):
        """Without this, a table that typed nothing would pass the test above
        vacuously: zero violations because zero edges were ever examined."""
        nodes, edges = as_candidates(seed())

        report = report_edges(nodes, edges)

        assert report.checked == len(edges)
        assert report.unchecked == 0

    def test_both_endpoints_of_every_golden_edge_resolve_to_a_type(self):
        """`checked` only requires ONE typed endpoint, so it is not enough on its
        own. A seed edge with a typo'd `target` id would leave that endpoint
        unknown, still count as checked, and quietly stop exercising that row's
        range while the zero-violations test stayed green."""
        nodes, edges = as_candidates(seed())
        typed = {n.name for n in nodes if n.entity_type in {t.value for t in EntityType}}

        unresolved = sorted(
            f"{e.source_name} -{e.rel_type}-> {e.target_name}"
            for e in edges
            if e.source_name not in typed or e.target_name not in typed
        )

        assert unresolved == []

    @pytest.mark.parametrize("source", _known_sources(seed()))
    def test_no_violation_in_any_per_source_subset(self, source):
        """Sources come from the seed's own markers rather than a literal list,
        so a source added to the seed is covered without editing this file --
        and an empty subset (which would pass everything vacuously) cannot be
        parametrized in by mistake."""
        subset = extractable_subset(seed(), source)
        nodes, edges = as_candidates(subset)

        report = report_edges(nodes, edges)

        assert edges, f"{source} subset is empty"
        assert report.violations == []
        assert report.checked == len(edges)


# One satisfying triple per constrained relationship type. The coverage test
# below fails if a type is added to the table without a case here, so this list
# cannot silently fall behind LAYER_MAP.
VALID_CASES = [
    # Spatial
    ("LOCATION", "CONTAINS", "LOCATION"),
    ("LOCATION", "LOCATED_IN", "LOCATION"),
    ("LOCATION", "CONNECTED_TO", "LOCATION"),
    ("NPC", "TRAVELED_TO", "LOCATION"),
    # Social
    ("NPC", "KNOWS", "NPC"),
    ("NPC", "MEMBER_OF", "FACTION"),
    ("NPC", "OWNS", "LOCATION"),
    ("NPC", "RELATED_TO", "NPC"),
    ("MONSTER", "SERVES", "NPC"),
    ("NPC", "WIELDS", "ITEM"),
    ("NPC", "GUARDS", "NPC"),
    ("FACTION", "ALLIED_WITH", "FACTION"),
    ("NPC", "ENEMY_OF", "MONSTER"),
    ("MONSTER", "HOSTILE_TO", "NPC"),
    # Narrative
    ("NPC", "SEEKS", "QUEST"),
    ("NPC", "OPPOSES", "FACTION"),
    ("NPC", "IDENTITY_OF", "NPC"),
    ("QUEST", "OBJECTIVE_AT", "LOCATION"),
    ("NPC", "GAVE_QUEST", "QUEST"),
    ("NPC", "COMPLETED", "QUEST"),
    ("QUEST", "PREREQUISITE_OF", "QUEST"),
    ("ITEM", "RESOLVES_TO", "LOCATION"),
    ("MONSTER", "THREATENS", "LOCATION"),
]


class TestValidEdgesPass:
    """Over-firing is the failure that would make this check worse than nothing."""

    @pytest.mark.parametrize(("source_type", "rel_type", "target_type"), VALID_CASES)
    def test_a_valid_edge_passes(self, source_type, rel_type, target_type):
        nodes = [node("A", source_type), node("B", target_type)]

        assert check_edges(nodes, [edge("A", rel_type, "B")]) == []

    def test_every_constrained_type_has_a_valid_case(self):
        covered = {RelationshipType(rel) for _, rel, _ in VALID_CASES}

        assert covered == set(RELATIONSHIP_DOMAIN_RANGE)

    @pytest.mark.parametrize(
        ("source", "source_type", "rel_type", "target", "target_type"),
        [
            ("four wooden chests", "ITEM", "CONTAINS", "500 pp", "ITEM"),
            ("iron chest", "ITEM", "CONTAINS", "Strahd's family crest", "ITEM"),
            ("wardrobe", "ITEM", "CONTAINS", "dancing dress", "ITEM"),
            ("gemstones", "ITEM", "LOCATED_IN", "belt pouches", "ITEM"),
            ("Burgomaster", "NPC", "LOCATED_IN", "Coffin", "ITEM"),
        ],
    )
    def test_a_container_may_be_an_item(
        self, source, source_type, rel_type, target, target_type
    ):
        """The table's first proposal made every container a LOCATION, and the
        corpus is full of real treasure-in-a-chest facts it rejected: chapter 4
        alone has four `Treasure` sections. `LOCATION CONTAINS ITEM` was already
        legal, so refusing `ITEM CONTAINS ITEM` asserted that a coin may sit in a
        room but not in the chest standing in it."""
        nodes = [node(source, source_type), node(target, target_type)]

        assert check_edges(nodes, [edge(source, rel_type, target)]) == []

    def test_widening_the_container_types_does_not_readmit_a_person(self):
        """`Chapel LOCATED_IN Donavich` must still fail: an NPC is not a
        container, however item-like the corpus's keyed rooms are typed."""
        nodes = [node("Chapel", "LOCATION"), node("Donavich", "NPC")]

        violations = check_edges(nodes, [edge("Chapel", "LOCATED_IN", "Donavich")])

        assert [v.reason for v in violations] == ["range"]

    def test_a_whole_valid_chapter_yields_nothing(self):
        """Per-edge cases cannot catch cross-edge contamination -- a name typed
        by one edge's node leaking into another's lookup."""
        nodes = [
            node("Church of Barovia", "LOCATION"),
            node("Donavich", "NPC"),
            node("Doru", "NPC"),
            node("Village of Barovia", "LOCATION"),
        ]
        edges = [
            edge("Village of Barovia", "CONTAINS", "Church of Barovia"),
            edge("Donavich", "LOCATED_IN", "Church of Barovia"),
            edge("Doru", "LOCATED_IN", "Church of Barovia"),
            edge("Donavich", "RELATED_TO", "Doru"),
            edge("Donavich", "GUARDS", "Doru"),
        ]

        assert check_edges(nodes, edges) == []


# The nine type-impossible edges from the hand read of 30 chapter-4 edges, with
# the endpoint types the chapter-4 candidate set actually assigned them.
NINE_FALSE_EDGES = [
    ("Chapel", "LOCATION", "LOCATED_IN", "Donavich", "NPC", "range"),
    ("Dining Hall", "LOCATION", "LOCATED_IN", "invisible stalker", "MONSTER", "range"),
    ("grave", "LOCATION", "TRAVELED_TO", "Abbey", "LOCATION", "domain"),
    ("Castle Ravenloft", "LOCATION", "CONNECTED_TO", "Strahd", "NPC", "range"),
    ("Burgomaster's Mansion", "LOCATION", "OBJECTIVE_AT", "Ireena", "NPC", "both"),
    ("Rahadin", "NPC", "GAVE_QUEST", "Dining Hall", "LOCATION", "range"),
    ("Cyrus Belview", "NPC", "GAVE_QUEST", "Iron Chest", "ITEM", "range"),
    ("Guards' Post", "LOCATION", "GUARDS", "Skeleton", "MONSTER", "domain"),
    ("Arik Lorensk", "NPC", "MEMBER_OF", "Blood on the Vine", "LOCATION", "range"),
]


class TestTheNineFalseEdges:
    @pytest.mark.parametrize(
        ("source", "source_type", "rel_type", "target", "target_type", "reason"),
        NINE_FALSE_EDGES,
    )
    def test_each_is_flagged_with_the_right_reason(
        self, source, source_type, rel_type, target, target_type, reason
    ):
        nodes = [node(source, source_type), node(target, target_type)]

        violations = check_edges(nodes, [edge(source, rel_type, target)])

        assert len(violations) == 1
        assert violations[0].reason == reason
        assert violations[0].rel_type == rel_type
        assert violations[0].source_type == source_type
        assert violations[0].target_type == target_type
        assert violations[0].edge_index == 0

    def test_all_nine_are_caught_together(self):
        nodes = [
            node(name, entity_type)
            for source, source_type, _, target, target_type, _ in NINE_FALSE_EDGES
            for name, entity_type in ((source, source_type), (target, target_type))
        ]
        edges = [edge(s, rel, t) for s, _, rel, t, _, _ in NINE_FALSE_EDGES]

        assert len(check_edges(nodes, edges)) == 9

    def test_the_edge_index_locates_the_edge_in_the_input_list(self):
        nodes = [node("Chapel", "LOCATION"), node("Donavich", "NPC")]
        edges = [
            edge("Donavich", "LOCATED_IN", "Chapel"),
            edge("Donavich", "KNOWS", "Donavich"),
            edge("Chapel", "LOCATED_IN", "Donavich"),
        ]

        assert [v.edge_index for v in check_edges(nodes, edges)] == [2]


# One rejected edge per (relationship, side) of the table -- 46 sides in all.
#
# `VALID_CASES` above pins every row against being NARROWED. Nothing pinned them
# against being WIDENED, and widening a side to every canon entity type deletes
# that constraint outright. Swept exhaustively, 33 of the 46 sides could be
# deleted with the whole suite still green. That is the failure this codebase has
# hit repeatedly: someone silences a false positive by adding LOCATION to SERVES'
# range, the tests stay green, the violation count quietly drops, and the next
# hand read is drawn from a set the table stopped covering.
#
# A `both` case pins BOTH of its sides: widening either one changes the reason,
# which the assertion below reads.
#
# Cases are real candidate edges lifted from the chapter-3 and chapter-4
# artifacts wherever the corpus has one. The four marked INVENTED are the sides
# no artifact exercises -- COMPLETED appears in no extraction run at all.
NEGATIVE_CASES = [
    # --- Spatial ---
    # A place is not joined to a person by a passage.
    ("Donavich", "NPC", "CONNECTED_TO", "the cemetery", "LOCATION", "domain"),
    ("Castle Ravenloft", "LOCATION", "CONNECTED_TO", "Strahd", "NPC", "range"),
    # A person is not a container: the treasure is in the room, not in Strahd.
    ("Strahd von Zarovich", "NPC", "CONTAINS", "300 pp", "ITEM", "domain"),
    # A shop does not contain a rules table. LORE has no place to sit.
    ("Bildrath's Mercantile", "LOCATION", "CONTAINS", "Adventuring Gear table", "LORE", "range"),
    # Lore is not located anywhere; the text about it merely sits in a section.
    ("Strahd's ancestors", "LORE", "LOCATED_IN", "Hall of Heroes", "LOCATION", "domain"),
    # An event OCCURS somewhere -- a type the extractor is not offered, so the
    # model reaches for the nearest one it has.
    ("March of the Dead", "EVENT", "LOCATED_IN", "Cemetery", "LOCATION", "domain"),
    ("Chapel", "LOCATION", "LOCATED_IN", "Donavich", "NPC", "range"),
    # A graveyard does not travel.
    ("Graveyard", "LOCATION", "TRAVELED_TO", "Castle Ravenloft", "LOCATION", "domain"),
    ("Doru", "MONSTER", "TRAVELED_TO", "Donavich", "NPC", "range"),
    # --- Social ---
    ("Morninglord", "LORE", "ALLIED_WITH", "Ulmist Inquisition", "FACTION", "domain"),
    ("Ghostly Adventurers", "MONSTER", "ALLIED_WITH", "Castle Ravenloft", "LOCATION", "range"),
    # INVENTED: no artifact edge has a non-agent enemy on the source side.
    ("Castle Ravenloft", "LOCATION", "ENEMY_OF", "Strahd", "NPC", "domain"),
    ("Gustav Herrenghast", "NPC", "ENEMY_OF", "Icon of Ravenloft", "ITEM", "range"),
    # A room is not guarded by being a room, and a place does not stand watch.
    ("Amber Temple", "LOCATION", "GUARDS", "Tsolenka Pass", "LOCATION", "domain"),
    ("Strahd", "MONSTER", "GUARDS", "Amber Temple", "LORE", "range"),
    ("Barovia", "LOCATION", "HOSTILE_TO", "Strahd", "NPC", "domain"),
    ("Donavich", "NPC", "HOSTILE_TO", "Castle Ravenloft", "LOCATION", "range"),
    # A tavern is not acquainted with anyone.
    ("Blood of the Vine Tavern", "LOCATION", "KNOWS", "Ismark Kolyanovich", "NPC", "domain"),
    ("bats", "MONSTER", "KNOWS", "Castle Ravenloft", "LOCATION", "range"),
    # MEMBER_OF's group is a FACTION. A castle joins nothing, and a tavern is not
    # a group its barkeep belongs to.
    ("Tser Pool", "LOCATION", "MEMBER_OF", "Vistani", "FACTION", "domain"),
    ("Arik Lorensk", "NPC", "MEMBER_OF", "Blood of the Vine Tavern", "LOCATION", "range"),
    # A vintage does not own the winery that makes it -- an inverted OWNS.
    ("Champagne du le Stomp", "ITEM", "OWNS", "Wizard of Wines winery", "LOCATION", "domain"),
    # People are not property. Strahd SEEKS Ireena; he does not own her.
    ("Strahd", "NPC", "OWNS", "Ireena Kolyana", "NPC", "range"),
    ("Morgantha", "NPC", "OWNS", "Lucian Jarov", "NPC", "range"),
    # RELATED_TO is kin ONLY -- "parent, child, sibling, cousin, uncle, nephew".
    # Widening it to any agent readmits the group-membership noise MEMBER_OF and
    # SERVES exist for, and blunts the IDENTITY_OF / RELATED_TO contrast the
    # glosses were written to fix.
    ("Barovian witches", "FACTION", "RELATED_TO", "Strahd", "NPC", "domain"),
    ("Strahd", "NPC", "RELATED_TO", "Barovian witches", "FACTION", "range"),
    # A land does not serve, and a servant serves a master, not a building or a
    # musical instrument.
    ("Barovia", "SETTING", "SERVES", "Donavich", "NPC", "domain"),
    ("Pidwick", "NPC", "SERVES", "harp", "ITEM", "range"),
    # A chest carries nothing, and nobody wields a tower.
    ("iron chest", "ITEM", "WIELDS", "Strahd's family crest", "ITEM", "domain"),
    ("Prince Ariel du Plumette", "NPC", "WIELDS", "high tower", "LOCATION", "range"),
    # --- Narrative ---
    # INVENTED (both sides): COMPLETED appears in no extraction run on disk.
    ("Church of Barovia", "LOCATION", "COMPLETED", "Free Doru", "QUEST", "domain"),
    ("Ismark Kolyanovich", "NPC", "COMPLETED", "Blood on the Vine Tavern", "LOCATION", "range"),
    # A quest does not hand out quests, and the quest given is not a person.
    ("Convince Ireena to Open the Door", "QUEST", "GAVE_QUEST", "Ireena Kolyana", "NPC", "both"),
    ("Cyrus Belview", "NPC", "GAVE_QUEST", "Iron Chest", "ITEM", "range"),
    # IDENTITY_OF is one being under two names. A mansion is not a person's other
    # life, and a group is not one either.
    ("Burgomaster's Mansion", "LOCATION", "IDENTITY_OF", "Ireena Kolyana", "NPC", "domain"),
    ("Cats", "MONSTER", "IDENTITY_OF", "Witches in area K56", "FACTION", "range"),
    ("Masonry Wall", "ITEM", "OBJECTIVE_AT", "Castle's Wine Cellar", "LOCATION", "domain"),
    ("Escort Ireena to Vallaki", "QUEST", "OBJECTIVE_AT", "Ireena Kolyana", "NPC", "range"),
    ("Burgomaster's Mansion", "LOCATION", "OPPOSES", "Strahd", "NPC", "domain"),
    ("Donavich", "NPC", "OPPOSES", "E5g. Undercroft", "LOCATION", "range"),
    # PREREQUISITE_OF gates one happening on another; two priests gate nothing.
    ("Kolyan Indirovich", "NPC", "PREREQUISITE_OF", "Donavich", "NPC", "both"),
    # RESOLVES_TO collapses a canon fan-out. A tower is not a fan-out, and
    # INVENTED on the range side: no artifact edge resolves to a non-place.
    ("Morgatha", "NPC", "RESOLVES_TO", "Strahd", "NPC", "domain"),
    ("Tome of Strahd", "ITEM", "RESOLVES_TO", "Escort Ireena to Vallaki", "QUEST", "range"),
    # An event wants nothing, and a faction is not something to be obtained.
    ("March of the Dead", "EVENT", "SEEKS", "Strahd", "NPC", "domain"),
    ("Bildrath Cantemir", "NPC", "SEEKS", "Vistani", "FACTION", "range"),
    # A land does not endanger, and an event is not endangered.
    ("Barovia", "LOCATION", "THREATENS", "Strahd", "NPC", "domain"),
    ("Cemetery", "LOCATION", "THREATENS", "March of the Dead", "EVENT", "both"),
]


class TestNegativeCasesTheGoldenSetDoesNotReach:
    def test_every_row_side_of_the_table_has_a_rejected_case(self):
        """The sweep that found the 33 unpinned sides, as a standing assertion:
        every side must appear as the offending one in at least one case above.
        A relationship type added to LAYER_MAP fails this until both of its sides
        are pinned, the same way the totality test works."""
        pinned = set()
        for _, _, rel, _, _, reason in NEGATIVE_CASES:
            for side in ("domain", "range"):
                if reason in (side, "both"):
                    pinned.add((RelationshipType(rel), side))
        missing = sorted(
            f"{rel.value}.{side}"
            for rel in RELATIONSHIP_DOMAIN_RANGE
            for side in ("domain", "range")
            if (rel, side) not in pinned
        )

        assert missing == []

    @pytest.mark.parametrize(
        ("source", "source_type", "rel_type", "target", "target_type", "reason"),
        NEGATIVE_CASES,
    )
    def test_it_is_flagged(self, source, source_type, rel_type, target, target_type, reason):
        nodes = [node(source, source_type), node(target, target_type)]

        violations = check_edges(nodes, [edge(source, rel_type, target)])

        assert [v.reason for v in violations] == [reason]


class TestUntypedEndpointsAreUnchecked:
    """`structure.py` emits edges with no node for the section's own place."""

    def test_an_untyped_target_is_not_a_violation(self):
        nodes = [node("Donavich", "NPC")]

        report = report_edges(nodes, [edge("Donavich", "LOCATED_IN", "Chapel")])

        assert report.violations == []

    def test_an_edge_with_both_endpoints_untyped_is_counted_unchecked(self):
        report = report_edges([], [edge("Chapel", "CONTAINS", "Undercroft")])

        assert report.violations == []
        assert report.unchecked == 1
        assert report.checked == 0

    def test_a_half_typed_edge_is_checked_on_the_side_it_can_be(self):
        """A derived `LOCATED_IN` names a section place that has no node of its
        own. The typed side is still evidence, so it is checked, not waved
        through -- and the unknown side is reported as an empty type."""
        nodes = [node("Chapel", "LOCATION")]

        report = report_edges(nodes, [edge("Chapel", "TRAVELED_TO", "Undercroft")])

        assert report.checked == 1
        assert report.unchecked == 0
        assert [v.reason for v in report.violations] == ["domain"]
        assert report.violations[0].target_type == ""

    def test_an_untyped_source_never_produces_a_domain_violation(self):
        nodes = [node("Donavich", "NPC")]

        report = report_edges(nodes, [edge("Undercroft", "MEMBER_OF", "Donavich")])

        assert [v.reason for v in report.violations] == ["range"]
        assert report.violations[0].source_type == ""

    def test_a_node_whose_entity_type_is_unparseable_leaves_the_endpoint_unknown(self):
        """An entity_type the ontology does not define is a typing failure, not
        evidence that the edge is wrong."""
        nodes = [node("Chapel", "PLACE"), node("Donavich", "")]

        report = report_edges(nodes, [edge("Chapel", "LOCATED_IN", "Donavich")])

        assert report.violations == []
        assert report.unchecked == 1

    def test_an_unknown_relationship_type_is_unchecked(self):
        nodes = [node("Donavich", "NPC"), node("Chapel", "LOCATION")]

        report = report_edges(nodes, [edge("Donavich", "SPOKE_TO", "Chapel")])

        assert report.violations == []
        assert report.unchecked == 1

    def test_a_name_with_two_types_passes_if_either_type_would(self):
        """A coined QUEST sharing a LOCATION's name is a measured occurrence in
        this corpus. Charging the edge with the wrong one of the two would be a
        fabricated violation."""
        nodes = [
            node("Village of Barovia", "QUEST"),
            node("Village of Barovia", "LOCATION"),
            node("Church", "LOCATION"),
        ]

        report = report_edges(nodes, [edge("Village of Barovia", "CONTAINS", "Church")])

        assert report.violations == []
        assert report.checked == 1

    def test_a_derived_structural_edge_over_untyped_places_is_unchecked(self):
        derived = edge(
            "The Village of Barovia",
            "CONTAINS",
            "Church of Barovia",
            evidence=STRUCTURAL_EVIDENCE,
        )

        report = report_edges([], [derived])

        assert report.violations == []
        assert report.unchecked == 1


class TestNameMatching:
    def test_endpoint_types_match_case_insensitively_and_stripped(self):
        nodes = [node("  DONAVICH ", "NPC"), node("chapel", "LOCATION")]

        report = report_edges(nodes, [edge("Donavich", "LOCATED_IN", " Chapel")])

        assert report.checked == 1
        assert report.violations == []


class TestReversal:
    def test_true_when_swapping_the_endpoints_would_satisfy_the_table(self):
        nodes = [node("Chapel", "LOCATION"), node("Donavich", "NPC")]

        violations = check_edges(nodes, [edge("Chapel", "LOCATED_IN", "Donavich")])

        assert violations[0].reversal_would_pass is True

    def test_false_for_a_genuinely_nonsensical_pair(self):
        """`Cyrus Belview GAVE_QUEST Iron Chest` is wrong in both directions: an
        iron chest gives out no quests either."""
        nodes = [node("Cyrus Belview", "NPC"), node("Iron Chest", "ITEM")]

        violations = check_edges(nodes, [edge("Cyrus Belview", "GAVE_QUEST", "Iron Chest")])

        assert violations[0].reversal_would_pass is False

    def test_the_report_counts_the_reversals_for_the_artifact(self):
        """The count is written into the run object of the candidate artifact,
        so it has to be readable off the report and not only off the printed
        block -- it is the evidence for whether a repair pass is worth building,
        and a terminal scrolls away."""
        nodes = [
            node("Chapel", "LOCATION"),
            node("Donavich", "NPC"),
            node("Iron Chest", "ITEM"),
            node("Cyrus Belview", "NPC"),
        ]
        edges = [
            edge("Chapel", "LOCATED_IN", "Donavich"),  # reversal passes
            edge("Cyrus Belview", "GAVE_QUEST", "Iron Chest"),  # wrong both ways
            edge("Donavich", "LOCATED_IN", "Chapel"),  # not a violation at all
        ]

        report = report_edges(nodes, edges)

        assert len(report.violations) == 2
        assert report.reversals_would_pass == 1

    def test_a_reversal_is_detected_but_never_performed(self):
        """No auto-repair: we cannot yet tell a genuine reversal from a
        coincidence, and manufacturing an edge the model never proposed is a
        bigger risk than leaving a wrong one flagged."""
        nodes = [node("Chapel", "LOCATION"), node("Donavich", "NPC")]
        edges = [edge("Chapel", "LOCATED_IN", "Donavich")]

        kept, report = enforce(nodes, edges, reject=True)

        assert kept == []
        assert report.violations[0].reversal_would_pass is True
        assert edges[0].source_name == "Chapel"
        assert edges[0].target_name == "Donavich"


class TestEnforce:
    def test_reject_off_leaves_the_edge_list_unchanged(self):
        nodes = [node("Chapel", "LOCATION"), node("Donavich", "NPC")]
        edges = [
            edge("Chapel", "LOCATED_IN", "Donavich"),
            edge("Donavich", "LOCATED_IN", "Chapel"),
        ]

        kept, report = enforce(nodes, edges, reject=False)

        assert kept == edges
        assert len(report.violations) == 1

    def test_reject_on_drops_only_the_violating_edge(self):
        nodes = [node("Chapel", "LOCATION"), node("Donavich", "NPC")]
        good = edge("Donavich", "LOCATED_IN", "Chapel")
        edges = [edge("Chapel", "LOCATED_IN", "Donavich"), good]

        kept, report = enforce(nodes, edges, reject=True)

        assert kept == [good]
        assert len(report.violations) == 1

    def test_reject_on_keeps_unchecked_edges(self):
        """Rejecting what could not be typed would delete the derived structural
        layer, which is the one part of the output known to be clean."""
        untyped = edge("Chapel", "CONTAINS", "Undercroft", evidence=STRUCTURAL_EVIDENCE)

        kept, report = enforce([], [untyped], reject=True)

        assert kept == [untyped]
        assert report.unchecked == 1

    def test_the_cli_defaults_to_reporting_not_rejecting(self):
        """The table is new and untested against anything but chapter 3's golden
        set, and silent filtering has twice hidden a defect in this project."""
        args = build_parser().parse_args(["Chapter 3"])

        assert args.reject_violations is False

    def test_the_cli_flag_turns_rejection_on(self):
        args = build_parser().parse_args(["Chapter 3", "--reject-violations"])

        assert args.reject_violations is True


def violation(reason: str, reversal: bool) -> Violation:
    return Violation(
        edge_index=0,
        rel_type="LOCATED_IN",
        source_name="Chapel",
        target_name="Donavich",
        source_type="LOCATION",
        target_type="NPC",
        reason=reason,
        reversal_would_pass=reversal,
    )


class TestFormatReport:
    def test_reports_violations_and_unchecked_separately(self):
        report = ConstraintReport(
            violations=[violation("range", True), violation("domain", False)],
            checked=10,
            unchecked=7,
        )

        text = format_report(report)

        assert "constraint violations: 2 of 10 typed edges (domain 1, range 1, both 0)" in text
        assert "of which reversal would pass: 1" in text
        assert "unchecked (endpoint type unknown): 7" in text

    def test_a_clean_run_still_prints_the_counts(self):
        """A silent pass is indistinguishable from a check that never ran."""
        text = format_report(ConstraintReport(violations=[], checked=10, unchecked=4))

        assert "constraint violations: 0 of 10 typed edges (domain 0, range 0, both 0)" in text
        assert "unchecked (endpoint type unknown): 4" in text
