"""The adventure log: what the table learned, by the night they learned it."""

import pytest

from backend.campaign import sessions
from backend.core.database import neo4j_session
from backend.player import reader as visibility

PREFIX = "pytest-log"
SLUG = f"{PREFIX}-camp"
NPC = f"{PREFIX}:ismark"
SCENE = f"{PREFIX}:the-village"


@pytest.fixture
def graph():
    with neo4j_session() as session:
        def clean(s):
            s.run("MATCH (n) WHERE n.campaign = $c DETACH DELETE n",
                  {"c": SLUG}).consume()
            s.run("MATCH (n) WHERE n.id STARTS WITH $p DETACH DELETE n",
                  {"p": PREFIX}).consume()
            s.run("MATCH (c:Campaign {slug:$c}) DETACH DELETE c",
                  {"c": SLUG}).consume()

        clean(session)
        session.run(
            "CREATE (:Campaign {slug:$slug, name:'Log', campaign:$slug}) "
            "CREATE (:Entity:NPC {id:$n, plane:'canon', name:'Ismark'}) "
            "CREATE (:Section {id:$s, plane:'canon', heading:'The Village', "
            "  text:'Mist.'})",
            {"slug": SLUG, "n": NPC, "s": SCENE}).consume()
        yield session
        clean(session)


def _open(graph, title=""):
    return graph.execute_write(lambda tx: sessions.open_session(
        tx, slug=SLUG, title=title))


class TestItWritesItself:
    def test_a_reveal_takes_the_session_the_table_is_in(self, graph):
        """Asking a DM to stamp each one by hand is asking for a log that is
        right for two sessions and then abandoned."""
        opened = _open(graph, "The Road In")
        graph.execute_write(lambda tx: visibility.reveal(
            tx, slug=SLUG, target=NPC))
        found = graph.execute_read(lambda tx: visibility.log(tx, slug=SLUG))
        assert found[0]["number"] == opened["number"]
        assert [x["name"] for x in found[0]["learned"]] == ["Ismark"]

    def test_an_explicit_stamp_still_wins(self, graph):
        """For a DM writing up a session afterwards, or correcting one."""
        first = _open(graph)
        _open(graph)
        graph.execute_write(lambda tx: visibility.reveal(
            tx, slug=SLUG, target=NPC, at_session=first["id"]))
        found = graph.execute_read(lambda tx: visibility.log(tx, slug=SLUG))
        assert [f["number"] for f in found] == [1]

    def test_what_came_before_any_session_is_its_own_night(self, graph):
        """A table that revealed things before opening a session has a real
        history, and dropping it would lose the opening of every campaign that
        started here."""
        graph.execute_write(lambda tx: visibility.reveal(
            tx, slug=SLUG, target=NPC))
        found = graph.execute_read(lambda tx: visibility.log(tx, slug=SLUG))
        assert found[0]["number"] == 0


class TestWhatItShows:
    def test_newest_night_first(self, graph):
        _open(graph)
        graph.execute_write(lambda tx: visibility.reveal(
            tx, slug=SLUG, target=NPC))
        _open(graph)
        graph.execute_write(lambda tx: visibility.reveal(
            tx, slug=SLUG, target=SCENE))
        found = graph.execute_read(lambda tx: visibility.log(tx, slug=SLUG))
        assert [f["number"] for f in found] == [2, 1]

    def test_a_scene_and_a_person_are_told_apart(self, graph):
        _open(graph)
        for target in (NPC, SCENE):
            graph.execute_write(lambda tx, t=target: visibility.reveal(
                tx, slug=SLUG, target=t))
        learned = graph.execute_read(
            lambda tx: visibility.log(tx, slug=SLUG))[0]["learned"]
        assert sorted(x["kind"] for x in learned) == ["scene", "who"]

    def test_it_shows_the_name_the_table_knows(self, graph):
        """The log is what the PLAYERS remember, so it uses their word for it."""
        _open(graph)
        graph.execute_write(lambda tx: visibility.reveal(
            tx, slug=SLUG, target=NPC, as_name="the burgomaster's son"))
        learned = graph.execute_read(
            lambda tx: visibility.log(tx, slug=SLUG))[0]["learned"]
        assert [x["name"] for x in learned] == ["the burgomaster's son"]
        assert "Ismark" not in str(learned)

    def test_concealing_takes_it_out_of_the_log(self, graph):
        """The log reports grants, so it cannot show what is no longer
        granted -- there is no second record to go stale."""
        _open(graph)
        graph.execute_write(lambda tx: visibility.reveal(
            tx, slug=SLUG, target=NPC))
        graph.execute_write(lambda tx: visibility.conceal(
            tx, slug=SLUG, target=NPC))
        assert graph.execute_read(lambda tx: visibility.log(tx, slug=SLUG)) == []

    def test_an_untold_table_has_no_log(self, graph):
        _open(graph)
        assert graph.execute_read(lambda tx: visibility.log(tx, slug=SLUG)) == []
