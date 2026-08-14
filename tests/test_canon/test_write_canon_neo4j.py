"""The half of the write path that only a real Neo4j can pin.

Atomicity in particular cannot be asserted against a fake: a stub session that
records calls passes whether or not the calls shared a transaction, which is
precisely the bug. Every test here runs against the live local database and is
marked `neo4j`, which the suite deselects by default.

Test nodes carry the `pytest:` BOOK prefix in their ids rather than `cos:`, so
the fixture's cleanup can never reach a real chapter's canon -- and, now that
ids are global to a book, a test node named `Church` can never MERGE onto the
real book's. Test chapters are additionally slugged `pytest-`.
"""

from dataclasses import replace

import pytest

from backend.canon.assembler import slugify
from backend.canon.writer import (
    CANON_PLANE,
    CampaignDataAttached,
    ChapterAlreadyWritten,
    WriteEdge,
    WriteNode,
    count_canon_nodes,
    ensure_schema,
    write_chapter,
)
from backend.core.database import neo4j_session
from backend.graph.schema import RelationshipType
from backend.scripts.review_queue import fetch_rows, render

pytestmark = pytest.mark.neo4j

CHAPTER_A = "pytest-chapter-a"
CHAPTER_B = "pytest-chapter-b"
TEST_ID_PREFIX = "pytest:"


def _clean(session) -> None:
    """Ids are GLOBAL now, so a test node named `Church` would MERGE onto the
    real book's Church and this cleanup would then delete it. Every test node
    therefore carries the `pytest:` book prefix instead of `cos:`, and cleanup
    reaches nothing else."""
    session.run(
        "MATCH (n:Entity) WHERE n.id STARTS WITH $prefix DETACH DELETE n",
        {"prefix": TEST_ID_PREFIX},
    )
    session.run("MATCH (c:Chapter) WHERE c.slug IN $slugs DETACH DELETE c", {"slugs": SLUGS})


SLUGS = [CHAPTER_A, CHAPTER_B]


@pytest.fixture
def graph():
    """A session whose test chapters are empty before and after."""
    with neo4j_session() as session:
        ensure_schema(session)
        _clean(session)
        yield session
        _clean(session)


def ident(name: str, key: str = "", chapter_slug: str = CHAPTER_A) -> str:
    """`mint_id`'s shape under the `pytest:` book -- see `_clean`."""
    if key:
        return f"{TEST_ID_PREFIX}{chapter_slug}:{key.lower()}-{slugify(name)}"
    return f"{TEST_ID_PREFIX}{slugify(name)}"


def node(
    name: str,
    chapter_slug: str = CHAPTER_A,
    entity_type: str = "LOCATION",
    key: str = "",
) -> WriteNode:
    return WriteNode(
        id=ident(name, key, chapter_slug),
        name=name,
        entity_types=(entity_type,),
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


class TestStatusInTheGraph:
    """The split has to be queryable, or it does not exist.

    Recording it only in a run artifact would leave a DM or a generator reading
    `Ismark OPPOSES Ireena` out of the graph with exactly the same authority as
    `Church CONTAINS Undercroft`, which is the defect this whole layer answers.
    """

    def test_a_query_can_separate_accepted_from_proposed(self, graph):
        church, undercroft = node("Church"), node("Undercroft")
        ireena = node("Ireena Kolyana", entity_type="NPC")
        derived = link(undercroft, church)
        proposed = WriteEdge(
            source_id=ireena.id,
            target_id=church.id,
            rel_type=RelationshipType.THREATENS,
            chapter_slug=CHAPTER_A,
            evidence="Ireena menaces the church.",
        )
        write_chapter(graph, CHAPTER_A, [church, undercroft, ireena], [derived, proposed])

        rows = graph.run(
            """
            MATCH ()-[r]->() WHERE r.chapter_slug = $slug
            RETURN type(r) AS t, r.status AS status ORDER BY t
            """,
            {"slug": CHAPTER_A},
        ).data()
        assert rows == [
            {"t": "LOCATED_IN", "status": "accepted"},
            {"t": "THREATENS", "status": "proposed"},
        ]

    def test_node_status_lands_too(self, graph):
        accepted = replace(node("Church"), status="accepted")
        write_chapter(graph, CHAPTER_A, [accepted, node("Gertruda", entity_type="NPC")], [])

        rows = graph.run(
            "MATCH (n:Entity)-[:MENTIONED_IN]->(:Chapter {slug:$slug}) "
            "RETURN n.name AS name, n.status AS status ORDER BY name",
            {"slug": CHAPTER_A},
        ).data()
        assert rows == [
            {"name": "Church", "status": "accepted"},
            {"name": "Gertruda", "status": "proposed"},
        ]

    def test_the_review_queue_reads_the_proposed_edges_and_skips_the_accepted(self, graph):
        """What a human sees at gate G3 comes out of the graph, not a file."""
        church, undercroft = node("Church"), node("Undercroft")
        ireena = node("Ireena Kolyana", entity_type="NPC")
        proposed = WriteEdge(
            source_id=ireena.id,
            target_id=church.id,
            rel_type=RelationshipType.THREATENS,
            chapter_slug=CHAPTER_A,
            evidence="Ireena menaces the church.",
            conflict="IDENTITY_OF",
        )
        write_chapter(
            graph, CHAPTER_A, [church, undercroft, ireena], [link(undercroft, church), proposed]
        )

        rows = fetch_rows(graph, CHAPTER_A)

        assert [r["rel_type"] for r in rows] == ["THREATENS"]
        assert rows[0]["evidence"] == "Ireena menaces the church."
        assert rows[0]["conflict"] == "IDENTITY_OF"
        assert "CONFLICTS WITH IDENTITY_OF" in render(CHAPTER_A, rows)


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
            {"id": ident("Undercroft")},
        ).single()["c"] == 0

    def test_an_empty_chapter_is_not_a_written_one(self, graph):
        """Nothing to refuse: the refusal is about existing nodes, not the slug."""
        write_chapter(graph, CHAPTER_A, [node("Church")], [])
        assert count_canon_nodes(graph, CHAPTER_A) == 1


