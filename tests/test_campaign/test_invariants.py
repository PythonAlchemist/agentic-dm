"""Each invariant, shown catching the thing it exists for.

A check that never fires is worse than no check: it is a green light nobody
has earned. So every one of these seeds the exact shape it is meant to find,
asserts it is caught, and cleans up after itself.

The four shapes here are not hypothetical. Each is a defect that reached a
real graph and was found by hand afterwards -- edges outliving a deleted
section, mentions outliving one, a chain outliving a deleted campaign, and
half-broken mentions the sweep for the second was too narrow to see.
"""

import pytest

from backend.campaign import invariants
from backend.canon.writer import CANON_PLANE
from backend.graph.schema import NAMED_BY_BOOK
from backend.core.database import neo4j_session

PREFIX = "pytest-inv"


def _rows(session, check_name: str) -> list[dict]:
    for check, rows in invariants.run(session):
        if check.name == check_name:
            return rows
    raise AssertionError(f"no check named {check_name!r}")


@pytest.fixture
def graph():
    """A session, wiped of this file's nodes either side."""
    def clean(s):
        s.run(f"MATCH (n) WHERE n.id STARTS WITH '{PREFIX}' DETACH DELETE n")
        s.run(f"MATCH (n) WHERE n.campaign = '{PREFIX}' DETACH DELETE n")
        s.run(f"MATCH ()-[r]->() WHERE r.campaign = '{PREFIX}' DELETE r")
        s.run(f"MATCH (c:Campaign {{slug:'{PREFIX}'}}) DETACH DELETE c")

    with neo4j_session() as session:
        clean(session)
        yield session
        clean(session)


class TestAMentionIsATriangle:
    """An entity, a section, and the node joining them. Half of one points at
    nothing and is invisible to every read that traverses the pair, so it
    accumulates silently -- 573 of them once."""

    NAME = "a mention is a triangle"

    def test_a_mention_with_no_section_is_caught(self, graph):
        graph.run(
            f"CREATE (e:Entity {{id:'{PREFIX}:e', plane:'canon'}}) "
            f"CREATE (m:Mention {{id:'{PREFIX}:m', campaign:'{PREFIX}'}}) "
            "CREATE (m)-[:REFERS_TO]->(e)"
        )
        rows = _rows(graph, self.NAME)
        assert any(r["id"] == f"{PREFIX}:m" for r in rows)
        assert any("no section" in (r["why"] or "") for r in rows)

    def test_a_mention_with_no_entity_is_caught(self, graph):
        graph.run(
            f"CREATE (s:Section {{id:'{PREFIX}:s', plane:'campaign'}}) "
            f"CREATE (m:Mention {{id:'{PREFIX}:m2', campaign:'{PREFIX}'}}) "
            "CREATE (m)-[:IN_SECTION]->(s)"
        )
        rows = _rows(graph, self.NAME)
        assert any(r["id"] == f"{PREFIX}:m2" for r in rows)

    def test_a_whole_triangle_is_not(self, graph):
        graph.run(
            f"CREATE (e:Entity {{id:'{PREFIX}:e3', plane:'canon'}}) "
            f"CREATE (s:Section {{id:'{PREFIX}:s3', plane:'campaign'}}) "
            f"CREATE (m:Mention {{id:'{PREFIX}:e3@{PREFIX}:s3', campaign:'{PREFIX}'}}) "
            "CREATE (m)-[:REFERS_TO]->(e) CREATE (m)-[:IN_SECTION]->(s)"
        )
        assert not [r for r in _rows(graph, self.NAME) if PREFIX in str(r["id"])]


