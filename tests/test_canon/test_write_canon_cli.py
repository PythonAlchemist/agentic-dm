"""The CLI around the write path: what it reads, and what it leaves on disk.

No Neo4j and no API calls: everything asserted here is a property of the
argument parser, the artifact reader, or the run artifact the verifier reads.
"""

import json
from pathlib import Path

import pytest

from backend.canon.cooccurrence import WidestSentence
from backend.canon.models import CandidateNode
from backend.canon.structure import place_from_chapter_title
from backend.canon.writer import FilterReport, WriteEdge, WriteNode
from backend.graph.schema import RelationshipType
from backend.scripts.write_canon import (
    DEFAULT_GAZETTEER,
    DEFAULT_RUNS_DIR,
    build_parser,
    chapter_place_of_run,
    format_co_occurrence,
    format_report,
    parse_artifact,
    run_artifact,
)

SLUG = "the-village-of-barovia"


class TestParser:
    def test_chapter_slug_is_required(self):
        with pytest.raises(SystemExit):
            build_parser().parse_args(["ch3.json"])

    def test_replace_is_off_by_default(self):
        """Refusing to overwrite is gate G6. It must not be reachable by accident."""
        assert build_parser().parse_args(["ch3.json", "--chapter", SLUG]).replace is False

    def test_accepted_only_is_off_by_default(self):
        """The loop's goal predicate counts nodes, so an accepted-only write
        would report a chapter done with most of it gone -- and throwing the
        proposed set away before a human reads it destroys the review queue."""
        args = build_parser().parse_args(["ch3.json", "--chapter", SLUG])

        assert args.accepted_only is False

    def test_the_accepted_only_flag_turns_it_on(self):
        args = build_parser().parse_args(["ch3.json", "--chapter", SLUG, "--accepted-only"])

        assert args.accepted_only is True

    def test_defaults_point_at_the_paths_the_verifier_uses(self):
        args = build_parser().parse_args(["ch3.json", "--chapter", SLUG])
        assert args.runs_dir == DEFAULT_RUNS_DIR
        assert str(DEFAULT_RUNS_DIR) == "data/canon/runs"

    def test_the_gazetteer_defaults_to_whatever_the_book_names(self):
        """`None` here is not "unset", it is "ask the book".

        The flag used to default to the Curse of Strahd wiki index, which made
        that one book's name list the default for every book. Keys from the
        Golden Vault has no index at all -- its wiki page carries no
        `==Index==` -- and gating it on Barovia's names dropped 366 candidates
        including the adventure's own quest-giver.
        """
        args = build_parser().parse_args(["ch3.json", "--chapter", SLUG])
        assert args.gazetteer is None

    def test_the_default_book_is_still_curse_of_strahd(self):
        """Which is where the old default came from, now said once and in the
        book's own file rather than as a constant beside an unrelated flag."""
        from backend.canon.books import load

        args = build_parser().parse_args(["ch3.json", "--chapter", SLUG])
        assert load(args.book).gazetteer == "data/gazetteer/curse-of-strahd.json"


class TestParseArtifact:
    def test_candidates_and_run_block_are_read(self):
        nodes, edges, run = parse_artifact(
            {
                "run": {"failed": 0, "model": "gpt-4o-mini"},
                "nodes": [{"name": "Church", "entity_type": "LOCATION", "votes": 5}],
                "edges": [
                    {
                        "source_name": "Undercroft",
                        "target_name": "Church",
                        "rel_type": "LOCATED_IN",
                        "evidence": "derived from document structure",
                    }
                ],
            }
        )
        assert nodes == [CandidateNode(name="Church", entity_type="LOCATION", votes=5)]
        assert edges[0].evidence == "derived from document structure"
        assert run["failed"] == 0

    def test_unknown_keys_do_not_make_an_artifact_unloadable(self):
        """Later stages record their own decisions beside each candidate."""
        nodes, _, _ = parse_artifact(
            {"nodes": [{"name": "Church", "entity_type": "LOCATION", "stage_b_verdict": "keep"}]}
        )
        assert nodes == [CandidateNode(name="Church", entity_type="LOCATION")]

    def test_a_missing_run_block_is_empty_not_an_error(self):
        """An artifact predating the run block still loads -- and its emptiness
        is what makes the verifier's check 6 fail, which is the correct outcome."""
        _, _, run = parse_artifact({"nodes": []})
        assert run == {}


