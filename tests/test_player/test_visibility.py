"""What a player may see, and the shapes that keep it that way.

Every assertion here is about ABSENCE, which is the hard thing to test and the
only thing that matters: a leak is a row that should not have been in a result,
and a test that only checks what IS present never catches one.
"""

import pytest

from backend.campaign import roles
from backend.core.database import neo4j_session
from backend.player import reader as visibility

PREFIX = "pytest-vis"
SLUG = f"{PREFIX}-camp"
STRAHD = f"{PREFIX}:strahd"
IREENA = f"{PREFIX}:ireena"
SECRET = f"{PREFIX}:the-twist"
KNOWN = f"{PREFIX}:the-village"

DM_ENTITY = """
MATCH (e:Entity {id:$id})
RETURN e.id AS entity_id, e.name AS name, labels(e) AS labels
"""


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
            "CREATE (c:Campaign {slug:$slug, name:'Vis', campaign:$slug}) "
            "CREATE (s:Entity:NPC {id:$s, plane:'canon', name:'Strahd von Zarovich'}) "
            "CREATE (i:Entity:NPC {id:$i, plane:'canon', name:'Ireena Kolyana'}) "
            "CREATE (s)-[:HUNTS {status:'accepted'}]->(i) "
            "CREATE (twist:Section {id:$twist, heading:'The Twist', "
            "  text:'Ireena is his lost bride.', plane:'canon'}) "
            "CREATE (village:Section {id:$village, heading:'The Village', "
            "  text:'Mist lies over the village.', plane:'canon'}) "
            # `<entity>@<section>` AND CARRYING THE PREFIX. A mention id
            # spells its pair -- one of the invariants -- and an id that does
            # not start with the cleanup prefix survives teardown and collides
            # on the next run.
            "CREATE (m1:Mention {id:$m1})-[:REFERS_TO]->(s) "
            "CREATE (m1)-[:IN_SECTION]->(twist) "
            "CREATE (m2:Mention {id:$m2})-[:REFERS_TO]->(s) "
            "CREATE (m2)-[:IN_SECTION]->(village)",
            {"slug": SLUG, "s": STRAHD, "i": IREENA,
             "twist": SECRET, "village": KNOWN,
             "m1": f"{STRAHD}@{SECRET}", "m2": f"{STRAHD}@{KNOWN}"},
        ).consume()
        session.execute_write(lambda tx: roles.seat(
            tx, slug=SLUG, reader="ana", role=roles.PLAYER))
        yield session
        clean(session)


def _card(graph, reader, entity=STRAHD):
    return graph.execute_read(lambda tx: visibility.entity_for(
        tx, slug=SLUG, reader=reader, entity_id=entity,
        dm_query=DM_ENTITY, dm_params={"id": entity}))


def _reveal(graph, target, **kw):
    return graph.execute_write(lambda tx: visibility.reveal(
        tx, slug=SLUG, target=target, **kw))


class TestTheDefaultIsDeny:
    def test_a_player_sees_nothing_until_told(self, graph):
        assert _card(graph, "ana") is None

    def test_the_dm_sees_it_anyway(self, graph):
        assert _card(graph, "")["name"] == "Strahd von Zarovich"

    def test_a_reader_with_no_seat_gets_the_player_view(self, graph):
        """A bug in seating must be a closed door, not a spoiler."""
        assert _card(graph, "stranger") is None

    def test_an_unidentified_reader_is_the_dm(self, graph):
        """`ACCESS_TOKENS` unset: one person at the machine, running their own
        game. Every other unknown falls the other way."""
        assert visibility.audience(graph, slug=SLUG, reader="") == visibility.DM

    def test_a_seated_dm_is_a_dm(self, graph):
        graph.execute_write(lambda tx: roles.seat(
            tx, slug=SLUG, reader="ben", role=roles.DM))
        assert _card(graph, "ben")["name"] == "Strahd von Zarovich"