class TestAClaimBelongsToACampaignThatExists:
    """An edge carrying a slug nothing answers to is an assertion nobody
    stands behind, sitting on the book. Deleting a section used to leave these
    between two CANON entities, because neither endpoint was the campaign's to
    take with it."""

    NAME = "a claim belongs to a campaign that exists"

    def test_an_edge_of_a_vanished_campaign_is_caught(self, graph):
        graph.run(
            f"CREATE (a:Entity {{id:'{PREFIX}:a', plane:'canon'}}) "
            f"CREATE (b:Entity {{id:'{PREFIX}:b', plane:'canon'}}) "
            f"CREATE (a)-[:KNOWS {{campaign:'{PREFIX}', plane:'campaign'}}]->(b)"
        )
        assert any(r["campaign"] == PREFIX for r in _rows(graph, self.NAME))

    def test_an_edge_of_a_live_campaign_is_not(self, graph):
        graph.run(f"CREATE (:Campaign {{slug:'{PREFIX}'}})")
        graph.run(
            f"CREATE (a:Entity {{id:'{PREFIX}:a2', plane:'canon'}}) "
            f"CREATE (b:Entity {{id:'{PREFIX}:b2', plane:'canon'}}) "
            f"CREATE (a)-[:KNOWS {{campaign:'{PREFIX}', plane:'campaign'}}]->(b)"
        )
        assert not [r for r in _rows(graph, self.NAME) if r["campaign"] == PREFIX]


class TestANodeBelongsToACampaignThatExists:
    """`create` had no inverse for a long time, so removing a table by hand
    left its sections and entities behind."""

    NAME = "a node belongs to a campaign that exists"

    def test_a_section_of_a_vanished_campaign_is_caught(self, graph):
        graph.run(
            f"CREATE (:Section {{id:'{PREFIX}:sec', plane:'campaign', "
            f"campaign:'{PREFIX}'}})"
        )
        assert any(r["id"] == f"{PREFIX}:sec" for r in _rows(graph, self.NAME))

    def test_the_campaign_node_does_not_report_itself(self, graph):
        """It carries its own slug in `slug`, not `campaign`, and a check that
        flagged every table as an orphan would be read once and ignored."""
        graph.run(f"CREATE (:Campaign {{slug:'{PREFIX}'}})")
        assert not [r for r in _rows(graph, self.NAME) if r["campaign"] == PREFIX]


class TestAMentionsIdSpellsItsPair:
    """Composing the id out of both endpoints is what makes a re-ingest MERGE
    onto the same node. An id naming an entity the mention no longer points at
    reads fine and re-ingests as a second mention beside the stale one -- 628
    of them once, after coreference repointed `REFERS_TO` and renamed
    nothing."""

    NAME = "a mention's id spells its pair"

    def test_a_stale_id_is_caught(self, graph):
        graph.run(
            f"CREATE (e:Entity {{id:'{PREFIX}:right', plane:'canon'}}) "
            f"CREATE (s:Section {{id:'{PREFIX}:sec2', plane:'campaign'}}) "
            f"CREATE (m:Mention {{id:'{PREFIX}:wrong@{PREFIX}:sec2', "
            f"campaign:'{PREFIX}'}}) "
            "CREATE (m)-[:REFERS_TO]->(e) CREATE (m)-[:IN_SECTION]->(s)"
        )
        rows = _rows(graph, self.NAME)
        assert any(f"{PREFIX}:wrong@" in str(r["id"]) for r in rows)

    def test_a_correct_id_is_not(self, graph):
        graph.run(
            f"CREATE (e:Entity {{id:'{PREFIX}:ok', plane:'canon'}}) "
            f"CREATE (s:Section {{id:'{PREFIX}:sec3', plane:'campaign'}}) "
            f"CREATE (m:Mention {{id:'{PREFIX}:ok@{PREFIX}:sec3', "
            f"campaign:'{PREFIX}'}}) "
            "CREATE (m)-[:REFERS_TO]->(e) CREATE (m)-[:IN_SECTION]->(s)"
        )
        assert not [r for r in _rows(graph, self.NAME) if PREFIX in str(r["id"])]


