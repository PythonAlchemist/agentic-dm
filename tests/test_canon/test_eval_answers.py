"""The answer harness's scoring, with no model and no money.

The whole rule is substring tests against hand-authored strings, so it can be
checked against strings. What cannot be checked here -- whether the strings are
the RIGHT ones -- is a reading, and the notes in `evals/canon-answers.yaml`
carry the answer beside each check so a reader can do it.
"""

from pathlib import Path

import pytest
import yaml

from backend.scripts.eval_answers import check, render, spend_of, verdict

ANSWERS = Path("evals/canon-answers.yaml")


class TestChecking:
    def test_an_answer_holding_every_required_string_passes(self):
        q = {"id": "a", "must": ["Alenka", "Mirabel"]}
        assert verdict(check(q, "Alenka and Mirabel own it. [1]")) == "pass"

    def test_one_missing_string_is_a_failure(self):
        """All three tavern owners are required, because naming one is the
        shape of an answer written from the passage's first sentence."""
        q = {"id": "a", "must": ["Alenka", "Mirabel", "Sorvia"]}
        row = check(q, "Alenka owns it. [1]")
        assert row["missing"] == ["Mirabel", "Sorvia"]
        assert verdict(row) == "FAIL"

    def test_matching_ignores_case(self):
        q = {"id": "a", "must": ["Rahadin"]}
        assert check(q, "his chamberlain is RAHADIN [1]")["missing"] == []

    def test_a_tripwire_string_appearing_is_a_failure(self):
        """`Strahd KNOWS Davian Martikov` is a guessed edge that reaches the
        chamberlain question. Davian is not the chamberlain, so his name in
        that answer means a relationship list was read as an answer."""
        q = {"id": "a", "must": ["Rahadin"], "must_not": ["Davian"]}
        row = check(q, "Rahadin, though Davian Martikov also serves him. [1]")
        assert row["tripped"] == ["Davian"]
        assert verdict(row) == "FAIL"

    def test_a_required_citation_that_is_absent_is_a_failure(self):
        q = {"id": "a", "must": ["Rahadin"], "cites": True}
        row = check(q, "His chamberlain is Rahadin.")
        assert row["uncited"] is True
        assert verdict(row) == "FAIL"

    def test_a_citation_is_not_required_unless_asked_for(self):
        q = {"id": "a", "must": ["Rahadin"]}
        assert check(q, "His chamberlain is Rahadin.")["uncited"] is False


class TestRefusalIsNeverScored:
    """The one fuzzy check, and it decides a reading queue rather than a score."""

    def test_a_refusal_question_is_never_marked_pass(self):
        q = {"id": "a", "refuses": True}
        assert verdict(check(q, "The canon does not cover it.")) == "read it"

    def test_a_refusal_question_is_never_marked_fail_either(self):
        """Even an answer that plainly invented something is only queued for a
        human. A heuristic that could FAIL a run would be deciding the score."""
        q = {"id": "a", "refuses": True}
        assert verdict(check(q, "The beholder has AC 18 and 180 hit points.")) == "read it"

    def test_the_heuristic_still_reports_what_it_saw(self):
        q = {"id": "a", "refuses": True}
        assert check(q, "The canon does not cover it.")["refusal_looks_present"] is True
        assert check(q, "It has AC 18.")["refusal_looks_present"] is False

    def test_refusals_are_counted_apart_from_the_scored_questions(self):
        rows = [
            check({"id": "a1", "must": ["x"]}, "x"),
            check({"id": "a2", "refuses": True}, "the canon does not cover it"),
        ]
        out = render(rows)
        assert "passed every run     1/1" in out
        assert "needing a reading    1" in out

    def test_how_often_it_declined_is_reported_across_runs(self):
        q = {"id": "a1", "refuses": True}
        rows = [
            check(q, "the canon does not cover it"),
            check(q, "It has AC 18 and 180 hit points."),
        ]
        assert "declined 1/2" in render(rows, repeat=2)


