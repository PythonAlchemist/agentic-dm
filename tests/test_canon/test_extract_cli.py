"""CLI plumbing. The extraction itself is tested in test_extract.py."""

import asyncio
import json
from dataclasses import asdict, replace

import pytest

import backend.scripts.extract_canon as extract_canon
from backend.canon.extract import EXTRACTION_SEED, anchor_quests, merge_edges
from backend.canon.models import CandidateEdge, CandidateNode, Chapter
from backend.canon.sections import split_sections
from backend.canon.structure import STRUCTURAL_EVIDENCE, structural_edges
from backend.scripts.extract_canon import _gradeable_subset, _known_sources, find_chapter


def _chapters(*chapters: Chapter):
    """A `load_chapters` stand-in that ignores its corpus/splitter arguments.

    `load_chapters` grew `corpus` and keyword-only parameters when the pipeline
    pivoted to the D&D Beyond harvest, and a zero-argument lambda would fail on
    the call rather than on anything these tests are about.
    """
    return lambda *_, **__: list(chapters)


def chapter(title: str) -> Chapter:
    return Chapter(slug="s", title=title, start_page=1, end_page=2, markdown="x")


class TestFindChapter:
    def test_matches_on_a_prefix(self):
        chapters = [chapter("Chapter 3: The Village of Barovia"),
                    chapter("Chapter 4: Castle Ravenloft")]

        assert find_chapter(chapters, "Chapter 3").title.startswith("Chapter 3")

    def test_match_is_case_insensitive(self):
        chapters = [chapter("Chapter 3: The Village of Barovia")]

        assert find_chapter(chapters, "chapter 3") is chapters[0]

    def test_unknown_chapter_raises_with_the_available_titles(self):
        chapters = [chapter("Chapter 3: The Village of Barovia")]

        with pytest.raises(ValueError) as exc:
            find_chapter(chapters, "Chapter 9")
        assert "Chapter 3" in str(exc.value)

    def test_ambiguous_prefix_raises(self):
        chapters = [chapter("Chapter 1: Into the Mists"),
                    chapter("Chapter 10: The Ruins of Berez")]

        with pytest.raises(ValueError):
            find_chapter(chapters, "Chapter 1")


def golden_data(**markers: list[str]) -> dict:
    """A minimal seed dict: one unmarked node (DEFAULT_SOURCE) plus one node
    per extractable_from marker requested."""
    nodes = [{"id": "cos:npc:a", "name": "A", "entity_type": "NPC"}]
    for marker in markers.get("markers", []):
        nodes.append(
            {"id": f"cos:npc:{marker}", "name": marker, "entity_type": "NPC",
             "extractable_from": marker}
        )
    return {"nodes": nodes, "edges": []}


class TestKnownSources:
    def test_default_source_is_always_known(self):
        assert "ch3" in _known_sources(golden_data())

    def test_includes_markers_actually_present_in_the_seed(self):
        assert _known_sources(golden_data(markers=["ch1"])) == ["ch1", "ch3"]

    def test_does_not_claim_a_marker_that_has_no_entries(self):
        """EXTRACTABLE_SOURCES allows ch2, but if nothing in the seed is
        marked ch2, claiming it as available would just move the silent-empty
        bug one level up."""
        assert "ch2" not in _known_sources(golden_data(markers=["ch1"]))


class TestGradeableSubset:
    def test_returns_the_subset_for_a_real_source(self):
        data = golden_data(markers=["ch1"])
        subset = _gradeable_subset(data, "ch3")

        assert len(subset["nodes"]) == 1

    def test_unknown_source_raises_naming_available_sources(self):
        """Measured: --grade ch4, --grade appendix-d, and --grade typo-source
        each printed a perfect 1.00/1.00 recall after a paid run, because
        extractable_subset silently returns nothing for an unmatched marker."""
        data = golden_data(markers=["ch1"])

        with pytest.raises(ValueError) as exc:
            _gradeable_subset(data, "ch4")

        assert "ch4" in str(exc.value)
        assert "ch1" in str(exc.value)
        assert "ch3" in str(exc.value)


def _one_section_chapter() -> Chapter:
    return Chapter(
        slug="chapter-3-the-village-of-barovia",
        title="Chapter 3: The Village of Barovia",
        start_page=80,
        end_page=81,
        markdown="## E1. Shop\n\nBody.",
    )


def _fake_extractor(nodes=None, edges=None, failed=0, rejected_entity_types=0, seen=None):
    """Stands in for CandidateExtractor: canned results, no network call."""

    class _Fake:
        def __init__(self, *a, **kw):
            self.rejected_entity_types = rejected_entity_types
            self.model = "fake-model"
            self.temperature = 0.0

        async def extract_units(self, units, layers=None):
            if seen is not None:
                seen.extend(units)
            return nodes or [], edges or [], failed

    return _Fake