class TestAMentionIsOnePerPair:
    """`mention_id` IS the pair, so two nodes for one is not a state the scan
    can produce -- only a repoint that left the old node standing."""

    NAME = "a mention is one per pair"

    def test_two_mentions_of_one_pair_are_caught(self, graph):
        graph.run(
            f"CREATE (e:Entity {{id:'{PREFIX}:dup', plane:'canon'}}) "
            f"CREATE (s:Section {{id:'{PREFIX}:sec4', plane:'campaign'}}) "
            f"CREATE (m1:Mention {{id:'{PREFIX}:dup@{PREFIX}:sec4', "
            f"campaign:'{PREFIX}'}}) "
            f"CREATE (m2:Mention {{id:'{PREFIX}:other', campaign:'{PREFIX}'}}) "
            "CREATE (m1)-[:REFERS_TO]->(e) CREATE (m1)-[:IN_SECTION]->(s) "
            "CREATE (m2)-[:REFERS_TO]->(e) CREATE (m2)-[:IN_SECTION]->(s)"
        )
        assert any(r["id"] == f"{PREFIX}:dup" for r in _rows(graph, self.NAME))


class TestAClaimOutlivesNoProse:
    """The FIRST of the four to appear, and the one the campaign check cannot
    see: the edge names a live table, and what is gone is the section whose
    text asserted it. Discarding a draft about Elra left the book holding
    `Elra Lionheart THREATENS Markos Delphi` from prose that no longer
    existed."""

    NAME = "a claim outlives no prose"

    def test_an_edge_whose_section_is_gone_is_caught(self, graph):
        graph.run(f"CREATE (:Campaign {{slug:'{PREFIX}'}})")
        graph.run(
            f"CREATE (a:Entity {{id:'{PREFIX}:x', plane:'canon'}}) "
            f"CREATE (b:Entity {{id:'{PREFIX}:y', plane:'canon'}}) "
            f"CREATE (a)-[:KNOWS {{campaign:'{PREFIX}', "
            f"from_section:'{PREFIX}:vanished#0'}}]->(b)"
        )
        rows = _rows(graph, self.NAME)
        assert any(r["id"] == f"{PREFIX}:vanished#0" for r in rows), rows

    def test_an_edge_whose_section_is_there_is_not(self, graph):
        graph.run(f"CREATE (:Campaign {{slug:'{PREFIX}'}})")
        graph.run(
            f"CREATE (s:Section {{id:'{PREFIX}:live#0', plane:'campaign', "
            f"campaign:'{PREFIX}'}}) "
            f"CREATE (a:Entity {{id:'{PREFIX}:x2', plane:'canon'}}) "
            f"CREATE (b:Entity {{id:'{PREFIX}:y2', plane:'canon'}}) "
            f"CREATE (a)-[:KNOWS {{campaign:'{PREFIX}', "
            f"from_section:'{PREFIX}:live#0'}}]->(b)"
        )
        assert not [r for r in _rows(graph, self.NAME) if PREFIX in str(r["id"])]


