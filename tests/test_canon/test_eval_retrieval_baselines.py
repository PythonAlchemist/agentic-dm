"""Recording a retrieval run so the next comparison is not against a memory.

`evals/baselines/README.md` makes this argument for the ANSWER eval, where a
model makes the number move. Retrieval is deterministic and had no recorder at
all, and the gap bit: a day of graph repair was checked against a remembered
"85%/90%", and settling whether anything had moved meant grepping commit
messages for the last run that happened to print its figures.
"""

import json

from backend.scripts.eval_retrieval import _compare, _outcome, _save


class TestTheThreeOutcomesAreKeptApart:
    """`no-anchor` and `missed` are different repairs -- one needs an alias or
    an entity that was never extracted, the other is ranking or coverage. One
    number blurs them and points a reader at the wrong fix."""

    def test_a_question_that_never_anchored(self):
        assert _outcome({"anchored": False, "hit": False}) == "no-anchor"

    def test_an_anchored_question_that_missed(self):
        assert _outcome({"anchored": True, "hit": False}) == "missed"

    def test_an_anchored_question_that_hit(self):
        assert _outcome({"anchored": True, "hit": True}) == "hit"

    def test_anchoring_is_checked_before_the_hit(self):
        """A hit without an anchor is not a state the scorer produces, and if
        it ever were, calling it a hit would hide the anchoring failure."""
        assert _outcome({"anchored": False, "hit": True}) == "no-anchor"


def _row(*, anchored=True, hit=False, needs="graph"):
    """The shape `score` returns, trimmed to what `summarize` reads."""
    return {"anchored": anchored, "hit": hit, "rr": 1.0 if hit else 0.0,
            "needs": needs, "hit_path": "name" if hit else "",
            "path": "graph" if anchored else "-", "id": "qX",
            "miss_reason": "", "dropped": 0}


def _run(tmp_path, name, outcomes, recall=0.85, anchored_recall=0.9, mrr=0.6):
    path = tmp_path / name
    path.write_text(json.dumps({
        "label": "", "limit": 8, "questions": len(outcomes),
        "recall_overall": recall, "recall_anchored": anchored_recall,
        "anchored": len(outcomes), "mrr": mrr, "by_book": {},
        "outcomes": outcomes,
    }))
    return path


class TestComparingTwoRuns:
    def test_an_identical_run_reports_no_change(self, tmp_path, capsys):
        a = _run(tmp_path, "a.json", {"q1": "hit", "q2": "missed"})
        assert _compare(a, a) == 0
        out = capsys.readouterr().out
        assert "no question changed outcome" in out
        # THE WORD MATTERS. The answer eval must say "indistinguishable";
        # this one may say "identical", and conflating them would import a
        # caveat that does not apply.
        assert "identical rather than indistinguishable" in out

    def test_a_question_that_changed_is_named(self, tmp_path, capsys):
        a = _run(tmp_path, "a.json", {"q1": "missed", "q2": "hit"})
        b = _run(tmp_path, "b.json", {"q1": "hit", "q2": "hit"})
        _compare(a, b)
        out = capsys.readouterr().out
        assert "1 question(s) changed outcome" in out
        assert "q1" in out and "missed -> hit" in out

    def test_a_question_added_or_removed_is_visible(self, tmp_path, capsys):
        """A suite that grew is not a retrieval change, and a comparison that
        silently dropped the new question would read as though it were."""
        a = _run(tmp_path, "a.json", {"q1": "hit"})
        b = _run(tmp_path, "b.json", {"q1": "hit", "q2": "missed"})
        _compare(a, b)
        assert "absent -> missed" in capsys.readouterr().out

    def test_the_headline_figures_are_printed_both_ways(self, tmp_path, capsys):
        a = _run(tmp_path, "a.json", {"q1": "hit"}, recall=0.80)
        b = _run(tmp_path, "b.json", {"q1": "hit"}, recall=0.85)
        _compare(a, b)
        out = capsys.readouterr().out
        assert "80.00% -> 85.00%" in out


class TestWhatIsWritten:
    def test_it_records_outcomes_by_question_id(self, tmp_path):
        rows = [_row(hit=True), _row(anchored=False)]
        questions = [{"id": "q1"}, {"id": "q2"}]
        out = tmp_path / "deep" / "run.json"
        _save(out, "a label", 8, questions, rows, [])
        saved = json.loads(out.read_text())
        assert saved["outcomes"] == {"q1": "hit", "q2": "no-anchor"}
        assert saved["label"] == "a label"

    def test_no_prose_from_either_book_is_written(self, tmp_path):
        """Why these can be committed while everything under `data/` cannot."""
        rows = [_row(hit=True)]
        questions = [{"id": "q1", "question": "Who is Strahd?",
                      "gold": ["cos:castle-ravenloft#1"]}]
        out = tmp_path / "run.json"
        _save(out, "", 8, questions, rows, [])
        body = out.read_text()
        assert "Who is Strahd?" not in body