class TestRunArtifact:
    def build(self, **overrides) -> dict:
        report = FilterReport(candidate_nodes=3, candidate_edges=2, gazetteer_dropped=1)
        report.written_nodes = 2
        report.written_edges = 1
        defaults = dict(
            chapter_slug=SLUG,
            source=Path("ch3.json"),
            extraction_run={"failed": 0, "model": "gpt-4o-mini", "samples": 5},
            candidate_nodes=[{"name": "Church"}, {"name": "Undercroft"}, {"name": "bed"}],
            candidate_edges=[{"source_name": "Undercroft"}, {"source_name": "bed"}],
            report=report,
            nodes=[
                WriteNode(id="a", name="Church", entity_types=("LOCATION",), chapter_slug=SLUG),
                WriteNode(id="b", name="Undercroft", entity_types=("LOCATION",), chapter_slug=SLUG),
            ],
            edges=[
                WriteEdge(
                    source_id="b",
                    target_id="a",
                    rel_type=RelationshipType.LOCATED_IN,
                    chapter_slug=SLUG,
                )
            ],
            replaced={"deleted_nodes": 0, "deleted_edges": 0},
        )
        return run_artifact(**{**defaults, **overrides})

    def test_the_extraction_run_block_is_carried_through_untouched(self):
        """It is the only record of what was paid for."""
        assert self.build()["run"] == {"failed": 0, "model": "gpt-4o-mini", "samples": 5}

    def test_nodes_are_the_candidates_not_the_survivors(self):
        """The verifier's band compares what landed against what was PROPOSED.

        Listing survivors here would score 100% of itself by construction --
        the band would be incapable of ever failing.
        """
        art = self.build()
        assert len(art["nodes"]) == 3
        assert art["write"]["filters"]["written_nodes"] == 2

    def test_every_drop_count_travels_with_the_run(self):
        filters = self.build()["write"]["filters"]
        for key in (
            "gazetteer_dropped",
            "unnameable",
            "duplicate_nodes",
            "self_loops",
            "constraint_violations",
            "dangling_edges",
            "ambiguous_edges",
            "duplicate_edges",
            "endpoint_resolved",
            "undecidable_keyed",
        ):
            assert key in filters, key

    def test_the_undecidable_keyed_places_are_named(self):
        """A room the book keys twice, mentioned from neither section, is the
        one drop a reader cannot reconstruct from the graph -- it is not there."""
        report = FilterReport(candidate_nodes=1, candidate_edges=0)
        report.undecidable_keyed = 1
        report.dropped_undecidable_keyed = ["LOCATION Empty Cell (k61a/k62a)"]
        printed = format_report(report)
        assert "undecidable keyed place (two keys, neither its):  1" in printed
        assert "- undecidable keyed: LOCATION Empty Cell (k61a/k62a)" in printed

    def test_the_resolved_edges_are_named_in_the_artifact(self):
        """The verifier's constraint check proves nothing about these, so which
        ones they are has to be recoverable without a graph query."""
        report = FilterReport(candidate_nodes=3, candidate_edges=2)
        report.endpoint_resolved = 1
        report.resolved_endpoints = ["Ireena -IDENTITY_OF-> Tatyana  ->  cos:x:npc:tatyana"]
        write = self.build(report=report)["write"]
        assert write["resolved_endpoints"] == report.resolved_endpoints
        assert write["filters"]["endpoint_resolved"] == 1

    def test_written_counts_are_broken_down_by_type(self):
        write = self.build()["write"]
        assert write["written_nodes_by_type"] == {"LOCATION": 2}
        assert write["written_edges_by_type"] == {"LOCATED_IN": 1}

    def test_the_written_split_is_read_off_what_was_written(self):
        """Not off the plan's counts: `--accepted-only` narrows the write after
        planning, and an artifact stating the plan's split would describe a
        graph that was never written."""
        accepted = WriteEdge(
            source_id="b",
            target_id="a",
            rel_type=RelationshipType.LOCATED_IN,
            chapter_slug=SLUG,
            evidence="derived from document structure",
        )
        write = self.build(
            nodes=[
                WriteNode(
                    id="a", name="Church", entity_types=("LOCATION",), chapter_slug=SLUG,
                    status="accepted",
                )
            ],
            edges=[accepted],
            accepted_only=True,
        )["write"]

        assert write["written_edges_by_status"] == {"accepted": 1}
        assert write["written_nodes_by_status"] == {"accepted": 1}
        assert write["accepted_only"] is True

    def test_the_conflicts_travel_with_the_run(self):
        """The graph now holds contradictions on purpose. The only record of
        which ones is this list and the `conflict` property beside them."""
        report = FilterReport(candidate_nodes=2, candidate_edges=2)
        report.exclusive_conflicts = 1
        report.conflicts = ["cos:x:npc:ireena -IDENTITY_OF|RELATED_TO-> cos:x:npc:tatyana"]

        write = self.build(report=report)["write"]

        assert write["conflicts"] == report.conflicts
        assert write["filters"]["exclusive_conflicts"] == 1

    def test_the_accepted_only_default_is_recorded_as_false(self):
        assert self.build()["write"]["accepted_only"] is False

    def test_the_artifact_is_json_serialisable(self):
        json.dumps(self.build())

    def test_the_co_occurrence_census_travels_with_the_run(self):
        """Printed AND recorded: the ratio's movement across chapters is the
        signal, and a terminal has scrolled away by chapter 12."""
        written = self.build(
            replaced={
                "deleted_nodes": 0,
                "deleted_edges": 0,
                "co_occurrences": 6,
                "co_occurrence_counts": [("Strahd", 2)],
                "widest_sentence": WidestSentence(
                    entities=3, passage="Strahd rules Barovia.", names=("Strahd",)
                ),
            }
        )["write"]
        assert written["co_occurrences"] == 6
        assert written["co_occurrence_counts"] == [("Strahd", 2)]
        assert written["widest_sentence"] == {
            "entities": 3,
            "passage": "Strahd rules Barovia.",
            "names": ("Strahd",),
        }

    def test_a_widest_sentence_of_none_stays_none_and_serialises(self):
        """A chapter no sentence of which names two entities is a real outcome,
        and `asdict(None)` would raise on it."""
        written = self.build(
            replaced={"deleted_nodes": 0, "deleted_edges": 0, "widest_sentence": None}
        )["write"]
        assert written["widest_sentence"] is None
        json.dumps(written)