class TestACanonEntitySaysWhetherTheBookNamesIt:
    """An entity holding no mention cites no prose, and reads like one that
    does. 154 of them were sitting in the graph when this was written -- eight
    spell scrolls named by pattern, `Closet 1`, `Potion of Far Realm Surprise`.

    KEEPING ONE IS FINE; keeping one SILENTLY is not. The DM ruled these worth
    having, so the rule is not that every entity is named by the book but that
    none stays unsupported without saying so."""

    NAME = "a canon entity says whether the book names it"

    #: THE REAL PREDICATE, NARROWED TO THIS FILE'S NODES. `invariants.run` is
    #: not used here as it is above: this check has 154 true rows in any graph
    #: with the books loaded, and its `LIMIT 50` means a seeded node is not
    #: reliably among them. Narrowing the file's own WHERE keeps the thing
    #: under test the thing that ships, rather than a copy that can drift.
    @staticmethod
    def _scoped(session):
        cypher = invariants.UNSUPPORTED_ENTITIES.replace(
            "RETURN", f"AND e.id STARTS WITH '{PREFIX}' RETURN", 1
        )
        return [dict(r) for r in session.run(cypher)]

    def test_an_entity_no_mention_names_is_caught(self, graph):
        graph.run(f"CREATE (:Entity {{id:'{PREFIX}:invented', plane:'canon', "
                  "name:'Potion of Far Realm Surprise'})")
        rows = self._scoped(graph)
        assert any(r["id"] == f"{PREFIX}:invented" for r in rows), rows
        assert any("Potion of Far Realm Surprise" in (r["why"] or "") for r in rows)

    def test_an_entity_a_mention_names_is_not(self, graph):
        graph.run(
            f"CREATE (e:Entity {{id:'{PREFIX}:said', plane:'canon', name:'Ireena'}}) "
            f"CREATE (s:Section {{id:'{PREFIX}:sec9', plane:'canon'}}) "
            f"CREATE (m:Mention {{id:'{PREFIX}:said@{PREFIX}:sec9', plane:'canon'}}) "
            "CREATE (m)-[:REFERS_TO]->(e) CREATE (m)-[:IN_SECTION]->(s)"
        )
        assert not self._scoped(graph)

    def test_a_campaign_entity_is_not(self, graph):
        """AUTHORED NPCs ARE NOT THE DEFECT. The DM inventing someone is the
        campaign plane working; the check is about the canon plane claiming
        the book said something it did not."""
        graph.run(f"CREATE (:Entity {{id:'{PREFIX}:authored', plane:'campaign', "
                  f"name:'Someone the DM made up', campaign:'{PREFIX}'}})")
        assert not self._scoped(graph)

    def test_the_check_is_wired_in(self, graph):
        """`run` reports it, so adding the constant without registering it
        cannot pass -- the failure the route sweep in `test_auth` was written
        for, one file over."""
        assert self.NAME in {c.name for c, _ in invariants.run(graph)}

    def test_only_the_books_own_prose_answers_for_it(self, graph):
        """`expand` writes a CAMPAIGN-plane section and mention pointing at the
        entity it fleshes out, and that entity is often the book's. Without the
        plane on the mention, a DM writing up `Monodrones` would satisfy this
        check with their own prose -- the promise failing in the direction
        nobody would check."""
        graph.run(
            f"CREATE (e:Entity {{id:'{PREFIX}:mono', plane:'canon', "
            "name:'Monodrones'}) "
            f"CREATE (s:Section {{id:'{PREFIX}:scene', plane:'campaign', "
            f"campaign:'{PREFIX}'}}) "
            f"CREATE (m:Mention {{id:'{PREFIX}:mm', plane:'campaign', "
            f"campaign:'{PREFIX}'}}) "
            "CREATE (m)-[:REFERS_TO]->(e) CREATE (m)-[:IN_SECTION]->(s)"
        )
        rows = self._scoped(graph)
        assert any(r["id"] == f"{PREFIX}:mono" for r in rows), (
            "a campaign-plane mention is the DM naming it, not the book"
        )

    def test_an_entity_that_admits_it_is_not_caught(self, graph):
        """The whole point of the reshape: a node the DM chose to keep, which
        says on itself that the book does not name it, is not a violation."""
        graph.run(f"CREATE (:Entity {{id:'{PREFIX}:kept', plane:'canon', "
                  f"name:'Monodrones', {NAMED_BY_BOOK}:false}})")
        assert not self._scoped(graph)

    def test_the_mark_does_not_excuse_a_campaign_entity_of_anything(self, graph):
        """Guarding the reshape against the obvious over-reach: marking is a
        statement about canon, and setting it true is not a way to silence the
        check -- only `false` or absent are states this recognises."""
        graph.run(f"CREATE (:Entity {{id:'{PREFIX}:sneaky', plane:'canon', "
                  f"name:'Closet 1', {NAMED_BY_BOOK}:true}})")
        assert not self._scoped(graph), (
            "any non-null value counts as the node having answered; if this "
            "ever needs to be stricter, the query is the place"
        )

    def test_the_property_spelled_here_is_the_real_one(self):
        """As with the plane below: the constant lives in `graph.schema` and
        this module stays free of it, so the duplication is checked."""
        assert NAMED_BY_BOOK in invariants.UNSUPPORTED_ENTITIES

    def test_the_plane_spelled_here_is_the_real_one(self):
        """The constant hardcodes `canon` to keep this module free of
        `canon.writer` and everything behind it. That duplication is checked
        rather than remembered, which is what the rest of the file is for."""
        assert f"plane:'{CANON_PLANE}'" in invariants.UNSUPPORTED_ENTITIES


