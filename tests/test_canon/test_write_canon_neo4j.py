"""The half of the write path that only a real Neo4j can pin.

Atomicity in particular cannot be asserted against a fake: a stub session that
records calls passes whether or not the calls shared a transaction, which is
precisely the bug. Every test here runs against the live local database and is
marked `neo4j`, which the suite deselects by default.

Test chapters use slugs prefixed `pytest-`, so the fixture's cleanup can never
reach a real chapter's canon.
"""

import pytest

from backend.canon.writer import (
    CANON_PLANE,
    CampaignDataAttached,
    ChapterAlreadyWritten,
    WriteEdge,
    WriteNode,
    count_canon_nodes,
    ensure_schema,
    mint_id,
    write_chapter,
)
from backend.core.database import neo4j_session
from backend.graph.schema import RelationshipType

pytestmark = pytest.mark.neo4j

CHAPTER_A = "pytest-chapter-a"
CHAPTER_B = "pytest-chapter-b"
TEST_ID_PREFIX = "pytest:"


def _clean(session) -> None:
    session.run(
        """
        MATCH (n:Entity)
        WHERE n.chapter_slug IN $slugs OR n.id STARTS WITH $prefix
        DETACH DELETE n
        """,
        {"slugs": [CHAPTER_A, CHAPTER_B], "prefix": TEST_ID_PREFIX},
    )


@pytest.fixture
def graph():
    """A session whose test chapters are empty before and after."""
    with neo4j_session() as session:
        ensure_schema(session)
        _clean(session)
        yield session
        _clean(session)


def node(name: str, chapter_slug: str = CHAPTER_A, entity_type: str = "LOCATION") -> WriteNode:
    return WriteNode(
        id=mint_id(chapter_slug, entity_type, name),
        name=name,
        entity_type=entity_type,
        chapter_slug=chapter_slug,
        section_heading="E5. Church",
        section_index=3,
        votes=5,
        description=f"{name} description",
    )


def link(
    source: WriteNode,
    target: WriteNode,
    rel_type: RelationshipType = RelationshipType.LOCATED_IN,
    chapter_slug: str = CHAPTER_A,
) -> WriteEdge:
    return WriteEdge(
        source_id=source.id,
        target_id=target.id,
        rel_type=rel_type,
        chapter_slug=chapter_slug,
        evidence="derived from document structure",
        section_heading="E5g. Undercroft",
        section_index=4,
        votes=0,
    )


class TestHappyPath:
    def test_nodes_and_edges_land_stamped_canon(self, graph):
        church, undercroft = node("Church"), node("Undercroft")
        write_chapter(graph, CHAPTER_A, [church, undercroft], [link(undercroft, church)])

        record = graph.run("MATCH (n:Entity {id:$id}) RETURN n", {"id": church.id}).single()
        assert dict(record["n"]) == {"id": church.id, **church.properties}

        rel = graph.run(
            """
            MATCH (a:Entity {id:$source})-[r]->(b:Entity {id:$target})
            RETURN type(r) AS t, properties(r) AS p
            """,
            {"source": undercroft.id, "target": church.id},
        ).single()
        assert rel["t"] == "LOCATED_IN"
        assert rel["p"]["plane"] == CANON_PLANE
        assert rel["p"]["chapter_slug"] == CHAPTER_A
        assert rel["p"]["layer"] == "spatial"
        assert rel["p"]["evidence"] == "derived from document structure"


    def test_a_resolved_endpoint_is_visible_in_the_graph(self, graph):
        """The verifier's constraint check is vacuous on these edges. A reader
        of the graph must be able to tell which ones without re-deriving it."""
        ireena = node("Ireena Kolyana", entity_type="NPC")
        tatyana = node("Tatyana", entity_type="NPC")
        resolved = WriteEdge(
            source_id=ireena.id,
            target_id=tatyana.id,
            rel_type=RelationshipType.IDENTITY_OF,
            chapter_slug=CHAPTER_A,
            endpoint_resolved="constraint",
        )
        write_chapter(graph, CHAPTER_A, [ireena, tatyana], [resolved, link(tatyana, ireena)])

        rows = graph.run(
            """
            MATCH ()-[r]->() WHERE r.chapter_slug = $slug
            RETURN type(r) AS t, r.endpoint_resolved AS resolved
            ORDER BY t
            """,
            {"slug": CHAPTER_A},
        ).data()
        assert rows == [
            {"t": "IDENTITY_OF", "resolved": "constraint"},
            {"t": "LOCATED_IN", "resolved": None},
        ]


