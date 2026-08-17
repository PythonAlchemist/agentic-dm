"""Recording a human's decision on proposed canon."""

import pytest

from backend.scripts.accept_edges import parse_spec


class TestParsingASpec:
    def test_it_splits_on_pipes(self):
        assert parse_spec("Mirabel|OWNS|Blood of the Vine Tavern") == (
            "Mirabel",
            "OWNS",
            "Blood of the Vine Tavern",
        )

    def test_surrounding_space_is_trimmed(self):
        assert parse_spec(" Doru | SERVES | Strahd ") == ("Doru", "SERVES", "Strahd")

    def test_a_name_containing_commas_and_colons_survives(self):
        """`The Blade of Truth: The Uses of Logic in the War Against Diabolist
        Heresies, as Fought by the Ulmist Inquisition` is a real entity in this
        book. A comma-separated spec would shred it -- which is why the
        separator is a pipe, a character the corpus never uses."""
        long_name = "The Blade of Truth: The Uses of Logic, as Fought by the Inquisition"
        assert parse_spec(f"{long_name}|LOCATED_IN|Office") == (
            long_name,
            "LOCATED_IN",
            "Office",
        )

    @pytest.mark.parametrize(
        "spec", ["Mirabel|OWNS", "just some text", "A||B", "|OWNS|B", "A|OWNS|"]
    )
    def test_a_malformed_spec_is_refused_rather_than_half_applied(self, spec):
        """A spec that parses to nonsense would match no edge and report a
        no-op, which reads exactly like an edge that was already accepted."""
        with pytest.raises(ValueError, match="expected"):
            parse_spec(spec)
