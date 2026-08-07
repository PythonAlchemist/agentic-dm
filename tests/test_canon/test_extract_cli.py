"""CLI plumbing. The extraction itself is tested in test_extract.py."""

import asyncio

import pytest

import backend.scripts.extract_canon as extract_canon
from backend.canon.models import CandidateNode, Chapter
from backend.scripts.extract_canon import _gradeable_subset, _known_sources, find_chapter


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


def _fake_extractor(nodes=None, edges=None, failed=0, rejected_entity_types=0):
    """Stands in for CandidateExtractor: canned results, no network call."""

    class _Fake:
        def __init__(self, *a, **kw):
            self.rejected_entity_types = rejected_entity_types

        async def extract_units(self, units, layers=None):
            return nodes or [], edges or [], failed

    return _Fake


class TestExtractionFailureSignaling:
    """Finding 5: a swallowed API failure must not be indistinguishable from a
    quiet, well-behaved chapter."""

    @pytest.mark.asyncio
    async def test_run_carries_the_failure_count_in_its_summary(self, monkeypatch):
        monkeypatch.setattr(extract_canon, "load_chapters", lambda: [_one_section_chapter()])
        monkeypatch.setattr(extract_canon, "CandidateExtractor", _fake_extractor(failed=3))

        summary = await extract_canon.run("Chapter 3", None, None, None)

        assert summary["failed"] == 3

    def test_main_exits_nonzero_when_any_call_failed(self, monkeypatch):
        monkeypatch.setattr(extract_canon, "load_chapters", lambda: [_one_section_chapter()])
        monkeypatch.setattr(extract_canon, "CandidateExtractor", _fake_extractor(failed=1))
        monkeypatch.setattr("sys.argv", ["extract_canon.py", "Chapter 3"])

        with pytest.raises(SystemExit) as exc:
            extract_canon.main()

        assert exc.value.code != 0

    def test_main_exits_zero_on_a_clean_run(self, monkeypatch):
        monkeypatch.setattr(extract_canon, "load_chapters", lambda: [_one_section_chapter()])
        monkeypatch.setattr(extract_canon, "CandidateExtractor", _fake_extractor(failed=0))
        monkeypatch.setattr("sys.argv", ["extract_canon.py", "Chapter 3"])

        with pytest.raises(SystemExit) as exc:
            extract_canon.main()

        assert exc.value.code == 0

    def test_main_exits_nonzero_and_prints_available_sources_for_a_bad_grade_source(
        self, monkeypatch, capsys
    ):
        monkeypatch.setattr(extract_canon, "load_chapters", lambda: [_one_section_chapter()])
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
        monkeypatch.setattr(extract_canon, "load_chapters", lambda: [_one_section_chapter()])
        monkeypatch.setattr(extract_canon, "CandidateExtractor", _fake_extractor(failed=1))

        asyncio.run(extract_canon.run("Chapter 3", None, None, out_path))

        assert out_path.read_text() == '{"last": "good output"}'

    def test_out_path_is_written_on_a_clean_run(self, monkeypatch, tmp_path):
        out_path = tmp_path / "candidates.json"
        out_path.write_text('{"stale": true}')
        monkeypatch.setattr(extract_canon, "load_chapters", lambda: [_one_section_chapter()])
        monkeypatch.setattr(extract_canon, "CandidateExtractor", _fake_extractor(failed=0))

        asyncio.run(extract_canon.run("Chapter 3", None, None, out_path))

        assert out_path.read_text() != '{"stale": true}'


class TestRejectedEntityTypeReporting:
    """Section 5 of the task-9 brief: rejected counts must be printed before
    the scores whenever non-zero, and never silently swallowed."""

    @pytest.mark.asyncio
    async def test_printed_when_nonzero(self, monkeypatch, capsys):
        monkeypatch.setattr(extract_canon, "load_chapters", lambda: [_one_section_chapter()])
        monkeypatch.setattr(
            extract_canon, "CandidateExtractor", _fake_extractor(rejected_entity_types=3)
        )

        summary = await extract_canon.run("Chapter 3", None, None, None)

        assert "rejected 3 nodes with an unknown entity_type" in capsys.readouterr().out
        assert summary["rejected_entity_types"] == 3

    @pytest.mark.asyncio
    async def test_not_printed_when_zero(self, monkeypatch, capsys):
        monkeypatch.setattr(extract_canon, "load_chapters", lambda: [_one_section_chapter()])
        monkeypatch.setattr(extract_canon, "CandidateExtractor", _fake_extractor())

        await extract_canon.run("Chapter 3", None, None, None)

        assert "unknown entity_type" not in capsys.readouterr().out


class TestDroppedQuestReporting:
    """anchor_quests runs at chapter level, after all layer passes and the
    derived structural edges are merged in -- see run()."""

    @pytest.mark.asyncio
    async def test_printed_when_nonzero(self, monkeypatch, capsys):
        orphan_quest = CandidateNode(name="Free Doru", entity_type="QUEST")
        monkeypatch.setattr(extract_canon, "load_chapters", lambda: [_one_section_chapter()])
        monkeypatch.setattr(
            extract_canon, "CandidateExtractor", _fake_extractor(nodes=[orphan_quest])
        )

        summary = await extract_canon.run("Chapter 3", None, None, None)

        assert "dropped 1 unanchored QUEST nodes" in capsys.readouterr().out
        assert summary["dropped_quests"] == 1
        assert summary["nodes"] == 0

    @pytest.mark.asyncio
    async def test_not_printed_when_zero(self, monkeypatch, capsys):
        monkeypatch.setattr(extract_canon, "load_chapters", lambda: [_one_section_chapter()])
        monkeypatch.setattr(extract_canon, "CandidateExtractor", _fake_extractor())

        await extract_canon.run("Chapter 3", None, None, None)

        assert "unanchored QUEST" not in capsys.readouterr().out