class TestReplace:
    def test_replace_removes_only_that_chapters_canon(self, graph):
        a_church = node("Church", CHAPTER_A)
        b_chapel = node("Chapel", CHAPTER_B)
        b_undercroft = node("Undercroft", CHAPTER_B)
        write_chapter(graph, CHAPTER_A, [a_church], [])
        write_chapter(
            graph,
            CHAPTER_B,
            [b_chapel, b_undercroft],
            [link(b_undercroft, b_chapel, chapter_slug=CHAPTER_B)],
        )

        summary = write_chapter(graph, CHAPTER_A, [node("Crypt", CHAPTER_A)], [], replace=True)

        assert summary["deleted_nodes"] == 1
        assert count_canon_nodes(graph, CHAPTER_A) == 1
        assert graph.run(
            "MATCH (n:Entity {id:$id}) RETURN count(n) AS c", {"id": a_church.id}
        ).single()["c"] == 0
        # Chapter B named different entities, and nothing about replacing A
        # reaches them.
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

    def test_replace_leaves_campaign_data_carrying_the_same_chapter_slug(self, graph):
        """`plane='canon'` is the only thing protecting somebody's game.

        Both deletes are scoped by plane AND chapter_slug. The plane half is
        inert today only because nothing on the campaign plane carries a
        `chapter_slug` -- the moment stage 2b copies one across for provenance,
        dropping that predicate would delete a table's own nodes and edges on
        every canon re-run. So the campaign node here carries the SAME
        chapter_slug as the canon it sits beside.
        """
        canon = node("Church")
        write_chapter(graph, CHAPTER_A, [canon], [])
        graph.run(
            """
            CREATE (a:Entity {id:$a, name:'party notes', plane:'campaign', chapter_slug:$slug})
            CREATE (b:Entity {id:$b, name:'session 3', plane:'campaign', chapter_slug:$slug})
            CREATE (a)-[:OCCURRED_AT {plane:'campaign', chapter_slug:$slug}]->(b)
            """,
            {
                "a": f"{TEST_ID_PREFIX}campaign-a",
                "b": f"{TEST_ID_PREFIX}campaign-b",
                "slug": CHAPTER_A,
            },
        )

        write_chapter(graph, CHAPTER_A, [node("Crypt")], [], replace=True)

        assert (
            graph.run(
                "MATCH (n:Entity {plane:'campaign', chapter_slug:$slug}) RETURN count(n) AS c",
                {"slug": CHAPTER_A},
            ).single()["c"]
            == 2
        )
        assert (
            graph.run(
                "MATCH ()-[r]->() WHERE r.plane = 'campaign' AND r.chapter_slug = $slug "
                "RETURN count(r) AS c",
                {"slug": CHAPTER_A},
            ).single()["c"]
            == 1
        )
        # ...and the canon half was still replaced.
        assert count_canon_nodes(graph, CHAPTER_A) == 1

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


