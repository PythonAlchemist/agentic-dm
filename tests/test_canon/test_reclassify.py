"""The stage-B measurement script.

This file exists because the four-way split IS the result. A bug in
`classify_outcome` would not crash anything -- it would print a confident,
wrong table, and every one of the four buckets is a claim someone would act on.
Likewise `split_edges`: re-typing the derived structural edges, or dropping
them, would change the measured recall without changing the experiment.
"""

import json
from pathlib import Path

import pytest

from backend.canon.classify import NO_ANSWER, NONE_RELATION, Decision
from backend.canon.models import CandidateEdge, CandidateNode
from backend.canon.structure import STRUCTURAL_EVIDENCE
from backend.scripts.reclassify import (
    CHANGED,
    DECLINED,
    FAILED,
    FLIPPED,
    KEPT,
    NO_RELATION_LEGAL,
    SELF_LOOP,
    SYMMETRIC_RELATIONS,
    build_parser,
    classify_outcome,
    load_artifact,
    retyped_edge,
    split_edges,
)


def edge(source: str = "Ismark", rel_type: str = "KNOWS", target: str = "Ireena",
         **kwargs) -> CandidateEdge:
    return CandidateEdge(source_name=source, rel_type=rel_type, target_name=target, **kwargs)


class TestSplitEdges:
    def test_derived_edges_are_identified_by_the_structural_marker(self):
        edges = [
            edge(evidence="Ismark is Ireena's brother."),
            edge("Barovia", "CONTAINS", "Church", evidence=STRUCTURAL_EVIDENCE),
            edge(evidence=""),
        ]

        llm, derived = split_edges(edges)

        assert llm == [0, 2]
        assert derived == [1]

    def test_the_two_lists_partition_the_edges(self):
        """A dropped edge would change recall without changing the experiment."""
        edges = [edge(evidence=STRUCTURAL_EVIDENCE)] * 3 + [edge()] * 4

        llm, derived = split_edges(edges)

        assert sorted(llm + derived) == list(range(len(edges)))


class TestClassifyOutcome:
    def test_same_type_same_direction_is_kept(self):
        outcome = classify_outcome(
            edge("Ismark", "KNOWS", "Ireena"),
            Decision("Ismark", "Ireena", "KNOWS", "clear"),
            was_asked=True,
        )

        assert outcome == KEPT

    def test_same_type_reversed_endpoints_is_a_flip(self):
        """The reversal case -- `Strahd -GUARDS-> vampire spawn` off evidence
        that says they serve him. Folding this into `kept` would report the
        diagnosed failure as agreement."""
        outcome = classify_outcome(
            edge("Strahd", "SERVES", "Vampire Spawn"),
            Decision("Vampire Spawn", "Strahd", "SERVES", "clear"),
            was_asked=True,
        )

        assert outcome == FLIPPED

    def test_a_different_type_is_a_change_whatever_the_direction(self):
        for decision in (
            Decision("Strahd", "Vampire Spawn", "OWNS", "clear"),
            Decision("Vampire Spawn", "Strahd", "SERVES", "clear"),
        ):
            outcome = classify_outcome(
                edge("Strahd", "GUARDS", "Vampire Spawn"), decision, was_asked=True
            )

            assert outcome == CHANGED

    def test_a_decline_on_an_asked_pair_is_the_models_own(self):
        outcome = classify_outcome(edge(), Decision("", "", NONE_RELATION, ""), was_asked=True)

        assert outcome == DECLINED

    def test_a_decline_on_an_unasked_pair_belongs_to_the_table(self):
        """Counting a table decline as a model decline would manufacture the
        precision signal this whole experiment is measuring."""
        outcome = classify_outcome(edge(), Decision("", "", NONE_RELATION, ""), was_asked=False)

        assert outcome == NO_RELATION_LEGAL
        assert outcome != DECLINED

    def test_a_non_answer_is_never_a_decline(self):
        outcome = classify_outcome(edge(), Decision("", "", NO_ANSWER, ""), was_asked=True)

        assert outcome == FAILED
        assert outcome != DECLINED

    def test_the_seven_outcomes_are_distinct_labels(self):
        labels = [KEPT, FLIPPED, CHANGED, DECLINED, NO_RELATION_LEGAL, SELF_LOOP, FAILED]

        assert len(set(labels)) == len(labels)

    def test_a_self_loop_decline_is_its_own_bucket(self):
        """Three different authorities can produce a `NONE`: the model, the type
        table, and the two names being one entity. Only the first is a decline,
        and only the first belongs in the decline rate."""
        outcome = classify_outcome(
            edge("Helga", "IDENTITY_OF", "Helga"),
            Decision("", "", NONE_RELATION, ""),
            was_asked=False,
            is_self_loop=True,
        )

        assert outcome == SELF_LOOP
        assert outcome not in (DECLINED, NO_RELATION_LEGAL)

    def test_a_table_decline_is_not_relabelled_as_a_self_loop(self):
        outcome = classify_outcome(
            edge(), Decision("", "", NONE_RELATION, ""), was_asked=False, is_self_loop=False
        )

        assert outcome == NO_RELATION_LEGAL


