"""A recording becomes sections and mentions, and nothing else.

The old processor ran an NER pipeline with `create_missing_entities=True` over
the least reliable prose in the system. What follows is mostly the negative:
what a transcript may NOT do to the graph.
"""

import pytest

from backend.campaign import sessions, transcripts
from backend.campaign.transcripts import Said
from backend.core.database import neo4j_session

PREFIX = "pytest-tr"
SLUG = f"{PREFIX}-camp"
NPC = f"{PREFIX}:ireena"


@pytest.fixture
def graph():
    with neo4j_session() as session:
        def clean(s):
            s.run("MATCH (n) WHERE n.campaign = $c DETACH DELETE n",
                  {"c": SLUG}).consume()
            s.run("MATCH (n) WHERE n.id STARTS WITH $p DETACH DELETE n",
                  {"p": PREFIX}).consume()
            s.run("MATCH (b:Book {slug:$p}) DETACH DELETE b",
                  {"p": PREFIX}).consume()

        clean(session)
        session.run(
            "CREATE (b:Book {slug:$book, id:$book}) "
            "CREATE (c:Campaign {slug:$slug, name:'T', campaign:$slug}) "
            "CREATE (c)-[:DRAWS_ON]->(b) "
            "CREATE (:Entity:NPC {id:$n, plane:'canon', name:'Ireena Kolyana'})",
            {"slug": SLUG, "book": PREFIX, "n": NPC},
        ).consume()
        yield session
        clean(session)


def _session(graph, number=1) -> str:
    return graph.execute_write(lambda tx: sessions.open_session(
        tx, slug=SLUG, number=number))["id"]


def _record(graph, said, number=1):
    # OPENED FIRST, OUTSIDE THE LAMBDA. A write inside an `execute_write`
    # callback opens a transaction inside a transaction and kills the
    # connection.
    session = _session(graph, number)
    return graph.execute_write(lambda tx: transcripts.record(
        tx, slug=SLUG, session=session, number=number, said=said))


class TestChunking:
    """Sections big enough to be a scene, small enough to quote."""

    def test_a_turn_is_never_split(self):
        long = Said("Ana", "x" * 4000)
        assert transcripts.chunk([long], budget=100) == [[long]]

    def test_turns_pack_up_to_the_budget(self):
        said = [Said("A", "y" * 40) for _ in range(6)]
        packed = transcripts.chunk(said, budget=100)
        assert [len(p) for p in packed] == [2, 2, 2]

    def test_the_speaker_is_part_of_the_text(self):
        """"Who said that?" is the first question a DM asks of a quote."""
        assert transcripts.render([Said("Ana", "I open the door")]) == (
            "Ana: I open the door")


