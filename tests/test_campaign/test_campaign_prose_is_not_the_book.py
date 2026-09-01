"""A DM's own prose naming a canon entity does not make it the book's.

THE PATH THAT MAKES THIS POSSIBLE. `rescan` reads a stored campaign section
and scans it against the canon entities of the books the table draws on, so a
scene that says "the Jolly Pelican" links to the ship the book minted. That is
correct and useful, and it means CAMPAIGN-PLANE MENTIONS POINT AT CANON
ENTITIES -- seven of them in the live graph the day this was written.

WHY IT MATTERS HERE. `named_by_book` is decided by whether a mention names the
entity, and a mention is a mention to Cypher. Before the plane was named in
those queries, a DM writing up one of the 154 entities the book never names
would have cleared its mark, and the reader would then have said "The book."
over it -- the project's one promise failing on prose written last night.

These run the real writer rather than hand-building a mention, because the
hand-built version is exactly the thing that agreed with the bug.
"""

import pytest

from backend.campaign import homebrew, store
from backend.campaign.model import Campaign
from backend.core.database import neo4j_session
from backend.graph.schema import NAMED_BY_BOOK
from backend.scripts.drop_unsupported import FIND
from backend.scripts.merge_duplicates import _BOOK_ENTITIES
from backend.scripts.mark_unnamed import TO_CLEAR, TO_MARK

SLUG = "pytest-prose"
BOOK = "pytest-prose-book"
#: A single capitalised word, so `mention_pattern`'s proper-noun rule matches
#: it in running prose -- the same rule that refuses `spellbook`.
NAME = "Zorblax"
ENTITY = f"{BOOK}:zorblax"
SECTION = f"hb:{SLUG}:a-scene#0"


def _clean(session):
    session.run("MATCH (c:Campaign {slug:$s}) DETACH DELETE c", {"s": SLUG})
    for prefix in (f"{BOOK}:", f"hb:{SLUG}:"):
        session.run("MATCH (n) WHERE n.id STARTS WITH $p DETACH DELETE n",
                    {"p": prefix})
    session.run("MATCH (b:Book {slug:$b}) DETACH DELETE b", {"b": BOOK})
    # AN ALIAS HAS NO `id`, so the prefix sweep above cannot see it, and its
    # name is unique-constrained -- one left behind fails the next run with a
    # constraint error rather than a useful message.
    session.run("MATCH (a:Alias {name:$n}) DETACH DELETE a", {"n": NAME})


@pytest.fixture
def table(tmp_path):
    with neo4j_session() as session:
        _clean(session)
        session.run(
            "CREATE (b:Book {slug:$b, title:'A Prose Test Book', plane:'canon'}) "
            # A canon entity the book never names, saying so on itself.
            "CREATE (e:Entity:NPC {id:$e, plane:'canon', name:$n}) "
            "SET e." + NAMED_BY_BOOK + " = false "
            "CREATE (a:Alias {name:$n, normalized:$norm}) "
            "CREATE (a)-[:ALIAS_OF]->(e)",
            {"b": BOOK, "e": ENTITY, "n": NAME, "norm": NAME.lower()},
        )
        session.execute_write(
            lambda tx: store.create(
                tx, Campaign(slug=SLUG, name="Prose Test", books=(BOOK,))
            )
        )
        # The DM's own scene, naming the thing the book does not.
        session.run(
            "MATCH (c:Campaign {slug:$s}) "
            "CREATE (sec:Section {id:$id, plane:'campaign', campaign:$s, "
            "heading:'A Scene', text:$t}) "
            "MERGE (c)-[:HAS_SECTION]->(sec)",
            {"s": SLUG, "id": SECTION,
             "t": f"{NAME} meets the party at the gate and offers a bargain."},
        )
        yield session
        _clean(session)


def _rescan(session):
    return session.execute_write(
        lambda tx: homebrew.rescan(tx, slug=SLUG, section_id=SECTION)
    )


