"""The model's own tools read the session's book, and only that one.

`CanonRetriever` is emphatic that a session reads ONE book, and paid for the
rule in measurements: a second book's passages cost 91 of 758 passage slots and
dropped MRR from 0.61 to 0.56. The tools the model drives were book-blind, so
it could resolve `Strahd` inside a Golden Vault session, expand his edges, and
fold Barovia into the subgraph -- which is the session's memory, so the bleed
then persisted across turns.

`passages` also rebuilt section ids as `f"cos:{chapter}#{index}"`, the book slug
hardcoded, so every id it returned for the second book named a section that does
not exist.
"""

import pytest

from backend.agents import graph_tools


class TestTheBookIsTheCallersNotTheModels:
    def test_it_is_applied_after_the_models_arguments(self, monkeypatch):
        """A tool call must not be able to reach into the other book by asking
        for it -- the caller holds the book, the model holds the question."""
        seen = {}
        monkeypatch.setitem(
            graph_tools.TOOLS, "resolve",
            lambda **kw: seen.update(kw) or graph_tools.Result(rows=()),
        )
        graph_tools.call("resolve", {"name": "Strahd", "book": "cos"}, book="kftgv")
        assert seen["book"] == "kftgv"

    def test_no_book_leaves_the_call_untouched(self, monkeypatch):
        """Canon-only callers that genuinely span books still work."""
        seen = {}
        monkeypatch.setitem(
            graph_tools.TOOLS, "resolve",
            lambda **kw: seen.update(kw) or graph_tools.Result(rows=()),
        )
        graph_tools.call("resolve", {"name": "Strahd"})
        assert "book" not in seen

    def test_an_unknown_tool_is_still_an_error(self):
        """Not a no-op: a model naming a tool that does not exist has
        misunderstood what it was offered, and an empty result would let it
        conclude the graph holds nothing."""
        with pytest.raises(KeyError):
            graph_tools.call("no_such_tool", {}, book="cos")


class TestExpandStaysInsideTheBook:
    def _rows(self, monkeypatch, rows, book):
        class _Session:
            def run(self, *_a, **_k):
                return [dict(r) for r in rows]

            def __enter__(self): return self
            def __exit__(self, *_): return False

        monkeypatch.setattr(graph_tools, "read_only_session", lambda: _Session())
        return graph_tools.expand("cos:strahd", book=book).rows

    def test_an_edge_reaching_the_other_book_is_dropped(self, monkeypatch):
        rows = [
            {"other_id": "cos:ireena", "other": "Ireena", "status": "accepted"},
            {"other_id": "kftgv:vault", "other": "Vault", "status": "accepted"},
        ]
        kept = self._rows(monkeypatch, rows, "cos")
        assert [r["other_id"] for r in kept] == ["cos:ireena"]

    def test_without_a_book_nothing_is_dropped(self, monkeypatch):
        rows = [
            {"other_id": "cos:ireena", "other": "Ireena", "status": "accepted"},
            {"other_id": "kftgv:vault", "other": "Vault", "status": "accepted"},
        ]
        assert len(self._rows(monkeypatch, rows, None)) == 2

    def test_accepted_still_sorts_before_proposed(self, monkeypatch):
        """A model reading a truncated list should meet the derived facts
        before the guesses."""
        rows = [
            {"other_id": "cos:a", "other": "A", "status": "proposed"},
            {"other_id": "cos:b", "other": "B", "status": "accepted"},
        ]
        kept = self._rows(monkeypatch, rows, "cos")
        assert [r["status"] for r in kept] == ["accepted", "proposed"]
