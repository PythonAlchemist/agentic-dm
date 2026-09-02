"""A night of play, and the difference between what was meant and what happened.

Every time-indexed fact the roadmap wants -- who held the sword in session
three, what the party knew by session five -- is a dangling pointer until
sessions exist as nodes. This is why they are built before inventory and before
player visibility rather than after them.
"""

import pytest

from backend.campaign import sessions
from backend.core.database import neo4j_session

PREFIX = "pytest-sess"
SLUG = f"{PREFIX}-camp"


@pytest.fixture
def table():
    with neo4j_session() as session:
        def clean(s):
            s.run("MATCH (n) WHERE n.campaign = $c DETACH DELETE n", {"c": SLUG}).consume()
            s.run("MATCH (c:Campaign {slug:$c}) DETACH DELETE c", {"c": SLUG}).consume()
            s.run("MATCH (s:Section) WHERE s.id STARTS WITH $p DETACH DELETE s",
                  {"p": PREFIX}).consume()

        clean(session)
        session.run("CREATE (:Campaign {slug:$c, name:'S', plane:'campaign'})",
                    {"c": SLUG}).consume()
        for i in range(3):
            session.run(
                "CREATE (:Section {id:$id, heading:$h, plane:'campaign', campaign:$c})",
                {"id": f"{PREFIX}:scene-{i}", "h": f"Scene {i}", "c": SLUG},
            ).consume()
        yield session
        clean(session)


def _open(t, **kw):
    return t.execute_write(lambda tx: sessions.open_session(tx, slug=SLUG, **kw))


class TestOpeningANight:
    def test_the_first_session_is_number_one(self, table):
        assert _open(table)["number"] == 1

    def test_numbers_come_from_what_exists(self, table):
        """Counted by the graph, not by the caller: two clients opening a
        session at once would otherwise both call it the fifth."""
        _open(table)
        _open(table)
        assert _open(table)["number"] == 3

    def test_the_id_says_which_table_it_belongs_to(self, table):
        """`transcript/processor.py` minted `session_<uuid4>` ids carrying no
        campaign, which made its debris invisible even to `ORPHANED_NODES`."""
        assert _open(table)["id"] == f"hb:{SLUG}:session-1"

    def test_re_opening_by_number_does_not_double_it(self, table):
        _open(table, number=1)
        _open(table, number=1)
        assert len(table.execute_read(lambda tx: sessions.sessions(tx, slug=SLUG))) == 1

    def test_a_session_needs_a_campaign_to_belong_to(self, table):
        with pytest.raises(ValueError):
            table.execute_write(
                lambda tx: sessions.open_session(tx, slug=f"{PREFIX}-nowhere"))


class TestPlannedAgainstPlayed:
    """Two edges, not a status. A single field would let one overwrite the
    other and lose exactly the comparison this exists for."""

    def _night(self, table):
        return _open(table)["id"]

    def test_what_was_planned_and_not_reached_is_missed(self, table):
        night = self._night(table)
        table.execute_write(lambda tx: sessions.plan(
            tx, slug=SLUG, session=night, section=f"{PREFIX}:scene-0"))
        table.execute_write(lambda tx: sessions.plan(
            tx, slug=SLUG, session=night, section=f"{PREFIX}:scene-1"))
        table.execute_write(lambda tx: sessions.cover(
            tx, slug=SLUG, session=night, section=f"{PREFIX}:scene-0"))

        found = table.execute_read(
            lambda tx: sessions.diff(tx, slug=SLUG, session=night))
        assert [s["id"] for s in found["missed"]] == [f"{PREFIX}:scene-1"]

    def test_what_happened_unplanned_is_where_a_campaign_diverges(self, table):
        night = self._night(table)
        table.execute_write(lambda tx: sessions.plan(
            tx, slug=SLUG, session=night, section=f"{PREFIX}:scene-0"))
        table.execute_write(lambda tx: sessions.cover(
            tx, slug=SLUG, session=night, section=f"{PREFIX}:scene-2"))

        found = table.execute_read(
            lambda tx: sessions.diff(tx, slug=SLUG, session=night))
        assert [s["id"] for s in found["unplanned"]] == [f"{PREFIX}:scene-2"]

    def test_planning_the_same_scene_twice_is_planning_it_once(self, table):
        night = self._night(table)
        for _ in range(2):
            table.execute_write(lambda tx: sessions.plan(
                tx, slug=SLUG, session=night, section=f"{PREFIX}:scene-0"))
        found = table.execute_read(
            lambda tx: sessions.diff(tx, slug=SLUG, session=night))
        assert len(found["planned"]) == 1

    def test_unplanning_removes_it_from_the_intention_only(self, table):
        night = self._night(table)
        table.execute_write(lambda tx: sessions.plan(
            tx, slug=SLUG, session=night, section=f"{PREFIX}:scene-0"))
        table.execute_write(lambda tx: sessions.cover(
            tx, slug=SLUG, session=night, section=f"{PREFIX}:scene-0"))
        table.execute_write(lambda tx: sessions.unplan(
            tx, slug=SLUG, session=night, section=f"{PREFIX}:scene-0"))

        found = table.execute_read(
            lambda tx: sessions.diff(tx, slug=SLUG, session=night))
        assert found["planned"] == []
        assert [s["id"] for s in found["covered"]] == [f"{PREFIX}:scene-0"]

    def test_a_night_with_nothing_on_it_diffs_to_nothing(self, table):
        # OPENED OUTSIDE THE READ. Calling a write inside `execute_read` nests
        # one transaction in another on the same session, which kills the
        # connection rather than failing an assertion.
        night = self._night(table)
        found = table.execute_read(
            lambda tx: sessions.diff(tx, slug=SLUG, session=night))
        assert found == {"planned": [], "covered": [], "missed": [], "unplanned": []}

    def test_the_roster_counts_both_lists(self, table):
        night = self._night(table)
        table.execute_write(lambda tx: sessions.plan(
            tx, slug=SLUG, session=night, section=f"{PREFIX}:scene-0"))
        table.execute_write(lambda tx: sessions.cover(
            tx, slug=SLUG, session=night, section=f"{PREFIX}:scene-1"))
        row = table.execute_read(lambda tx: sessions.sessions(tx, slug=SLUG))[0]
        assert (row["planned"], row["covered"]) == (1, 1)


class TestDeletingTheTableTakesItsNights:
    def test_the_sweep_reaches_a_session(self, table):
        from backend.campaign import store

        _open(table)
        table.execute_write(lambda tx: store.delete_campaign(tx, SLUG))
        n = table.run("MATCH (s:Session {campaign:$c}) RETURN count(s) AS n",
                      {"c": SLUG}).single()["n"]
        assert n == 0