class TestSymmetricRelations:
    """A flip on one of these costs golden recall without changing the claim,
    because `grade.py` matches direction-sensitively. Listed so the recall delta
    can be read honestly, never to silently repair anything."""

    def test_the_flagged_relations_have_a_symmetric_gloss(self):
        assert "RELATED_TO" in SYMMETRIC_RELATIONS
        assert "CONNECTED_TO" in SYMMETRIC_RELATIONS

    def test_a_directional_relation_is_not_listed(self):
        for directional in ("LOCATED_IN", "CONTAINS", "SERVES", "GAVE_QUEST", "OWNS"):
            assert directional not in SYMMETRIC_RELATIONS


class TestRetypedEdge:
    def test_the_decisions_endpoints_and_type_replace_the_originals(self):
        result = retyped_edge(
            edge("Strahd", "GUARDS", "Vampire Spawn", evidence="The vampire spawn serve Strahd."),
            Decision("Vampire Spawn", "Strahd", "SERVES", "clear"),
        )

        assert (result.source_name, result.rel_type, result.target_name) == (
            "Vampire Spawn", "SERVES", "Strahd",
        )

    def test_the_layer_is_recomputed_not_inherited(self):
        """A spatial-pass edge re-typed SERVES is a social edge. Keeping the old
        label would make `layer` record which PASS found the pair rather than
        what the edge is."""
        result = retyped_edge(
            edge("Doru", "TRAVELED_TO", "Strahd", layer="spatial"),
            Decision("Doru", "Strahd", "SERVES", "implied"),
        )

        assert result.layer == "social"

    def test_evidence_and_provenance_survive_re_typing(self):
        original = edge(
            "Ismark", "TRAVELED_TO", "Vallaki",
            evidence="He wants to escort Ireena to Vallaki.",
            section_heading="E2. Blood of the Vine Tavern",
            chapter_slug="chapter-3-the-village-of-barovia",
            section_index=7,
            votes=5,
        )

        result = retyped_edge(original, Decision("Ismark", "Vallaki", "SEEKS", "implied"))

        assert result.evidence == original.evidence
        assert result.section_heading == original.section_heading
        assert result.chapter_slug == original.chapter_slug
        assert result.section_index == original.section_index

    def test_votes_are_preserved_because_re_typing_did_not_earn_them(self):
        """`votes` counts EXTRACTION samples. Zeroing or bumping it would make a
        re-typed edge look differently supported than the pair actually is."""
        result = retyped_edge(
            edge(votes=5), Decision("Ireena", "Ismark", "RELATED_TO", "clear")
        )

        assert result.votes == 5


class TestLoadArtifact:
    def test_reads_the_shape_extract_canon_writes(self, tmp_path: Path):
        path = tmp_path / "artifact.json"
        path.write_text(json.dumps({
            "run": {"chapter": "Chapter 3", "seed": 20260806},
            "nodes": [{"name": "Ismark", "entity_type": "NPC", "layer": "social"}],
            "edges": [{"source_name": "Ismark", "target_name": "Ireena",
                       "rel_type": "RELATED_TO", "evidence": "his sister"}],
        }))

        payload, nodes, edges = load_artifact(path)

        assert payload["run"]["seed"] == 20260806
        assert nodes == [CandidateNode(name="Ismark", entity_type="NPC", layer="social")]
        assert edges == [CandidateEdge(source_name="Ismark", target_name="Ireena",
                                       rel_type="RELATED_TO", evidence="his sister")]


class TestParser:
    def test_the_artifact_is_required_and_the_output_is_not(self):
        args = build_parser().parse_args(["ch4.json"])

        assert args.artifact == Path("ch4.json")
        assert args.out is None
        assert args.grade_against is None

    def test_it_does_not_offer_to_modify_the_input(self):
        """The baseline must stay untouched for the comparison -- the script
        writes a NEW artifact or none at all."""
        with pytest.raises(SystemExit):
            build_parser().parse_args(["ch4.json", "--in-place"])