class TestExtractionFailureSignaling:
    """Finding 5: a swallowed API failure must not be indistinguishable from a
    quiet, well-behaved chapter."""

    @pytest.mark.asyncio
    async def test_run_carries_the_failure_count_in_its_summary(self, monkeypatch):
        monkeypatch.setattr(extract_canon, "load_chapters", _chapters(_one_section_chapter()))
        monkeypatch.setattr(extract_canon, "CandidateExtractor", _fake_extractor(failed=3))

        summary = await extract_canon.run("Chapter 3", None, None, None)

        assert summary["failed"] == 3

    def test_main_exits_nonzero_when_any_call_failed(self, monkeypatch):
        monkeypatch.setattr(extract_canon, "load_chapters", _chapters(_one_section_chapter()))
        monkeypatch.setattr(extract_canon, "CandidateExtractor", _fake_extractor(failed=1))
        monkeypatch.setattr("sys.argv", ["extract_canon.py", "Chapter 3"])

        with pytest.raises(SystemExit) as exc:
            extract_canon.main()

        assert exc.value.code != 0

    def test_main_exits_zero_on_a_clean_run(self, monkeypatch):
        monkeypatch.setattr(extract_canon, "load_chapters", _chapters(_one_section_chapter()))
        monkeypatch.setattr(extract_canon, "CandidateExtractor", _fake_extractor(failed=0))
        monkeypatch.setattr("sys.argv", ["extract_canon.py", "Chapter 3"])

        with pytest.raises(SystemExit) as exc:
            extract_canon.main()

        assert exc.value.code == 0

    def test_main_exits_nonzero_and_prints_available_sources_for_a_bad_grade_source(
        self, monkeypatch, capsys
    ):
        monkeypatch.setattr(extract_canon, "load_chapters", _chapters(_one_section_chapter()))
        monkeypatch.setattr(extract_canon, "CandidateExtractor", _fake_extractor())
        monkeypatch.setattr(
            "sys.argv", ["extract_canon.py", "Chapter 3", "--grade", "typo-source"]
        )

        with pytest.raises(SystemExit) as exc:
            extract_canon.main()

        assert exc.value.code != 0
        assert "typo-source" in capsys.readouterr().err

    def test_out_path_is_not_overwritten_when_the_run_had_failures(self, monkeypatch, tmp_path):
        out_path = tmp_path / "candidates.json"
        out_path.write_text('{"last": "good output"}')
        monkeypatch.setattr(extract_canon, "load_chapters", _chapters(_one_section_chapter()))
        monkeypatch.setattr(extract_canon, "CandidateExtractor", _fake_extractor(failed=1))

        asyncio.run(extract_canon.run("Chapter 3", None, None, out_path))

        assert out_path.read_text() == '{"last": "good output"}'

    def test_out_path_is_written_on_a_clean_run(self, monkeypatch, tmp_path):
        out_path = tmp_path / "candidates.json"
        out_path.write_text('{"stale": true}')
        monkeypatch.setattr(extract_canon, "load_chapters", _chapters(_one_section_chapter()))
        monkeypatch.setattr(extract_canon, "CandidateExtractor", _fake_extractor(failed=0))

        asyncio.run(extract_canon.run("Chapter 3", None, None, out_path))

        assert out_path.read_text() != '{"stale": true}'


class TestRejectedEntityTypeReporting:
    """Section 5 of the task-9 brief: rejected counts must be printed before
    the scores whenever non-zero, and never silently swallowed."""

    @pytest.mark.asyncio
    async def test_printed_when_nonzero(self, monkeypatch, capsys):
        monkeypatch.setattr(extract_canon, "load_chapters", _chapters(_one_section_chapter()))
        monkeypatch.setattr(
            extract_canon, "CandidateExtractor", _fake_extractor(rejected_entity_types=3)
        )

        summary = await extract_canon.run("Chapter 3", None, None, None)

        assert "rejected 3 nodes with an unknown entity_type" in capsys.readouterr().out
        assert summary["rejected_entity_types"] == 3

    @pytest.mark.asyncio
    async def test_not_printed_when_zero(self, monkeypatch, capsys):
        monkeypatch.setattr(extract_canon, "load_chapters", _chapters(_one_section_chapter()))
        monkeypatch.setattr(extract_canon, "CandidateExtractor", _fake_extractor())

        await extract_canon.run("Chapter 3", None, None, None)

        assert "unknown entity_type" not in capsys.readouterr().out


