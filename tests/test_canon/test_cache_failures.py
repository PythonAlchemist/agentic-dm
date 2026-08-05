"""Tests for cache-boundary failures in PageTranscriber.

The cache is meant to be a pure optimization: a broken cache should degrade to
"transcribe (and possibly re-bill) this page," never to an exception that
propagates out of transcribe_page/transcribe_pages, and never to silently
discarding a transcript that was already successfully produced (and billed).
"""

import pytest

from backend.canon.cache import TranscriptCache
from backend.canon.models import PageTranscript
from backend.canon.transcriber import PageTranscriber
from tests.test_canon.test_transcriber import make_client, make_page


class _PutRaisesCache(TranscriptCache):
    """A cache whose put() always fails, simulating e.g. a full disk."""

    def put(self, transcript: PageTranscript) -> None:
        raise OSError("No space left on device")


class TestCorruptSidecar:
    @pytest.mark.asyncio
    async def test_corrupt_json_sidecar_is_a_cache_miss_not_a_crash(self, tmp_path):
        """A corrupt/unparseable JSON sidecar must fall back to re-transcription."""
        cache = TranscriptCache(tmp_path)
        page = make_page()

        cache.pages_dir.mkdir(parents=True, exist_ok=True)
        cache.page_path(page.page_number).write_text("stale markdown")
        cache._meta_path(page.page_number).write_text("{not valid json")

        client = make_client("# Fresh transcription\n\nBody.")
        transcriber = PageTranscriber(cache, client=client)

        result = await transcriber.transcribe_page(page)

        assert result.status == "ok"
        assert result.markdown == "# Fresh transcription\n\nBody."
        client.chat.completions.create.assert_called_once()


class TestCachePutFailure:
    @pytest.mark.asyncio
    async def test_put_failure_still_returns_ok_with_markdown_intact(self, tmp_path):
        """A cache write failure must not destroy an already-billed transcript."""
        cache = _PutRaisesCache(tmp_path)
        client = make_client("# Successfully transcribed\n\nExpensive prose.")
        transcriber = PageTranscriber(cache, client=client)

        result = await transcriber.transcribe_page(make_page())

        assert result.status == "ok"
        assert result.markdown == "# Successfully transcribed\n\nExpensive prose."

    @pytest.mark.asyncio
    async def test_put_failure_via_transcribe_pages_preserves_markdown(self, tmp_path):
        """The batch path must not turn a put() failure into a lost/failed page."""
        cache = _PutRaisesCache(tmp_path)
        client = make_client("# Batch page\n\nContent that must survive.")
        transcriber = PageTranscriber(cache, client=client)

        results = await transcriber.transcribe_pages([make_page()])

        assert len(results) == 1
        assert results[0].status == "ok"
        assert results[0].markdown == "# Batch page\n\nContent that must survive."
