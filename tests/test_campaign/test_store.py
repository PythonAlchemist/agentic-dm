"""The chain against a real graph: seeding, rewiring, and the refusal.

`test_chain.py` proves the arithmetic without a database. This proves the
arithmetic reaches Neo4j intact, and -- more importantly -- that a rewire which
would corrupt a running order rolls back instead of committing.
"""

import pytest

from backend.campaign import store
from backend.campaign.chain import Rewire, insert_plan, remove_plan, seed_plan
from backend.campaign.model import Campaign
from backend.core.database import neo4j_session

SLUG = "pytest-table"
BOOK = "pytest-campaign-book"
SECTIONS = [f"{BOOK}:ch#{i}" for i in range(5)]
SCENE = "hb:pytest-table:sea-battle"


def _clean(session):
    session.run("MATCH (c:Campaign {slug:$s}) DETACH DELETE c", {"s": SLUG})
    session.run(
        "MATCH (s:Section) WHERE s.id STARTS WITH $p DETACH DELETE s", {"p": f"{BOOK}:"}
    )
    session.run("MATCH (s:Section {id:$i}) DETACH DELETE s", {"i": SCENE})


@pytest.fixture
def table(tmp_path):
    """A five-section book, a campaign, and a seeded chain."""
    with neo4j_session() as session:
        _clean(session)
        for index, section_id in enumerate(SECTIONS):
            session.run(
                "CREATE (:Section {id:$id, index:$i, plane:'canon', heading:$h})",
                {"id": section_id, "i": index, "h": f"Section {index}"},
            )
        session.run("CREATE (:Section {id:$id, plane:'campaign', heading:'Sea Battle'})",
                    {"id": SCENE})

        campaign = Campaign(slug=SLUG, name="A Test Table")
        plan = seed_plan(SECTIONS)
        session.execute_write(lambda tx: store.create(tx, campaign))
        session.execute_write(
            lambda tx: store.apply_rewire(
                tx, SLUG, plan, frozenset(SECTIONS), log_path=tmp_path / "log.jsonl"
            )
        )
        session.log_path = tmp_path / "log.jsonl"
        yield session
        _clean(session)


class TestUnmakingATable:
    """`create` had no inverse, so an abandoned campaign left its running
    order lying on the book -- 542 `NEXT` links between CANON sections, each
    carrying the slug of a campaign that no longer existed. Deleting the
    `:Campaign` node does not touch them, because they join two nodes it does
    not own."""

    def test_the_chain_over_the_book_goes_too(self, table):
        before = table.run(
            "MATCH ()-[r:NEXT {campaign:$s}]->() RETURN count(r) AS n", {"s": SLUG}
        ).single()["n"]
        assert before > 0, "the fixture seeded a chain to remove"
        counts = table.execute_write(lambda tx: store.delete_campaign(tx, SLUG))
        assert counts["relationships"] >= before
        after = table.run(
            "MATCH ()-[r]->() WHERE r.campaign = $s RETURN count(r) AS n", {"s": SLUG}
        ).single()["n"]
        assert after == 0

    def test_the_book_is_untouched(self, table):
        """The invariant the whole design rests on. Everything removed was
        created by the campaign; canon survives with its campaign-plane
        attachments gone and nothing else changed."""
        before = table.run(
            "MATCH (x:Section {plane:'canon'}) RETURN count(x) AS n"
        ).single()["n"]
        table.execute_write(lambda tx: store.delete_campaign(tx, SLUG))
        after = table.run(
            "MATCH (x:Section {plane:'canon'}) RETURN count(x) AS n"
        ).single()["n"]
        assert after == before

    def test_the_campaign_node_goes_last_and_goes(self, table):
        table.execute_write(lambda tx: store.delete_campaign(tx, SLUG))
        assert table.run(
            "MATCH (c:Campaign {slug:$s}) RETURN count(c) AS n", {"s": SLUG}
        ).single()["n"] == 0

    def test_deleting_a_campaign_that_is_not_there_removes_nothing(self, table):
        """Reported as zeroes rather than raised: asking to remove something
        already gone is not an error, and the counts say so."""
        counts = table.execute_write(
            lambda tx: store.delete_campaign(tx, "pytest-no-such-table")
        )
        assert set(counts.values()) == {0}
        assert table.run(
            "MATCH (c:Campaign {slug:$s}) RETURN count(c) AS n", {"s": SLUG}
        ).single()["n"] == 1, "the real one is untouched"


