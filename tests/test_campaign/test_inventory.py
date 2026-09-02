"""Who is carrying what, and who was carrying it before.

The interesting assertions are about TIME. A holding that ends is closed, never
deleted -- that the party carried the Sunsword for six sessions is true whether
or not they still do.
"""

import pytest

from backend.campaign import inventory
from backend.core.database import neo4j_session

PREFIX = "pytest-inv2"
SLUG = f"{PREFIX}-camp"
SWORD = f"{PREFIX}:sunsword"
ISMARK = f"{PREFIX}:ismark"
IREENA = f"{PREFIX}:ireena"


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
            "CREATE (:Campaign {slug:$slug, name:'Inv', campaign:$slug}) "
            "CREATE (:Entity:ITEM {id:$s, plane:'canon', name:'Sunsword'}) "
            "CREATE (:Entity:NPC {id:$i, plane:'canon', name:'Ismark'}) "
            "CREATE (:Entity:NPC {id:$r, plane:'canon', name:'Ireena'})",
            {"slug": SLUG, "s": SWORD, "i": ISMARK, "r": IREENA},
        ).consume()
        yield session
        clean(session)


def _give(graph, holder, at=""):
    return graph.execute_write(lambda tx: inventory.give(
        tx, slug=SLUG, item=SWORD, holder=holder, at_session=at))


class TestHolding:
    def test_giving_records_a_holder(self, graph):
        _give(graph, ISMARK)
        held = graph.execute_read(lambda tx: inventory.held_by(
            tx, slug=SLUG, holder=ISMARK))
        assert [h["name"] for h in held] == ["Sunsword"]

    def test_canon_is_not_touched(self, graph):
        """The Sunsword is the book's; who carries it is this table's."""
        _give(graph, ISMARK)
        row = graph.run(
            "MATCH (e:Entity {id:$s}) RETURN e.plane AS plane, e.campaign AS c",
            {"s": SWORD}).single()
        assert row["plane"] == "canon" and row["c"] is None

    def test_an_item_that_is_not_there_is_refused(self, graph):
        with pytest.raises(ValueError):
            graph.execute_write(lambda tx: inventory.give(
                tx, slug=SLUG, item=f"{PREFIX}:nothing", holder=ISMARK))


class TestHandingOver:
    def test_the_previous_holder_is_closed(self, graph):
        _give(graph, ISMARK, at="1")
        found = _give(graph, IREENA, at="4")
        assert found["took_from"] == 1

    def test_only_one_holder_is_open(self, graph):
        """An item with two open holders is not a state a DM can see and fix;
        the graph would just answer "who has it" twice."""
        _give(graph, ISMARK, at="1")
        _give(graph, IREENA, at="4")
        open_now = graph.run(
            "MATCH ()-[h:HOLDS {campaign:$c}]->(:Entity {id:$s}) "
            "WHERE h.until_session IS NULL RETURN count(h) AS n",
            {"c": SLUG, "s": SWORD}).single()["n"]
        assert open_now == 1

    def test_the_old_holder_stops_carrying_it(self, graph):
        _give(graph, ISMARK, at="1")
        _give(graph, IREENA, at="4")
        assert graph.execute_read(lambda tx: inventory.held_by(
            tx, slug=SLUG, holder=ISMARK)) == []

    def test_dropping_closes_rather_than_deletes(self, graph):
        _give(graph, ISMARK, at="1")
        assert graph.execute_write(lambda tx: inventory.drop(
            tx, slug=SLUG, item=SWORD, holder=ISMARK, at_session="2")) == 1
        edges = graph.run(
            "MATCH ()-[h:HOLDS]->(:Entity {id:$s}) RETURN count(h) AS n",
            {"s": SWORD}).single()["n"]
        assert edges == 1


class TestHistory:
    def test_every_hand_it_passed_through(self, graph):
        """The reason time is a property rather than a second graph."""
        _give(graph, ISMARK, at="1")
        _give(graph, IREENA, at="4")
        found = graph.execute_read(lambda tx: inventory.provenance(
            tx, slug=SLUG, item=SWORD))
        assert [f["holder"] for f in found] == ["Ismark", "Ireena"]
        assert found[0]["until_session"] == "4"

    def test_an_unknown_session_is_recorded_as_unknown(self, graph):
        """A DM writing history from memory does not always know which
        session, and inventing one is worse than leaving it out."""
        _give(graph, ISMARK)
        found = graph.execute_read(lambda tx: inventory.provenance(
            tx, slug=SLUG, item=SWORD))
        assert found[0]["since_session"] is None


class TestTheParty:
    """The party is an entity, so "the party has it" is not a special case."""

    def test_it_is_minted_on_demand(self, graph):
        _give(graph, inventory.party_id(SLUG))
        row = graph.run(
            "MATCH (p:Entity {id:$id}) RETURN p.name AS name, p.plane AS plane, "
            "labels(p) AS labels", {"id": inventory.party_id(SLUG)}).single()
        assert row["name"] == "The party" and row["plane"] == "campaign"
        assert "FACTION" in row["labels"]

    def test_a_typo_in_a_slug_does_not_conjure_a_party(self, graph):
        with pytest.raises(ValueError):
            graph.execute_write(lambda tx: inventory.ensure_party(
                tx, slug=f"{PREFIX}-typo"))

    def test_the_ledger_reads_by_holder(self, graph):
        _give(graph, inventory.party_id(SLUG))
        found = graph.execute_read(lambda tx: inventory.ledger(tx, slug=SLUG))
        assert [(f["holder"], f["name"]) for f in found] == [
            ("The party", "Sunsword")]


class TestClosingWithoutADate:
    """The case that was broken, and could not be seen from any single read.

    Setting a Cypher property to NULL removes it, so closing an undated holding
    with a NULL stamp left `until_session IS NULL` true and closed nothing. The
    item stayed open under both holders and the graph answered "who has it"
    twice, with both rows looking like facts.
    """

    def test_an_undated_handover_still_closes_the_old_holder(self, graph):
        _give(graph, ISMARK)
        _give(graph, IREENA)
        open_now = graph.run(
            "MATCH ()-[h:HOLDS {campaign:$c}]->(:Entity {id:$s}) "
            "WHERE h.until_session IS NULL RETURN count(h) AS n",
            {"c": SLUG, "s": SWORD}).single()["n"]
        assert open_now == 1

    def test_an_undated_drop_still_closes_it(self, graph):
        _give(graph, ISMARK)
        graph.execute_write(lambda tx: inventory.drop(
            tx, slug=SLUG, item=SWORD, holder=ISMARK))
        assert graph.execute_read(lambda tx: inventory.held_by(
            tx, slug=SLUG, holder=ISMARK)) == []

    def test_an_unknown_end_is_recorded_as_unknown_not_as_open(self, graph):
        _give(graph, ISMARK)
        _give(graph, IREENA)
        found = graph.execute_read(lambda tx: inventory.provenance(
            tx, slug=SLUG, item=SWORD))
        closed = [f for f in found if f["holder"] == "Ismark"][0]
        assert closed["until_session"] == ""