class TestAtomicity:
    def test_a_write_that_raises_partway_leaves_the_graph_unchanged(self, graph):
        """The property everything else hangs off.

        The loop discovers work by asking which chapters have at least one node,
        so a chapter that half-commits looks DONE forever and carries a silently
        truncated chapter into every campaign that inherits the canon plane.

        The failure here is real, not injected: the second edge names an
        endpoint that no node in the batch creates, so its `MATCH ... MERGE`
        matches nothing and `_write_edge` raises -- after two nodes and one edge
        have already been written inside the transaction. A writer that
        committed as it went would leave those behind.
        """
        church, undercroft = node("Church"), node("Undercroft")
        missing = node("Crypt")  # deliberately NOT written
        edges = [link(undercroft, church), link(church, missing)]

        with pytest.raises(ValueError, match="edge endpoint missing"):
            write_chapter(graph, CHAPTER_A, [church, undercroft], edges)

        assert count_canon_nodes(graph, CHAPTER_A) == 0
        assert (
            graph.run(
                "MATCH ()-[r]->() WHERE r.chapter_slug = $slug RETURN count(r) AS c",
                {"slug": CHAPTER_A},
            ).single()["c"]
            == 0
        )

    def test_a_failed_replace_leaves_the_previous_chapter_intact(self, graph):
        """A delete that commits before a failed write is the same hazard.

        The first write succeeds; the second asks to replace it and then fails.
        What must survive is the FIRST chapter, whole -- not an empty chapter
        that the loop's predicate would read as unwritten and a human as done.
        """
        church, undercroft = node("Church"), node("Undercroft")
        write_chapter(graph, CHAPTER_A, [church, undercroft], [link(undercroft, church)])

        crypt = node("Crypt")
        with pytest.raises(ValueError, match="edge endpoint missing"):
            write_chapter(
                graph, CHAPTER_A, [church], [link(church, crypt)], replace=True
            )

        assert count_canon_nodes(graph, CHAPTER_A) == 2
        assert (
            graph.run(
                "MATCH ()-[r]->() WHERE r.chapter_slug = $slug RETURN count(r) AS c",
                {"slug": CHAPTER_A},
            ).single()["c"]
            == 1
        )


class TestRewriteRefusal:
    def test_writing_a_chapter_that_already_has_nodes_refuses(self, graph):
        church = node("Church")
        write_chapter(graph, CHAPTER_A, [church], [])

        with pytest.raises(ChapterAlreadyWritten) as caught:
            write_chapter(graph, CHAPTER_A, [node("Undercroft")], [])

        assert caught.value.chapter_slug == CHAPTER_A
        assert caught.value.nodes == 1
        assert count_canon_nodes(graph, CHAPTER_A) == 1
        assert graph.run(
            "MATCH (n:Entity {id:$id}) RETURN count(n) AS c",
            {"id": mint_id(CHAPTER_A, "LOCATION", "Undercroft")},
        ).single()["c"] == 0

    def test_an_empty_chapter_is_not_a_written_one(self, graph):
        """Nothing to refuse: the refusal is about existing nodes, not the slug."""
        write_chapter(graph, CHAPTER_A, [node("Church")], [])
        assert count_canon_nodes(graph, CHAPTER_A) == 1


