"""Tests for the canon ingestion CLI."""

import pytest

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
