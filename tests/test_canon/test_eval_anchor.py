"""Scoring where a generated scene would be filed.

`evals/anchor-cases.yaml` was written carefully -- multi-accept semantics, a
`why` on every case -- and nothing read it. A measurement that never runs is a
design document, and this one describes the weakest link in the store flow.
"""

from backend.scripts.eval_anchor import render, score, summarize


def _case(accept, cid="a01"):
    return {"id": cid, "subject": "a scene", "why": "because", "accept": accept}


class TestEveryDefensibleAnswerCounts:
    """The seed's own rule, and not a softening: a beat can honestly sit in
    more than one place, and insisting on a single id would score good
    suggestions as failures."""

    def test_the_first_acceptable_id_hits(self):
        row = score(_case(["ch#4", "ch#5"]), "ch#4", ("ch",))
        assert row["hit"]

    def test_a_later_acceptable_id_hits_too(self):
        row = score(_case(["ch#4", "ch#5"]), "ch#5", ("ch",))
        assert row["hit"]

    def test_an_unacceptable_id_does_not(self):
        assert not score(_case(["ch#4"]), "ch#9", ("ch",))["hit"]

    def test_suggesting_nothing_does_not(self):
        assert not score(_case(["ch#4"]), "", ())["hit"]


class TestTheTwoWaysOfBeingWrongAreKeptApart:
    """Right chapter and wrong beat is a ranking problem; another adventure
    entirely is the anthology rule not holding. A single pass rate hides
    which, and points a reader at the wrong repair."""

    def test_the_right_chapter_is_recorded(self):
        row = score(_case(["kftgv:prisoner-13#7"]), "kftgv:prisoner-13#8", ())
        assert not row["hit"] and row["right_chapter"]

    def test_another_chapter_is_not(self):
        row = score(_case(["cos:into-the-valley#0"]), "cos:castle-ravenloft#11", ())
        assert not row["hit"] and not row["right_chapter"]

    def test_nothing_suggested_is_not_the_right_chapter(self):
        assert not score(_case(["ch#4"]), "", ())["right_chapter"]

    def test_they_are_counted_separately(self):
        rows = [
            score(_case(["a#1"], "c1"), "a#1", ()),
            score(_case(["a#1"], "c2"), "a#2", ()),
            score(_case(["a#1"], "c3"), "b#1", ()),
        ]
        found = summarize(rows)
        assert found["hits"] == 1
        assert found["right_chapter_wrong_beat"] == 1
        assert found["elsewhere"] == 1

    def test_a_near_miss_is_still_a_miss(self):
        """A DM still has to move the card."""
        rows = [score(_case(["a#1"]), "a#2", ())]
        assert summarize(rows)["rate"] == 0.0


class TestWhatAReaderIsShown:
    def test_a_miss_carries_its_reasoning(self):
        """A bare "6/10" says nothing about which way the suggestion was
        wrong; the seed's `why` is the whole point of writing one."""
        rows = [score(_case(["a#1"]), "b#1", ())]
        shown = render(rows, summarize(rows))
        assert "because" in shown and "b#1" in shown

    def test_an_empty_suggestion_reads_as_nothing(self):
        rows = [score(_case(["a#1"]), "", ())]
        assert "(nothing)" in render(rows, summarize(rows))

    def test_no_cases_does_not_divide_by_zero(self):
        assert summarize([])["rate"] == 0.0