class TestReplace:
    def test_replace_removes_only_that_chapters_canon(self, graph):
        a_church = node("Church", CHAPTER_A)
        b_church = node("Church", CHAPTER_B)
        b_undercroft = node("Undercroft", CHAPTER_B)
        write_chapter(graph, CHAPTER_A, [a_church], [])
        write_chapter(
            graph,
            CHAPTER_B,
            [b_church, b_undercroft],
            [link(b_undercroft, b_church, chapter_slug=CHAPTER_B)],
        )

        summary = write_chapter(graph, CHAPTER_A, [node("Crypt", CHAPTER_A)], [], replace=True)

        assert summary["deleted_nodes"] == 1
        assert count_canon_nodes(graph, CHAPTER_A) == 1
        assert graph.run(
            "MATCH (n:Entity {id:$id}) RETURN count(n) AS c", {"id": a_church.id}
        ).single()["c"] == 0
        # Chapter B is a different chapter of the same book, and same-named
        # rooms in two chapters are two rooms.
        assert count_canon_nodes(graph, CHAPTER_B) == 2
        assert (
            graph.run(
                "MATCH ()-[r]->() WHERE r.chapter_slug = $slug RETURN count(r) AS c",
                {"slug": CHAPTER_B},
            ).single()["c"]
            == 1
        )

    def test_replace_deletes_this_chapters_canon_edges(self, graph):
        church, undercroft = node("Church"), node("Undercroft")
        write_chapter(graph, CHAPTER_A, [church, undercroft], [link(undercroft, church)])

        summary = write_chapter(graph, CHAPTER_A, [church], [], replace=True)

        assert summary["deleted_edges"] == 1
        assert (
            graph.run(
                "MATCH ()-[r]->() WHERE r.chapter_slug = $slug RETURN count(r) AS c",
                {"slug": CHAPTER_A},
            ).single()["c"]
            == 0
        )

    def test_replace_refuses_when_campaign_data_hangs_off_the_chapter(self, graph):
        """A campaign's own play is somebody's game.

        DETACH DELETE would take the campaign's INSTANCE_OF edge with the canon
        node it points at. Refusing is the only behaviour that keeps "never
        delete anything outside plane='canon'" true.
        """
        church = node("Church")
        write_chapter(graph, CHAPTER_A, [church], [])
        graph.run(
            """
            MATCH (canon:Entity {id:$canon_id})
            CREATE (pc:Entity {id:$pc_id, name:$name, plane:'campaign'})
            CREATE (pc)-[:INSTANCE_OF {plane:'campaign'}]->(canon)
            """,
            {
                "canon_id": church.id,
                "pc_id": f"{TEST_ID_PREFIX}campaign-church",
                "name": "the table's own church",
            },
        )

        with pytest.raises(CampaignDataAttached):
            write_chapter(graph, CHAPTER_A, [node("Crypt")], [], replace=True)

        assert count_canon_nodes(graph, CHAPTER_A) == 1
        assert (
            graph.run(
                "MATCH (n:Entity {id:$id})-[r]->() RETURN count(r) AS c",
                {"id": f"{TEST_ID_PREFIX}campaign-church"},
            ).single()["c"]
            == 1
        )


class TestChapterScoping:
    def test_two_chapters_same_room_are_two_nodes(self, graph):
        a = node("Chapel", CHAPTER_A)
        b = node("Chapel", CHAPTER_B)
        write_chapter(graph, CHAPTER_A, [a], [])
        write_chapter(graph, CHAPTER_B, [b], [])

        assert a.id != b.id
        # Scoped to the test chapters: a real chapter's canon may be in this
        # database, and it has a `Chapel` of its own.
        assert (
            graph.run(
                """
                MATCH (n:Entity)
                WHERE n.name = 'Chapel' AND n.plane = $plane AND n.chapter_slug IN $slugs
                RETURN count(n) AS c
                """,
                {"plane": CANON_PLANE, "slugs": [CHAPTER_A, CHAPTER_B]},
            ).single()["c"]
            == 2
        )