class TestSeeding:
    def test_the_chain_is_the_books_order(self, table):
        assert store.running_order(table, SLUG) == SECTIONS

    def test_a_second_campaign_does_not_see_this_ones_chain(self, table):
        """`campaign` is a property on NEXT, not part of its type, so two
        tables chain the same canon sections without colliding."""
        assert store.running_order(table, "some-other-table") == []


class TestInsert:
    def test_a_scene_lands_in_the_running_order(self, table):
        links, start = store.read_chain(table, SLUG)
        plan = insert_plan(links, start, SCENE, after=SECTIONS[2])
        table.execute_write(
            lambda tx: store.apply_rewire(
                tx, SLUG, plan, frozenset(SECTIONS + [SCENE]), log_path=table.log_path
            )
        )
        assert store.running_order(table, SLUG) == SECTIONS[:3] + [SCENE] + SECTIONS[3:]

    def test_the_mutation_is_logged(self, table):
        links, start = store.read_chain(table, SLUG)
        plan = insert_plan(links, start, SCENE, after=SECTIONS[2])
        table.execute_write(
            lambda tx: store.apply_rewire(
                tx, SLUG, plan, frozenset(SECTIONS + [SCENE]), log_path=table.log_path
            )
        )
        records = store.replay(table.log_path)
        assert records and records[-1]["campaign"] == SLUG
        assert [SECTIONS[2], SCENE] in records[-1]["link"]


class TestSkip:
    def test_the_order_closes_over_a_skipped_section(self, table):
        links, start = store.read_chain(table, SLUG)
        cut = SECTIONS[2]
        plan = remove_plan(links, start, cut)
        expected = frozenset(SECTIONS) - {cut}
        table.execute_write(
            lambda tx: store.apply_rewire(tx, SLUG, plan, expected, log_path=table.log_path)
        )
        table.execute_write(lambda tx: store.mark_skipped(tx, SLUG, cut))
        assert store.running_order(table, SLUG) == [s for s in SECTIONS if s != cut]

    def test_a_skip_is_recorded_as_a_fact(self, table):
        """Recorded, never inferred from absence: reconciliation must be able
        to tell a section the DM cut from one the book gained afterwards."""
        cut = SECTIONS[2]
        table.execute_write(lambda tx: store.mark_skipped(tx, SLUG, cut))
        assert store.read_skipped(table, SLUG) == frozenset({cut})

    def test_unskipping_clears_the_record(self, table):
        cut = SECTIONS[2]
        table.execute_write(lambda tx: store.mark_skipped(tx, SLUG, cut))
        table.execute_write(lambda tx: store.clear_skipped(tx, SLUG, cut))
        assert store.read_skipped(table, SLUG) == frozenset()


class TestACorruptingRewireRollsBack:
    """The guarantee that makes a linked list survivable here."""

    def test_a_plan_that_would_sever_the_chain_is_refused(self, table):
        links, start = store.read_chain(table, SLUG)
        severing = Rewire(unlink=((SECTIONS[1], SECTIONS[2]),))
        with pytest.raises(store.ChainCorrupted):
            table.execute_write(
                lambda tx: store.apply_rewire(
                    tx, SLUG, severing, frozenset(SECTIONS), log_path=table.log_path
                )
            )

    def test_and_the_running_order_is_untouched(self, table):
        links, start = store.read_chain(table, SLUG)
        severing = Rewire(unlink=((SECTIONS[1], SECTIONS[2]),))
        with pytest.raises(store.ChainCorrupted):
            table.execute_write(
                lambda tx: store.apply_rewire(
                    tx, SLUG, severing, frozenset(SECTIONS), log_path=table.log_path
                )
            )
        assert store.running_order(table, SLUG) == SECTIONS

    def test_a_plan_that_would_lose_a_section_is_refused(self, table):
        """The failure `expected` exists for: the remaining links stay
        perfectly sound and the chain is simply shorter."""
        links, start = store.read_chain(table, SLUG)
        losing = Rewire(
            unlink=((SECTIONS[3], SECTIONS[4]),),
        )
        with pytest.raises(store.ChainCorrupted):
            table.execute_write(
                lambda tx: store.apply_rewire(
                    tx, SLUG, losing, frozenset(SECTIONS), log_path=table.log_path
                )
            )
        assert store.running_order(table, SLUG) == SECTIONS