class TestEveryCheckAgreesWithTheRowLimit:
    """`check_invariants` distinguishes a capped page from a total by counting
    to `ROW_LIMIT`, which only works while the queries and the constant say the
    same number."""

    def test_every_query_takes_the_shared_limit(self):
        for check in invariants.CHECKS:
            assert f"LIMIT {invariants.ROW_LIMIT}" in check.cypher, check.name

    def test_every_check_says_what_to_do(self):
        """A violation nobody can act on is a check they learn to skip."""
        for check in invariants.CHECKS:
            assert check.fix.strip(), check.name


class TestAMentionJoinsOneBook:
    """`mint_id` promises entities "merge across the chapters of one book but
    never across books". The scan did not keep it: `_known_entities` filtered on
    plane alone, so writing one book's chapter scanned the other book's entities
    against its prose, and multi-word forms fold case. 332 mentions claimed that
    Keys from the Golden Vault names Curse of Strahd entities -- `cos:key` 82
    times. The retriever's book filter hid them from a DM instead of surfacing
    them, which is why they sat there."""

    NAME = "a mention joins one book"

    def _seed(self, graph, entity_id, section_id):
        graph.run(
            "CREATE (e:Entity {id:$e, plane:'canon'}) "
            "CREATE (s:Section {id:$s, plane:'canon'}) "
            "CREATE (m:Mention {id:$e + '@' + $s, plane:'canon'}) "
            "CREATE (m)-[:REFERS_TO]->(e) CREATE (m)-[:IN_SECTION]->(s)",
            {"e": entity_id, "s": section_id},
        )

    def test_a_mention_across_two_books_is_caught(self, graph):
        self._seed(graph, f"{PREFIX}A:key", f"{PREFIX}B:ch#1")
        rows = _rows(graph, self.NAME)
        assert any(PREFIX in str(r["id"]) for r in rows), rows

    def test_a_mention_inside_one_book_is_not(self, graph):
        self._seed(graph, f"{PREFIX}A:key", f"{PREFIX}A:ch#1")
        assert not [r for r in _rows(graph, self.NAME) if PREFIX in str(r["id"])]

    def test_a_campaign_mention_of_a_canon_entity_is_not(self, graph):
        """The normal, wanted case: a DM's scene naming the Jolly Pelican.
        Seven of those existed the day this was written."""
        graph.run(
            f"CREATE (e:Entity {{id:'{PREFIX}A:pelican', plane:'canon'}}) "
            # THE ID MUST START WITH THE PREFIX. `hb:{PREFIX}:...` does not,
            # so the fixture's sweep never saw it and the next run collided on
            # the uniqueness constraint.
            f"CREATE (s:Section {{id:'{PREFIX}:hb-scene#0', plane:'campaign'}}) "
            f"CREATE (m:Mention {{id:'{PREFIX}:m', plane:'campaign'}}) "
            "CREATE (m)-[:REFERS_TO]->(e) CREATE (m)-[:IN_SECTION]->(s)"
        )
        assert not [r for r in _rows(graph, self.NAME) if PREFIX in str(r["id"])]