def _three_section_chapter() -> Chapter:
    return Chapter(
        slug="chapter-3-the-village-of-barovia",
        title="Chapter 3: The Village of Barovia",
        start_page=80,
        end_page=81,
        markdown="## E1. Shop\n\nA.\n\n## E2. Tavern\n\nB.\n\n## E3. Church\n\nC.",
    )


class TestRunProvenance:
    """Finding 5: a first-ever `--out ch4.json` with 12 of 180 calls rate-limited
    writes a 93%-complete file that is byte-shaped exactly like a clean one. The
    no-clobber guard cannot fire -- there is nothing to clobber -- and stage 2b
    consumes the artifact, not the exit code."""

    def _written(self, monkeypatch, tmp_path, **kw):
        out_path = tmp_path / "candidates.json"
        monkeypatch.setattr(extract_canon, "load_chapters", _chapters(_one_section_chapter()))
        monkeypatch.setattr(extract_canon, "CandidateExtractor", _fake_extractor(**kw))
        asyncio.run(extract_canon.run("Chapter 3", None, None, out_path))
        return json.loads(out_path.read_text())

    def test_the_artifact_records_how_it_was_produced(self, monkeypatch, tmp_path):
        written = self._written(monkeypatch, tmp_path)

        run = written["run"]
        assert run["model"] == "fake-model"
        assert run["temperature"] == 0.0
        assert run["seed"] == EXTRACTION_SEED
        assert run["chapter"] == "Chapter 3: The Village of Barovia"
        assert run["total_calls"] == 3  # 1 unit x 3 layers
        assert run["failed"] == 0

    def test_a_partial_run_is_distinguishable_from_a_clean_one_by_the_file_alone(
        self, monkeypatch, tmp_path
    ):
        written = self._written(monkeypatch, tmp_path, failed=2)

        assert written["run"]["failed"] == 2
        assert written["run"]["complete"] is False

    def test_a_clean_run_says_so(self, monkeypatch, tmp_path):
        assert self._written(monkeypatch, tmp_path)["run"]["complete"] is True


class TestLimit:
    """The try-a-few-first valve on the only path that spends money: chapter 4
    alone is ~84 units x 3 layers."""

    @pytest.mark.asyncio
    async def test_limit_caps_the_units_processed(self, monkeypatch):
        seen: list = []
        monkeypatch.setattr(extract_canon, "load_chapters", _chapters(_three_section_chapter()))
        monkeypatch.setattr(extract_canon, "CandidateExtractor", _fake_extractor(seen=seen))

        summary = await extract_canon.run("Chapter 3", None, None, None, limit=2)

        assert [u.heading for u in seen] == ["E1. Shop", "E2. Tavern"]
        assert summary["units"] == 2

    @pytest.mark.asyncio
    async def test_no_limit_processes_every_unit(self, monkeypatch):
        seen: list = []
        monkeypatch.setattr(extract_canon, "load_chapters", _chapters(_three_section_chapter()))
        monkeypatch.setattr(extract_canon, "CandidateExtractor", _fake_extractor(seen=seen))

        await extract_canon.run("Chapter 3", None, None, None)

        assert len(seen) == 3

    @pytest.mark.asyncio
    async def test_a_limited_run_is_recorded_as_partial(self, monkeypatch, tmp_path):
        """A capped run covers part of the chapter, so its artifact must not
        claim to be a complete extraction of it."""
        out_path = tmp_path / "candidates.json"
        monkeypatch.setattr(extract_canon, "load_chapters", _chapters(_three_section_chapter()))
        monkeypatch.setattr(extract_canon, "CandidateExtractor", _fake_extractor())

        await extract_canon.run("Chapter 3", None, None, out_path, limit=2)

        run = json.loads(out_path.read_text())["run"]
        assert run["units"] == 2
        assert run["units_available"] == 3
        assert run["complete"] is False

    def test_the_flag_is_wired_to_the_parser(self, monkeypatch):
        seen: list = []
        monkeypatch.setattr(extract_canon, "load_chapters", _chapters(_three_section_chapter()))
        monkeypatch.setattr(extract_canon, "CandidateExtractor", _fake_extractor(seen=seen))
        monkeypatch.setattr("sys.argv", ["extract_canon.py", "Chapter 3", "--limit", "1"])

        with pytest.raises(SystemExit):
            extract_canon.main()

        assert len(seen) == 1