class TestReplacingAChainedChapterIsRefused:
    """A campaign's running order must survive a re-harvest of its book.

    THE GAP THIS CLOSED. `write_canon --replace` guards the chapter's ENTITY
    nodes against campaign attachments and says so in a clear refusal. A chain
    hangs off SECTION nodes, which that guard never walks -- so the only thing
    standing between a re-extraction and a destroyed running order was that the
    section delete is `DELETE s` rather than `DETACH DELETE s`, which raises a
    driver error naming neither the campaign nor the repair.
    """

    CHAPTER = "pytest-chained-chapter"

    @pytest.fixture
    def chained(self, table):
        """The five sections put under a real Chapter and chained."""
        table.run(
            "CREATE (c:Chapter {slug:$slug, plane:'canon', index:0})", {"slug": self.CHAPTER}
        )
        for section_id in SECTIONS:
            table.run(
                """
                MATCH (c:Chapter {slug:$slug}), (s:Section {id:$id})
                MERGE (c)-[:HAS_SECTION]->(s)
                """,
                {"slug": self.CHAPTER, "id": section_id},
            )
        yield table
        table.run("MATCH (c:Chapter {slug:$slug}) DETACH DELETE c", {"slug": self.CHAPTER})

    def test_the_refusal_names_the_campaign(self, chained):
        from backend.canon.writer import CampaignDataAttached, _delete_chapter

        with pytest.raises(CampaignDataAttached) as raised:
            chained.execute_write(_delete_chapter, self.CHAPTER)
        assert SLUG in raised.value.campaigns
        assert "reconcile_chain" in str(raised.value)

    def test_the_running_order_survives_the_attempt(self, chained):
        from backend.canon.writer import CampaignDataAttached, _delete_chapter

        with pytest.raises(CampaignDataAttached):
            chained.execute_write(_delete_chapter, self.CHAPTER)
        assert store.running_order(chained, SLUG) == SECTIONS


class TestReconcile:
    """A book that grew after the campaign was seeded.

    THE REAL CASE, reproduced: Keys from the Golden Vault was seeded, then its
    Introduction was harvested -- a chapter the first harvest never resolved --
    and every section of it was in the book and in no campaign's running order.
    """

    CHAPTER = "pytest-reconcile-chapter"
    LATE = f"{BOOK}:ch#late"

    @pytest.fixture
    def grown(self, table):
        """The seeded five, under a Book/Chapter, plus a sixth arriving late."""
        table.run("CREATE (b:Book {slug:$b, plane:'canon'})", {"b": BOOK})
        table.run(
            "CREATE (c:Chapter {slug:$slug, plane:'canon', index:0})", {"slug": self.CHAPTER}
        )
        table.run(
            "MATCH (b:Book {slug:$b}), (c:Chapter {slug:$slug}) MERGE (b)-[:HAS_CHAPTER]->(c)",
            {"b": BOOK, "slug": self.CHAPTER},
        )
        table.run(
            "CREATE (:Section {id:$id, index:99, plane:'canon', heading:'Late Arrival'})",
            {"id": self.LATE},
        )
        for section_id in SECTIONS + [self.LATE]:
            table.run(
                """
                MATCH (c:Chapter {slug:$slug}), (s:Section {id:$id})
                MERGE (c)-[:HAS_SECTION]->(s)
                """,
                {"slug": self.CHAPTER, "id": section_id},
            )
        table.execute_write(
            lambda tx: tx.run(
                "MATCH (c:Campaign {slug:$s}), (b:Book {slug:$b}) MERGE (c)-[:DRAWS_ON]->(b)",
                {"s": SLUG, "b": BOOK},
            )
        )
        yield table
        table.run("MATCH (b:Book {slug:$b}) DETACH DELETE b", {"b": BOOK})
        table.run("MATCH (c:Chapter {slug:$slug}) DETACH DELETE c", {"slug": self.CHAPTER})
        table.run("MATCH (s:Section {id:$id}) DETACH DELETE s", {"id": self.LATE})

    def test_a_section_added_after_seeding_is_reported(self, grown):
        from backend.scripts.reconcile_chain import survey

        assert survey(grown, SLUG)["unseeded"] == [self.LATE]

    def test_a_skipped_section_is_not_reported_as_unseeded(self, grown):
        """The distinction the SKIPPED record exists to make: the DM cut this,
        so it is placed, not missing."""
        from backend.scripts.reconcile_chain import survey

        cut = SECTIONS[2]
        links, start = store.read_chain(grown, SLUG)
        plan = remove_plan(links, start, cut)
        grown.execute_write(
            lambda tx: store.apply_rewire(
                tx, SLUG, plan, frozenset(SECTIONS) - {cut}, log_path=grown.log_path
            )
        )
        grown.execute_write(lambda tx: store.mark_skipped(tx, SLUG, cut))
        assert cut not in survey(grown, SLUG)["unseeded"]

    def test_without_the_skip_record_it_would_look_unseeded(self, grown):
        """The counterfactual, so the SKIPPED edge is not quietly droppable."""
        from backend.scripts.reconcile_chain import survey

        cut = SECTIONS[2]
        links, start = store.read_chain(grown, SLUG)
        plan = remove_plan(links, start, cut)
        grown.execute_write(
            lambda tx: store.apply_rewire(
                tx, SLUG, plan, frozenset(SECTIONS) - {cut}, log_path=grown.log_path
            )
        )
        assert cut in survey(grown, SLUG)["unseeded"]

    def test_a_sound_chain_reports_nothing(self, table):
        from backend.scripts.reconcile_chain import survey

        report = survey(table, SLUG)
        assert report["problems"] == () and report["unseeded"] == []


