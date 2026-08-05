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
