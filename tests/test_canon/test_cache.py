"""Tests for the canon transcript cache."""

import pytest

from backend.canon.cache import TranscriptCache
from backend.canon.models import PageTranscript


@pytest.fixture
def transcript():
    return PageTranscript(
        page_number=61,
        markdown="# Village of Barovia\n\nText.",
        image_sha256="a" * 64,
        model="gpt-4o",
        input_tokens=1105,
        output_tokens=900,
    )


class TestTranscriptCache:
    def test_get_returns_none_on_miss(self, tmp_path):
        cache = TranscriptCache(tmp_path)
        assert cache.get(61, "a" * 64) is None

    def test_put_then_get_roundtrip(self, tmp_path, transcript):
        cache = TranscriptCache(tmp_path)
        cache.put(transcript)

        got = cache.get(61, "a" * 64)
        assert got is not None
        assert got.markdown == transcript.markdown
        assert got.page_number == 61
        assert got.model == "gpt-4o"

    def test_hash_mismatch_is_a_miss(self, tmp_path, transcript):
        """A changed source image must invalidate the cached page."""
        cache = TranscriptCache(tmp_path)
        cache.put(transcript)

        assert cache.get(61, "b" * 64) is None

    def test_writes_human_readable_markdown(self, tmp_path, transcript):
        cache = TranscriptCache(tmp_path)
        cache.put(transcript)

        assert cache.page_path(61).read_text() == transcript.markdown

    def test_failed_transcripts_are_not_cached(self, tmp_path):
        """A failure must not poison the cache and block a later retry."""
        cache = TranscriptCache(tmp_path)
        cache.put(
            PageTranscript(
                page_number=7,
                markdown="",
                image_sha256="c" * 64,
                model="gpt-4o",
                status="failed",
                error="timeout",
            )
        )

        assert cache.get(7, "c" * 64) is None


class TestGetBest:
    def test_prefers_the_transcript_with_more_structure(self, tmp_path):
        """The source PDF repeats every page, and the two transcriptions differ.

        Keeping whichever came first discarded better-structured text: chapter 3
        lost two keyed sections that way.
        """
        cache = TranscriptCache(tmp_path)
        cache.put(
            PageTranscript(
                page_number=80,
                markdown="Some prose with no headings at all.",
                image_sha256="a" * 64,
                model="gpt-4o",
            )
        )
        cache.put(
            PageTranscript(
                page_number=81,
                markdown="## E1. Bildrath's Mercantile\n\nProse.\n\n## E2. Tavern\n\nMore.",
                image_sha256="a" * 64,
                model="gpt-4o",
            )
        )

        best = cache.get_best([80, 81], "a" * 64)

        assert best is not None
        assert best.page_number == 81

    def test_falls_back_to_length_when_structure_ties(self, tmp_path):
        cache = TranscriptCache(tmp_path)
        cache.put(PageTranscript(80, "short", "b" * 64, "gpt-4o"))
        cache.put(PageTranscript(81, "considerably longer prose here", "b" * 64, "gpt-4o"))

        assert cache.get_best([80, 81], "b" * 64).page_number == 81

    def test_returns_none_when_nothing_is_cached(self, tmp_path):
        assert TranscriptCache(tmp_path).get_best([1, 2], "c" * 64) is None

    def test_a_single_page_still_works(self, tmp_path):
        cache = TranscriptCache(tmp_path)
        cache.put(PageTranscript(5, "body", "d" * 64, "gpt-4o"))

        assert cache.get_best([5], "d" * 64).page_number == 5