class TestWhatARecordingBecomes:
    def test_it_becomes_sections_of_the_campaign_plane(self, graph):
        _record(graph, [Said("Ana", "We ride for Barovia.")])
        rows = graph.run(
            "MATCH (s:Section {campaign:$c, kind:'transcript'}) "
            "RETURN s.plane AS plane, s.id AS id", {"c": SLUG}).data()
        assert [r["plane"] for r in rows] == ["campaign"]
        assert rows[0]["id"].startswith(f"hb:{SLUG}:session-1-t")

    def test_a_name_the_graph_knows_becomes_a_mention(self, graph):
        found = _record(graph, [Said("Ana", "Ireena Kolyana meets us at dusk.")])
        assert found["mentions"] == 1

    def test_a_name_the_graph_does_not_know_mints_nothing(self, graph):
        """The one thing the old processor did that this may not. A model
        reading four hours of table talk and creating entities from it puts
        invented names beside the book's, in the store that is supposed to
        tell them apart."""
        before = graph.run("MATCH (e:Entity) RETURN count(e) AS n").single()["n"]
        _record(graph, [Said("Ana", "Then Gorbo the Unmentioned appeared.")])
        after = graph.run("MATCH (e:Entity) RETURN count(e) AS n").single()["n"]
        assert after == before

    def test_it_writes_no_relationship(self, graph):
        """A transcript is evidence, not assertion. "Somebody said Strahd at
        9:14" is checkable; "Strahd betrayed Ireena" is a claim."""
        _record(graph, [Said("Ana", "Ireena Kolyana betrayed us all.")])
        found = graph.run(
            "MATCH (:Entity {id:$n})-[r]-(:Entity) RETURN count(r) AS n",
            {"n": NPC}).single()["n"]
        assert found == 0

    def test_canon_is_not_touched(self, graph):
        _record(graph, [Said("Ana", "Ireena Kolyana rides with us.")])
        row = graph.run(
            "MATCH (e:Entity {id:$n}) RETURN e.plane AS plane, e.campaign AS c",
            {"n": NPC}).single()
        assert row["plane"] == "canon" and row["c"] is None

    def test_re_uploading_replaces_rather_than_appends(self, graph):
        """The wrong file, or half the recording. Both are ordinary."""
        _record(graph, [Said("Ana", "Ireena Kolyana. " * 200)])
        second = _record(graph, [Said("Ana", "One line only.")])
        assert second["replaced"] > 0
        rows = graph.run(
            "MATCH (s:Section {campaign:$c, kind:'transcript'}) RETURN count(s) AS n",
            {"c": SLUG}).single()["n"]
        assert rows == 1

    def test_replacing_takes_the_old_mentions_with_it(self, graph):
        """A mention whose section is gone is half a triangle, which the first
        invariant exists to catch."""
        _record(graph, [Said("Ana", "Ireena Kolyana is here.")])
        _record(graph, [Said("Ana", "Nothing to report.")])
        left = graph.run(
            "MATCH (m:Mention {campaign:$c}) WHERE NOT (m)-[:IN_SECTION]->() "
            "RETURN count(m) AS n", {"c": SLUG}).single()["n"]
        assert left == 0

    def test_a_session_that_does_not_exist_is_refused(self, graph):
        with pytest.raises(ValueError):
            graph.execute_write(lambda tx: transcripts.record(
                tx, slug=SLUG, session=f"hb:{SLUG}:session-99", number=99,
                said=[Said("Ana", "hello")]))


class TestWhatItSuggests:
    def test_a_planned_scene_whose_cast_was_named_comes_back(self, graph):
        """Evidence, offered. Not a verdict, and not an edge."""
        graph.run(
            "MATCH (c:Campaign {slug:$c}) "
            "CREATE (s:Section {id:$id, heading:'The Village', text:$t, "
            "  plane:'campaign', campaign:$c}) "
            "MERGE (c)-[:HAS_SECTION]->(s)",
            {"c": SLUG, "id": f"hb:{SLUG}:village",
             "t": "Ireena Kolyana waits here."}).consume()
        graph.execute_write(lambda tx: __import__(
            "backend.campaign.homebrew", fromlist=["rescan"]).rescan(
                tx, slug=SLUG, section_id=f"hb:{SLUG}:village"))

        session = _session(graph)
        graph.execute_write(lambda tx: sessions.plan(
            tx, slug=SLUG, session=session, section=f"hb:{SLUG}:village"))
        graph.execute_write(lambda tx: transcripts.record(
            tx, slug=SLUG, session=session, number=1,
            said=[Said("Ana", "Ireena Kolyana rides with us.")]))

        found = graph.execute_read(lambda tx: transcripts.touched(
            tx, slug=SLUG, session=session))
        assert [f["heading"] for f in found] == ["The Village"]
        assert found[0]["names"] == ["Ireena Kolyana"]

    def test_it_writes_nothing(self, graph):
        session = _session(graph)
        graph.execute_write(lambda tx: transcripts.record(
            tx, slug=SLUG, session=session, number=1,
            said=[Said("Ana", "Ireena Kolyana rides with us.")]))
        graph.execute_read(lambda tx: transcripts.touched(
            tx, slug=SLUG, session=session))
        covered = graph.run(
            "MATCH (:Session {id:$s})-[r:COVERED]->() RETURN count(r) AS n",
            {"s": session}).single()["n"]
        assert covered == 0
