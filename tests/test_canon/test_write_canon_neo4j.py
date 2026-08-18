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

from backend.canon.aliases import WriteAlias
from backend.canon.assembler import slugify
from backend.canon.cooccurrence import plan_co_occurrences
from backend.canon.models import Section
from backend.canon.passage import derive_passage
from backend.canon.spine import ChapterSpine, plan_spine, section_id
from backend.canon.writer import (
    CANON_PLANE,
    CampaignDataAttached,
    ChapterAlreadyWritten,
    WriteEdge,
    WriteNode,
    count_canon_nodes,
    count_mentions,
    ensure_schema,
    write_chapter,
)
from backend.core.database import neo4j_session
from backend.graph.schema import CO_OCCURS_WITH, RelationshipType
from backend.scripts.review_queue import fetch_rows, render

pytestmark = pytest.mark.neo4j

CHAPTER_A = "pytest-chapter-a"
CHAPTER_B = "pytest-chapter-b"
TEST_ID_PREFIX = "pytest:"
TEST_BOOK = "pytest-book"

#: A keyed test place mints `cos:<chapter>:<key>-<slug>` through `mint_id`, which
#: hardcodes the book -- so the `pytest:` prefix cannot reach those and cleanup
#: has to name the chapter-scoped shape too.
KEYED_ID_PREFIXES = [f"cos:{CHAPTER_A}:", f"cos:{CHAPTER_B}:"]


def _clean(session) -> None:
    """Ids are GLOBAL now, so a test node named `Church` would MERGE onto the
    real book's Church and this cleanup would then delete it. Every test node
    therefore carries the `pytest:` book prefix instead of `cos:`, and cleanup
    reaches nothing else.

    The spine is cleaned by CHAPTER, which is the only scope that identifies a
    section or a mention -- both are chapter-owned by construction, and both are
    slugged `pytest-` here.
    """
    session.run(
        "MATCH (n:Entity) WHERE n.id STARTS WITH $prefix DETACH DELETE n",
        {"prefix": TEST_ID_PREFIX},
    )
    for prefix in KEYED_ID_PREFIXES:
        session.run(
            "MATCH (n:Entity) WHERE n.id STARTS WITH $prefix DETACH DELETE n",
            {"prefix": prefix},
        )
    session.run("MATCH (m:Mention) WHERE m.chapter_slug IN $slugs DETACH DELETE m",
                {"slugs": SLUGS})
    session.run("MATCH (s:Section) WHERE s.chapter_slug IN $slugs DETACH DELETE s",
                {"slugs": SLUGS})
    session.run("MATCH (c:Chapter) WHERE c.slug IN $slugs DETACH DELETE c", {"slugs": SLUGS})
    session.run("MATCH (b:Book {slug:$slug}) DETACH DELETE b", {"slug": TEST_BOOK})
    # An `:Alias` node is GLOBAL -- it is keyed on the surface form and nothing
    # else -- so it cannot be cleaned by an id prefix or a chapter. Orphans are
    # the honest scope: the entities above have just been DETACH DELETEd, so
    # every alias that named one now names nothing, and an alias naming nothing
    # is garbage whoever created it.
    session.run("MATCH (a:Alias) WHERE NOT (a)-[:ALIAS_OF]->() DETACH DELETE a")


SLUGS = [CHAPTER_A, CHAPTER_B]


@pytest.fixture
def graph():
    """A session whose test chapters are empty before and after."""
    with neo4j_session() as session:
        ensure_schema(session)
        _clean(session)
        yield session
        _clean(session)


#: Prefixed onto EVERY TOKEN of every test entity's name, and every token is
#: needed. The mention scan matches on NAME across the whole canon plane, so a
#: test node called `Church` is found by the real book's `E5. Church` sitting in
#: the same local database, and `count_canon_nodes` answers 2 for a chapter that
#: wrote one node. A suffix is not enough either: matching is whole-WORD, so the
#: real `Church` still matches inside `Church of Pytest`, and the real `Tatyana`
#: still matches inside `Ireena Tatyana`. Gluing the marker to the front of each
#: token puts a word character immediately before every real name, which the
#: matcher's `(?<!\\w)` refuses.
#:
#: The id prefix protects the graph from the tests; this protects the tests from
#: the graph.
NAME_MARKER = "Zz"


def named(name: str) -> str:
    """The name a test entity actually wears. See `NAME_MARKER`."""
    return " ".join(f"{NAME_MARKER}{token}" for token in name.split())


def ident(name: str, key: str = "", chapter_slug: str = CHAPTER_A) -> str:
    """`mint_id`'s shape under the `pytest:` book -- see `_clean`."""
    if key:
        return f"{TEST_ID_PREFIX}{chapter_slug}:{key.lower()}-{slugify(named(name))}"
    return f"{TEST_ID_PREFIX}{slugify(named(name))}"


def node(
    name: str,
    chapter_slug: str = CHAPTER_A,
    entity_type: str = "LOCATION",
    key: str = "",
) -> WriteNode:
    return WriteNode(
        id=ident(name, key, chapter_slug),
        name=named(name),
        entity_types=(entity_type,),
        chapter_slug=chapter_slug,
        votes=5,
    )


def spine(
    *nodes: WriteNode,
    chapter_slug: str = CHAPTER_A,
    chapter_index: int = 0,
    sections: list[Section] | None = None,
    location_ids: set[str] | None = None,
) -> ChapterSpine:
    """A spine with one prose section per node, whose text names that node.

    So every node written by a test earns a real `:Mention` from a real scan
    rather than from a fixture asserting one -- which is what `count_canon_nodes`
    and the replace path now read. Headings are deliberately UNKEYED (`Section
    0`, not `E1. Church`), so nothing here accidentally derives a `DESCRIBES`;
    the tests that want one build their sections by hand.
    """
    if sections is None:
        sections = [
            Section(
                chapter_slug=chapter_slug,
                chapter_title="A Test Chapter",
                heading=f"Section {index}",
                index=index,
                markdown=f"This section is about {written.name} and nothing else.",
                depth=1,
                parent_index=-1,
            )
            for index, written in enumerate(nodes)
        ]
    return plan_spine(
        book_slug=TEST_BOOK,
        book_title="A Test Book",
        chapter_slug=chapter_slug,
        chapter_title="A Test Chapter",
        chapter_index=chapter_index,
        sections=sections,
        location_ids=location_ids or set(),
    )