class TestTypeIsALabel:
    """`MATCH (n:NPC)` rather than `MATCH (n:Entity {entity_type:'NPC'})`.

    A label is what Neo4j indexes, what the browser colours by, and -- unlike a
    scalar property -- what can hold two readings of a disputed type at once.
    """

    def test_the_type_is_a_label(self, graph):
        eva = node("Madam Eva", entity_type="NPC")
        write_chapter(graph, CHAPTER_A, [eva], [])

        assert graph.run(
            "MATCH (n:NPC {id:$id}) RETURN count(n) AS c", {"id": eva.id}
        ).single()["c"] == 1

    def test_the_type_is_not_also_a_property(self, graph):
        eva = node("Madam Eva", entity_type="NPC")
        write_chapter(graph, CHAPTER_A, [eva], [])

        assert graph.run(
            "MATCH (n:Entity {id:$id}) RETURN n.entity_type AS t", {"id": eva.id}
        ).single()["t"] is None

    def test_a_disputed_type_is_one_node_wearing_both_labels(self, graph):
        barovia = replace(node("Barovia"), entity_types=("LOCATION", "SETTING"))
        write_chapter(graph, CHAPTER_A, [barovia], [])

        rows = graph.run(
            "MATCH (n:Entity {id:$id}) RETURN labels(n) AS labels", {"id": barovia.id}
        ).data()
        assert len(rows) == 1
        assert sorted(rows[0]["labels"]) == ["Entity", "LOCATION", "SETTING"]

    def test_entity_still_finds_everything(self, graph):
        """The `:Entity` label is kept so existing whole-graph queries survive."""
        write_chapter(graph, CHAPTER_A, [node("Madam Eva", entity_type="NPC")], [])
        assert count_canon_nodes(graph, CHAPTER_A) == 1


class TestLocationSubtypeIsALabel:
    """A rung of the spatial hierarchy, beside `:LOCATION` and never instead.

    `:LOCATION` is what makes "every place" a one-word query, and it stays on
    every one of them. The subtype narrows it: `MATCH (n:AREA)` is every room.
    """

    def area(self, name: str = "Chapel", subtype: str = "AREA") -> WriteNode:
        return replace(node(name), location_subtype=subtype)

    def test_the_subtype_lands_beside_location(self, graph):
        chapel = self.area()
        write_chapter(graph, CHAPTER_A, [chapel], [])

        labels = graph.run(
            "MATCH (n:Entity {id:$id}) RETURN labels(n) AS labels", {"id": chapel.id}
        ).single()["labels"]
        assert sorted(labels) == ["AREA", "Entity", "LOCATION"]

    def test_an_unclassified_place_gets_no_rung(self, graph):
        """No default: a place with no derivable and no authored subtype must be
        visibly unclassified rather than quietly filed somewhere."""
        castle = node("Castle Ravenloft")
        write_chapter(graph, CHAPTER_A, [castle], [])

        labels = graph.run(
            "MATCH (n:Entity {id:$id}) RETURN labels(n) AS labels", {"id": castle.id}
        ).single()["labels"]
        assert sorted(labels) == ["Entity", "LOCATION"]

    def test_a_place_wears_exactly_one_rung(self, graph):
        """A place reclassified must not end up wearing both rungs. `SET`
        unions, so the write has to clear the rungs it is replacing.

        Two CHAPTERS, not a `--replace` of one. A replace deletes the node and
        writes it fresh, so the old labels go with the node and the REMOVE is
        never exercised -- the version of this test that did that passed with
        the REMOVE clause deleted, which is a test that cannot fail.

        The scenario is real: an unkeyed place is one global node, and editing
        its authored rung (`Vallaki` REGION to SETTLEMENT) re-labels a node that
        every other chapter naming it keeps alive.
        """
        first = self.area("Vallaki", "SETTLEMENT")
        write_chapter(graph, CHAPTER_A, [first], [])
        write_chapter(
            graph,
            CHAPTER_B,
            [replace(first, chapter_slug=CHAPTER_B, location_subtype="REGION")],
            [],
        )

        labels = graph.run(
            "MATCH (n:Entity {id:$id}) RETURN labels(n) AS labels", {"id": first.id}
        ).single()["labels"]
        assert sorted(labels) == ["Entity", "LOCATION", "REGION"]

    def test_the_superseded_rung_is_gone_not_merely_outnumbered(self, graph):
        """Stated as its own assertion because the one above passes on a node
        wearing `:REGION:SETTLEMENT` if the reader only checks membership."""
        first = self.area("Vallaki", "SETTLEMENT")
        write_chapter(graph, CHAPTER_A, [first], [])
        write_chapter(
            graph,
            CHAPTER_B,
            [replace(first, chapter_slug=CHAPTER_B, location_subtype="REGION")],
            [],
        )

        assert graph.run(
            "MATCH (n:SETTLEMENT {id:$id}) RETURN count(n) AS c", {"id": first.id}
        ).single()["c"] == 0

    def test_a_chapter_that_says_nothing_about_the_rung_leaves_it_alone(self, graph):
        """A chapter merely MENTIONING a place must not strip the rung the
        chapter that is ABOUT it established. Only a write that HAS a rung
        clears, which is why the REMOVE is conditional.

        `Vallaki` unkeyed is one global node. Chapter 5 is about it and writes
        SITE; chapter 3 names it in passing, derives nothing, and writes the
        same id. Whichever lands second must not be the one that decides.
        """
        about = self.area("Vallaki", "SITE")
        write_chapter(graph, CHAPTER_A, [about], [])
        write_chapter(graph, CHAPTER_B, [node("Vallaki", CHAPTER_B)], [])

        labels = graph.run(
            "MATCH (n:Entity {id:$id}) RETURN labels(n) AS labels", {"id": about.id}
        ).single()["labels"]
        assert sorted(labels) == ["Entity", "LOCATION", "SITE"]

    def test_every_place_is_still_one_word_away(self, graph):
        write_chapter(
            graph,
            CHAPTER_A,
            [self.area(), self.area("Church", "SITE"), node("Castle Ravenloft")],
            [],
        )

        found = graph.run(
            "MATCH (n:LOCATION {plane:$plane}) WHERE n.id STARTS WITH $prefix "
            "RETURN count(n) AS c",
            {"plane": CANON_PLANE, "prefix": TEST_ID_PREFIX},
        ).single()["c"]
        assert found == 3


