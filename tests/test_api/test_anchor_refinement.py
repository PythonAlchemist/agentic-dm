"""Every path that drafts something files it by the same rule.

`suggest_anchor` answers "which section does the subject name most", which is
right 4 times in 10 on the hand-authored cases and wrong in one direction: a
scene about GETTING somewhere files where the party arrives rather than where
they set out. `place_it` asks a model over the closed list of passages the
material was written against, and the chat card already used it -- while
`/lab/generate` and `/homebrew/draft-expansion` kept only the deterministic
answer. The same generation, from the same retrieval, was filed by a better
rule in one tab than the other.
"""

import ast
from pathlib import Path

import pytest

LAB = Path("backend/api/routes/lab.py")
HOMEBREW = Path("backend/api/routes/homebrew.py")


def _calls(path: Path, function: str) -> set[str]:
    """Every function and attribute called inside one handler."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function:
            found = set()
            for inner in ast.walk(node):
                if isinstance(inner, ast.Call):
                    if isinstance(inner.func, ast.Attribute):
                        found.add(inner.func.attr)
                    elif isinstance(inner.func, ast.Name):
                        found.add(inner.func.id)
            return found
    raise AssertionError(f"no {function!r} in {path}")


class TestEveryDraftingPathRefinesItsAnchor:
    @pytest.mark.parametrize("path,handler", [
        (LAB, "generate"),
        (HOMEBREW, "draft_expansion"),
    ])
    def test_it_does_not_stop_at_the_deterministic_guess(self, path, handler):
        calls = _calls(path, handler)
        assert "suggest_anchor" in calls, "the fallback is still there"
        assert "place_it" in calls or "_placed" in calls, (
            f"{handler} files by the 40% rule while the chat card does better"
        )

    def test_the_chat_card_still_does_too(self):
        """The path this was copied FROM. If it ever stops, the others are
        cargo-culting a refinement nothing uses."""
        calls = _calls(Path("backend/agents/dm_agent.py"), "_run_requested_generations")
        assert "place_it" in calls or "suggest_anchor" in calls


class TestABetterAnchorIsNeverWorthAnError:
    """The DM has already paid for the card. A placement call that fails costs
    them a better anchor and nothing else."""

    @pytest.mark.parametrize("path,handler", [
        (LAB, "_placed"),
        (HOMEBREW, "draft_expansion"),
    ])
    def test_the_call_is_wrapped(self, path, handler):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == handler:
                assert any(isinstance(n, ast.Try) for n in ast.walk(node)), (
                    f"{handler} lets a placement failure reach the DM"
                )
                return
        raise AssertionError(f"no {handler!r} in {path}")
