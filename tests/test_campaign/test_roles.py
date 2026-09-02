"""Who sits at a table, and in which chair.

The gate knows WHO a request is from and `ownership` knows whether the table is
theirs -- one bit, yours or not yours. The roadmap needs two chairs at the same
table: a DM who sees everything, and a player who must not.
"""

import pytest

from backend.campaign import roles
from backend.campaign.ownership import claim
from backend.core.database import neo4j_session

PREFIX = "pytest-roles"
SLUG = f"{PREFIX}-camp"


@pytest.fixture
def table():
    with neo4j_session() as session:
        def clean(s):
            s.run("MATCH (p:Player {campaign:$c}) DETACH DELETE p", {"c": SLUG}).consume()
            s.run("MATCH (c:Campaign {slug:$c}) DETACH DELETE c", {"c": SLUG}).consume()

        clean(session)
        session.run(
            "CREATE (:Campaign {slug:$c, name:'Roles', plane:'campaign'})",
            {"c": SLUG},
        ).consume()
        yield session
        clean(session)


def _seat(session, reader, role):
    return session.execute_write(
        lambda tx: roles.seat(tx, slug=SLUG, reader=reader, role=role))


def _role(session, reader):
    return session.execute_read(
        lambda tx: roles.role_of(tx, slug=SLUG, reader=reader))


class TestASeatIsAnEdge:
    """One person runs one table and plays at another, so the role cannot live
    on the person."""

    def test_a_seated_player_has_that_role(self, table):
        _seat(table, "bob", roles.PLAYER)
        assert _role(table, "bob") == roles.PLAYER

    def test_a_seated_dm_has_that_role(self, table):
        _seat(table, "ana", roles.DM)
        assert _role(table, "ana") == roles.DM

    def test_seating_twice_moves_the_chair_rather_than_adding_one(self, table):
        _seat(table, "bob", roles.PLAYER)
        _seat(table, "bob", roles.DM)
        assert _role(table, "bob") == roles.DM
        assert len(table.execute_read(lambda tx: roles.seated(tx, slug=SLUG))) == 1

    def test_a_chair_that_does_not_exist_is_refused(self, table):
        with pytest.raises(ValueError):
            _seat(table, "bob", "spectator")

    def test_a_seat_needs_somebody_in_it(self, table):
        with pytest.raises(ValueError):
            _seat(table, "", roles.PLAYER)


class TestDefaultDeny:
    def test_an_unseated_reader_has_no_role(self, table):
        assert _role(table, "stranger") == ""

    def test_an_unidentified_reader_has_no_role(self, table):
        """On an open deployment there is nobody to check, and this will not
        invent an identity to check."""
        assert _role(table, "") == ""

    def test_a_campaign_that_does_not_exist_gives_no_role(self, table):
        role = table.execute_read(
            lambda tx: roles.role_of(tx, slug=f"{PREFIX}-nowhere", reader="ana"))
        assert role == ""

    def test_seating_cannot_conjure_a_campaign(self, table):
        """A typo in a slug must not create a table with one player in it."""
        table.execute_write(
            lambda tx: roles.seat(tx, slug=f"{PREFIX}-typo", reader="ana",
                                  role=roles.DM))
        n = table.run("MATCH (c:Campaign {slug:$c}) RETURN count(c) AS n",
                      {"c": f"{PREFIX}-typo"}).single()["n"]
        assert n == 0


class TestTheOwnerIsTheDM:
    """`ownership.claim` records whoever first writes to a table. Requiring
    them to then grant themselves a chair would be a rule whose only effect is
    locking a DM out of their own game."""

    def test_the_owner_needs_no_seat(self, table):
        table.execute_write(lambda tx: claim(tx, SLUG, "ana"))
        assert _role(table, "ana") == roles.DM

    def test_but_the_owner_can_still_be_seated_as_something_else(self, table):
        """A DM handing their table over should not be fought by a default."""
        table.execute_write(lambda tx: claim(tx, SLUG, "ana"))
        _seat(table, "ana", roles.PLAYER)
        assert _role(table, "ana") == roles.PLAYER

    def test_ownership_does_not_leak_to_anybody_else(self, table):
        table.execute_write(lambda tx: claim(tx, SLUG, "ana"))
        assert _role(table, "bob") == ""


class TestTakingTheChairAway:
    def test_unseat_removes_the_role(self, table):
        _seat(table, "bob", roles.PLAYER)
        assert table.execute_write(
            lambda tx: roles.unseat(tx, slug=SLUG, reader="bob")) == 1
        assert _role(table, "bob") == ""

    def test_unseating_nobody_is_not_an_error(self, table):
        assert table.execute_write(
            lambda tx: roles.unseat(tx, slug=SLUG, reader="ghost")) == 0

    def test_the_roster_lists_everyone(self, table):
        _seat(table, "ana", roles.DM)
        _seat(table, "bob", roles.PLAYER)
        found = table.execute_read(lambda tx: roles.seated(tx, slug=SLUG))
        assert [(r["reader"], r["role"]) for r in found] == [
            ("ana", roles.DM), ("bob", roles.PLAYER)]
