"""Estimating what a call cost, and refusing to when the table cannot say."""

from datetime import date

import pytest
import yaml

from backend.core import pricing


@pytest.fixture
def table(tmp_path):
    path = tmp_path / "pricing.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "models": {
                    "cheap": {"input_per_1m": 1.0, "output_per_1m": 2.0,
                              "last_verified": "2026-01-15"},
                    "unchecked": {"input_per_1m": 3.0, "output_per_1m": 4.0,
                                  "last_verified": None},
                    "half-priced": {"input_per_1m": 1.0, "last_verified": None},
                }
            },
            # Without this, safe_dump sorts the keys and the order test asserts
            # alphabetical order rather than the file's -- passing for a reason
            # that has nothing to do with the code.
            sort_keys=False,
        )
    )
    return path


class TestUsage:
    def test_it_reads_an_openai_usage_block(self):
        class R:
            usage = type("U", (), {"prompt_tokens": 100, "completion_tokens": 20})()

        usage = pricing.Usage.from_response(R())
        assert (usage.input_tokens, usage.output_tokens, usage.total) == (100, 20, 120)

    def test_a_response_with_no_usage_reads_as_zero_not_as_a_guess(self):
        """A streamed or mocked response carries none. Zero shows as zero on the
        dashboard rather than as a plausible number nobody can source."""
        usage = pricing.Usage.from_response(object())
        assert usage.total == 0


class TestEstimate:
    def test_the_arithmetic_is_per_million_tokens(self, table):
        cost = pricing.estimate(
            "cheap", pricing.Usage(input_tokens=1_000_000, output_tokens=500_000), table
        )
        assert cost.usd == pytest.approx(1.0 + 1.0)

    def test_input_and_output_are_priced_separately(self, table):
        """Output costs more than input on every vendor, so a single blended
        rate would misprice every call that generates more than it reads."""
        heavy_in = pricing.estimate("cheap", pricing.Usage(1_000_000, 0), table)
        heavy_out = pricing.estimate("cheap", pricing.Usage(0, 1_000_000), table)
        assert heavy_out.usd > heavy_in.usd

    def test_a_model_absent_from_the_table_has_no_price(self, table):
        """Falling back to another model's rate, or to zero, produces a number
        wrong in a direction nobody can see."""
        cost = pricing.estimate("unknown", pricing.Usage(1000, 100), table)
        assert cost.usd is None
        assert cost.unpriced is True

    def test_a_half_filled_entry_is_unpriced_rather_than_half_counted(self, table):
        cost = pricing.estimate("half-priced", pricing.Usage(1000, 1000), table)
        assert cost.usd is None
        assert cost.unpriced is True

    def test_the_verification_date_travels_with_the_estimate(self, table):
        cost = pricing.estimate("cheap", pricing.Usage(1000, 100), table)
        assert cost.last_verified == date(2026, 1, 15)
        assert cost.verified is True

    def test_an_unverified_rate_still_produces_a_cost_but_says_it_is_unverified(
        self, table
    ):
        """A price nobody has checked is still what somebody is about to spend.
        Hiding it would be worse than showing it with a warning."""
        cost = pricing.estimate("unchecked", pricing.Usage(1_000_000, 0), table)
        assert cost.usd == pytest.approx(3.0)
        assert cost.verified is False

    def test_the_shipped_table_is_unverified_until_a_human_says_otherwise(self):
        """Every rate in `pricing.yaml` was written from memory by an assistant
        that cannot check a vendor's page. Until someone confirms them, the
        dashboard must say so."""
        assert all(m["last_verified"] is None for m in pricing.models())


class TestModelListing:
    def test_the_files_order_is_kept_so_the_cheapest_is_offered_first(self, table):
        assert [m["id"] for m in pricing.models(table)] == [
            "cheap",
            "unchecked",
            "half-priced",
        ]
