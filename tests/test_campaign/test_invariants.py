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
