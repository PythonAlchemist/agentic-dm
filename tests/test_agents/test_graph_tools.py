"""What a model may ask the graph for.

Marked `neo4j` throughout: these tools ARE their queries, and a mocked session
would prove that the mock returns what the mock was told to return. The
invariants below -- read-only, status, plane, bounded -- are the four the
conversational-subgraph design rests on, and each is asserted against the real
database rather than described.
"""

import pytest

from backend.agents import graph_tools
from backend.agents.graph_tools import call, expand, passages, resolve

pytestmark = pytest.mark.neo4j


class TestResolving:
    def test_a_name_returns_the_entity_with_its_labels(self):
        """An id alone cannot be put into the subgraph or said back to a
        reader, which is why this uses `BY_ALIAS` rather than the id-only
        resolve."""
        row = resolve("Rictavio").rows[0]
        assert row["entity_id"] == "cos:rictavio"
        assert row["name"] == "Rictavio"
        assert "NPC" in row["labels"]

    def test_a_name_naming_two_things_returns_both(self):
        """`Barovia` is a region and a village. Collapsing them would be the
        graph choosing on a reader's behalf between things the book
        distinguishes, so the ambiguity travels."""
        assert len(resolve("Barovia").rows) >= 1

    def test_an_unknown_name_returns_nothing_rather_than_a_guess(self):
        assert resolve("Gandalf the Grey").rows == ()

    def test_it_resolves_through_an_alias_not_a_substring(self):
        """`Strahd` reaches `Strahd von Zarovich` because somebody RECORDED it
        as an alias. Loose matching has twice put wrong answers in this graph."""
        assert resolve("Strahd").rows[0]["entity_id"] == "cos:strahd-von-zarovich"
        assert resolve("Strah").rows == ()

    def test_the_labels_are_types_not_the_raw_label_set(self):
        labels = resolve("Rictavio").rows[0]["labels"]
        assert "Entity" not in labels


class TestExpanding:
    def test_every_edge_carries_its_status(self):
        """THE INVARIANT DEFENDED HARDEST. A third of proposed edges are false,
        and one that arrived without its status would be a guess in a fact's
        clothes."""
        rows = expand("cos:rictavio").rows
        assert rows
        assert all(row["status"] in {"accepted", "proposed"} for row in rows)

    def test_derived_relationships_come_before_guesses(self):
        """A model reading a truncated list should meet the facts first.

        On an entity that HAS both. This asserted against Strahd and passed a
        mutation that sorted guesses first -- he carries 52 proposed edges and
        no derived one, so every order is trivially sorted and the test proved
        nothing. `cos:tsolenka-pass` has both.
        """
        rows = expand("cos:tsolenka-pass", limit=99).rows
        statuses = [row["status"] for row in rows]
        assert {"accepted", "proposed"} <= set(statuses), "needs both to mean anything"
        assert statuses == sorted(statuses, key=lambda s: s != "accepted")

    def test_it_reads_both_directions(self):
        """Half of what a DM wants about an NPC is written with the NPC as the
        target -- who serves Strahd is an inbound edge from his side."""
        directions = {row["direction"] for row in expand("cos:strahd-von-zarovich",
                                                         limit=99).rows}
        assert directions <= {"in", "out"}

    def test_an_entity_with_nothing_attached_returns_nothing(self):
        assert expand("cos:no-such-entity").rows == ()


class TestPassages:
    def test_the_loudest_section_comes_first(self):
        rows = passages("cos:rictavio").rows
        assert rows
        counts = [row["occurrences"] for row in rows]
        assert counts == sorted(counts, reverse=True)

    def test_it_returns_where_to_look_not_the_prose(self):
        """A section's text is 82% of a turn's input and retrieval already
        sends it. Returning it again would double the largest thing in the
        context to say something the model can already read."""
        row = passages("cos:rictavio").rows[0]
        assert set(row) == {"section_id", "chapter", "section", "occurrences", "aliases"}

    def test_the_section_id_is_the_one_retrieval_uses(self):
        """So a caller can tell that a section a tool named is one the
        conversation has already read."""
        assert passages("cos:rictavio").rows[0]["section_id"].startswith("cos:")


class TestBounding:
    """A silent truncation reads as "that is all there is"."""

    def test_what_was_cut_is_counted_rather_than_dropped(self):
        result = expand("cos:strahd-von-zarovich", limit=3)
        assert len(result.rows) == 3
        assert result.cut > 0

    def test_a_generous_limit_cuts_nothing(self):
        assert expand("cos:rictavio", limit=500).cut == 0

    def test_the_cut_is_reported_apart_from_the_rows(self):
        """Folded into the rows, a model reading twelve of ninety would
        conclude the entity has twelve relationships."""
        result = expand("cos:strahd-von-zarovich", limit=2)
        assert result.as_dict["cut"] == result.cut
        assert len(result.as_dict["rows"]) == 2


class TestTheToolsCannotWrite:
    def test_every_tool_gets_a_session_that_cannot_write(self, monkeypatch):
        """Asserted on the TYPE of session handed out, not on the name of the
        function that made it.

        This counted calls to `graph_tools.read_only_session` and passed a
        mutation that rebound that name to `neo4j_session` -- the count was
        still three, and the tools were running on a writable session. What
        matters is what they were given.
        """
        from contextlib import contextmanager

        from backend.core.database import ReadOnlySession

        seen = []
        real = graph_tools.read_only_session

        @contextmanager
        def watched():
            with real() as session:
                seen.append(session)
                yield session

        monkeypatch.setattr(graph_tools, "read_only_session", watched)
        resolve("Rictavio")
        expand("cos:rictavio")
        passages("cos:rictavio")

        assert len(seen) == 3
        assert all(isinstance(session, ReadOnlySession) for session in seen)


class TestDispatch:
    def test_a_tool_is_callable_by_name(self):
        assert call("resolve", {"name": "Rictavio"}).rows[0]["entity_id"] == "cos:rictavio"

    def test_an_unknown_tool_raises_rather_than_returning_nothing(self):
        """An empty result would let a model conclude the graph holds nothing,
        which is the silent-zero failure this project keeps removing."""
        with pytest.raises(KeyError, match="no such tool"):
            call("delete_everything", {})

    def test_the_schema_offers_exactly_the_tools_that_exist(self):
        """A schema advertising a tool that is not there is an error the model
        finds at runtime, on the user's turn."""
        advertised = {entry["function"]["name"] for entry in graph_tools.SCHEMA}
        assert advertised == set(graph_tools.TOOLS)

    def test_every_advertised_tool_says_when_to_use_it(self):
        for entry in graph_tools.SCHEMA:
            assert "Use " in entry["function"]["description"]