class TestFormatCoOccurrence:
    """The census the design asks to be watched, printed on every write."""

    def summary(self, **overrides) -> dict:
        return {
            "mentions": 100,
            "co_occurrences": 65,
            "co_occurrence_counts": [("Strahd von Zarovich", 10), ("vampire", 8)],
            "widest_sentence": WidestSentence(
                entities=3,
                passage="Adventurers find themselves in Barovia, ruled by Strahd.",
                names=("Barovia", "Strahd von Zarovich", "vampire"),
            ),
            **overrides,
        }

    def test_the_ratio_to_mentions_is_printed(self):
        """The number that says whether the sentence rule has come loose."""
        assert "0.65 per mention" in format_co_occurrence(self.summary())

    def test_the_widest_sentence_is_printed_with_its_edge_cost(self):
        printed = format_co_occurrence(self.summary())
        assert "widest sentence: 3 entities (6 edges)" in printed
        assert "Adventurers find themselves in Barovia" in printed

    def test_a_chapter_that_pairs_nothing_says_so_rather_than_printing_nothing(self):
        printed = format_co_occurrence(
            self.summary(co_occurrences=0, co_occurrence_counts=[], widest_sentence=None)
        )
        assert "no sentence in this chapter names two entities" in printed
        assert "0.00 per mention" in printed

    def test_a_chapter_with_no_mentions_does_not_divide_by_zero(self):
        printed = format_co_occurrence(
            self.summary(mentions=0, co_occurrences=0, widest_sentence=None)
        )
        assert "0.00 per mention" in printed

    def test_the_ranking_is_printed_so_a_common_noun_announces_itself(self):
        """`vampire` and `light` are known junk. If either heads this list that
        is a finding about those nodes, and it has to be visible to be found."""
        printed = format_co_occurrence(self.summary())
        assert "JUNK IS NOT FILTERED" in printed
        assert "vampire" in printed