class TestCeilingReporting:
    """A ceiling below 1.0 is a defect in the KEY, and the operator must see it
    next to the score without running an experiment."""

    @pytest.mark.asyncio
    async def test_recall_is_printed_against_the_ceiling(self, monkeypatch, capsys):
        monkeypatch.setattr(extract_canon, "load_chapters", _chapters(_one_section_chapter()))
        monkeypatch.setattr(extract_canon, "CandidateExtractor", _fake_extractor())

        summary = await extract_canon.run("Chapter 3", "ch3", None, None)

        out = capsys.readouterr().out
        assert "ceiling:" in out
        assert out.count("ceiling:") == 2, "both node and edge recall carry one"
        assert summary["node_ceiling"] == 1.0
        assert summary["edge_ceiling"] == 1.0


def _sampling_extractor(draws, seen_seeds=None, rejected=0):
    """Stands in for CandidateExtractor across N samples.

    `draws` is one `(nodes, edges, failed)` per sample, handed out by the seed
    the sample was drawn with -- which is how run() distinguishes them.
    """

    class _Fake:
        def __init__(self, *a, seed=EXTRACTION_SEED, **kw):
            self.seed = seed
            self.index = seed - EXTRACTION_SEED
            self.rejected_entity_types = rejected
            self.model = "fake-model"
            self.temperature = 0.0
            if seen_seeds is not None:
                seen_seeds.append(seed)

        async def extract_units(self, units, layers=None):
            nodes, edges, failed = draws[self.index]
            # Fresh objects per sample: the real extractor never hands two
            # samples the same instance, and consensus must not rely on it.
            return [replace(n) for n in nodes], [replace(e) for e in edges], failed

    return _Fake


def _keyed_chapter() -> Chapter:
    """One keyed section, so structural derivation has something to derive."""
    return Chapter(
        slug="chapter-3-the-village-of-barovia",
        title="Chapter 3: The Village of Barovia",
        start_page=80,
        end_page=81,
        markdown="## E1. Blood of the Vine Tavern\n\nBody.",
    )


class TestSampleSeeds:
    """Section 1: five draws at ONE seed would be voting on residual API
    nondeterminism -- the very thing being measured."""

    @pytest.mark.asyncio
    async def test_each_sample_is_drawn_with_its_own_seed(self, monkeypatch):
        seeds: list[int] = []
        monkeypatch.setattr(extract_canon, "load_chapters", _chapters(_one_section_chapter()))
        monkeypatch.setattr(
            extract_canon,
            "CandidateExtractor",
            _sampling_extractor([([], [], 0)] * 3, seen_seeds=seeds),
        )

        await extract_canon.run("Chapter 3", None, None, None, samples=3, node_k=1, edge_k=1)

        assert seeds == [EXTRACTION_SEED, EXTRACTION_SEED + 1, EXTRACTION_SEED + 2]

    @pytest.mark.asyncio
    async def test_a_single_sample_still_uses_the_pinned_seed(self, monkeypatch):
        seeds: list[int] = []
        monkeypatch.setattr(extract_canon, "load_chapters", _chapters(_one_section_chapter()))
        monkeypatch.setattr(
            extract_canon,
            "CandidateExtractor",
            _sampling_extractor([([], [], 0)], seen_seeds=seeds),
        )

        await extract_canon.run("Chapter 3", None, None, None)

        assert seeds == [EXTRACTION_SEED]


