"""Judging a proposed edge against the sentence the extractor cited.

Pure: what a verdict may be, what is refused, and how a rate is computed. The
model call is one function and is not tested here; what IS tested is that
nothing it returns is counted unchecked, because the output of this is a
NUMBER and a number built from unchecked answers is worse than no number.
"""

from backend.canon.edge_check import (
    Verdict,
    parse,
    precision,
    render,
)


class TestNothingIsCountedUnchecked:
    OFFERED = ["e1", "e2"]

    def test_a_clean_verdict_is_kept(self):
        got, refused = parse(
            '{"verdicts":[{"key":"e1","verdict":"supported","why":"states it"},'
            '{"key":"e2","verdict":"reversed","why":"other way round"}]}',
            self.OFFERED,
        )
        assert refused == []
        assert [v.verdict for v in got] == ["supported", "reversed"]

    def test_a_verdict_for_an_unasked_edge_is_refused(self):
        got, refused = parse(
            '{"verdicts":[{"key":"e9","verdict":"supported"}]}', self.OFFERED
        )
        assert got == []
        assert "nobody asked about" in refused[0]

    def test_a_word_that_is_not_a_verdict_is_refused(self):
        _, refused = parse(
            '{"verdicts":[{"key":"e1","verdict":"probably"}]}', self.OFFERED
        )
        assert "is not a verdict" in refused[0]

    def test_an_edge_asked_about_and_not_answered_is_reported(self):
        """A missing measurement is not a pass. Counting it as one would make
        the rate better the more the model skipped."""
        _, refused = parse(
            '{"verdicts":[{"key":"e1","verdict":"supported"}]}', self.OFFERED
        )
        assert any("no verdict returned" in r for r in refused)

    def test_one_edge_judged_twice_is_counted_once(self):
        got, refused = parse(
            '{"verdicts":[{"key":"e1","verdict":"supported"},'
            '{"key":"e1","verdict":"unsupported"}]}',
            ["e1"],
        )
        assert len(got) == 1
        assert any("judged twice" in r for r in refused)

    def test_an_unparseable_response_is_reported_not_raised(self):
        got, refused = parse("not json", self.OFFERED)
        assert got == []
        assert "unparseable" in refused[0]


class TestWhatTheRateMeans:
    def test_reversed_counts_as_wrong(self):
        """A real relationship pointing the wrong way reads as a fact, and is a
        different fact."""
        assert Verdict("e", "reversed").wrong
        assert Verdict("e", "unsupported").wrong
        assert not Verdict("e", "supported").wrong

    def test_unclear_is_excluded_from_the_rate_not_counted_against_it(self):
        """An unreadable sentence says nothing about whether the extractor was
        right. Folding it into either column moves the number for a reason that
        is not about edges."""
        tally = precision([
            Verdict("a", "supported"), Verdict("b", "unsupported"),
            Verdict("c", "unclear"), Verdict("d", "unclear"),
        ])
        assert tally["decided"] == 2
        assert tally["supported_rate"] == 0.5

    def test_a_sample_with_nothing_decided_has_no_rate(self):
        """`None`, not 0.0 or 1.0 -- a rate nobody could compute is not a rate
        of zero."""
        assert precision([Verdict("a", "unclear")])["supported_rate"] is None

    def test_no_verdicts_at_all_has_no_rate(self):
        assert precision([])["supported_rate"] is None


class TestWhatTheModelIsShown:
    def test_the_claim_and_its_sentence_travel_together(self):
        block = render([{
            "key": "e1", "source": "Ismark", "rel_type": "OPPOSES",
            "target": "Ireena", "evidence": "Ismark guards his sister Ireena.",
        }])
        assert "Ismark -OPPOSES-> Ireena" in block
        assert "Ismark guards his sister Ireena." in block
        assert "key: e1" in block
