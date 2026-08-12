"""The CLI around the write path: what it reads, and what it leaves on disk.

No Neo4j and no API calls: everything asserted here is a property of the
argument parser, the artifact reader, or the run artifact the verifier reads.
"""

import json
from pathlib import Path

import pytest

from backend.canon.models import CandidateNode
from backend.canon.writer import FilterReport, WriteEdge, WriteNode
from backend.graph.schema import RelationshipType
from backend.scripts.write_canon import (
    DEFAULT_GAZETTEER,
    DEFAULT_RUNS_DIR,
    build_parser,
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

    def test_defaults_point_at_the_paths_the_verifier_uses(self):
        args = build_parser().parse_args(["ch3.json", "--chapter", SLUG])
        assert args.runs_dir == DEFAULT_RUNS_DIR
        assert args.gazetteer == DEFAULT_GAZETTEER
        assert str(DEFAULT_RUNS_DIR) == "data/canon/runs"


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
                WriteNode(id="a", name="Church", entity_type="LOCATION", chapter_slug=SLUG),
                WriteNode(id="b", name="Undercroft", entity_type="LOCATION", chapter_slug=SLUG),
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
        ):
            assert key in filters, key

    def test_written_counts_are_broken_down_by_type(self):
        write = self.build()["write"]
        assert write["written_nodes_by_type"] == {"LOCATION": 2}
        assert write["written_edges_by_type"] == {"LOCATED_IN": 1}

    def test_the_artifact_is_json_serialisable(self):
        json.dumps(self.build())


class TestFormatReport:
    def test_a_zero_drop_is_still_printed(self):
        """A silent pass is indistinguishable from a filter that never ran."""
        printed = format_report(FilterReport(candidate_nodes=1, candidate_edges=0))
        assert "self-loops:" in printed
        assert "gazetteer" in printed

    def test_examples_are_capped_but_the_count_is_not(self):
        report = FilterReport(candidate_nodes=40, candidate_edges=0)
        report.gazetteer_dropped = 40
        report.dropped_gazetteer = [f"ITEM thing {i}" for i in range(40)]
        printed = format_report(report)
        assert "keyed place): 40" in printed
        assert "and 32 more" in printed
