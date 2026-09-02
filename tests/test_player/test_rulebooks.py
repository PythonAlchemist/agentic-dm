"""A player owns the Player's Handbook.

Making a DM reveal `Fireball` to their own party is a rule whose only effect is
busywork, and a product that hid the rules from the people playing by them
would be wrong about what a secret is.

NOTHING IN THE REAL GRAPH IS PUBLIC TODAY -- both books loaded are adventures.
These tests load a rulebook of their own, which is the only way to exercise a
branch that currently matches nothing.
"""

import pytest

from backend.campaign import roles
from backend.core.database import neo4j_session
from backend.player import reader as visibility

PREFIX = "pytest-srd"
SLUG = f"{PREFIX}-camp"
RULEBOOK = f"{PREFIX}-book"
ADVENTURE = f"{PREFIX}-adv"
SPELL = f"{RULEBOOK}:fireball"
SPELL_TEXT = f"{RULEBOOK}:fireball-rules"
VILLAIN = f"{ADVENTURE}:the-villain"

DM_ENTITY = "MATCH (e:Entity {id:$id}) RETURN e.id AS entity_id, e.name AS name"


@pytest.fixture
def graph():
    with neo4j_session() as session:
        def clean(s):
            s.run("MATCH (n) WHERE n.campaign = $c DETACH DELETE n",
                  {"c": SLUG}).consume()
            s.run("MATCH (n) WHERE n.id STARTS WITH $p DETACH DELETE n",
                  {"p": PREFIX}).consume()
            s.run("MATCH (b:Book) WHERE b.slug STARTS WITH $p DETACH DELETE b",
                  {"p": PREFIX}).consume()
            s.run("MATCH (c:Campaign {slug:$c}) DETACH DELETE c",
                  {"c": SLUG}).consume()

        clean(session)
        session.run(
            # ONE PROPERTY ON ONE NODE makes a whole book public. Loading a
            # rulebook needs no per-entity migration.
            "CREATE (:Book {slug:$rb, id:$rb, plane:'canon', reference:true}) "
            "CREATE (:Book {slug:$adv, id:$adv, plane:'canon'}) "
            "CREATE (c:Campaign {slug:$slug, name:'SRD', campaign:$slug}) "
            "CREATE (:Entity:LORE {id:$spell, plane:'canon', name:'Fireball'}) "
            "CREATE (:Section {id:$text, plane:'canon', heading:'Fireball', "
            "  text:'A bright streak flashes from your pointing finger.'}) "
            "CREATE (:Entity:NPC {id:$villain, plane:'canon', "
            "  name:'The Villain'})",
            {"rb": RULEBOOK, "adv": ADVENTURE, "slug": SLUG, "spell": SPELL,
             "text": SPELL_TEXT, "villain": VILLAIN}).consume()
        session.execute_write(lambda tx: roles.seat(
            tx, slug=SLUG, reader="ana", role=roles.PLAYER))
        yield session
        clean(session)


def _card(graph, entity):
    return graph.execute_read(lambda tx: visibility.entity_for(
        tx, slug=SLUG, reader="ana", entity_id=entity,
        dm_query=DM_ENTITY, dm_params={"id": entity}))


class TestTheRulesAreNotASecret:
    def test_a_spell_needs_no_grant(self, graph):
        assert _card(graph, SPELL)["name"] == "Fireball"

    def test_its_prose_needs_no_grant_either(self, graph):
        """A spell nobody may read is a spell nobody can cast."""
        found = graph.execute_read(lambda tx: visibility.section_for(
            tx, slug=SLUG, reader="ana", section_id=SPELL_TEXT,
            dm_query="MATCH (s:Section {id:$id}) RETURN s.text AS text",
            dm_params={"id": SPELL_TEXT}))
        assert "bright streak" in found["text"]

    def test_the_adventure_beside_it_still_needs_one(self, graph):
        """The mark is on the BOOK, so one book being public says nothing
        about the next."""
        assert _card(graph, VILLAIN) is None

    def test_may_see_agrees(self, graph):
        assert visibility.may_see(graph, slug=SLUG, reader="ana", target=SPELL)
        assert not visibility.may_see(
            graph, slug=SLUG, reader="ana", target=VILLAIN)


class TestTheMarkIsOnTheBook:
    def test_unmarking_it_shuts_the_whole_book(self, graph):
        """One property, and a whole book's worth of visibility follows it."""
        graph.run("MATCH (b:Book {slug:$rb}) REMOVE b.reference",
                  {"rb": RULEBOOK}).consume()
        assert _card(graph, SPELL) is None

    def test_a_false_mark_is_not_a_true_one(self, graph):
        """Set true only, never false -- the discipline `NAMED_BY_BOOK`
        records. A book that is not a rulebook needs no property to say so."""
        graph.run("MATCH (b:Book {slug:$adv}) SET b.reference = false",
                  {"adv": ADVENTURE}).consume()
        assert _card(graph, VILLAIN) is None

    def test_a_prefix_is_a_whole_segment_not_a_string_start(self, graph):
        """`pytest-srd-book:` must not make `pytest-srd-book-two:` public. The
        colon is doing real work in the clause."""
        graph.run(
            "CREATE (:Entity:NPC {id:$id, plane:'canon', name:'Impostor'})",
            {"id": f"{RULEBOOK}-two:impostor"}).consume()
        assert _card(graph, f"{RULEBOOK}-two:impostor") is None


class TestSearchAndRetrievalAgree:
    def test_a_player_can_search_the_rules(self, graph):
        from backend.api.routes.table import SEARCH_PLAYER

        rows = [dict(r) for r in graph.run(SEARCH_PLAYER, {
            "slug": SLUG, "q": "fire", "label": "", "limit": 20})]
        assert [r["name"] for r in rows] == ["Fireball"]

    def test_but_not_the_adventure(self, graph):
        from backend.api.routes.table import SEARCH_PLAYER

        rows = [dict(r) for r in graph.run(SEARCH_PLAYER, {
            "slug": SLUG, "q": "villain", "label": "", "limit": 20})]
        assert rows == []

    def test_the_retriever_answers_out_of_the_rules(self, graph):
        from backend.player.retrieval import PlayerRetriever

        found = PlayerRetriever(campaign=SLUG, book=RULEBOOK).retrieve(
            "what does fireball do?")
        assert [a.name for a in found.anchors] == ["Fireball"]
