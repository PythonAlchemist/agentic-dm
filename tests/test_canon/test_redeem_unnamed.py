"""Minting the mentions a newly authored alias makes findable.

`sync_authored_aliases` adds the spelling and refuses to add the mentions,
saying they "arrive with the next full write" -- right caution for a re-write,
which re-derives canon and re-seeds a running order the DM has edited, and too
much for an alias the book demonstrably writes.

`Gunther Arasek` is the case: a real man in a real stockyard, holding no
mention at all, because the book writes "Gunther and Yelena Arasek" and his own
name is never one run of text.
"""

import pytest

from backend.core.database import neo4j_session
from backend.graph.schema import NAMED_BY_BOOK
from backend.scripts.redeem_unnamed import TARGETS, WRITE

PREFIX = "pytest-redeem"
PARAMS = {"plane": "canon", "ids": []}


@pytest.fixture
def graph():
    def clean(s):
        s.run(f"MATCH (n) WHERE n.id STARTS WITH '{PREFIX}' DETACH DELETE n")
        s.run("MATCH (a:Alias) WHERE a.name STARTS WITH 'Pytestred' DETACH DELETE a")

    with neo4j_session() as session:
        clean(session)
        yield session
        clean(session)


def _entity(session, suffix, name, marked=True, alias=None):
    session.run(
        f"CREATE (e:Entity:NPC {{id:$id, plane:'canon', name:$n}}) "
        + (f"SET e.{NAMED_BY_BOOK} = false " if marked else "")
        + ("CREATE (a:Alias {name:$a, normalized:$norm}) "
           "CREATE (a)-[:ALIAS_OF]->(e)" if alias else ""),
        {"id": f"{PREFIX}:{suffix}", "n": name, "a": alias,
         "norm": (alias or "").lower()},
    )
    return f"{PREFIX}:{suffix}"


class TestWhichEntitiesAreTried:
    def test_the_default_is_everything_marked_unnamed(self, graph):
        eid = _entity(graph, "quiet", "Pytestred Quiet")
        assert eid in {r["id"] for r in graph.run(TARGETS, PARAMS)}

    def test_an_entity_that_already_cites_prose_is_not_tried(self, graph):
        """It has nothing to gain, and trying it is work for no outcome."""
        eid = _entity(graph, "fine", "Pytestred Fine", marked=False)
        assert eid not in {r["id"] for r in graph.run(TARGETS, PARAMS)}

    def test_an_explicit_id_overrides_the_default(self, graph):
        eid = _entity(graph, "named", "Pytestred Named", marked=False)
        rows = {r["id"] for r in graph.run(
            TARGETS, {"plane": "canon", "ids": [eid]})}
        assert rows == {eid}

    def test_the_aliases_come_with_it(self, graph):
        eid = _entity(graph, "withalias", "Pytestred Full", alias="Pytestred")
        row = next(r for r in graph.run(TARGETS, PARAMS) if r["id"] == eid)
        assert "Pytestred" in row["aliases"]


class TestItOnlyEverAdds:
    """Nothing is deleted, repointed or renamed, so an entity that already
    cites prose cannot lose any -- the difference from `homebrew.rescan`,
    whose whole job is to reconcile."""

    def _write(self, graph, eid, section, mid, offsets, display):
        graph.run(WRITE, {
            "entity": eid, "section": section, "id": mid, "plane": "canon",
            "chapter": "pytest-ch", "occurrences": len(offsets),
            "offsets": offsets, "display_name": display})

    def test_it_mints_the_missing_mention(self, graph):
        eid = _entity(graph, "gunther", "Pytestred Arasek")
        graph.run(f"CREATE (:Section {{id:'{PREFIX}:sec', plane:'canon', "
                  "text:'Pytestred and Yelena run the yard.'})")
        self._write(graph, eid, f"{PREFIX}:sec", f"{eid}@{PREFIX}:sec",
                    [0], "Pytestred")
        row = graph.run(
            "MATCH (m:Mention)-[:REFERS_TO]->(:Entity {id:$e}) "
            "RETURN m.display_name AS d, m.offsets AS o", {"e": eid}).single()
        assert row["d"] == "Pytestred" and row["o"] == [0]

    def test_running_it_twice_is_running_it_once(self, graph):
        eid = _entity(graph, "twice", "Pytestred Twice")
        graph.run(f"CREATE (:Section {{id:'{PREFIX}:s2', plane:'canon', text:'x'}})")
        for _ in range(2):
            self._write(graph, eid, f"{PREFIX}:s2", f"{eid}@{PREFIX}:s2",
                        [0], "Pytestred")
        n = graph.run("MATCH (m:Mention)-[:REFERS_TO]->(:Entity {id:$e}) "
                      "RETURN count(m) AS n", {"e": eid}).single()["n"]
        assert n == 1

    def test_an_existing_mention_keeps_the_offsets_it_had(self, graph):
        """ON CREATE only: a mention a real write produced is left exactly as
        that write left it."""
        eid = _entity(graph, "keep", "Pytestred Keep")
        graph.run(f"CREATE (:Section {{id:'{PREFIX}:s3', plane:'canon', text:'x'}})")
        self._write(graph, eid, f"{PREFIX}:s3", f"{eid}@{PREFIX}:s3", [11, 22], "A")
        self._write(graph, eid, f"{PREFIX}:s3", f"{eid}@{PREFIX}:s3", [99], "B")
        row = graph.run("MATCH (m:Mention {id:$i}) RETURN m.offsets AS o, "
                        "m.display_name AS d", {"i": f"{eid}@{PREFIX}:s3"}).single()
        assert row["o"] == [11, 22] and row["d"] == "A"