def write(
    session,
    chapter_slug: str,
    nodes: list[WriteNode],
    edges: list[WriteEdge],
    *,
    replace: bool = False,
    chapter_spine: ChapterSpine | None = None,
    aliases: list[WriteAlias] | None = None,
) -> dict:
    """`write_chapter` with a spine that names every node it is given.

    `aliases` defaults to nothing AUTHORED, which is the ordinary case: every
    node still ends up with its own name as an `:Alias`, from the backfill
    inside the transaction.
    """
    return write_chapter(
        session,
        chapter_slug,
        nodes,
        edges,
        chapter_spine or spine(*nodes, chapter_slug=chapter_slug),
        aliases or [],
        replace=replace,
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
        write(graph, CHAPTER_A, [church, undercroft], [link(undercroft, church)])

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
        write(graph, CHAPTER_A, [ireena, tatyana], [resolved, link(tatyana, ireena)])

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
        write(graph, CHAPTER_A, [church, undercroft, ireena], [derived, proposed])

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
        write(graph, CHAPTER_A, [accepted, node("Gertruda", entity_type="NPC")], [])

        rows = graph.run(
            "MATCH (:Chapter {slug:$slug})-[:HAS_SECTION]->(:Section)"
            "<-[:IN_SECTION]-(:Mention)-[:REFERS_TO]->(n:Entity) "
            "RETURN DISTINCT n.name AS name, n.status AS status ORDER BY name",
            {"slug": CHAPTER_A},
        ).data()
        assert rows == [
            {"name": named("Church"), "status": "accepted"},
            {"name": named("Gertruda"), "status": "proposed"},
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
        write(
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
            write(graph, CHAPTER_A, [church, undercroft], edges)

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
        write(graph, CHAPTER_A, [church, undercroft], [link(undercroft, church)])

        crypt = node("Crypt")
        with pytest.raises(ValueError, match="edge endpoint missing"):
            write(
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
        write(graph, CHAPTER_A, [church], [])

        with pytest.raises(ChapterAlreadyWritten) as caught:
            write(graph, CHAPTER_A, [node("Undercroft")], [])

        assert caught.value.chapter_slug == CHAPTER_A
        assert caught.value.nodes == 1
        assert count_canon_nodes(graph, CHAPTER_A) == 1
        assert graph.run(
            "MATCH (n:Entity {id:$id}) RETURN count(n) AS c",
            {"id": ident("Undercroft")},
        ).single()["c"] == 0

    def test_an_empty_chapter_is_not_a_written_one(self, graph):
        """Nothing to refuse: the refusal is about existing nodes, not the slug."""
        write(graph, CHAPTER_A, [node("Church")], [])
        assert count_canon_nodes(graph, CHAPTER_A) == 1


class TestReplace:
    def test_replace_removes_only_that_chapters_canon(self, graph):
        a_church = node("Church", CHAPTER_A)
        b_chapel = node("Chapel", CHAPTER_B)
        b_undercroft = node("Undercroft", CHAPTER_B)
        write(graph, CHAPTER_A, [a_church], [])
        write(
            graph,
            CHAPTER_B,
            [b_chapel, b_undercroft],
            [link(b_undercroft, b_chapel, chapter_slug=CHAPTER_B)],
        )

        summary = write(graph, CHAPTER_A, [node("Crypt", CHAPTER_A)], [], replace=True)

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
        write(graph, CHAPTER_A, [church, undercroft], [link(undercroft, church)])

        summary = write(graph, CHAPTER_A, [church], [], replace=True)

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
        write(graph, CHAPTER_A, [canon], [])
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

        write(graph, CHAPTER_A, [node("Crypt")], [], replace=True)

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
        write(graph, CHAPTER_A, [church], [])
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
            write(graph, CHAPTER_A, [node("Crypt")], [], replace=True)

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
        write(graph, CHAPTER_A, [eva], [])

        assert graph.run(
            "MATCH (n:NPC {id:$id}) RETURN count(n) AS c", {"id": eva.id}
        ).single()["c"] == 1

    def test_the_type_is_not_also_a_property(self, graph):
        eva = node("Madam Eva", entity_type="NPC")
        write(graph, CHAPTER_A, [eva], [])

        assert graph.run(
            "MATCH (n:Entity {id:$id}) RETURN n.entity_type AS t", {"id": eva.id}
        ).single()["t"] is None

    def test_a_disputed_type_is_one_node_wearing_both_labels(self, graph):
        barovia = replace(node("Barovia"), entity_types=("LOCATION", "SETTING"))
        write(graph, CHAPTER_A, [barovia], [])

        rows = graph.run(
            "MATCH (n:Entity {id:$id}) RETURN labels(n) AS labels", {"id": barovia.id}
        ).data()
        assert len(rows) == 1
        assert sorted(rows[0]["labels"]) == ["Entity", "LOCATION", "SETTING"]

    def test_entity_still_finds_everything(self, graph):
        """The `:Entity` label is kept so existing whole-graph queries survive."""
        write(graph, CHAPTER_A, [node("Madam Eva", entity_type="NPC")], [])
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
        write(graph, CHAPTER_A, [chapel], [])

        labels = graph.run(
            "MATCH (n:Entity {id:$id}) RETURN labels(n) AS labels", {"id": chapel.id}
        ).single()["labels"]
        assert sorted(labels) == ["AREA", "Entity", "LOCATION"]

    def test_an_unclassified_place_gets_no_rung(self, graph):
        """No default: a place with no derivable and no authored subtype must be
        visibly unclassified rather than quietly filed somewhere."""
        castle = node("Castle Ravenloft")
        write(graph, CHAPTER_A, [castle], [])

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
        write(graph, CHAPTER_A, [first], [])
        write(
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
        write(graph, CHAPTER_A, [first], [])
        write(
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
        write(graph, CHAPTER_A, [about], [])
        write(graph, CHAPTER_B, [node("Vallaki", CHAPTER_B)], [])

        labels = graph.run(
            "MATCH (n:Entity {id:$id}) RETURN labels(n) AS labels", {"id": about.id}
        ).single()["labels"]
        assert sorted(labels) == ["Entity", "LOCATION", "SITE"]

    def test_every_place_is_still_one_word_away(self, graph):
        write(
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


class TestArtifactIsALabel:
    """`:Artifact` beside `:ITEM`, and never instead of it.

    `:ITEM` is what makes "every object in the book" a one-word query and stays
    on every one of them. `:Artifact` narrows it to the three the Tarokka
    reading sends the party after.
    """

    def item(self, name: str = "Sunsword", is_artifact: bool = True, **kwargs) -> WriteNode:
        return replace(node(name, entity_type="ITEM"), is_artifact=is_artifact, **kwargs)

    def labels_of(self, graph, node_id: str) -> list[str]:
        return sorted(
            graph.run(
                "MATCH (n:Entity {id:$id}) RETURN labels(n) AS labels", {"id": node_id}
            ).single()["labels"]
        )

    def test_the_label_lands_beside_item(self, graph):
        sunsword = self.item()
        write(graph, CHAPTER_A, [sunsword], [])

        assert self.labels_of(graph, sunsword.id) == ["Artifact", "Entity", "ITEM"]

    def test_an_unauthored_item_stays_plain(self, graph):
        """No default. "Mundane" is the absence of significance, and the honest
        encoding of an absence is no label."""
        lamp = self.item("oil lamp", is_artifact=False)
        write(graph, CHAPTER_A, [lamp], [])

        assert self.labels_of(graph, lamp.id) == ["Entity", "ITEM"]

    def test_the_rung_remove_does_not_reach_it(self, graph):
        """THE TRAP. A place wears exactly one rung, so writing one REMOVEs
        every other rung. `:Artifact` is not on that ladder and must survive it,
        and so must the `:ITEM` it narrows.

        The scenario is a disputed type, which is routine here: two samples read
        one candidate as an object and as a place, the node wears both, and the
        rung it derives is written over labels that have nothing to do with it.
        """
        disputed = replace(
            self.item("Sunsword"),
            entity_types=("ITEM", "LOCATION"),
            location_subtype="AREA",
        )
        write(graph, CHAPTER_A, [disputed], [])

        assert self.labels_of(graph, disputed.id) == [
            "AREA",
            "Artifact",
            "Entity",
            "ITEM",
            "LOCATION",
        ]

    def test_a_rung_write_that_says_nothing_about_items_does_not_strip_it(self, graph):
        """THE TRAP, in the only form that can actually spring it.

        The test above passes even against a REMOVE that sweeps `:Artifact`,
        because the SET that puts the label back runs in the same statement --
        measured, by widening the REMOVE and watching it still pass. That is a
        test that cannot fail, and this project has shipped ten of them.

        So: the second write types the node only LOCATION, which gates
        `artifact_label` off and emits no SET at all, and its rung REMOVE runs
        alone against labels the FIRST write left behind. A REMOVE scoped to
        anything wider than the rungs takes `:Artifact` here and nothing puts it
        back.
        """
        first = self.item("Sunsword")
        write(graph, CHAPTER_A, [first], [])
        write(
            graph,
            CHAPTER_B,
            [
                replace(
                    first,
                    chapter_slug=CHAPTER_B,
                    entity_types=("LOCATION",),
                    is_artifact=False,
                    location_subtype="AREA",
                )
            ],
            [],
        )

        assert self.labels_of(graph, first.id) == [
            "AREA",
            "Artifact",
            "Entity",
            "ITEM",
            "LOCATION",
        ]

    def test_every_item_is_still_one_word_away(self, graph):
        """The narrowing must not cost the broad query the whole point of it."""
        write(
            graph, CHAPTER_A, [self.item(), self.item("oil lamp", is_artifact=False)], []
        )

        found = graph.run(
            "MATCH (n:ITEM {plane:$plane}) WHERE n.id STARTS WITH $prefix RETURN count(n) AS c",
            {"plane": CANON_PLANE, "prefix": TEST_ID_PREFIX},
        ).single()["c"]
        assert found == 2

    def test_the_artifacts_are_one_word_away_too(self, graph):
        """The point of the label: `MATCH (n:Artifact)` is the question a DM
        asks constantly, and a flat :ITEM could not answer it."""
        write(
            graph, CHAPTER_A, [self.item(), self.item("oil lamp", is_artifact=False)], []
        )

        found = graph.run(
            "MATCH (n:Artifact {plane:$plane}) WHERE n.id STARTS WITH $prefix "
            "RETURN n.name AS name",
            {"plane": CANON_PLANE, "prefix": TEST_ID_PREFIX},
        ).value("name")
        assert found == [named("Sunsword")]


class TestGlobalEntities:
    def test_one_npc_named_by_two_chapters_is_one_node(self, graph):
        a = node("Madam Eva", CHAPTER_A, "NPC")
        b = node("Madam Eva", CHAPTER_B, "NPC")
        write(graph, CHAPTER_A, [a], [])
        write(graph, CHAPTER_B, [b], [])

        assert a.id == b.id
        assert graph.run(
            "MATCH (n:Entity {id:$id}) RETURN count(n) AS c", {"id": a.id}
        ).single()["c"] == 1

    def test_a_second_chapter_adds_a_mention_rather_than_a_node(self, graph):
        write(graph, CHAPTER_A, [node("Madam Eva", CHAPTER_A, "NPC")], [])
        write(graph, CHAPTER_B, [node("Madam Eva", CHAPTER_B, "NPC")], [])

        slugs = graph.run(
            """
            MATCH (m:Mention)-[:REFERS_TO]->(:Entity {id:$id})
            RETURN m.chapter_slug AS slug ORDER BY slug
            """,
            {"id": ident("Madam Eva")},
        ).value()
        assert slugs == [CHAPTER_A, CHAPTER_B]

    def test_a_keyed_place_in_two_chapters_is_still_two_rooms(self, graph):
        """`K61a. Empty Cell` and a same-named cell in another chapter are not
        one room, and merging them by name would delete an edge."""
        a = node("Empty Cell", CHAPTER_A, key="K61a")
        b = node("Empty Cell", CHAPTER_B, key="K61a")
        write(graph, CHAPTER_A, [a], [])
        write(graph, CHAPTER_B, [b], [])

        assert a.id != b.id
        assert graph.run(
            "MATCH (n:Entity) WHERE n.id STARTS WITH $p AND n.name = $name "
            "RETURN count(n) AS c",
            {"p": TEST_ID_PREFIX, "name": named("Empty Cell")},
        ).single()["c"] == 2

    def test_replacing_one_chapter_keeps_a_node_another_chapter_still_names(self, graph):
        write(graph, CHAPTER_A, [node("Madam Eva", CHAPTER_A, "NPC")], [])
        write(graph, CHAPTER_B, [node("Madam Eva", CHAPTER_B, "NPC")], [])

        write(graph, CHAPTER_B, [node("Strahd", CHAPTER_B, "NPC")], [], replace=True)

        assert graph.run(
            "MATCH (n:Entity {id:$id}) RETURN count(n) AS c", {"id": ident("Madam Eva")}
        ).single()["c"] == 1
        assert count_canon_nodes(graph, CHAPTER_A) == 1
        assert count_canon_nodes(graph, CHAPTER_B) == 1


def prose(index: int, heading: str, text: str, chapter_slug: str = CHAPTER_A) -> Section:
    return Section(
        chapter_slug=chapter_slug,
        chapter_title="A Test Chapter",
        heading=heading,
        index=index,
        markdown=text,
        depth=1,
        parent_index=-1,
    )


class TestTheSpineInTheGraph:
    """Book, chapter, sections -- and the order the book reveals things."""

    def test_the_spine_hangs_together(self, graph):
        write(graph, CHAPTER_A, [node("Church")], [], chapter_spine=spine(
            node("Church"),
            chapter_index=3,
            sections=[prose(0, "Section 0", f"The {named('Church')} stands here."),
                      prose(1, "Section 1", "Nothing at all.")],
        ))

        row = graph.run(
            """
            MATCH (b:Book {slug:$book})-[h:HAS_CHAPTER]->(c:Chapter {slug:$slug})
                  -[hs:HAS_SECTION]->(s:Section)
            RETURN b.title AS book, c.index AS chapter_index, h.index AS edge_index,
                   collect(s.index) AS sections, count(hs) AS edges
            """,
            {"book": TEST_BOOK, "slug": CHAPTER_A},
        ).single()
        assert row["book"] == "A Test Book"
        assert row["chapter_index"] == 3
        assert row["edge_index"] == 3
        assert sorted(row["sections"]) == [0, 1]

    def test_every_node_a_write_creates_carries_a_caption(self, graph):
        """The invariant the Browser stylesheet's single caption rule rests on.

        Asserted over LABELS DISCOVERED IN THE GRAPH rather than a list written
        here, so a node kind added later fails this test instead of quietly
        rendering as a bare id. That is the whole point: an enumerated list
        would have to be remembered, and the thing being guarded against is
        precisely forgetting.
        """
        eva = node("Madam Eva", CHAPTER_A, "NPC")
        write(graph, CHAPTER_A, [eva], [], chapter_spine=spine(
            eva,
            sections=[prose(0, "Section 0", f"{named('Madam Eva')} reads the cards.")],
        ))

        missing = graph.run(
            """
            MATCH (n)
            WHERE (n.chapter_slug = $slug OR n.slug = $slug OR n.slug = $book
                   OR (n:Alias AND n.name STARTS WITH $marker))
              AND (n.display_name IS NULL OR trim(n.display_name) = '')
            RETURN collect(DISTINCT labels(n)) AS labels
            """,
            {"slug": CHAPTER_A, "book": TEST_BOOK, "marker": NAME_MARKER},
        ).single()["labels"]
        assert missing == []

    def test_a_caption_says_what_the_node_is(self, graph):
        """One assertion per node kind, because "non-empty" is not "right"."""
        eva = node("Madam Eva", CHAPTER_A, "NPC")
        write(graph, CHAPTER_A, [eva], [], chapter_spine=spine(
            eva,
            sections=[prose(0, "The Old Bonegrinder",
                            f"{named('Madam Eva')} reads. {named('Madam Eva')} waits.")],
        ))

        row = graph.run(
            """
            MATCH (b:Book {slug:$book})-[:HAS_CHAPTER]->(c:Chapter {slug:$slug})
                  -[:HAS_SECTION]->(s:Section)<-[:IN_SECTION]-(m:Mention)
                  -[:REFERS_TO]->(e:Entity)
            MATCH (a:Alias)-[:ALIAS_OF]->(e)
            RETURN b.display_name AS book, c.display_name AS chapter,
                   s.display_name AS section, m.display_name AS mention,
                   e.display_name AS entity, a.display_name AS alias
            """,
            {"book": TEST_BOOK, "slug": CHAPTER_A},
        ).single()
        assert row["book"] == "A Test Book"
        assert row["chapter"] == "A Test Chapter"
        assert row["section"] == "The Old Bonegrinder"
        assert row["entity"] == named("Madam Eva")
        assert row["alias"] == named("Madam Eva")
        # The SECTION, plus how loudly it names the entity. Not the entity:
        # expanding an entity draws its mentions and no sections, and captioning
        # each with the name of the node they all point at made six mentions of
        # Ismark render as six identical circles.
        assert row["mention"] == "The Old Bonegrinder x2"

    def test_a_mention_named_once_carries_no_count(self, graph):
        """`x1` on every quiet mention would be noise on the majority of nodes."""
        eva = node("Madam Eva", CHAPTER_A, "NPC")
        write(graph, CHAPTER_A, [eva], [], chapter_spine=spine(
            eva,
            sections=[prose(0, "Section 0", f"{named('Madam Eva')} reads the cards.")],
        ))
        caption = graph.run(
            "MATCH (m:Mention {chapter_slug:$slug}) RETURN m.display_name AS d",
            {"slug": CHAPTER_A},
        ).single()["d"]
        assert caption == "Section 0"

    def test_two_mentions_of_one_entity_get_different_captions(self, graph):
        """THE DEFECT THAT MOVED THE CAPTION, stated as the property it broke.

        Expanding an entity in the Browser draws its mentions and no sections,
        so a caption naming the entity is the name of the node they all point
        at. Six mentions of Ismark rendered as six identical circles, truncated
        to `Ismark Kolyan...` -- which cut off the occurrence count, the only
        part that had differed.
        """
        eva = node("Madam Eva", CHAPTER_A, "NPC")
        write(graph, CHAPTER_A, [eva], [], chapter_spine=spine(
            eva,
            sections=[
                prose(0, "The Old Bonegrinder", f"{named('Madam Eva')} reads."),
                prose(1, "Tser Pool", f"{named('Madam Eva')} waits."),
            ],
        ))
        captions = [
            r["d"]
            for r in graph.run(
                "MATCH (m:Mention {chapter_slug:$slug}) RETURN m.display_name AS d",
                {"slug": CHAPTER_A},
            )
        ]
        assert len(captions) == 2
        assert len(set(captions)) == 2, captions

    def test_a_section_carries_the_text_a_mention_quotes(self, graph):
        write(graph, CHAPTER_A, [node("Church")], [], chapter_spine=spine(
            sections=[prose(0, "Section 0", f"The {named('Church')} stands in fog.")],
        ))
        text = graph.run(
            "MATCH (s:Section {id:$id}) RETURN s.text AS t",
            {"id": section_id(CHAPTER_A, 0)},
        ).single()["t"]
        assert text == f"The {named('Church')} stands in fog."

    def test_a_range_query_bounded_by_chapter_index_returns_strictly_fewer(self, graph):
        """Revelation order has to be CAPTURED, not merely modelled: bounding on
        `chapter.index` must actually narrow what is knowable."""
        eva = node("Madam Eva", CHAPTER_A, "NPC")
        write(graph, CHAPTER_A, [eva], [], chapter_spine=spine(
            eva, chapter_index=1,
            sections=[prose(0, "Section 0", f"{named('Madam Eva')} reads the cards.")],
        ))
        later = node("Madam Eva", CHAPTER_B, "NPC")
        write(graph, CHAPTER_B, [later], [], chapter_spine=spine(
            later, chapter_index=2, chapter_slug=CHAPTER_B,
            sections=[prose(0, "Section 0", f"{named('Madam Eva')} again.", CHAPTER_B)],
        ))

        def known(up_to: int) -> int:
            return graph.run(
                """
                MATCH (m:Mention)-[:REFERS_TO]->(:Entity {id:$id}),
                      (m)-[:IN_SECTION]->(s:Section)<-[:HAS_SECTION]-(c:Chapter)
                WHERE c.index <= $up_to
                RETURN count(m) AS c
                """,
                {"id": eva.id, "up_to": up_to},
            ).single()["c"]

        assert known(1) == 1
        assert known(2) == 2

    def test_a_keyed_section_describes_the_place_it_names(self, graph):
        # A keyed place's id comes from `mint_id`, which hardcodes the book, so
        # the section can only describe it if the node wears that exact id.
        chapel = replace(node("Chapel"), id=f"cos:{CHAPTER_A}:e5f-chapel")
        write(graph, CHAPTER_A, [chapel], [], chapter_spine=spine(
            sections=[prose(0, "E5f. Chapel", f"A priest prays in the {named('Chapel')}.")],
            location_ids={chapel.id},
        ))

        described = graph.run(
            """
            MATCH (s:Section)-[d:DESCRIBES]->(e:Entity)
            WHERE s.chapter_slug = $slug
            RETURN e.id AS id, d.chapter_slug AS chapter
            """,
            {"slug": CHAPTER_A},
        ).single()
        assert described["id"] == chapel.id
        assert described["chapter"] == CHAPTER_A


class TestMentionsInTheGraph:
    def test_a_mention_joins_its_entity_to_its_section_and_points_into_it(self, graph):
        eva = node("Madam Eva", entity_type="NPC")
        body = f"Nobody is here. {named('Madam Eva')} deals the cards."
        write(graph, CHAPTER_A, [eva], [], chapter_spine=spine(
            sections=[prose(0, "Section 0", body)],
        ))

        row = graph.run(
            """
            MATCH (e:Entity {id:$id})<-[:REFERS_TO]-(m:Mention)-[:IN_SECTION]->(s:Section)
            RETURN properties(m) AS props, m.offset AS offset, m.occurrences AS occurrences,
                   m.chapter_slug AS chapter, m.plane AS plane,
                   s.id AS section, s.text AS text
            """,
            {"id": eva.id},
        ).single()
        assert "evidence" not in row["props"]
        assert row["occurrences"] == 1
        assert row["chapter"] == CHAPTER_A
        assert row["plane"] == CANON_PLANE
        assert row["section"] == section_id(CHAPTER_A, 0)
        # The offset indexes the SECTION's own text, which is the whole basis of
        # deriving the passage rather than storing it.
        assert row["text"][row["offset"]:].startswith(named("Madam Eva"))
        assert derive_passage(row["text"], row["offset"]) == (
            f"{named('Madam Eva')} deals the cards."
        )

    def test_every_mention_in_the_graph_yields_a_passage(self, graph):
        """Success criterion 4, restated for a derived passage. Asserted over
        the graph rather than the plan, because a mention whose offset had come
        apart from its section would still MERGE without complaint."""
        write(graph, CHAPTER_A, [node("Church"), node("Undercroft")], [])
        rows = graph.run(
            """
            MATCH (m:Mention {chapter_slug:$slug})-[:IN_SECTION]->(s:Section)
            RETURN m.offset AS offset, s.text AS text
            """,
            {"slug": CHAPTER_A},
        ).data()
        assert count_mentions(graph, CHAPTER_A) > 0
        assert len(rows) == count_mentions(graph, CHAPTER_A)
        assert all(derive_passage(r["text"], r["offset"]).strip() for r in rows)

    def test_no_mention_in_the_graph_stores_a_copy_of_the_prose(self, graph):
        """THE DELETION, over the whole chapter. A MERGE that left the old
        property in place on some nodes and not others would pass any check
        that looked at one."""
        write(graph, CHAPTER_A, [node("Church"), node("Undercroft")], [])
        stored = graph.run(
            "MATCH (m:Mention {chapter_slug:$slug}) WHERE m.evidence IS NOT NULL "
            "RETURN count(m) AS c",
            {"slug": CHAPTER_A},
        ).single()["c"]
        assert count_mentions(graph, CHAPTER_A) > 0
        assert stored == 0

    def test_an_entity_from_an_earlier_chapter_is_mentioned_by_a_later_one(self, graph):
        """An entity is global to the book, so a later chapter naming it in its
        text is a fact about the LATER chapter. Scanning only the chapter's own
        plan would rebuild, one level up, the defect this replaces."""
        eva = node("Madam Eva", CHAPTER_A, "NPC")
        write(graph, CHAPTER_A, [eva], [])
        write(graph, CHAPTER_B, [node("Church", CHAPTER_B)], [], chapter_spine=spine(
            chapter_slug=CHAPTER_B,
            sections=[prose(0, "Section 0",
                            f"The {named('Church')}, where {named('Madam Eva')} never goes.",
                            CHAPTER_B)],
        ))

        chapters = graph.run(
            "MATCH (m:Mention)-[:REFERS_TO]->(:Entity {id:$id}) "
            "RETURN m.chapter_slug AS slug ORDER BY slug",
            {"id": eva.id},
        ).value()
        assert chapters == [CHAPTER_A, CHAPTER_B]

    def test_rewriting_a_chapter_updates_its_mentions_rather_than_doubling_them(self, graph):
        church = node("Church")
        write(graph, CHAPTER_A, [church], [])
        before = count_mentions(graph, CHAPTER_A)
        write(graph, CHAPTER_A, [church], [], replace=True)
        assert before > 0
        assert count_mentions(graph, CHAPTER_A) == before

    def test_a_replace_takes_this_chapters_mentions_and_sections_with_it(self, graph):
        # Three sections first, then a rewrite with one. A replace that only
        # MERGEd the new spine over the old would leave two orphaned sections
        # holding text the chapter no longer has, and every mention in them.
        write(graph, CHAPTER_A, [node("Church"), node("Undercroft"), node("Hall")], [])
        write(graph, CHAPTER_B, [node("Chapel", CHAPTER_B)], [])
        assert self._sections(graph, CHAPTER_A) == 3

        write(graph, CHAPTER_A, [node("Crypt")], [], replace=True)

        assert self._sections(graph, CHAPTER_A) == 1
        assert graph.run(
            "MATCH (m:Mention)-[:REFERS_TO]->(:Entity {id:$id}) RETURN count(m) AS c",
            {"id": ident("Church")},
        ).single()["c"] == 0
        # ... and chapter B is untouched.
        assert count_mentions(graph, CHAPTER_B) == 1
        assert self._sections(graph, CHAPTER_B) == 1

    @staticmethod
    def _sections(graph, chapter_slug: str) -> int:
        return graph.run(
            "MATCH (s:Section {chapter_slug:$slug}) RETURN count(s) AS c",
            {"slug": chapter_slug},
        ).single()["c"]

    def test_a_node_the_text_never_names_is_still_this_chapters(self, graph):
        """The union's second arm, and it is load-bearing.

        Chapter 3 writes `Ismark Kolyanovich`, whose full name the chapter's
        prose never spells -- it says "Ismark". `MENTIONED_IN` covered him by
        construction and mentions do not, so the ontology edges this chapter
        asserted are the other half of what a chapter owns. Without that arm he
        is invisible to the loop's predicate and survives his own `--replace`.
        """
        named_node, unnamed = node("Church"), node("Undercroft")
        write(
            graph,
            CHAPTER_A,
            [named_node, unnamed],
            [link(unnamed, named_node)],
            # A spine that names only ONE of the two nodes.
            chapter_spine=spine(named_node),
        )

        assert count_mentions(graph, CHAPTER_A) == 1
        assert count_canon_nodes(graph, CHAPTER_A) == 2

        write(graph, CHAPTER_A, [named_node], [], replace=True)
        assert graph.run(
            "MATCH (n:Entity {id:$id}) RETURN count(n) AS c", {"id": unnamed.id}
        ).single()["c"] == 0

    def test_the_mention_scan_shares_the_chapters_one_transaction(self, graph):
        """The atomicity pin, extended to the spine.

        The write raises on an edge whose endpoint no node creates -- AFTER the
        nodes, the sections and the mentions have all been written inside the
        transaction. A writer that committed as it went would leave a chapter
        full of sections and mentions behind, and the loop's predicate reads
        exactly those, so the chapter would look DONE.
        """
        church, undercroft = node("Church"), node("Undercroft")
        missing = node("Crypt")  # deliberately NOT written

        with pytest.raises(ValueError, match="edge endpoint missing"):
            write(graph, CHAPTER_A, [church, undercroft], [link(church, missing)])

        assert count_mentions(graph, CHAPTER_A) == 0
        assert graph.run(
            "MATCH (s:Section {chapter_slug:$slug}) RETURN count(s) AS c",
            {"slug": CHAPTER_A},
        ).single()["c"] == 0
        assert graph.run(
            "MATCH (b:Book {slug:$slug}) RETURN count(b) AS c", {"slug": TEST_BOOK},
        ).single()["c"] == 0
        assert count_canon_nodes(graph, CHAPTER_A) == 0


class TestSilentNoOpsRaise:
    """A `MATCH ... MERGE` that matches nothing writes nothing and says nothing.

    That is exactly how a chapter acquires fewer mentions than it scanned, or
    fewer places than it described, with no error anywhere. Both writers count
    what they wrote and raise on zero, so the whole chapter rolls back instead.
    """

    def test_a_mention_of_an_entity_that_is_not_there_raises(self, graph):
        from backend.canon.spine import WriteMention
        from backend.canon.writer import _write_mention

        write(graph, CHAPTER_A, [node("Church")], [])
        orphan = WriteMention(
            id="pytest:nobody@" + section_id(CHAPTER_A, 0),
            entity_id="pytest:nobody",
            section_id=section_id(CHAPTER_A, 0),
            chapter_slug=CHAPTER_A,
            occurrences=1,
            offset=0,
            entity_name=named("Nobody"),
            section_heading="A Section",
        )
        with pytest.raises(ValueError, match="mention endpoint missing"):
            graph.execute_write(_write_mention, orphan)

    def test_a_section_describing_a_place_that_is_not_there_raises(self, graph):
        """A MERGE on the target instead of a MATCH would invent a bare place
        node that no extraction ever proposed."""
        ghost = f"cos:{CHAPTER_A}:e5f-ghost"
        with pytest.raises(ValueError, match="DESCRIBES endpoint missing"):
            write(graph, CHAPTER_A, [node("Church")], [], chapter_spine=spine(
                sections=[prose(0, "E5f. Ghost", "Nothing is here.")],
                location_ids={ghost},
            ))
        assert graph.run(
            "MATCH (n:Entity {id:$id}) RETURN count(n) AS c", {"id": ghost}
        ).single()["c"] == 0

    def test_a_co_occurrence_whose_mention_is_not_there_raises(self, graph):
        """Unreachable from `write_chapter`, which plans these from the very
        mentions it just wrote -- and asserted anyway, because the guard is what
        makes that ordering safe to rely on rather than merely true today."""
        from backend.canon.cooccurrence import CoOccurrence
        from backend.canon.writer import _write_co_occurrence

        church = node("Church")
        write(graph, CHAPTER_A, [church], [])
        orphan = CoOccurrence(
            mention_id="pytest:nobody@" + section_id(CHAPTER_A, 0),
            entity_id=church.id,
        )
        with pytest.raises(ValueError, match="co-occurrence endpoint missing"):
            graph.execute_write(_write_co_occurrence, orphan)


class TestCoOccurrenceInTheGraph:
    """`(:Mention)-[:CO_OCCURS_WITH]->(:Entity)`, live.

    The pairing rules are pinned without a database in `test_cooccurrence.py`.
    What only a real Neo4j can show is that the plan's ROW COUNT survives the
    write: every statement here MERGEs, so a planner emitting a row twice would
    land one edge, and only comparing `len(plan)` against the graph's count
    catches it. That is the failure mode this change is most exposed to -- the
    quantity under test is a number of pairs.
    """

    #: Two entities in the first sentence and a third in the second, so the
    #: right answer (2) differs from both the section-granular answer (6) and
    #: from a one-directional read (1).
    BODY = "{a} walks with {b}. Far away, {c} waits alone."

    def _sections(self, a, b, c):
        return [prose(0, "Section 0", self.BODY.format(a=a.name, b=b.name, c=c.name))]

    def _write_three(self, graph):
        eva = node("Madam Eva", entity_type="NPC")
        ismark = node("Ismark", entity_type="NPC")
        doru = node("Doru", entity_type="NPC")
        summary = write(
            graph,
            CHAPTER_A,
            [eva, ismark, doru],
            [],
            chapter_spine=spine(sections=self._sections(eva, ismark, doru)),
        )
        return eva, ismark, doru, summary

    @staticmethod
    def _edges(graph, chapter_slug: str = CHAPTER_A) -> list[tuple[str, str]]:
        """`(the mention's own entity, the entity it co-occurs with)`, as a LIST.

        A list rather than a set, and the rows are returned one per relationship
        rather than collected: a `set` here would absorb exactly the duplicate
        this test exists to find.
        """
        return [
            (r["from"], r["to"])
            for r in graph.run(
                """
                MATCH (src:Entity)<-[:REFERS_TO]-(m:Mention {chapter_slug:$slug})
                      -[:CO_OCCURS_WITH]->(dst:Entity)
                RETURN src.id AS from, dst.id AS to
                """,
                {"slug": chapter_slug},
            )
        ]

    def test_a_mention_points_at_the_entity_its_sentence_also_names(self, graph):
        eva, ismark, doru, _ = self._write_three(graph)
        assert sorted(self._edges(graph)) == sorted(
            [(eva.id, ismark.id), (ismark.id, eva.id)]
        )

    def test_the_entity_in_the_next_sentence_is_not_reached(self, graph):
        eva, ismark, doru, _ = self._write_three(graph)
        assert doru.id not in {end for pair in self._edges(graph) for end in pair}

    def test_the_graphs_edge_count_equals_the_plans_row_count(self, graph):
        """The duplicate guard. Every write MERGEs, so a plan that emitted the
        same (mention, entity) row twice would land one edge and this equality
        would break -- which is the only place it can be caught."""
        eva, ismark, doru, summary = self._write_three(graph)
        planned = plan_co_occurrences(
            spine(sections=self._sections(eva, ismark, doru)).sections,
            _scan(graph, CHAPTER_A),
        )
        assert len(planned) == 2
        assert summary["co_occurrences"] == len(planned)
        assert len(self._edges(graph)) == len(planned)

    def test_no_mention_co_occurs_with_its_own_entity(self, graph):
        """A sentence naming one entity twice names ONE entity."""
        eva = node("Madam Eva", entity_type="NPC")
        write(graph, CHAPTER_A, [eva], [], chapter_spine=spine(
            sections=[prose(0, "Section 0", f"{eva.name} deals for {eva.name} alone.")],
        ))
        assert self._edges(graph) == []

    def test_the_edge_carries_no_status(self, graph):
        """It is deterministic, so it is not in the trust split. A `status`
        would invite a reader to look for a reviewer who never existed."""
        self._write_three(graph)
        props = graph.run(
            f"""
            MATCH (:Mention {{chapter_slug:$slug}})-[r:{CO_OCCURS_WITH}]->(:Entity)
            RETURN properties(r) AS p LIMIT 1
            """,
            {"slug": CHAPTER_A},
        ).single()["p"]
        assert "status" not in props

    def test_the_pair_can_be_read_back_out_of_the_prose(self, graph):
        """The whole point of hanging it off a MENTION: the claim is checkable.
        Both names must appear in the passage the mention derives."""
        eva, ismark, _, _ = self._write_three(graph)
        for row in graph.run(
            f"""
            MATCH (m:Mention {{chapter_slug:$slug}})-[:{CO_OCCURS_WITH}]->(dst:Entity),
                  (m)-[:IN_SECTION]->(s:Section), (m)-[:REFERS_TO]->(src:Entity)
            RETURN s.text AS text, m.offset AS offset, src.name AS src, dst.name AS dst
            """,
            {"slug": CHAPTER_A},
        ):
            passage = derive_passage(row["text"], row["offset"])
            assert row["src"] in passage
            assert row["dst"] in passage

    def test_rewriting_a_chapter_does_not_double_them(self, graph):
        eva, ismark, doru, _ = self._write_three(graph)
        before = len(self._edges(graph))
        write(
            graph,
            CHAPTER_A,
            [eva, ismark, doru],
            [],
            chapter_spine=spine(sections=self._sections(eva, ismark, doru)),
            replace=True,
        )
        assert before == 2
        assert len(self._edges(graph)) == before

    def test_a_replace_takes_them_with_the_mentions_they_hang_off(self, graph):
        eva, ismark, doru, _ = self._write_three(graph)
        assert len(self._edges(graph)) == 2
        write(graph, CHAPTER_A, [node("Church")], [], replace=True)
        assert self._edges(graph) == []

    def test_a_replace_does_not_count_them_as_canon_edges(self, graph):
        """`deleted_edges` is what a human compares against `written_edges` to
        see whether a rewrite removed what it replaced. Co-occurrences are
        removed with the MENTIONS, not with the edges, so putting a
        `chapter_slug` on them would inflate that figure by the size of the
        co-occurrence graph and make the comparison unreadable."""
        eva, ismark, doru, _ = self._write_three(graph)
        assert len(self._edges(graph)) == 2
        summary = write(
            graph,
            CHAPTER_A,
            [eva, ismark, doru],
            [link(eva, ismark)],
            chapter_spine=spine(sections=self._sections(eva, ismark, doru)),
            replace=True,
        )
        assert summary["deleted_edges"] == 0  # the first write asserted none
        assert len(self._edges(graph)) == 2

    def test_they_share_the_chapters_one_transaction(self, graph):
        """Atomicity, extended. The write raises on an edge whose endpoint no
        node creates -- and a writer that committed as it went would leave the
        co-occurrences behind, pointing into a chapter that has no mentions."""
        eva, ismark = node("Madam Eva", entity_type="NPC"), node("Ismark", "NPC")
        with pytest.raises(ValueError, match="edge endpoint missing"):
            write(
                graph,
                CHAPTER_A,
                [eva, ismark],
                [link(eva, node("Crypt"))],
                chapter_spine=spine(
                    sections=[prose(0, "Section 0", f"{eva.name} walks with {ismark.name}.")],
                ),
            )
        assert self._edges(graph) == []

    def test_a_second_chapter_co_occurs_against_an_earlier_chapters_entity(self, graph):
        """An entity is global to the book, so chapter B naming Madam Eva and
        Ismark in one sentence is a fact about chapter B whichever chapter
        minted them."""
        eva, ismark, _, _ = self._write_three(graph)
        later = node("Chapel", CHAPTER_B)
        write(graph, CHAPTER_B, [later], [], chapter_spine=spine(
            chapter_slug=CHAPTER_B,
            chapter_index=1,
            sections=[prose(
                0, "Section 0", f"{eva.name} met {ismark.name} here.", CHAPTER_B
            )],
        ))
        assert sorted(self._edges(graph, CHAPTER_B)) == sorted(
            [(eva.id, ismark.id), (ismark.id, eva.id)]
        )


def _scan(graph, chapter_slug: str):
    """This chapter's mentions, read back out of the graph.

    Read rather than re-planned so the row count compared against the write is
    the one the graph actually holds.
    """
    from backend.canon.spine import WriteMention

    return [
        WriteMention(
            id=r["id"],
            entity_id=r["entity"],
            section_id=r["section"],
            chapter_slug=chapter_slug,
            occurrences=r["occurrences"],
            offset=r["offset"],
            entity_name=r["entity_name"],
            section_heading=r["section_heading"],
        )
        for r in graph.run(
            """
            MATCH (e:Entity)<-[:REFERS_TO]-(m:Mention {chapter_slug:$slug})
                  -[:IN_SECTION]->(s:Section)
            RETURN m.id AS id, e.id AS entity, s.id AS section,
                   m.occurrences AS occurrences, m.offset AS offset,
                   e.name AS entity_name, s.heading AS section_heading
            """,
            {"slug": chapter_slug},
        )
    ]


class TestDescriptionIsGone:
    def test_no_canon_node_carries_a_description(self, graph):
        """Deleted from the ontology, not merely stopped being written: a
        property that is absent on new writes but present on old ones is the
        last-write-wins defect wearing a hat."""
        write(graph, CHAPTER_A, [node("Church")], [])
        props = graph.run(
            "MATCH (n:Entity {id:$id}) RETURN properties(n) AS p", {"id": ident("Church")}
        ).single()["p"]
        assert "description" not in props


class TestAliases:
    """`(:Entity)<-[:ALIAS_OF]-(:Alias)<-[:USES_ALIAS]-(:Mention)`, live.

    The pure rules are pinned in `test_aliases.py` and `test_spine.py`. What
    only a database can show is that the alias reaches the graph BEFORE the scan
    reads it, that a replace unpicks it, and that resolving a name is one
    traversal.
    """

    def _aliases_of(self, graph, entity_id: str) -> set[str]:
        return {
            row["name"]
            for row in graph.run(
                "MATCH (a:Alias)-[:ALIAS_OF]->(:Entity {id:$id}) RETURN a.name AS name",
                {"id": entity_id},
            )
        }

    def _resolve(self, graph, name: str) -> set[str]:
        """The ONE lookup path, exercised through the function callers use.

        `resolve_name` reads `:Alias` and never `e.name`. If that traversal
        cannot find an entity under its own canonical name, the invariant this
        design rests on is broken and no caller can paper over it.
        """
        from backend.canon.aliases import resolve_name

        return set(resolve_name(graph, name))

    def test_every_written_node_answers_to_its_own_name(self, graph):
        """The invariant lookup rests on. Not conditional on anyone authoring
        anything: no alias was passed to this write."""
        church = node("Church")
        write(graph, CHAPTER_A, [church], [])
        assert self._aliases_of(graph, church.id) == {church.name}
        assert self._resolve(graph, church.name) == {church.id}

    def test_the_alias_carries_the_whole_normalisation_and_no_more(self, graph):
        church = node("Church")
        write(graph, CHAPTER_A, [church], [])
        row = graph.run(
            "MATCH (a:Alias {name:$name}) RETURN a.normalized AS n", {"name": church.name}
        ).single()
        assert row["n"] == church.name.lower()

    def test_a_canon_entity_written_by_something_else_is_still_given_its_name(self, graph):
        """`load_seed` writes canon entities and knows nothing about aliases.
        Without the backfill such a node is unreachable by name and invisible to
        the scan -- a silent zero, which is what all of this exists to remove."""
        stray = f"{TEST_ID_PREFIX}stray"
        graph.run(
            "CREATE (e:Entity {id:$id, name:$name, plane:$plane})",
            {"id": stray, "name": named("Stray"), "plane": CANON_PLANE},
        )
        write(graph, CHAPTER_A, [node("Church")], [])
        assert self._resolve(graph, named("Stray")) == {stray}

    def test_the_backfills_cypher_normalisation_agrees_with_the_python_one(self, graph):
        """`_BACKFILL_ALIASES` restates `normalize` in Cypher, because a Cypher
        MERGE cannot call Python. That is two implementations of one rule, and
        the only thing stopping them drifting is this test: the name below is
        padded, mixed-case AND curly, so all three operations have to agree.
        """
        from backend.canon.aliases import normalize

        awkward = "  ZzBildrath’s ZzMERCANTILE  "
        stray = f"{TEST_ID_PREFIX}awkward"
        graph.run(
            "CREATE (e:Entity {id:$id, name:$name, plane:$plane})",
            {"id": stray, "name": awkward, "plane": CANON_PLANE},
        )
        write(graph, CHAPTER_A, [node("Church")], [])
        stored = graph.run(
            "MATCH (a:Alias {name:$name}) RETURN a.normalized AS n", {"name": awkward}
        ).single()["n"]
        assert stored == normalize(awkward)
        assert self._resolve(graph, "zzbildrath's zzmercantile") == {stray}

    def test_an_authored_alias_reaches_the_entity(self, graph):
        ismark = node("Ismark Kolyanovich", entity_type="NPC")
        write(
            graph,
            CHAPTER_A,
            [ismark],
            [],
            aliases=[WriteAlias(ismark.id, named("Ismark"))],
        )
        assert self._aliases_of(graph, ismark.id) == {ismark.name, named("Ismark")}

    def test_both_spellings_resolve_to_the_same_entity(self, graph):
        """Success criterion 2, in the form the graph can answer it: the long
        name and the short one are one entity, with nothing fuzzy in the path."""
        ismark = node("Ismark Kolyanovich", entity_type="NPC")
        write(
            graph,
            CHAPTER_A,
            [ismark],
            [],
            aliases=[WriteAlias(ismark.id, named("Ismark"))],
        )
        short = self._resolve(graph, named("Ismark"))
        assert short == self._resolve(graph, named("Ismark Kolyanovich")) == {ismark.id}

    def test_a_curly_apostrophe_resolves_to_the_straight_one(self, graph):
        """One character apart, and the only reason the two are one name."""
        shop = WriteNode(
            id=f"{TEST_ID_PREFIX}shop",
            name="ZzBildrath’s ZzMercantile",
            entity_types=("LOCATION",),
            chapter_slug=CHAPTER_A,
        )
        write(
            graph,
            CHAPTER_A,
            [shop],
            [],
            aliases=[WriteAlias(shop.id, "ZzBildrath's ZzMercantile")],
        )
        assert self._resolve(graph, "ZzBildrath's ZzMercantile") == {shop.id}
        assert self._resolve(graph, "ZzBildrath’s ZzMercantile") == {shop.id}

    def test_the_scan_finds_a_section_that_uses_only_the_alias(self, graph):
        """The eight, in miniature. The section never writes the full name."""
        strahd = node("Strahd von Zarovich", entity_type="NPC")
        chapter_spine = spine(
            sections=[prose(0, "Section 0", f"{named('Strahd')} is watching.")],
        )
        summary = write(
            graph,
            CHAPTER_A,
            [strahd],
            [],
            chapter_spine=chapter_spine,
            aliases=[WriteAlias(strahd.id, named("Strahd"))],
        )
        assert summary["mentions"] == 1
        assert count_mentions(graph, CHAPTER_A) == 1

    def test_the_mention_records_which_spelling_the_section_used(self, graph):
        strahd = node("Strahd von Zarovich", entity_type="NPC")
        chapter_spine = spine(
            sections=[prose(0, "Section 0", f"{named('Strahd')} is watching.")],
        )
        write(
            graph,
            CHAPTER_A,
            [strahd],
            [],
            chapter_spine=chapter_spine,
            aliases=[WriteAlias(strahd.id, named("Strahd"))],
        )
        row = graph.run(
            """
            MATCH (m:Mention {chapter_slug:$slug})-[u:USES_ALIAS]->(a:Alias)
            RETURN a.name AS name, u.occurrences AS n
            """,
            {"slug": CHAPTER_A},
        ).single()
        assert (row["name"], row["n"]) == (named("Strahd"), 1)

    def test_the_alias_lands_before_the_scan_reads_it(self, graph):
        """Written after, the scan would look for last week's set of names and
        the chapter would need a second write to correct -- which is the two-pass
        write one transaction per chapter exists to forbid.

        Measured rather than asserted about ordering: the mention below can only
        exist if the alias was already in the graph when `_known_entities` ran.
        """
        strahd = node("Strahd von Zarovich", entity_type="NPC")
        chapter_spine = spine(
            sections=[prose(0, "Section 0", f"{named('Strahd')} is watching.")],
        )
        write(
            graph,
            CHAPTER_A,
            [strahd],
            [],
            chapter_spine=chapter_spine,
            aliases=[WriteAlias(strahd.id, named("Strahd"))],
        )
        found = graph.run(
            """
            MATCH (:Mention {chapter_slug:$slug})-[:REFERS_TO]->(e:Entity {id:$id})
            RETURN count(*) AS c
            """,
            {"slug": CHAPTER_A, "id": strahd.id},
        ).single()["c"]
        assert found == 1

    def test_one_alias_node_serves_every_entity_that_answers_to_it(self, graph):
        """A shared surface form is ONE node with two `ALIAS_OF` edges, which is
        the graph saying the name is ambiguous rather than picking one."""
        region = WriteNode(
            id=f"{TEST_ID_PREFIX}region",
            name=named("Barovia Region"),
            entity_types=("LOCATION",),
            chapter_slug=CHAPTER_A,
        )
        village = WriteNode(
            id=f"{TEST_ID_PREFIX}village",
            name=named("Barovia Village"),
            entity_types=("LOCATION",),
            chapter_slug=CHAPTER_A,
        )
        shared = named("Barovia")
        write(
            graph,
            CHAPTER_A,
            [region, village],
            [],
            aliases=[WriteAlias(region.id, shared), WriteAlias(village.id, shared)],
        )
        nodes = graph.run(
            "MATCH (a:Alias {name:$name}) RETURN count(a) AS c", {"name": shared}
        ).single()["c"]
        assert nodes == 1
        assert self._resolve(graph, shared) == {region.id, village.id}

    def test_a_replace_takes_this_chapters_aliases_with_it(self, graph):
        strahd = node("Strahd von Zarovich", entity_type="NPC")
        write(
            graph, CHAPTER_A, [strahd], [], aliases=[WriteAlias(strahd.id, named("Strahd"))]
        )
        write(graph, CHAPTER_A, [node("Church")], [], replace=True)
        assert self._resolve(graph, named("Strahd")) == set()
        left = graph.run(
            "MATCH (a:Alias {name:$name}) RETURN count(a) AS c", {"name": named("Strahd")}
        ).single()["c"]
        assert left == 0

    def test_a_replace_leaves_an_alias_another_entity_still_answers_to(self, graph):
        """An `:Alias` is global. Deleting `Barovia` the name because the
        village was rewritten would silently truncate the region."""
        region = WriteNode(
            id=f"{TEST_ID_PREFIX}region",
            name=named("Barovia Region"),
            entity_types=("LOCATION",),
            chapter_slug=CHAPTER_B,
        )
        village = WriteNode(
            id=f"{TEST_ID_PREFIX}village",
            name=named("Barovia Village"),
            entity_types=("LOCATION",),
            chapter_slug=CHAPTER_A,
        )
        shared = named("Barovia")
        write(graph, CHAPTER_B, [region], [], aliases=[WriteAlias(region.id, shared)])
        write(graph, CHAPTER_A, [village], [], aliases=[WriteAlias(village.id, shared)])

        write(graph, CHAPTER_A, [node("Church")], [], replace=True)
        assert self._resolve(graph, shared) == {region.id}

    def test_a_replace_cannot_reach_an_alias_it_never_touched(self, graph):
        """The orphan sweep is scoped to the names this delete just unpicked.

        An orphan the delete did not create is left alone. Sweeping every
        orphaned `:Alias` in the database instead would work today and would put
        a chapter's rewrite one bad edit away from emptying the book's whole
        name index -- which happened to the live graph during a mutation run of
        exactly that edit.
        """
        bystander = f"{NAME_MARKER}Bystander"
        graph.run(
            "CREATE (a:Alias {name:$name, normalized:$n})",
            {"name": bystander, "n": bystander.lower()},
        )
        try:
            write(graph, CHAPTER_A, [node("Church")], [])
            write(graph, CHAPTER_A, [node("Crypt")], [], replace=True)
            survived = graph.run(
                "MATCH (a:Alias {name:$name}) RETURN count(a) AS c", {"name": bystander}
            ).single()["c"]
            assert survived == 1
        finally:
            graph.run("MATCH (a:Alias {name:$name}) DETACH DELETE a", {"name": bystander})

    def test_a_replaced_node_leaves_no_alias_behind_it(self, graph):
        """`DELETE n` is deliberately not `DETACH DELETE`, so a surviving
        `ALIAS_OF` would raise. It must be unpicked, not detached."""
        church = node("Church")
        write(graph, CHAPTER_A, [church], [])
        write(graph, CHAPTER_A, [node("Crypt")], [], replace=True)
        assert self._resolve(graph, church.name) == set()

    def test_a_failed_write_leaves_no_alias_behind(self, graph):
        """Aliases are inside the one transaction like everything else."""
        church = node("Church")
        missing = node("Crypt")
        with pytest.raises(ValueError, match="edge endpoint missing"):
            write(
                graph,
                CHAPTER_A,
                [church],
                [link(church, missing)],
                aliases=[WriteAlias(church.id, named("Kirk"))],
            )
        assert self._resolve(graph, named("Kirk")) == set()
        assert self._resolve(graph, church.name) == set()

    def test_an_alias_of_an_entity_that_is_not_there_raises(self, graph):
        """A `MATCH ... MERGE` that matches nothing writes nothing and says
        nothing, which is how an entity silently loses its own name."""
        from backend.canon.writer import _write_alias

        write(graph, CHAPTER_A, [node("Church")], [])
        with pytest.raises(ValueError, match="alias endpoint missing"):
            graph.execute_write(
                _write_alias, WriteAlias(f"{TEST_ID_PREFIX}nobody", named("Nobody"))
            )

    def test_resolving_a_name_never_reads_the_entitys_own_name_property(self, graph):
        """The single-path rule, made checkable. An entity whose `:Alias` has
        been removed is unresolvable EVEN THOUGH `e.name` still says what it is
        called -- which is what proves the read path has one source.
        """
        church = node("Church")
        write(graph, CHAPTER_A, [church], [])
        graph.run(
            "MATCH (a:Alias)-[r:ALIAS_OF]->(:Entity {id:$id}) DELETE r", {"id": church.id}
        )
        still_named = graph.run(
            "MATCH (n:Entity {id:$id}) RETURN n.name AS name", {"id": church.id}
        ).single()["name"]
        assert still_named == church.name
        assert self._resolve(graph, church.name) == set()

    def test_resolving_returns_every_entity_that_answers_and_never_picks_one(self, graph):
        """`Barovia` is a region and a village. Choosing between them here would
        be a fuzzy match wearing different clothes."""
        region = WriteNode(
            id=f"{TEST_ID_PREFIX}region",
            name=named("Barovia Region"),
            entity_types=("LOCATION",),
            chapter_slug=CHAPTER_A,
        )
        village = WriteNode(
            id=f"{TEST_ID_PREFIX}village",
            name=named("Barovia Village"),
            entity_types=("LOCATION",),
            chapter_slug=CHAPTER_A,
        )
        shared = named("Barovia")
        write(
            graph,
            CHAPTER_A,
            [region, village],
            [],
            aliases=[WriteAlias(region.id, shared), WriteAlias(village.id, shared)],
        )
        assert self._resolve(graph, shared) == {region.id, village.id}

    def test_resolving_is_exact_and_never_a_prefix_or_a_substring(self, graph):
        """The bar the whole module is built to hold. `Strahd` reaches
        `Strahd von Zarovich` ONLY when someone has written it down."""
        strahd = node("Strahd von Zarovich", entity_type="NPC")
        write(graph, CHAPTER_A, [strahd], [])
        assert self._resolve(graph, named("Strahd")) == set()
        assert self._resolve(graph, named("Strahd von Zarovich")) == {strahd.id}

    def test_resolving_is_case_and_whitespace_insensitive_and_no_more(self, graph):
        church = node("Church")
        write(graph, CHAPTER_A, [church], [])
        assert self._resolve(graph, f"  {church.name.upper()}  ") == {church.id}

    def test_an_entity_with_no_recorded_name_is_refused_rather_than_skipped(self, graph):
        """The scan reads names through `ALIAS_OF` and nowhere else -- one path.
        An entity that reaches it with none can never be found, so it is a loud
        failure rather than an entity that quietly stops appearing."""
        from backend.canon.writer import _known_entities

        graph.run(
            "CREATE (e:Entity {id:$id, name:$name, plane:$plane})",
            {
                "id": f"{TEST_ID_PREFIX}nameless",
                "name": named("Nameless"),
                "plane": CANON_PLANE,
            },
        )
        with pytest.raises(ValueError, match="carry no :Alias"):
            graph.execute_write(_known_entities)
