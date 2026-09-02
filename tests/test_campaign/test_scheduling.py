"""Six adults and a calendar.

The assertion that matters is about silence: an unanswered date is unknown, not
a no. A screen that folds the two together schedules around people who have not
looked at their phone, and rules out the one evening everybody was free.
"""

import pytest

from backend.campaign import roles, scheduling, sessions
from backend.core.database import neo4j_session

PREFIX = "pytest-sched"
SLUG = f"{PREFIX}-camp"


@pytest.fixture
def graph():
    with neo4j_session() as session:
        def clean(s):
            s.run("MATCH (n) WHERE n.campaign = $c DETACH DELETE n",
                  {"c": SLUG}).consume()
            s.run("MATCH (n) WHERE n.id STARTS WITH $p DETACH DELETE n",
                  {"p": PREFIX}).consume()

        clean(session)
        session.run(
            "CREATE (:Campaign {slug:$slug, name:'Sched', campaign:$slug})",
            {"slug": SLUG}).consume()
        for who in ("ana", "ben", "cass"):
            session.execute_write(lambda tx, w=who: roles.seat(
                tx, slug=SLUG, reader=w, role=roles.PLAYER))
        yield session
        clean(session)


def _propose(graph, on="2026-09-14"):
    return graph.execute_write(lambda tx: scheduling.propose(
        tx, slug=SLUG, on=on))["id"]


class TestProposing:
    def test_an_evening_goes_on_the_table(self, graph):
        assert _propose(graph) == f"hb:{SLUG}:sitting-2026-09-14"

    def test_the_same_evening_twice_is_one_evening(self, graph):
        _propose(graph)
        _propose(graph)
        found = graph.execute_read(lambda tx: scheduling.sittings(tx, slug=SLUG))
        assert len(found) == 1

    def test_a_date_this_module_does_not_understand_is_still_a_date(self, graph):
        """"Thursday after next" means something to the six people in the
        group, and a validator would reject the shorthand they use."""
        found = graph.execute_write(lambda tx: scheduling.propose(
            tx, slug=SLUG, on="Thursday after next"))
        assert found["on"] == "Thursday after next"

    def test_an_empty_evening_is_refused(self, graph):
        with pytest.raises(ValueError):
            graph.execute_write(lambda tx: scheduling.propose(tx, slug=SLUG, on="  "))

    def test_a_typo_in_a_slug_does_not_conjure_a_table(self, graph):
        with pytest.raises(ValueError):
            graph.execute_write(lambda tx: scheduling.propose(
                tx, slug=f"{PREFIX}-typo", on="2026-09-14"))

    def test_withdrawing_takes_the_answers_with_it(self, graph):
        sitting = _propose(graph)
        graph.execute_write(lambda tx: scheduling.answer(
            tx, slug=SLUG, sitting=sitting, reader="ana", says=scheduling.YES))
        assert graph.execute_write(lambda tx: scheduling.withdraw(
            tx, slug=SLUG, sitting=sitting)) == 1
        left = graph.run(
            "MATCH ()-[a:CAN_MAKE {campaign:$c}]->() RETURN count(a) AS n",
            {"c": SLUG}).single()["n"]
        assert left == 0


class TestAnswering:
    def test_an_answer_is_recorded(self, graph):
        sitting = _propose(graph)
        got = graph.execute_write(lambda tx: scheduling.answer(
            tx, slug=SLUG, sitting=sitting, reader="ana", says=scheduling.YES))
        assert got == "yes"

    def test_changing_your_mind_replaces_rather_than_adds(self, graph):
        sitting = _propose(graph)
        for says in (scheduling.YES, scheduling.NO):
            graph.execute_write(lambda tx, s=says: scheduling.answer(
                tx, slug=SLUG, sitting=sitting, reader="ana", says=s))
        found = graph.execute_read(lambda tx: scheduling.sittings(tx, slug=SLUG))[0]
        assert found["yes"] == [] and found["no"] == ["ana"]

    def test_a_word_that_is_not_an_answer_is_refused(self, graph):
        sitting = _propose(graph)
        with pytest.raises(ValueError):
            graph.execute_write(lambda tx: scheduling.answer(
                tx, slug=SLUG, sitting=sitting, reader="ana", says="probably"))

    def test_nobody_cannot_answer(self, graph):
        sitting = _propose(graph)
        with pytest.raises(ValueError):
            graph.execute_write(lambda tx: scheduling.answer(
                tx, slug=SLUG, sitting=sitting, reader="", says=scheduling.YES))


class TestSilenceIsNotANo:
    def test_the_unanswered_are_counted_apart(self, graph):
        sitting = _propose(graph)
        graph.execute_write(lambda tx: scheduling.answer(
            tx, slug=SLUG, sitting=sitting, reader="ana", says=scheduling.YES))
        found = graph.execute_read(lambda tx: scheduling.sittings(tx, slug=SLUG))[0]
        assert found["yes"] == ["ana"]
        assert found["no"] == []
        assert found["unanswered"] == 2

    def test_a_full_table_leaves_nobody_unanswered(self, graph):
        sitting = _propose(graph)
        for who in ("ana", "ben", "cass"):
            graph.execute_write(lambda tx, w=who: scheduling.answer(
                tx, slug=SLUG, sitting=sitting, reader=w, says=scheduling.YES))
        found = graph.execute_read(lambda tx: scheduling.sittings(tx, slug=SLUG))[0]
        assert found["unanswered"] == 0 and len(found["yes"]) == 3


class TestPinningASessionToAnEvening:
    def test_the_session_takes_the_date(self, graph):
        sitting = _propose(graph)
        session = graph.execute_write(lambda tx: sessions.open_session(
            tx, slug=SLUG))["id"]
        found = graph.execute_write(lambda tx: scheduling.hold_on(
            tx, slug=SLUG, session=session, sitting=sitting))
        assert found["held_on"] == "2026-09-14"

    def test_a_session_that_is_not_there_is_refused(self, graph):
        sitting = _propose(graph)
        with pytest.raises(ValueError):
            graph.execute_write(lambda tx: scheduling.hold_on(
                tx, slug=SLUG, session=f"hb:{SLUG}:session-99", sitting=sitting))