class TestConsensusInTheCli:
    @pytest.mark.asyncio
    async def test_a_candidate_in_2_of_3_samples_survives_k2_and_is_dropped_at_k3(
        self, monkeypatch
    ):
        doru = CandidateNode(name="Doru", entity_type="NPC", section_index=0)
        draws = [([doru], [], 0), ([doru], [], 0), ([], [], 0)]
        monkeypatch.setattr(extract_canon, "load_chapters", _chapters(_one_section_chapter()))
        monkeypatch.setattr(extract_canon, "CandidateExtractor", _sampling_extractor(draws))

        at_2 = await extract_canon.run(
            "Chapter 3", None, None, None, samples=3, node_k=2, edge_k=2
        )
        at_3 = await extract_canon.run(
            "Chapter 3", None, None, None, samples=3, node_k=3, edge_k=3
        )

        assert at_2["nodes"] == 1
        assert at_3["nodes"] == 0

    @pytest.mark.asyncio
    async def test_the_vote_histogram_is_printed_before_the_scores(self, monkeypatch, capsys):
        doru = CandidateNode(name="Doru", entity_type="NPC", section_index=0)
        draws = [([doru], [], 0), ([doru], [], 0), ([], [], 0)]
        monkeypatch.setattr(extract_canon, "load_chapters", _chapters(_one_section_chapter()))
        monkeypatch.setattr(extract_canon, "CandidateExtractor", _sampling_extractor(draws))

        await extract_canon.run("Chapter 3", "ch3", None, None, samples=3, node_k=1, edge_k=1)

        out = capsys.readouterr().out
        assert "nodes  by votes: 2:1" in out
        assert "edges  by votes:" in out
        assert out.index("by votes") < out.index("node recall"), "histogram comes first"

    @pytest.mark.asyncio
    async def test_no_histogram_is_printed_for_a_single_sample(self, monkeypatch, capsys):
        monkeypatch.setattr(extract_canon, "load_chapters", _chapters(_one_section_chapter()))
        monkeypatch.setattr(extract_canon, "CandidateExtractor", _fake_extractor())

        await extract_canon.run("Chapter 3", None, None, None)

        assert "by votes" not in capsys.readouterr().out

    @pytest.mark.asyncio
    async def test_the_run_object_records_how_the_vote_was_run(self, monkeypatch, tmp_path):
        out_path = tmp_path / "candidates.json"
        monkeypatch.setattr(extract_canon, "load_chapters", _chapters(_one_section_chapter()))
        monkeypatch.setattr(
            extract_canon, "CandidateExtractor", _sampling_extractor([([], [], 0)] * 3)
        )

        await extract_canon.run(
            "Chapter 3", None, None, out_path, samples=3, node_k=2, edge_k=3
        )

        run = json.loads(out_path.read_text())["run"]
        assert run["samples"] == 3
        assert run["node_k"] == 2
        assert run["edge_k"] == 3
        assert run["seeds"] == [EXTRACTION_SEED, EXTRACTION_SEED + 1, EXTRACTION_SEED + 2]

    @pytest.mark.asyncio
    async def test_surviving_candidates_carry_their_vote_count_into_the_artifact(
        self, monkeypatch, tmp_path
    ):
        """Stage 2b weights by it, and it reads the artifact, not stdout."""
        out_path = tmp_path / "candidates.json"
        doru = CandidateNode(name="Doru", entity_type="NPC", section_index=0)
        monkeypatch.setattr(extract_canon, "load_chapters", _chapters(_one_section_chapter()))
        monkeypatch.setattr(
            extract_canon, "CandidateExtractor", _sampling_extractor([([doru], [], 0)] * 3)
        )

        await extract_canon.run(
            "Chapter 3", None, None, out_path, samples=3, node_k=2, edge_k=2
        )

        written = json.loads(out_path.read_text())
        assert [n["votes"] for n in written["nodes"]] == [3]

    def test_the_flags_are_wired_to_the_parser(self, monkeypatch, tmp_path):
        out_path = tmp_path / "candidates.json"
        monkeypatch.setattr(extract_canon, "load_chapters", _chapters(_one_section_chapter()))
        monkeypatch.setattr(
            extract_canon, "CandidateExtractor", _sampling_extractor([([], [], 0)] * 4)
        )
        monkeypatch.setattr(
            "sys.argv",
            ["extract_canon.py", "Chapter 3", "--samples", "4", "--node-k", "2",
             "--edge-k", "3", "-o", str(out_path)],
        )

        with pytest.raises(SystemExit):
            extract_canon.main()

        run = json.loads(out_path.read_text())["run"]
        assert (run["samples"], run["node_k"], run["edge_k"]) == (4, 2, 3)

    @pytest.mark.asyncio
    async def test_a_k_no_sample_count_can_satisfy_is_called_out(self, monkeypatch, capsys):
        """k=5 over 3 contributing samples silently empties the run. That must
        not read as 'the chapter contained nothing'."""
        monkeypatch.setattr(extract_canon, "load_chapters", _chapters(_one_section_chapter()))
        monkeypatch.setattr(
            extract_canon, "CandidateExtractor", _sampling_extractor([([], [], 0)] * 3)
        )

        await extract_canon.run(
            "Chapter 3", None, None, None, samples=3, node_k=5, edge_k=5
        )

        assert "no candidate can reach" in capsys.readouterr().out

    @pytest.mark.asyncio
    async def test_the_unreachable_k_warning_names_only_the_side_it_applies_to(
        self, monkeypatch, capsys
    ):
        """node_k and edge_k are separate knobs. With node_k=1 and edge_k=5 over
        3 samples only the edge set is emptied, and a warning that claimed the
        whole result was empty would overstate."""
        monkeypatch.setattr(extract_canon, "load_chapters", _chapters(_one_section_chapter()))
        monkeypatch.setattr(
            extract_canon, "CandidateExtractor", _sampling_extractor([([], [], 0)] * 3)
        )

        await extract_canon.run(
            "Chapter 3", None, None, None, samples=3, node_k=1, edge_k=5
        )

        out = capsys.readouterr().out
        assert "edge_k=5 over 3 voting sample(s)" in out
        assert "node_k" not in out, "node_k=1 is reachable and must not be warned about"


