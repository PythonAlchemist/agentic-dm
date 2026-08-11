"""Voting over independent extraction samples.

Extraction is sampled, not deterministic: two chapter-3 runs at temperature 0
with a fixed seed share only 0.40-0.49 of their unique edges while reporting
identical recall. Consensus keeps what recurs across samples drawn with
different seeds, so a candidate has to be found more than once to ship.
"""

import pytest

from backend.canon.consensus import consense, format_votes, vote_histograms
from backend.canon.models import CandidateEdge, CandidateNode


def node(name: str, entity_type: str = "NPC", section_index: int = 0, **kw) -> CandidateNode:
    return CandidateNode(
        name=name, entity_type=entity_type, section_index=section_index, **kw
    )


def edge(
    source: str = "Ismark",
    target: str = "Ireena",
    rel_type: str = "RELATED_TO",
    section_index: int = 0,
    **kw,
) -> CandidateEdge:
    return CandidateEdge(
        source_name=source,
        target_name=target,
        rel_type=rel_type,
        section_index=section_index,
        **kw,
    )


def samples_of_nodes(*per_sample: list[CandidateNode]):
    return [(nodes, []) for nodes in per_sample]


def samples_of_edges(*per_sample: list[CandidateEdge]):
    return [([], edges) for edges in per_sample]


class TestThreshold:
    def test_a_candidate_in_3_of_5_samples_survives_k3_and_is_dropped_at_k4(self):
        """The whole mechanism in one assertion: k is a floor on how many
        distinct samples had to find a candidate for it to ship."""
        present = [node("Doru")]
        absent: list[CandidateNode] = []
        samples = samples_of_nodes(present, present, present, absent, absent)

        at_3, _ = consense(samples, node_k=3, edge_k=3)
        at_4, _ = consense(samples, node_k=4, edge_k=4)

        assert [n.name for n in at_3] == ["Doru"]
        assert at_4 == []

    def test_the_same_holds_for_edges(self):
        present = [edge()]
        samples = samples_of_edges(present, present, present, [], [])

        _, at_3 = consense(samples, node_k=3, edge_k=3)
        _, at_4 = consense(samples, node_k=4, edge_k=4)

        assert len(at_3) == 1
        assert at_4 == []

    def test_node_k_and_edge_k_are_applied_independently(self):
        """One threshold used for both would make the measured trade-off curve
        for nodes and edges impossible to read apart."""
        samples = [
            ([node("Doru")], [edge()]),
            ([node("Doru")], []),
            ([], []),
        ]

        nodes, edges = consense(samples, node_k=2, edge_k=1)

        assert len(nodes) == 1
        assert len(edges) == 1

        nodes, edges = consense(samples, node_k=3, edge_k=1)

        assert nodes == []
        assert len(edges) == 1

    def test_k_below_1_is_rejected(self):
        """k=0 would admit candidates no sample produced once the tally is
        extended; it is a caller mistake, not a permissive setting."""
        with pytest.raises(ValueError):
            consense(samples_of_nodes([node("Doru")]), node_k=0, edge_k=1)

        with pytest.raises(ValueError):
            consense(samples_of_nodes([node("Doru")]), node_k=1, edge_k=0)


class TestOneVotePerSample:
    def test_a_candidate_appearing_twice_within_one_sample_counts_as_one_vote(self):
        """Three layer passes routinely name the same entity in one sample. If
        that counted three times, a single sample could clear k=3 by itself and
        the number would be a frequency count, not a consensus."""
        samples = samples_of_nodes([node("Doru"), node("Doru"), node("Doru")])

        survivors, _ = consense(samples, node_k=2, edge_k=2)

        assert survivors == []

    def test_the_same_holds_for_edges(self):
        samples = samples_of_edges([edge(), edge(), edge()])

        _, survivors = consense(samples, node_k=2, edge_k=2)

        assert survivors == []

    def test_a_repeated_candidate_still_earns_its_one_vote(self):
        samples = samples_of_nodes([node("Doru"), node("Doru")], [node("Doru")])

        survivors, _ = consense(samples, node_k=2, edge_k=2)

        assert [n.votes for n in survivors] == [2]

    def test_within_sample_duplicates_are_collapsed_in_the_output(self):
        samples = samples_of_nodes([node("Doru"), node("Doru")], [node("Doru")])

        survivors, _ = consense(samples, node_k=1, edge_k=1)

        assert len(survivors) == 1


