"""Storing an approved generation, and the guarantee that canon never sees it.

The contamination test is the important one. Every quality number this project
has -- 85%/90% retrieval, the 96-question suite -- is measured with a
campaign-less retriever, and a design that let homebrew reach those numbers
would corrupt the only instrument the project has for knowing anything.
"""

import json

import pytest

from backend.campaign import homebrew, store
from backend.campaign.model import AUTHORED, CAMPAIGN_PLANE, Campaign
from backend.canon.retrieval import CanonRetriever
from backend.core.database import neo4j_session

SLUG = "pytest-hb"
BOOK = "pytest-hb-book"
SECTIONS = [f"{BOOK}:ch#{i}" for i in range(4)]
ANCHOR = SECTIONS[2]

PAYLOAD = dict(
    slug=SLUG,
    kind="scene",
    title="The Sea Battle",
    body="Pirates board the prison barge two days out.",
    generated_body="Pirates board the prison barge two days out.",
    from_canon=[{"claim": "the voyage takes eight days", "cite": "[1]"}],
    invented=["the pirates", "their captain"],
    from_context=["the party chartered a boat"],
    sources=[{"source": ANCHOR, "citation": "[1]", "type": "canon"}],
)


def _clean(session):
    session.run("MATCH (c:Campaign {slug:$s}) DETACH DELETE c", {"s": SLUG})
    for prefix in (f"{BOOK}:", f"hb:{SLUG}:"):
        session.run("MATCH (n) WHERE n.id STARTS WITH $p DETACH DELETE n", {"p": prefix})
    session.run("MATCH (m:Mention {campaign:$s}) DETACH DELETE m", {"s": SLUG})
    session.run("MATCH (a:Alias {plane:$p}) WHERE NOT (a)-[:ALIAS_OF]->() DETACH DELETE a",
                {"p": CAMPAIGN_PLANE})


@pytest.fixture
def table(tmp_path):
    with neo4j_session() as session:
        _clean(session)
        for index, section_id in enumerate(SECTIONS):
            session.run(
                """
                CREATE (:Section {id:$id, index:$i, plane:'canon', heading:$h,
                                  text:'The voyage north takes eight days.'})
                """,
                {"id": section_id, "i": index, "h": f"Section {index}"},
            )
        session.execute_write(
            lambda tx: store.create(tx, Campaign(slug=SLUG, name="HB Test", books=()))
        )
        from backend.campaign.chain import seed_plan

        session.execute_write(
            lambda tx: store.apply_rewire(
                tx, SLUG, seed_plan(SECTIONS), frozenset(SECTIONS),
                log_path=tmp_path / "log.jsonl",
            )
        )
        session.log_path = tmp_path / "log.jsonl"
        yield session
        _clean(session)


def _store(session, **overrides):
    payload = {**PAYLOAD, **overrides}
    return session.execute_write(
        lambda tx: homebrew.write(tx, log_path=session.log_path, **payload)
    )


class TestWhatGetsWritten:
    def test_the_entity_is_authored_on_the_campaign_plane(self, table):
        stored = _store(table, anchor=ANCHOR)
        row = dict(
            table.run(
                "MATCH (e:Entity {id:$id}) RETURN e.plane AS plane, e.status AS status, "
                "labels(e) AS labels",
                {"id": stored.entity_id},
            ).single()
        )
        assert row["plane"] == CAMPAIGN_PLANE
        assert row["status"] == AUTHORED
        assert "EVENT" in row["labels"], "a scene is an EVENT, which canon already has"

    def test_the_name_resolves(self, table):
        """Without an alias, an episode is invisible to every name lookup this
        system has -- and so to retrieval, the subgraph, and later context."""
        stored = _store(table, anchor=ANCHOR)
        found = table.run(
            "MATCH (a:Alias)-[:ALIAS_OF]->(:Entity {id:$id}) RETURN a.name AS name",
            {"id": stored.entity_id},
        ).single()
        assert dict(found)["name"] == "The Sea Battle"

    def test_the_prose_is_a_section_so_it_can_be_retrieved(self, table):
        stored = _store(table, anchor=ANCHOR)
        row = dict(
            table.run(
                "MATCH (s:Section {id:$id}) RETURN s.text AS text, s.plane AS plane",
                {"id": stored.section_id},
            ).single()
        )
        assert "Pirates board" in row["text"] and row["plane"] == CAMPAIGN_PLANE

    def test_the_mention_triangle_is_complete(self, table):
        """The only way anything comes back as a passage."""
        stored = _store(table, anchor=ANCHOR)
        found = table.run(
            """
            MATCH (:Entity {id:$e})<-[:REFERS_TO]-(m:Mention)-[:IN_SECTION]->(:Section {id:$s})
            RETURN count(m) AS c
            """,
            {"e": stored.entity_id, "s": stored.section_id},
        ).single()["c"]
        assert found == 1

    def test_the_citation_becomes_a_queryable_edge(self, table):
        """`from_canon` stops being JSON and becomes structure: "what in my
        campaign leans on this passage" is now answerable."""
        stored = _store(table, anchor=ANCHOR)
        assert stored.citations == 1
        found = table.run(
            "MATCH (:Section {id:$s})-[:DERIVED_FROM]->(c:Section) RETURN c.id AS id",
            {"s": stored.section_id},
        ).single()
        assert dict(found)["id"] == ANCHOR

    def test_all_three_provenance_lists_survive(self, table):
        stored = _store(table, anchor=ANCHOR)
        row = dict(
            table.run(
                "MATCH (s:Section {id:$id}) RETURN s.from_canon AS c, s.invented AS i, "
                "s.from_context AS x",
                {"id": stored.section_id},
            ).single()
        )
        assert json.loads(row["i"]) == ["the pirates", "their captain"]
        assert json.loads(row["x"]) == ["the party chartered a boat"]
        assert json.loads(row["c"])[0]["cite"] == "[1]"

    def test_an_edit_is_recorded_as_one(self, table):
        stored = _store(table, anchor=ANCHOR, body="The DM rewrote this entirely.")
        edited = table.run(
            "MATCH (s:Section {id:$id}) RETURN s.edited AS edited", {"id": stored.section_id}
        ).single()
        assert dict(edited)["edited"] is True

    def test_canon_is_never_mutated(self, table):
        """The property that makes delete a clean inverse."""
        before = dict(
            table.run("MATCH (s:Section {id:$id}) RETURN properties(s) AS p",
                      {"id": ANCHOR}).single()
        )["p"]
        _store(table, anchor=ANCHOR)
        after = dict(
            table.run("MATCH (s:Section {id:$id}) RETURN properties(s) AS p",
                      {"id": ANCHOR}).single()
        )["p"]
        assert before == after


