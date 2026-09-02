"""Making a table, and the few things true of the whole of it.

`store.create` had existed all along with one caller: a script. The first thing
a person does with this product had no button, and the home page told them the
lab could do it, which was not true of the lab either.
"""

import pytest

from backend.campaign import setup, store
from backend.campaign.model import Campaign
from backend.core.database import neo4j_session

PREFIX = "pytest-setup"
SLUG = f"{PREFIX}-camp"
BOOK = f"{PREFIX}-book"
OTHER = f"{PREFIX}-other"


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
            "CREATE (:Book {slug:$b, id:$b, title:'A Book', plane:'canon'}) "
            "CREATE (:Book {slug:$o, id:$o, title:'Another', plane:'canon'})",
            {"b": BOOK, "o": OTHER}).consume()
        session.execute_write(lambda tx: store.create(
            tx, Campaign(slug=SLUG, name="Setup", books=(BOOK,)), owner="ana"))
        yield session
        clean(session)


class TestSettings:
    def test_it_reads_back_what_the_table_is(self, graph):
        found = graph.execute_read(lambda tx: setup.settings(tx, slug=SLUG))
        assert found["name"] == "Setup"
        assert found["books"] == [BOOK]
        assert found["owner"] == "ana"

    def test_a_table_that_is_not_there_is_refused(self, graph):
        with pytest.raises(ValueError):
            graph.execute_read(lambda tx: setup.settings(tx, slug=f"{PREFIX}-no"))

    def test_renaming_changes_the_name_and_not_the_key(self, graph):
        """Every node in the graph carries the slug, so renaming it is a
        migration rather than a setting."""
        graph.execute_write(lambda tx: setup.rename(tx, slug=SLUG, name="Renamed"))
        found = graph.execute_read(lambda tx: setup.settings(tx, slug=SLUG))
        assert (found["name"], found["slug"]) == ("Renamed", SLUG)

    def test_an_empty_name_is_refused(self, graph):
        with pytest.raises(ValueError):
            graph.execute_write(lambda tx: setup.rename(tx, slug=SLUG, name="  "))


class TestBooks:
    def test_the_picker_lists_what_the_graph_holds(self, graph):
        found = graph.execute_read(lambda tx: setup.books(tx))
        assert {BOOK, OTHER} <= {b["slug"] for b in found}

    def test_a_book_can_be_added(self, graph):
        graph.execute_write(lambda tx: setup.draw_on(tx, slug=SLUG, book=OTHER))
        found = graph.execute_read(lambda tx: setup.settings(tx, slug=SLUG))
        assert sorted(found["books"]) == sorted([BOOK, OTHER])

    def test_adding_the_same_book_twice_is_adding_it_once(self, graph):
        for _ in range(2):
            graph.execute_write(lambda tx: setup.draw_on(tx, slug=SLUG, book=OTHER))
        found = graph.execute_read(lambda tx: setup.settings(tx, slug=SLUG))
        assert len(found["books"]) == 2

    def test_a_book_that_does_not_exist_is_refused(self, graph):
        with pytest.raises(ValueError):
            graph.execute_write(lambda tx: setup.draw_on(
                tx, slug=SLUG, book=f"{PREFIX}-nope"))

    def test_dropping_a_book_keeps_what_the_table_wrote(self, graph):
        """It removes an edge, not prose. Those are the DM's own words about
        the book they read."""
        graph.execute_write(lambda tx: setup.write_premise(
            tx, slug=SLUG, text="We begin in the mists."))
        graph.execute_write(lambda tx: setup.stop_drawing(tx, slug=SLUG, book=BOOK))
        found = graph.execute_read(lambda tx: setup.settings(tx, slug=SLUG))
        assert found["books"] == [] and found["premise"] == "We begin in the mists."


class TestThePremise:
    def test_it_is_stored_as_a_section_of_the_campaign_plane(self, graph):
        graph.execute_write(lambda tx: setup.write_premise(
            tx, slug=SLUG, text="A debt, and a long road."))
        row = graph.run(
            "MATCH (s:Section {id:$id}) RETURN s.plane AS plane, s.kind AS kind, "
            "s.campaign AS campaign", {"id": setup.premise_id(SLUG)}).single()
        assert row["plane"] == "campaign"
        assert row["kind"] == "premise"
        assert row["campaign"] == SLUG

    def test_there_is_one_of_them(self, graph):
        """One answer to "what is this campaign". A list would invite three
        half-written ones with no way to tell which is current."""
        for text in ("first", "second"):
            graph.execute_write(lambda tx, t=text: setup.write_premise(
                tx, slug=SLUG, text=t))
        found = graph.run(
            "MATCH (s:Section {campaign:$c, kind:'premise'}) RETURN count(s) AS n",
            {"c": SLUG}).single()["n"]
        assert found == 1

    def test_it_is_reachable_from_the_campaign(self, graph):
        """`HAS_SECTION` is what `rescan` walks, so a premise that is not
        attached is a premise nothing ever reads."""
        graph.execute_write(lambda tx: setup.write_premise(
            tx, slug=SLUG, text="A debt."))
        found = graph.run(
            "MATCH (:Campaign {slug:$c})-[:HAS_SECTION]->(s:Section {id:$id}) "
            "RETURN count(s) AS n",
            {"c": SLUG, "id": setup.premise_id(SLUG)}).single()["n"]
        assert found == 1