class TestCanonAliasesForCollisionScanning:
    """The scan that stops a generated name silently duplicating a canon one."""

    @pytest.fixture
    def book(self, table):
        """Teardown in a FIXTURE, not after the assertion.

        Written inline first, and a failing assertion then skipped the cleanup
        and left a `:Book` behind that broke every later run on a uniqueness
        constraint. A fixture's teardown runs whether the test passes or not.
        """
        def clean():
            table.run("MATCH (n) WHERE n.id STARTS WITH 'pytest-alias' DETACH DELETE n")
            table.run("MATCH (b:Book {slug:'pytest-alias-book'}) DETACH DELETE b")
            table.run("MATCH (c:Chapter {slug:'pytest-alias-ch'}) DETACH DELETE c")
            table.run("MATCH (a:Alias {normalized:'pytestvarrin'}) DETACH DELETE a")

        clean()
        table.run(
            """
            CREATE (b:Book {slug:'pytest-alias-book', plane:'canon'})
            CREATE (c:Chapter {slug:'pytest-alias-ch', plane:'canon', index:0})
            CREATE (s:Section {id:'pytest-alias-book:ch#0', plane:'canon', index:0})
            CREATE (e:Entity {id:'pytest-alias-book:v', name:'Pytestvarrin', plane:'canon'})
            // AN ID, so `clean` can find it. Without one the prefix delete
            // walked past it while its section and entity went, and every run
            // left one more orphan in the development database.
            CREATE (m:Mention {id:'pytest-alias-book:v@pytest-alias-book:ch#0',
                               plane:'canon'})
            CREATE (a:Alias {name:'Pytestvarrin', normalized:'pytestvarrin', plane:'canon'})
            CREATE (b)-[:HAS_CHAPTER]->(c)
            CREATE (c)-[:HAS_SECTION]->(s)
            CREATE (m)-[:IN_SECTION]->(s)
            CREATE (m)-[:REFERS_TO]->(e)
            CREATE (a)-[:ALIAS_OF]->(e)
            """
        )
        yield table
        clean()

    def test_it_returns_folded_names_with_their_entity(self, book):
        found = dict(store.canon_aliases(book, ["pytest-alias-book"]))
        assert found["pytestvarrin"] == "pytest-alias-book:v"

    def test_an_undrawn_book_contributes_nothing(self, table):
        """A campaign collides only with what it actually draws on."""
        assert store.canon_aliases(table, []) == frozenset()