class TestFailedSamplesAreExcluded:
    """Section 3: a truncated sample makes every candidate in it look rarer
    than it is, so it must not become a weaker vote -- it must not vote."""

    def _draws(self):
        ghost = CandidateNode(name="Ghost", entity_type="NPC", section_index=0)
        doru = CandidateNode(name="Doru", entity_type="NPC", section_index=0)
        return [
            ([doru], [], 0),
            ([doru, ghost], [], 2),  # this sample lost 2 calls
            ([doru, ghost], [], 0),
        ]

    @pytest.mark.asyncio
    async def test_a_failed_sample_casts_no_vote(self, monkeypatch, tmp_path):
        out_path = tmp_path / "candidates.json"
        monkeypatch.setattr(extract_canon, "load_chapters", _chapters(_one_section_chapter()))
        monkeypatch.setattr(
            extract_canon, "CandidateExtractor", _sampling_extractor(self._draws())
        )

        await extract_canon.run(
            "Chapter 3", None, None, out_path, samples=3, node_k=2, edge_k=2
        )

        written = json.loads(out_path.read_text())
        names = [n["name"] for n in written["nodes"]]
        assert names == ["Doru"], "Ghost's two sightings include the excluded sample"
        assert [n["votes"] for n in written["nodes"]] == [2], (
            "Doru must not be credited with a vote from the excluded sample"
        )

    @pytest.mark.asyncio
    async def test_the_excluded_sample_is_named_on_stdout(self, monkeypatch, capsys):
        monkeypatch.setattr(extract_canon, "load_chapters", _chapters(_one_section_chapter()))
        monkeypatch.setattr(
            extract_canon, "CandidateExtractor", _sampling_extractor(self._draws())
        )

        await extract_canon.run(
            "Chapter 3", None, None, None, samples=3, node_k=2, edge_k=2
        )

        out = capsys.readouterr().out
        assert "sample 2" in out
        assert "FAILED" in out
        assert "excluded" in out.lower()

    @pytest.mark.asyncio
    async def test_the_artifact_records_which_samples_voted(self, monkeypatch, tmp_path):
        out_path = tmp_path / "candidates.json"
        monkeypatch.setattr(extract_canon, "load_chapters", _chapters(_one_section_chapter()))
        monkeypatch.setattr(
            extract_canon, "CandidateExtractor", _sampling_extractor(self._draws())
        )

        await extract_canon.run(
            "Chapter 3", None, None, out_path, samples=3, node_k=2, edge_k=2
        )

        run = json.loads(out_path.read_text())["run"]
        assert run["sample_failures"] == [0, 2, 0]
        assert run["samples_voting"] == 2
        assert run["complete"] is False

    @pytest.mark.asyncio
    async def test_an_excluded_sample_does_not_block_the_write(self, monkeypatch, tmp_path):
        """The no-clobber guard asks whether THIS OUTPUT is truncated. After
        exclusion the candidates came only from clean samples, so refusing to
        write throws away every paid call in the run -- on chapter 4 that is
        ~2,205 calls, where one failure somewhere is close to expected."""
        out_path = tmp_path / "candidates.json"
        out_path.write_text('{"last": "good output"}')
        monkeypatch.setattr(extract_canon, "load_chapters", _chapters(_one_section_chapter()))
        monkeypatch.setattr(
            extract_canon, "CandidateExtractor", _sampling_extractor(self._draws())
        )

        await extract_canon.run(
            "Chapter 3", None, None, out_path, samples=3, node_k=2, edge_k=2
        )

        written = json.loads(out_path.read_text())
        assert [n["name"] for n in written["nodes"]] == ["Doru"]
        assert written["run"]["failed"] == 2, "the failure is still recorded, not hidden"
        assert written["run"]["complete"] is False

    @pytest.mark.asyncio
    async def test_every_sample_failing_still_blocks_the_write(self, monkeypatch, tmp_path):
        """Nothing voted, so the artifact would be empty -- and an empty
        artifact must not clobber a good one."""
        out_path = tmp_path / "candidates.json"
        out_path.write_text('{"last": "good output"}')
        monkeypatch.setattr(extract_canon, "load_chapters", _chapters(_one_section_chapter()))
        monkeypatch.setattr(
            extract_canon, "CandidateExtractor", _sampling_extractor([([], [], 1)] * 3)
        )

        summary = await extract_canon.run(
            "Chapter 3", None, None, out_path, samples=3, node_k=1, edge_k=1
        )

        assert out_path.read_text() == '{"last": "good output"}'
        assert summary["samples_voting"] == 0
        assert summary["nodes"] == 0

    @pytest.mark.asyncio
    async def test_every_sample_failing_writes_a_first_artifact_marked_incomplete(
        self, monkeypatch, tmp_path
    ):
        """With nothing to clobber the artifact is still written, and reading it
        must be enough to tell it apart from a chapter that was simply quiet."""
        out_path = tmp_path / "candidates.json"
        monkeypatch.setattr(extract_canon, "load_chapters", _chapters(_one_section_chapter()))
        monkeypatch.setattr(
            extract_canon, "CandidateExtractor", _sampling_extractor([([], [], 1)] * 3)
        )

        await extract_canon.run(
            "Chapter 3", None, None, out_path, samples=3, node_k=1, edge_k=1
        )

        run = json.loads(out_path.read_text())["run"]
        assert run["samples_voting"] == 0
        assert run["complete"] is False

    @pytest.mark.asyncio
    async def test_rejected_entity_types_are_counted_only_for_voting_samples(
        self, monkeypatch, capsys
    ):
        """A candidate rejected inside an excluded sample never reached the
        output, so counting it describes candidates this run did not produce."""
        monkeypatch.setattr(extract_canon, "load_chapters", _chapters(_one_section_chapter()))
        monkeypatch.setattr(
            extract_canon,
            "CandidateExtractor",
            _sampling_extractor([([], [], 0), ([], [], 1), ([], [], 0)], rejected=4),
        )

        summary = await extract_canon.run(
            "Chapter 3", None, None, None, samples=3, node_k=1, edge_k=1
        )

        assert summary["rejected_entity_types"] == 8, "two voting samples, not three"
        assert "rejected 8 nodes" in capsys.readouterr().out

    @pytest.mark.asyncio
    async def test_a_single_sample_run_is_not_excluded_by_its_own_failure(
        self, monkeypatch
    ):
        """Present behaviour: a partial single run still writes its candidates,
        flagged partial. Excluding it would turn a degraded run into an empty
        one."""
        doru = CandidateNode(name="Doru", entity_type="NPC", section_index=0)
        monkeypatch.setattr(extract_canon, "load_chapters", _chapters(_one_section_chapter()))
        monkeypatch.setattr(
            extract_canon, "CandidateExtractor", _sampling_extractor([([doru], [], 2)])
        )

        summary = await extract_canon.run("Chapter 3", None, None, None)

        assert summary["nodes"] == 1
        assert summary["failed"] == 2