class TestGlobalEntities:
    def test_one_npc_named_by_two_chapters_is_one_node(self, graph):
        a = node("Madam Eva", CHAPTER_A, "NPC")
        b = node("Madam Eva", CHAPTER_B, "NPC")
        write_chapter(graph, CHAPTER_A, [a], [])
        write_chapter(graph, CHAPTER_B, [b], [])

        assert a.id == b.id
        assert graph.run(
            "MATCH (n:Entity {id:$id}) RETURN count(n) AS c", {"id": a.id}
        ).single()["c"] == 1

    def test_a_second_chapter_adds_an_edge_rather_than_a_node(self, graph):
        write_chapter(graph, CHAPTER_A, [node("Madam Eva", CHAPTER_A, "NPC")], [])
        write_chapter(graph, CHAPTER_B, [node("Madam Eva", CHAPTER_B, "NPC")], [])

        slugs = graph.run(
            """
            MATCH (n:Entity {id:$id})-[:MENTIONED_IN]->(c:Chapter)
            RETURN c.slug AS slug ORDER BY slug
            """,
            {"id": ident("Madam Eva")},
        ).value()
        assert slugs == [CHAPTER_A, CHAPTER_B]

    def test_a_keyed_place_in_two_chapters_is_still_two_rooms(self, graph):
        """`K61a. Empty Cell` and a same-named cell in another chapter are not
        one room, and merging them by name would delete an edge."""
        a = node("Empty Cell", CHAPTER_A, key="K61a")
        b = node("Empty Cell", CHAPTER_B, key="K61a")
        write_chapter(graph, CHAPTER_A, [a], [])
        write_chapter(graph, CHAPTER_B, [b], [])

        assert a.id != b.id
        assert graph.run(
            "MATCH (n:Entity) WHERE n.id STARTS WITH $p AND n.name = 'Empty Cell' "
            "RETURN count(n) AS c",
            {"p": TEST_ID_PREFIX},
        ).single()["c"] == 2

    def test_the_appearance_carries_the_section_it_was_read_in(self, graph):
        write_chapter(graph, CHAPTER_A, [node("Madam Eva", entity_type="NPC")], [])

        props = graph.run(
            "MATCH (:Entity {id:$id})-[m:MENTIONED_IN]->(:Chapter {slug:$slug}) "
            "RETURN properties(m) AS p",
            {"id": ident("Madam Eva"), "slug": CHAPTER_A},
        ).single()["p"]
        assert props == {"section_heading": "E5. Church", "section_index": 3}

    def test_replacing_one_chapter_keeps_a_node_another_chapter_still_names(self, graph):
        write_chapter(graph, CHAPTER_A, [node("Madam Eva", CHAPTER_A, "NPC")], [])
        write_chapter(graph, CHAPTER_B, [node("Madam Eva", CHAPTER_B, "NPC")], [])

        write_chapter(graph, CHAPTER_B, [node("Strahd", CHAPTER_B, "NPC")], [], replace=True)

        assert graph.run(
            "MATCH (n:Entity {id:$id}) RETURN count(n) AS c", {"id": ident("Madam Eva")}
        ).single()["c"] == 1
        assert count_canon_nodes(graph, CHAPTER_A) == 1
        assert count_canon_nodes(graph, CHAPTER_B) == 1
