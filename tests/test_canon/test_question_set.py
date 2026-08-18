"""The question set is the instrument. Nothing checked the instrument.

Every number this project reports about retrieval is measured against these
labels, and two of them were wrong for months: q21 ("Where are the Vistani
camps?") and q22 ("Who are Strahd's undead enemies in Barovia?") both pointed
at the section headed "Dream Pastries" -- the gold belonging to q13 and q14
directly above them in the file. Neither could be hit by any retrieval, and
both sat in the `anchored but missed` bucket, which is the bucket that says
RANKING is what needs fixing. Two rounds of ranking work were aimed partly at
questions that had no reachable answer.

What follows is what a MACHINE can check about a label. It cannot check that a
gold section answers its question -- that is a reading, and a human did it once
for all 46 -- but a gold that names no real section, or that silently agrees
with a neighbour's, is a defect a test can catch, and both are the shape the
real error took.
"""

from pathlib import Path

import pytest
import yaml

QUESTIONS = Path("evals/canon-questions.yaml")


@pytest.fixture(scope="module")
def questions() -> list[dict]:
    return yaml.safe_load(QUESTIONS.read_text())["questions"]


class TestTheLabelsAreWellFormed:
    """No database needed: these are properties of the file itself."""

    def test_every_question_has_at_least_one_gold_section(self, questions):
        missing = [q["id"] for q in questions if not q.get("sections")]
        assert not missing

    def test_every_id_is_unique(self, questions):
        ids = [q["id"] for q in questions]
        assert len(ids) == len(set(ids))

    def test_every_question_carries_a_note_saying_what_the_answer_is(self, questions):
        """The note is what made the corruption findable: q21's said "one at
        Tser Pool, one just outside Vallaki" while its gold was a section about
        a hag selling pastries. A gold with no note cannot be checked by
        anybody, including the person who wrote it."""
        assert not [q["id"] for q in questions if not q.get("note", "").strip()]

    def test_the_needs_label_is_one_of_the_three(self, questions):
        """A typo would silently drop a question out of every prediction bucket
        and out of the totals that are supposed to add up to the labelled set."""
        bad = [
            (q["id"], q["needs"])
            for q in questions
            if "needs" in q and q["needs"] not in ("graph", "text", "either")
        ]
        assert not bad

    def test_a_question_predicting_text_names_no_anchor_hint(self, questions):
        """`needs: text` claims the question names nothing the graph holds, so
        supplying the name a reader would resolve through contradicts it. The
        two fields would then disagree about the same question."""
        assert not [
            q["id"]
            for q in questions
            if q.get("needs") == "text" and q.get("anchor_hint")
        ]

    def test_a_gold_section_id_looks_like_one(self, questions):
        bad = [
            (q["id"], s)
            for q in questions
            for s in q["sections"]
            if not s.startswith("cos:") or "#" not in s
        ]
        assert not bad


@pytest.mark.neo4j
class TestTheLabelsPointAtRealSections:
    def test_every_gold_section_exists_in_the_graph(self, questions):
        """The structural half of the check that was missing.

        A gold naming no section scores zero forever and reads as a retrieval
        failure. This does not catch a gold pointing at the WRONG real section,
        which is what actually happened -- but it is the half a machine can own,
        and it will catch the next chapter rebuild that shifts an index.
        """
        from backend.canon.retrieval import CanonRetriever

        wanted = sorted({s for q in questions for s in q["sections"]})
        retriever = CanonRetriever()
        with retriever._session() as session:
            found = {
                row["id"]
                for row in retriever._rows(
                    session,
                    "MATCH (s:Section) WHERE s.id IN $ids RETURN s.id AS id",
                    {"ids": wanted},
                )
            }
        assert not [s for s in wanted if s not in found]

    def test_the_two_corrected_questions_no_longer_point_at_dream_pastries(
        self, questions
    ):
        """Pinned by name rather than by id, so this keeps meaning what it says
        if section indices shift again."""
        from backend.canon.retrieval import CanonRetriever

        by_id = {q["id"]: q for q in questions}
        retriever = CanonRetriever()
        with retriever._session() as session:
            for qid in ("q21", "q22"):
                for section_id in by_id[qid]["sections"]:
                    rows = retriever._rows(
                        session,
                        "MATCH (s:Section {id:$id}) RETURN s.heading AS heading",
                        {"id": section_id},
                    )
                    assert rows, f"{qid} names a section that does not exist"
                    assert rows[0]["heading"] != "Dream Pastries"
