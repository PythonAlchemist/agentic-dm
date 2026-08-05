"""Tests for vision page transcription."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.canon.cache import TranscriptCache
from backend.canon.models import PageImage, PageTranscript
from backend.canon.transcriber import PageTranscriber


def make_page(page_number: int = 61, sha: str = "a" * 64) -> PageImage:
    return PageImage(
        page_number=page_number,
        image_bytes=b"fake-image-bytes",
        ext="png",
        width=1278,
        height=1800,
        sha256=sha,
    )


def make_client(markdown: str = "# Heading\n\nBody.") -> MagicMock:
    """A mock AsyncOpenAI whose completion returns `markdown`."""
    message = MagicMock()
    message.content = markdown
    choice = MagicMock()
    choice.message = message
    usage = MagicMock()
    usage.prompt_tokens = 1105
    usage.completion_tokens = 900
    response = MagicMock()
    response.choices = [choice]
    response.usage = usage

    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=response)
    return client


class TestPageTranscriber:
    @pytest.mark.asyncio
    async def test_transcribes_a_page(self, tmp_path):
        client = make_client("# Village of Barovia\n\nProse.")
        transcriber = PageTranscriber(TranscriptCache(tmp_path), client=client)

        result = await transcriber.transcribe_page(make_page())

        assert result.status == "ok"
        assert result.markdown == "# Village of Barovia\n\nProse."
        assert result.page_number == 61
        assert result.input_tokens == 1105
        assert result.output_tokens == 900

    @pytest.mark.asyncio
    async def test_result_is_cached(self, tmp_path):
        cache = TranscriptCache(tmp_path)
        client = make_client()
        await PageTranscriber(cache, client=client).transcribe_page(make_page())

        assert cache.get(61, "a" * 64) is not None

    @pytest.mark.asyncio
    async def test_cache_hit_skips_the_api(self, tmp_path):
        cache = TranscriptCache(tmp_path)
        cache.put(
            PageTranscript(
                page_number=61,
                markdown="cached",
                image_sha256="a" * 64,
                model="gpt-4o",
            )
        )
        client = make_client()
        transcriber = PageTranscriber(cache, client=client)

        result = await transcriber.transcribe_page(make_page())

        assert result.markdown == "cached"
        client.chat.completions.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_failure_is_isolated_not_raised(self, tmp_path):
        client = MagicMock()
        client.chat.completions.create = AsyncMock(side_effect=RuntimeError("boom"))
        transcriber = PageTranscriber(TranscriptCache(tmp_path), client=client)

        result = await transcriber.transcribe_page(make_page())

        assert result.status == "failed"
        assert "boom" in result.error
        assert result.markdown == ""

    @pytest.mark.asyncio
    async def test_one_failure_does_not_abort_the_batch(self, tmp_path):
        ok = make_client().chat.completions.create.return_value
        client = MagicMock()
        client.chat.completions.create = AsyncMock(
            side_effect=[ok, RuntimeError("boom"), ok]
        )
        transcriber = PageTranscriber(TranscriptCache(tmp_path), client=client)

        results = await transcriber.transcribe_pages(
            [make_page(1, "a" * 64), make_page(2, "b" * 64), make_page(3, "c" * 64)]
        )

        assert [r.page_number for r in results] == [1, 2, 3]
        assert [r.status for r in results] == ["ok", "failed", "ok"]

    @pytest.mark.asyncio
    async def test_empty_choices_yields_failed_not_raised(self, tmp_path):
        response = MagicMock()
        response.choices = []
        response.usage = MagicMock(prompt_tokens=10, completion_tokens=0)
        client = MagicMock()
        client.chat.completions.create = AsyncMock(return_value=response)
        transcriber = PageTranscriber(TranscriptCache(tmp_path), client=client)

        result = await transcriber.transcribe_page(make_page())

        assert result.status == "failed"
        assert result.markdown == ""
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_usage_none_yields_failed_not_raised(self, tmp_path):
        message = MagicMock()
        message.content = "some text"
        choice = MagicMock()
        choice.message = message
        response = MagicMock()
        response.choices = [choice]
        response.usage = None
        client = MagicMock()
        client.chat.completions.create = AsyncMock(return_value=response)
        transcriber = PageTranscriber(TranscriptCache(tmp_path), client=client)

        result = await transcriber.transcribe_page(make_page())

        assert result.status == "failed"
        assert result.markdown == ""
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_batch_with_malformed_response_returns_one_transcript_per_page(
        self, tmp_path
    ):
        ok = make_client().chat.completions.create.return_value
        malformed = MagicMock()
        malformed.choices = []
        malformed.usage = MagicMock(prompt_tokens=10, completion_tokens=0)
        client = MagicMock()
        client.chat.completions.create = AsyncMock(side_effect=[ok, malformed, ok])
        transcriber = PageTranscriber(TranscriptCache(tmp_path), client=client)

        results = await transcriber.transcribe_pages(
            [make_page(1, "a" * 64), make_page(2, "b" * 64), make_page(3, "c" * 64)]
        )

        assert [r.page_number for r in results] == [1, 2, 3]
        assert [r.status for r in results] == ["ok", "failed", "ok"]

    @pytest.mark.asyncio
    async def test_sends_image_as_data_url(self, tmp_path):
        client = make_client()
        await PageTranscriber(TranscriptCache(tmp_path), client=client).transcribe_page(
            make_page()
        )

        kwargs = client.chat.completions.create.call_args.kwargs
        content = kwargs["messages"][0]["content"]
        image_part = next(p for p in content if p["type"] == "image_url")
        assert image_part["image_url"]["url"].startswith("data:image/png;base64,")