class TestRepeatedRuns:
    """One run of this suite is not a measurement, and the suite found that out
    about itself: the same question cited its section on one call and not on the
    next."""

    def test_a_question_passing_sometimes_is_flagged_inconsistent(self):
        q = {"id": "a1", "must": ["Rahadin"], "cites": True}
        rows = [check(q, "Rahadin [1]"), check(q, "Rahadin")]
        out = render(rows, repeat=2)
        assert "1/2" in out
        assert "INCONSISTENT" in out

    def test_a_question_passing_every_run_is_not_flagged(self):
        q = {"id": "a1", "must": ["Rahadin"]}
        out = render([check(q, "Rahadin"), check(q, "Rahadin")], repeat=2)
        assert "INCONSISTENT" not in out

    def test_a_question_failing_every_run_is_not_flagged_as_flaky_either(self):
        """Consistently broken is a different problem from flaky, and reporting
        it as flakiness would send someone looking for a race."""
        q = {"id": "a1", "must": ["Rahadin"]}
        out = render([check(q, "nobody"), check(q, "nobody")], repeat=2)
        assert "INCONSISTENT" not in out
        assert "0/2" in out

    def test_the_gap_between_always_and_ever_is_the_flakiness(self):
        solid = {"id": "a1", "must": ["x"]}
        flaky = {"id": "a2", "must": ["y"]}
        rows = [
            check(solid, "x"), check(solid, "x"),
            check(flaky, "y"), check(flaky, "nope"),
        ]
        out = render(rows, repeat=2)
        assert "passed every run     1/2" in out
        assert "passed at least one  2/2" in out

    def test_the_reason_shown_is_from_a_failing_run_not_a_passing_one(self):
        """A flaky question reporting its passing run's reason would print `-`
        and read as healthy."""
        q = {"id": "a1", "must": ["Rahadin"], "cites": True}
        out = render([check(q, "Rahadin [1]"), check(q, "Rahadin")], repeat=2)
        assert "no citation" in out


class TestReadingTheCost:
    """A run that cannot price itself has to say so.

    The first version read a key called `total`, which does not exist, and fell
    back to 0.0 -- so a run that had spent real money printed `$0.0000`. That is
    the exact failure `pricing.estimate` refuses to commit by returning `None`,
    committed instead by the caller.
    """

    def test_a_priced_call_reports_its_dollars(self):
        assert spend_of({"usd": 0.0123, "model": "m"}) == pytest.approx(0.0123)

    def test_an_unpriced_call_is_none_and_not_zero(self):
        assert spend_of({"usd": None, "model": "m", "unpriced": True}) is None

    def test_a_missing_cost_block_is_none_and_not_zero(self):
        assert spend_of(None) is None
        assert spend_of({}) is None

    def test_zero_is_still_zero_and_not_confused_with_unknown(self):
        """A genuinely free call and an unpriceable one are different facts."""
        assert spend_of({"usd": 0.0}) == 0.0


class TestTheAuthoredSet:
    @pytest.fixture(scope="class")
    def questions(self):
        return yaml.safe_load(ANSWERS.read_text())["questions"]

    def test_every_question_is_checkable_somehow(self, questions):
        """A question with no `must`, no `must_not` and no `refuses` scores
        `pass` on every possible answer, including an empty one."""
        vacuous = [
            q["id"]
            for q in questions
            if not (q.get("must") or q.get("must_not") or q.get("refuses"))
        ]
        assert not vacuous

    def test_every_question_carries_its_hand_checked_answer(self, questions):
        """The note is what lets a reader judge the check instead of trusting
        it -- the same reason `canon-questions.yaml` requires one."""
        assert not [q["id"] for q in questions if not q.get("note", "").strip()]

    def test_ids_are_unique(self, questions):
        ids = [q["id"] for q in questions]
        assert len(ids) == len(set(ids))

    def test_a_refusal_question_asks_for_nothing_it_also_forbids(self, questions):
        """`refuses` and `must` together would be incoherent: an answer cannot
        both decline and state the fact."""
        assert not [q["id"] for q in questions if q.get("refuses") and q.get("must")]