class TestSingleSamplePathIsUntouched:
    def _draw(self):
        # A duplicate within the one sample: consensus would collapse it, and
        # the single-run path must not.
        doru = CandidateNode(name="Doru", entity_type="NPC", section_index=0)
        return [doru, CandidateNode(name="Doru", entity_type="NPC", section_index=0)], [
            CandidateEdge(
                source_name="Doru",
                target_name="Donavich",
                rel_type="RELATED_TO",
                section_index=0,
            )
        ]

    @pytest.mark.asyncio
    async def test_samples_1_matches_the_pre_consensus_composition_candidate_for_candidate(
        self, monkeypatch, tmp_path
    ):
        out_path = tmp_path / "candidates.json"
        nodes, edges = self._draw()
        chapter = _keyed_chapter()
        monkeypatch.setattr(extract_canon, "load_chapters", _chapters(chapter))
        monkeypatch.setattr(
            extract_canon, "CandidateExtractor", _sampling_extractor([(nodes, edges, 0)])
        )

        await extract_canon.run("Chapter 3", None, None, out_path)

        # The pipeline as it stood before consensus existed: extract, derive,
        # merge, anchor -- with no vote in between.
        sections = split_sections(chapter)
        derived = structural_edges(
            sections, nodes, extract_canon.chapter_place(chapter, sections)
        )
        expected_nodes, expected_edges, _, _ = anchor_quests(
            nodes, merge_edges(edges, derived)
        )
        written = json.loads(out_path.read_text())
        assert written["nodes"] == [asdict(n) for n in expected_nodes]
        assert written["edges"] == [asdict(e) for e in expected_edges]

    @pytest.mark.asyncio
    async def test_samples_1_neither_deduplicates_nor_stamps_votes(self, monkeypatch, tmp_path):
        out_path = tmp_path / "candidates.json"
        nodes, edges = self._draw()
        monkeypatch.setattr(extract_canon, "load_chapters", _chapters(_keyed_chapter()))
        monkeypatch.setattr(
            extract_canon, "CandidateExtractor", _sampling_extractor([(nodes, edges, 0)])
        )

        await extract_canon.run("Chapter 3", None, None, out_path)

        written = json.loads(out_path.read_text())
        assert [n["name"] for n in written["nodes"]] == ["Doru", "Doru"]
        assert {n["votes"] for n in written["nodes"]} == {0}