class TestRevealing:
    def test_a_revealed_entity_arrives(self, graph):
        _reveal(graph, STRAHD)
        assert _card(graph, "ana")["name"] == "Strahd von Zarovich"

    def test_revealing_the_entity_does_not_hand_over_its_prose(self, graph):
        """A party can know Strahd exists for ten sessions before they may
        read what the book says about him."""
        _reveal(graph, STRAHD)
        found = _card(graph, "ana")
        assert [q for q in found["named_in"] if q["section_id"]] == []

    def test_a_revealed_section_brings_its_quote(self, graph):
        _reveal(graph, STRAHD)
        _reveal(graph, KNOWN)
        found = _card(graph, "ana")
        assert [q["heading"] for q in found["named_in"] if q["section_id"]] == [
            "The Village"]

    def test_the_unrevealed_section_is_absent_not_redacted(self, graph):
        _reveal(graph, STRAHD)
        _reveal(graph, KNOWN)
        payload = str(_card(graph, "ana"))
        assert "lost bride" not in payload
        assert "The Twist" not in payload

    def test_concealing_takes_it_back_off_the_table(self, graph):
        _reveal(graph, STRAHD)
        assert graph.execute_write(lambda tx: visibility.conceal(
            tx, slug=SLUG, target=STRAHD)) == 1
        assert _card(graph, "ana") is None

    def test_revealing_something_that_is_not_there_is_refused(self, graph):
        with pytest.raises(ValueError):
            _reveal(graph, f"{PREFIX}:nothing")


class TestConnections:
    def test_an_edge_to_something_unrevealed_does_not_appear(self, graph):
        """The connection list is the quietest leak in the product: it names
        things the player has never met, in a strip nobody reads carefully."""
        _reveal(graph, STRAHD)
        found = _card(graph, "ana")
        assert found["connections"] == []

    def test_both_ends_revealed_makes_the_edge_visible(self, graph):
        _reveal(graph, STRAHD)
        _reveal(graph, IREENA)
        found = _card(graph, "ana")
        assert [c["other"] for c in found["connections"]] == ["Ireena Kolyana"]


class TestRevealingUnderAnotherName:
    def test_the_table_is_told_the_alias(self, graph):
        _reveal(graph, STRAHD, as_name="the coachman")
        assert _card(graph, "ana")["name"] == "the coachman"

    def test_the_true_name_does_not_travel(self, graph):
        _reveal(graph, STRAHD, as_name="the coachman")
        assert "Strahd" not in str(_card(graph, "ana"))

    def test_the_dm_still_sees_the_true_name(self, graph):
        _reveal(graph, STRAHD, as_name="the coachman")
        assert _card(graph, "")["name"] == "Strahd von Zarovich"


class TestSections:
    def _read(self, graph, reader, section=SECRET):
        return graph.execute_read(lambda tx: visibility.section_for(
            tx, slug=SLUG, reader=reader, section_id=section,
            dm_query="MATCH (s:Section {id:$id}) RETURN s.text AS text",
            dm_params={"id": section}))

    def test_a_player_cannot_read_an_unrevealed_scene(self, graph):
        assert self._read(graph, "ana") is None

    def test_the_dm_can(self, graph):
        assert "lost bride" in self._read(graph, "")["text"]

    def test_a_revealed_scene_reads(self, graph):
        _reveal(graph, KNOWN)
        assert "Mist" in self._read(graph, "ana", KNOWN)["text"]


class TestWhatAModelMayBeGiven:
    def test_the_seed_is_the_revealed_set(self, graph):
        """SEEDED, NOT FILTERED. A model given the secret and asked not to
        mention it has already been given the secret."""
        _reveal(graph, STRAHD)
        _reveal(graph, KNOWN)
        found = graph.execute_read(lambda tx: visibility.visible_ids(tx, slug=SLUG))
        assert sorted(found) == sorted([STRAHD, KNOWN])

    def test_an_untold_table_seeds_nothing(self, graph):
        assert graph.execute_read(
            lambda tx: visibility.visible_ids(tx, slug=SLUG)) == []

    def test_may_see_answers_the_same_question(self, graph):
        _reveal(graph, STRAHD)
        assert visibility.may_see(graph, slug=SLUG, reader="ana", target=STRAHD)
        assert not visibility.may_see(
            graph, slug=SLUG, reader="ana", target=SECRET)
        assert visibility.may_see(graph, slug=SLUG, reader="", target=SECRET)