class TestTheRescanReallyDoesLinkThem:
    """If this stops being true the rest of the file proves nothing."""

    def test_the_scene_mints_a_mention_of_the_canon_entity(self, table):
        assert _rescan(table)["scanned"] >= 1
        row = table.run(
            "MATCH (m:Mention)-[:REFERS_TO]->(:Entity {id:$e}) "
            "RETURN m.plane AS plane, m.campaign AS campaign",
            {"e": ENTITY},
        ).single()
        assert row is not None, "the DM's prose did not reach the canon entity"
        assert row["plane"] == "campaign"
        assert row["campaign"] == SLUG


class TestAndItStillIsNotTheBook:
    def test_the_mark_survives_the_dm_writing_about_it(self, table):
        _rescan(table)
        cleared = {r["id"] for r in table.run(
            TO_CLEAR, {"plane": "canon", "prefix": BOOK})}
        assert ENTITY not in cleared, (
            "a DM writing this up is not the book naming it"
        )

    def test_an_unmarked_entity_is_still_selected_for_marking(self, table):
        """The same hole on the way in."""
        table.run(f"MATCH (e:Entity {{id:$e}}) REMOVE e.{NAMED_BY_BOOK}",
                  {"e": ENTITY})
        _rescan(table)
        marked = {r["id"] for r in table.run(
            TO_MARK, {"plane": "canon", "prefix": BOOK})}
        assert ENTITY in marked

    def test_a_canon_mention_would_have_cleared_it(self, table):
        """THE CONTROL. Without this the tests above would pass on a query that
        selects nothing at all, which is the failure mode they exist to catch."""
        table.run(
            "MATCH (e:Entity {id:$e}) "
            "CREATE (s:Section {id:$b, plane:'canon', text:$t}) "
            "CREATE (m:Mention {id:$e + '@' + $b, plane:'canon'}) "
            "CREATE (m)-[:REFERS_TO]->(e) CREATE (m)-[:IN_SECTION]->(s)",
            {"e": ENTITY, "b": f"{BOOK}:ch#0", "t": f"{NAME} is written here."},
        )
        cleared = {r["id"] for r in table.run(
            TO_CLEAR, {"plane": "canon", "prefix": BOOK})}
        assert ENTITY in cleared


class TestTheOtherPlacesThatAskTheSameQuestion:
    """Found by sweeping for mention queries that name no plane, after the
    first one produced a real defect. Two of the sites were saying something
    they did not mean; the rest move or rename mentions, where every plane is
    meant and naming one would be the bug."""

    def test_drop_unsupported_still_lists_it(self, table):
        """It says "entities no section of the BOOK names". A DM's scene is
        not the book, so writing one must not quietly take an entity off the
        list -- even though skipping it errs in the safe direction."""
        _rescan(table)
        listed = {r["id"] for r in table.run(
            FIND, {"plane": "canon", "prefix": f"{BOOK}:"})}
        assert ENTITY in listed

    def test_the_merge_census_counts_only_the_books_own_mentions(self, table):
        """`plan_globals` picks which half of a duplicate survives by how often
        the book names each. Counting campaign mentions would let the table's
        own prose decide what the book keeps."""
        _rescan(table)
        counted = {r["id"]: r["mentions"] for r in table.run(
            _BOOK_ENTITIES, {"plane": "canon", "prefix": BOOK})}
        assert counted[ENTITY] == 0, (
            "the DM writing about it is not the book naming it"
        )

    def test_the_census_does_count_a_canon_mention(self, table):
        """THE CONTROL, again: a census that always returns zero would pass the
        test above and be useless."""
        table.run(
            "MATCH (e:Entity {id:$e}) "
            "CREATE (s:Section {id:$b, plane:'canon', text:$t}) "
            "CREATE (m:Mention {id:$e + '@' + $b, plane:'canon'}) "
            "CREATE (m)-[:REFERS_TO]->(e) CREATE (m)-[:IN_SECTION]->(s)",
            {"e": ENTITY, "b": f"{BOOK}:ch#0", "t": f"{NAME} is written here."},
        )
        counted = {r["id"]: r["mentions"] for r in table.run(
            _BOOK_ENTITIES, {"plane": "canon", "prefix": BOOK})}
        assert counted[ENTITY] == 1