class TestStructuralEdgesAreDerivedAfterTheVote:
    """The ordering constraint. Derived edges are deterministic given a node
    set, so voting on them would be voting on one computation five times, and
    the derived layer would look weakly supported when it is not sampled at
    all."""

    @pytest.mark.asyncio
    async def test_derivation_runs_once_over_the_consensus_node_set(self, monkeypatch):
        calls: list[list[CandidateNode]] = []
        real = extract_canon.derive_structure

        def spy(sections, nodes, place):
            calls.append(list(nodes))
            return real(sections, nodes, place)

        agreed = CandidateNode(name="Rope", entity_type="ITEM", section_index=0)
        lone = CandidateNode(name="Phantom", entity_type="ITEM", section_index=0)
        draws = [([agreed, lone], [], 0), ([agreed], [], 0), ([agreed], [], 0)]
        monkeypatch.setattr(extract_canon, "load_chapters", _chapters(_keyed_chapter()))
        monkeypatch.setattr(extract_canon, "derive_structure", spy)
        monkeypatch.setattr(extract_canon, "CandidateExtractor", _sampling_extractor(draws))

        await extract_canon.run(
            "Chapter 3", None, None, None, samples=3, node_k=2, edge_k=2
        )

        assert len(calls) == 1, "one derivation, not one per sample"
        assert [n.name for n in calls[0]] == ["Rope"], (
            "a node that lost the vote must not still seed a derived edge"
        )

    @pytest.mark.asyncio
    async def test_a_derived_edge_survives_a_k_no_sample_count_could_reach(
        self, monkeypatch, tmp_path
    ):
        """edge_k=5 over 3 samples: any derived edge that had been put through
        the vote would carry 3 votes and be discarded here."""
        out_path = tmp_path / "candidates.json"
        agreed = CandidateNode(name="Rope", entity_type="ITEM", section_index=0)
        monkeypatch.setattr(extract_canon, "load_chapters", _chapters(_keyed_chapter()))
        monkeypatch.setattr(
            extract_canon, "CandidateExtractor", _sampling_extractor([([agreed], [], 0)] * 3)
        )

        await extract_canon.run(
            "Chapter 3", None, None, out_path, samples=3, node_k=3, edge_k=5
        )

        written = json.loads(out_path.read_text())
        derived = [e for e in written["edges"] if e["evidence"] == STRUCTURAL_EVIDENCE]
        # *Refitted 2026-08-17*: asserted through the chapter's own CONTAINS.
        # This used to look for `Rope LOCATED_IN Blood of the Vine Tavern`, a
        # node-derived placement that no longer exists -- "named in a section"
        # is not "present in that room". The property under test is unchanged:
        # a derived edge bypasses the vote entirely, so no `edge_k` can reach it.
        assert (
            "The Village of Barovia",
            "CONTAINS",
            "Blood of the Vine Tavern",
        ) in [(e["source_name"], e["rel_type"], e["target_name"]) for e in derived]
        assert {e["votes"] for e in derived} == {0}, (
            "0 means never voted on, not 'agreed by nobody'"
        )


class TestDroppedQuestReporting:
    """anchor_quests runs at chapter level, after all layer passes and the
    derived structural edges are merged in -- see run()."""

    @pytest.mark.asyncio
    async def test_printed_when_nonzero(self, monkeypatch, capsys):
        orphan_quest = CandidateNode(name="Free Doru", entity_type="QUEST", layer="narrative")
        orphan_edge = CandidateEdge(
            source_name="Free Doru", target_name="Undercroft", rel_type="OBJECTIVE_AT"
        )
        monkeypatch.setattr(extract_canon, "load_chapters", _chapters(_one_section_chapter()))
        monkeypatch.setattr(
            extract_canon,
            "CandidateExtractor",
            _fake_extractor(nodes=[orphan_quest], edges=[orphan_edge]),
        )

        summary = await extract_canon.run("Chapter 3", None, None, None)

        out = capsys.readouterr().out
        assert "dropped 1 unanchored QUEST nodes" in out
        assert "1 edge" in out, "the edges that went with them must be counted too"
        assert summary["dropped_quests"] == 1
        assert summary["dropped_edges"] == 1
        assert summary["nodes"] == 0

    @pytest.mark.asyncio
    async def test_not_printed_when_zero(self, monkeypatch, capsys):
        monkeypatch.setattr(extract_canon, "load_chapters", _chapters(_one_section_chapter()))
        monkeypatch.setattr(extract_canon, "CandidateExtractor", _fake_extractor())

        await extract_canon.run("Chapter 3", None, None, None)

        assert "unanchored QUEST" not in capsys.readouterr().out
