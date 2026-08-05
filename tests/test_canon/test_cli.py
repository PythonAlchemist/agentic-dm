"""Tests for the canon ingestion CLI."""

import pytest

import backend.scripts.ingest_canon as ingest_canon
from backend.canon.cache import TranscriptCache
from backend.canon.models import PageImage, PageTranscript
from backend.scripts.ingest_canon import estimate_cost, parse_page_range


class TestParsePageRange:
    def test_parses_inclusive_range(self):
        assert list(parse_page_range("40-42")) == [40, 41, 42]

    def test_parses_single_page(self):
        assert list(parse_page_range("61")) == [61]

    def test_rejects_reversed_range(self):
        with pytest.raises(ValueError):
            parse_page_range("50-40")

    def test_rejects_garbage(self):
        with pytest.raises(ValueError):
            parse_page_range("abc")


class TestEstimateCost:
    def test_scales_with_page_count(self):
        one = estimate_cost(1)
        many = estimate_cost(509)

        assert many["total_usd"] > one["total_usd"]
        assert many["pages"] == 509

    def test_full_book_is_in_the_expected_range(self):
        """The spec budgets ~$6.75 for transcription of 509 pages."""
        estimate = estimate_cost(509)
        assert 5.0 < estimate["total_usd"] < 9.0


class _FakeExtractor:
    """Stands in for PageExtractor: no PDF file, no fitz, just two pages."""

    def __init__(self, pdf_path):
        self.pdf_path = pdf_path

    @property
    def page_count(self) -> int:
        return 2

    def extract(self, pages=None):
        yield PageImage(
            page_number=60, image_bytes=b"a", ext="png", width=1, height=1, sha256="hash60"
        )
        yield PageImage(
            page_number=61, image_bytes=b"b", ext="png", width=1, height=1, sha256="hash61"
        )

    def close(self):
        pass


class _FakeTranscriber:
    """Stands in for PageTranscriber: cache-first, never touches the network."""

    def __init__(self, cache, client=None, model=None, concurrency=8):
        self.cache = cache

    async def transcribe_pages(self, pages):
        results = []
        for page in pages:
            cached = self.cache.get(page.page_number, page.sha256)
            if cached is not None:
                results.append(cached)
                continue
            fresh = PageTranscript(
                page_number=page.page_number,
                markdown=f"# Page {page.page_number}\n\nfresh content",
                image_sha256=page.sha256,
                model="gpt-4o",
                status="ok",
                input_tokens=100,
                output_tokens=50,
            )
            self.cache.put(fresh)
            results.append(fresh)
        return sorted(results, key=lambda t: t.page_number)


class TestRunCostAccounting:
    """Covers ingest_canon.run(): cache hits must not re-inflate the cost sum.

    No network call happens here: PageExtractor and PageTranscriber are
    replaced with fakes, and the real AsyncOpenAI client is never constructed.
    """

    @pytest.mark.asyncio
    async def test_cached_pages_excluded_from_cost_sum(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ingest_canon.settings, "canon_dir", tmp_path)
        monkeypatch.setattr(ingest_canon, "PageExtractor", _FakeExtractor)
        monkeypatch.setattr(ingest_canon, "PageTranscriber", _FakeTranscriber)

        book_slug = "test-book"
        # Pre-populate the cache for page 60 with a deliberately huge token
        # count. If a cache hit ever leaks into the cost sum, this makes the
        # failure obvious rather than a rounding-sized false pass.
        cache = TranscriptCache(tmp_path / book_slug)
        cache.put(
            PageTranscript(
                page_number=60,
                markdown="# Chapter One\n\ncached content",
                image_sha256="hash60",
                model="gpt-4o",
                status="ok",
                input_tokens=1_000_000,
                output_tokens=1_000_000,
            )
        )

        summary = await ingest_canon.run(
            pdf_path=tmp_path / "fake.pdf",
            book_slug=book_slug,
            pages=None,
            concurrency=1,
            skip_embed=True,
        )

        # Only page 61 (the fresh, non-cached page) should be billed.
        expected_usd = round(
            100 / 1_000_000 * ingest_canon.INPUT_RATE
            + 50 / 1_000_000 * ingest_canon.OUTPUT_RATE,
            2,
        )
        assert summary["usd"] == expected_usd
        assert summary["pages"] == 2