class TestACanonClaimCarriesItsEvidence:
    """Every edge the canon writer makes between two book entities carries the
    sentence it was read from. An edge minted any other way carries none -- and
    `POST /api/campaign/relationships` could MERGE one between two canon
    entities and stamp it accepted, after which `lookup.EDGES` served it to a DM
    as the book's own derived fact. A forged NODE trips
    `UNSUPPORTED_ENTITIES`; a forged EDGE tripped nothing."""

    NAME = "a canon claim carries its evidence"

    def test_a_canon_edge_citing_nothing_is_caught(self, graph):
        graph.run(
            f"CREATE (a:Entity {{id:'{PREFIX}:from', plane:'canon'}}) "
            f"CREATE (b:Entity {{id:'{PREFIX}:to', plane:'canon'}}) "
            "CREATE (a)-[:KNOWS {plane:'canon', status:'accepted'}]->(b)"
        )
        assert any(r["id"] == f"{PREFIX}:from" for r in _rows(graph, self.NAME))

    def test_a_canon_edge_that_cites_a_sentence_is_not(self, graph):
        graph.run(
            f"CREATE (a:Entity {{id:'{PREFIX}:src', plane:'canon'}}) "
            f"CREATE (b:Entity {{id:'{PREFIX}:dst', plane:'canon'}}) "
            "CREATE (a)-[:KNOWS {plane:'canon', evidence:'the book says so'}]->(b)"
        )
        assert not [r for r in _rows(graph, self.NAME) if PREFIX in str(r["id"])]

    def test_the_mention_plumbing_is_not_a_claim(self, graph):
        """`REFERS_TO` and its kin join the triangle; they assert nothing about
        the world and carry no evidence by design."""
        graph.run(
            f"CREATE (a:Entity {{id:'{PREFIX}:m1', plane:'canon'}}) "
            f"CREATE (b:Entity {{id:'{PREFIX}:m2', plane:'canon'}}) "
            "CREATE (a)-[:CO_OCCURS_WITH {plane:'canon'}]->(b)"
        )
        assert not [r for r in _rows(graph, self.NAME) if PREFIX in str(r["id"])]

    def test_a_campaign_edge_is_not_a_canon_claim(self, graph):
        """The DM's own assertions are theirs to make, and are marked as such."""
        graph.run(
            f"CREATE (a:Entity {{id:'{PREFIX}:c1', plane:'canon'}}) "
            f"CREATE (b:Entity {{id:'{PREFIX}:c2', plane:'canon'}}) "
            f"CREATE (a)-[:KNOWS {{plane:'campaign', campaign:'{PREFIX}'}}]->(b)"
        )
        assert not [r for r in _rows(graph, self.NAME) if PREFIX in str(r["id"])]


class TestTheSweepCoversEveryCampaignLabel:
    """`invariants.py` opens by recording the same defect four times in one
    week -- a campaign-plane thing outliving whatever made it, each instance
    invisible to the check written for the one before. Every label the roadmap
    adds is another instance waiting, so the sweep and this test read the one
    registry: adding a label without adding its delete fails here."""

    def test_delete_campaign_sweeps_each_registered_label(self):
        import inspect

        from backend.campaign import store
        from backend.graph.schema import CAMPAIGN_OWNED_LABELS

        source = inspect.getsource(store.delete_campaign)
        assert "CAMPAIGN_OWNED_LABELS" in source, (
            "the sweep must iterate the registry, not a hand-written list that "
            "can fall behind it"
        )
        assert CAMPAIGN_OWNED_LABELS, "an empty registry sweeps nothing"

    def test_apparatus_carries_no_plane(self):
        """Apparatus is not a claim, so it takes no side in a distinction that
        exists to separate the book's assertions from the DM's."""
        from backend.graph.schema import APPARATUS_LABELS

        assert "SessionMemory" in APPARATUS_LABELS
        assert "Entity" not in APPARATUS_LABELS
        assert "Section" not in APPARATUS_LABELS