class TestFormatReport:
    def test_a_zero_drop_is_still_printed(self):
        """A silent pass is indistinguishable from a filter that never ran."""
        printed = format_report(FilterReport(candidate_nodes=1, candidate_edges=0))
        assert "self-loops:" in printed
        assert "gazetteer" in printed

    def test_resolutions_are_printed_apart_from_drops(self):
        report = FilterReport(candidate_nodes=1, candidate_edges=1)
        report.endpoint_resolved = 1
        report.resolved_endpoints = ["Ireena -IDENTITY_OF-> Tatyana  ->  cos:x:npc:tatyana"]
        printed = format_report(report)
        assert "KEPT by endpoint resolution (not a drop)" in printed
        assert "constraint-unique endpoint chosen:               1" in printed
        assert "vacuous" in printed
        assert "- resolved: Ireena -IDENTITY_OF-> Tatyana" in printed

    def test_examples_are_capped_but_the_count_is_not(self):
        report = FilterReport(candidate_nodes=40, candidate_edges=0)
        report.gazetteer_dropped = 40
        report.dropped_gazetteer = [f"ITEM thing {i}" for i in range(40)]
        printed = format_report(report)
        assert "keyed place): 40" in printed
        assert "and 32 more" in printed

    def test_the_trust_split_is_printed(self):
        report = FilterReport(candidate_nodes=3, candidate_edges=2)
        report.accepted_nodes, report.proposed_nodes = 2, 1
        report.accepted_edges, report.proposed_edges = 1, 1

        printed = format_report(report)

        assert "nodes:  2 accepted, 1 proposed" in printed
        assert "edges:  1 accepted, 1 proposed" in printed

    def test_every_conflict_is_named_and_none_are_capped(self):
        """A contradiction the graph now holds ON PURPOSE is exactly what a
        human is here to read; capping the list would hide one."""
        report = FilterReport(candidate_nodes=0, candidate_edges=20)
        report.exclusive_conflicts = 20
        report.conflicts = [f"cos:x:npc:a{i} -IDENTITY_OF|RELATED_TO-> b" for i in range(20)]

        printed = format_report(report)

        assert "mutually exclusive pairs:                        20" in printed
        assert printed.count("- conflict:") == 20

    def test_a_zero_conflict_count_is_still_printed(self):
        assert "mutually exclusive pairs:" in format_report(
            FilterReport(candidate_nodes=1, candidate_edges=0)
        )


class TestChapterPlaceFromTheRunBlock:
    """Where the writer learns the chapter's own place.

    `derive_structure` names the parent of every top-level keyed area after the
    chapter title, and the extraction artifact records that title -- so the
    writer re-derives the place with the SAME function the extractor used
    rather than storing a second copy that can drift from it.

    Re-derived rather than added to the `run` block, because that block is the
    extraction's own record of what was paid for and this stage may not rewrite
    it -- and because the three already-extracted chapters would carry no such
    field, so a stored copy would need this fallback anyway.
    """

    def test_the_chapter_prefix_is_stripped(self):
        assert chapter_place_of_run({"chapter": "Chapter 3: The Village of Barovia"}) == (
            "The Village of Barovia"
        )

    def test_a_full_stop_prefix_is_stripped_too(self):
        assert chapter_place_of_run({"chapter": "Chapter 4. Castle Ravenloft"}) == (
            "Castle Ravenloft"
        )

    def test_a_titled_chapter_with_no_number_is_kept_whole(self):
        assert chapter_place_of_run({"chapter": "Introduction"}) == "Introduction"

    def test_a_missing_chapter_title_is_no_place(self):
        """Not a guess and not an error: the anti-fabrication guard in
        `plan_write` drops it again if the chapter keys nothing anyway."""
        assert chapter_place_of_run({}) is None

    def test_a_prefix_with_nothing_after_it_is_no_place(self):
        assert chapter_place_of_run({"chapter": "Chapter 12:"}) is None

    def test_it_agrees_with_the_extractors_own_derivation(self):
        """One function, called by both. Two copies of this rule would put the
        writer's parent name out of step with the deriver's edge, and every
        chapter-level CONTAINS would dangle again with nothing to show for it."""
        title = "Chapter 3: The Village of Barovia"

        assert chapter_place_of_run({"chapter": title}) == place_from_chapter_title(title)