class TestIdentity:
    def test_two_same_named_nodes_in_different_sections_vote_independently(self):
        """`Closet` occurs twice in chapter 4 (K44, K51) and `Empty Cell` three
        times. Voting on name alone would let one room's candidate corroborate
        another room's."""
        samples = samples_of_nodes(
            [node("Skeleton", section_index=1)],
            [node("Skeleton", section_index=2)],
        )

        survivors, _ = consense(samples, node_k=2, edge_k=2)

        assert survivors == []

    def test_same_named_edges_in_different_sections_vote_independently(self):
        samples = samples_of_edges(
            [edge(section_index=1)],
            [edge(section_index=2)],
        )

        _, survivors = consense(samples, node_k=2, edge_k=2)

        assert survivors == []

    def test_names_are_matched_case_and_whitespace_insensitively(self):
        """`undercroft` appears beside `Undercroft` in one chapter's candidates."""
        samples = samples_of_nodes([node("Undercroft")], [node("  undercroft ")])

        survivors, _ = consense(samples, node_k=2, edge_k=2)

        assert [n.votes for n in survivors] == [2]

    def test_normalization_is_only_case_and_whitespace(self):
        """Deliberately not the grade module's loose matcher: extraction must
        not depend on the thing that scores it, and a looser fold here would
        merge distinct entities before anyone could vote on them."""
        samples = samples_of_nodes([node("Ismark")], [node("Ismark the Lesser")])

        survivors, _ = consense(samples, node_k=2, edge_k=2)

        assert survivors == []

    def test_a_name_reused_for_a_different_entity_type_votes_independently(self):
        """A coined QUEST sharing a LOCATION's name is a measured occurrence --
        see anchor_quests. They are two candidates, not one with two votes."""
        samples = samples_of_nodes(
            [node("Village of Barovia", entity_type="LOCATION")],
            [node("Village of Barovia", entity_type="QUEST")],
        )

        survivors, _ = consense(samples, node_k=2, edge_k=2)

        assert survivors == []

    def test_edges_of_different_rel_types_vote_independently(self):
        """IDENTITY_OF versus RELATED_TO on the same pair is the exact inversion
        the fabrication check found."""
        samples = samples_of_edges(
            [edge(rel_type="IDENTITY_OF")],
            [edge(rel_type="RELATED_TO")],
        )

        _, survivors = consense(samples, node_k=2, edge_k=2)

        assert survivors == []

    def test_edge_direction_is_part_of_the_identity(self):
        samples = samples_of_edges(
            [edge(source="Ismark", target="Ireena")],
            [edge(source="Ireena", target="Ismark")],
        )

        _, survivors = consense(samples, node_k=2, edge_k=2)

        assert survivors == []


class TestSurvivingRecord:
    def test_a_survivor_keeps_the_record_from_its_first_seen_sample(self):
        samples = samples_of_nodes(
            [node("Doru", description="first")],
            [node("Doru", description="second")],
        )

        survivors, _ = consense(samples, node_k=2, edge_k=2)

        assert survivors[0].description == "first"

    def test_an_edge_survivor_keeps_its_first_seen_evidence(self):
        samples = samples_of_edges(
            [edge(evidence="first")],
            [edge(evidence="second")],
        )

        _, survivors = consense(samples, node_k=2, edge_k=2)

        assert survivors[0].evidence == "first"

    def test_the_vote_count_travels_with_the_survivor(self):
        """Stage 2b weights by it, so a number only stdout ever saw is no use."""
        samples = samples_of_nodes([node("Doru")], [node("Doru")], [node("Doru")])

        survivors, _ = consense(samples, node_k=2, edge_k=2)

        assert survivors[0].votes == 3

    def test_edge_survivors_carry_votes_too(self):
        samples = samples_of_edges([edge()], [edge()])

        _, survivors = consense(samples, node_k=1, edge_k=1)

        assert survivors[0].votes == 2

    def test_the_input_samples_are_not_mutated(self):
        """The measurement re-runs consensus at every k over one set of
        samples; stamping votes onto the inputs would carry the previous k's
        numbers into the next sweep."""
        original = node("Doru")
        samples = samples_of_nodes([original], [node("Doru")])

        consense(samples, node_k=1, edge_k=1)

        assert original.votes == 0

    def test_output_order_follows_first_appearance(self):
        samples = samples_of_nodes(
            [node("Doru"), node("Donavich")],
            [node("Donavich"), node("Doru")],
        )

        survivors, _ = consense(samples, node_k=2, edge_k=2)

        assert [n.name for n in survivors] == ["Doru", "Donavich"]


class TestNoSamples:
    def test_no_samples_yields_nothing(self):
        """Every sample failing must not be indistinguishable from a chapter
        that legitimately contained nothing -- the caller reports the failures,
        but this must not invent survivors out of an empty tally."""
        assert consense([], node_k=1, edge_k=1) == ([], [])


class TestVoteHistograms:
    def test_counts_candidates_by_how_many_samples_found_them(self):
        samples = [
            ([node("A"), node("B")], [edge(target="X")]),
            ([node("A")], [edge(target="X")]),
            ([node("A")], []),
        ]

        node_hist, edge_hist = vote_histograms(samples)

        assert node_hist == {3: 1, 1: 1}
        assert edge_hist == {2: 1}

    def test_the_histogram_covers_every_candidate_regardless_of_k(self):
        """It is the evidence for choosing k, so it must show the population
        below any k as well as above it."""
        samples = samples_of_nodes([node("A")], [node("A")], [node("B")])

        node_hist, _ = vote_histograms(samples)

        assert node_hist == {2: 1, 1: 1}

    def test_a_within_sample_duplicate_does_not_inflate_the_histogram(self):
        samples = samples_of_nodes([node("A"), node("A")])

        node_hist, _ = vote_histograms(samples)

        assert node_hist == {1: 1}

    def test_format_is_highest_vote_first(self):
        assert format_votes({1: 63, 5: 41, 3: 9}) == "5:41  3:9  1:63"

    def test_format_of_an_empty_histogram_is_empty(self):
        assert format_votes({}) == ""