class TestThePosition:
    def test_an_anchored_scene_lands_in_the_running_order(self, table):
        stored = _store(table, anchor=ANCHOR)
        order = store.running_order(table, SLUG)
        assert order.index(stored.section_id) == order.index(ANCHOR) + 1

    def test_an_unanchored_scene_is_stored_but_unplaced(self, table):
        """Legal, and the only option for a campaign with no book."""
        stored = _store(table, anchor=None)
        assert stored.chain_changes == 0
        assert stored.section_id not in store.running_order(table, SLUG)


class TestRefusals:
    def test_a_second_scene_of_the_same_name_is_refused(self, table):
        """Two scenes a DM named the same are two scenes; merging loses one."""
        _store(table, anchor=ANCHOR)
        with pytest.raises(homebrew.AlreadyStored):
            _store(table, anchor=ANCHOR)

    def test_a_citation_pointing_at_nothing_is_caught(self, table):
        _, bad = homebrew.cited_sections(
            [{"claim": "x", "cite": "[9]"}], PAYLOAD["sources"]
        )
        assert bad == ["[9]"]


class TestDelete:
    def test_everything_it_wrote_comes_back_out(self, table):
        stored = _store(table, anchor=ANCHOR)
        table.execute_write(
            lambda tx: homebrew.delete(tx, slug=SLUG, entity_id=stored.entity_id)
        )
        left = table.run(
            "MATCH (n) WHERE n.id IN [$e, $s] RETURN count(n) AS c",
            {"e": stored.entity_id, "s": stored.section_id},
        ).single()["c"]
        assert left == 0

    def test_the_running_order_closes_over_it(self, table):
        stored = _store(table, anchor=ANCHOR)
        table.execute_write(
            lambda tx: homebrew.delete(tx, slug=SLUG, entity_id=stored.entity_id)
        )
        assert store.running_order(table, SLUG) == SECTIONS

    def test_the_canon_it_cited_is_untouched(self, table):
        stored = _store(table, anchor=ANCHOR)
        table.execute_write(
            lambda tx: homebrew.delete(tx, slug=SLUG, entity_id=stored.entity_id)
        )
        assert table.run(
            "MATCH (s:Section {id:$id}) RETURN count(s) AS c", {"id": ANCHOR}
        ).single()["c"] == 1


class TestCanonIsBlindToAllOfIt:
    """CONTAMINATION TEST 1.

    Every measurement this project trusts is taken with a campaign-less
    retriever. If homebrew could reach one, the 96-question suite would stop
    measuring the book and nobody would be able to tell from the number.
    """

    def test_a_stored_scene_is_not_a_canon_entity(self, table):
        _store(table, anchor=ANCHOR)
        found = table.run(
            "MATCH (e:Entity {plane:'canon'}) WHERE e.name = 'The Sea Battle' RETURN count(e) AS c"
        ).single()["c"]
        assert found == 0

    def test_its_alias_is_not_on_the_canon_plane(self, table):
        """Alias resolution is the front door to retrieval."""
        _store(table, anchor=ANCHOR)
        found = table.run(
            "MATCH (a:Alias {plane:'canon'}) WHERE a.name = 'The Sea Battle' RETURN count(a) AS c"
        ).single()["c"]
        assert found == 0

    def test_a_canon_retriever_never_returns_it(self, table):
        """The end-to-end version, through the real retriever."""
        _store(table, anchor=ANCHOR)
        result = CanonRetriever(book="cos", limit=8).retrieve("the sea battle with pirates")
        assert not any("hb:" in p.section_id for p in result.passages)
        assert not any("hb:" in a.entity_id for a in result.anchors)

    def test_its_section_hangs_off_no_book(self, table):
        """`SEARCH_SECTIONS` matches through the book spine, so a section under
        a Campaign is unreachable by canon text search BY CONSTRUCTION."""
        _store(table, anchor=ANCHOR)
        found = table.run(
            """
            MATCH (s:Section {plane:'campaign'})
            WHERE (:Book)-[:HAS_CHAPTER]->(:Chapter)-[:HAS_SECTION]->(s)
            RETURN count(s) AS c
            """
        ).single()["c"]
        assert found == 0
