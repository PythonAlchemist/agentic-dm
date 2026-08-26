"""The sea battle, end to end: generated, tweaked, approved, in the graph.

The example this design was argued from, run as one test. A scene inserted
into a published adventure's voyage, bringing a location, two people and an
item with it, one of them rejected and one renamed before a person approves.

WHAT IT ASSERTS BEYOND "IT WORKED": that canon came out byte-identical, that
the drop counts add up, that the chain put the scene where the DM said, and
that every element can be found by its own name. A cluster feature that moved
the book is a cluster feature that leaked.
"""

import json

import pytest

from backend.campaign import homebrew, store
from backend.campaign.chain import seed_plan
from backend.campaign.cluster import plan_cluster
from backend.campaign.model import AUTHORED, CAMPAIGN_PLANE, Campaign
from backend.canon.retrieval import CanonRetriever
from backend.core.database import neo4j_session

SLUG = "pytest-acceptance"
BOOK = "pytest-acceptance-book"
CHAPTER = "pytest-acceptance-chapter"
SECTIONS = [f"{BOOK}:ch#{i}" for i in range(4)]
VOYAGE = SECTIONS[1]
VOYAGE_TEXT = "The barge crosses the freezing Vrakanth strait for eight days."

#: What a generation declared, after annotation. Named so nothing collides
#: with the live graph, because this test runs beside real data.
DECLARED = [
    {"name": "The Kraken's Purse", "kind": "location",
     "role": "the corsair vessel that runs the party down",
     "from_canon": [{"claim": "the crossing takes days", "cite": "[1]"}],
     "invented": ["her name", "her black sails"]},
    {"name": "Captain Soldreth", "kind": "npc", "role": "the corsair captain",
     "from_canon": [], "invented": ["his name", "his missing ear"]},
    {"name": "Pell the Bosun", "kind": "npc", "role": "his second",
     "from_canon": [], "invented": ["her name"]},
    {"name": "The Sealed Strongbox", "kind": "item",
     "role": "what the corsairs are actually after",
     "from_canon": [], "invented": ["its lock", "its contents"]},
]

BODY = "At dawn a black-sailed ship closes on the barge across the strait."


def _clean(session):
    session.run("MATCH (c:Campaign {slug:$s}) DETACH DELETE c", {"s": SLUG})
    session.run("MATCH (b:Book {slug:$b}) DETACH DELETE b", {"b": BOOK})
    session.run("MATCH (c:Chapter {slug:$c}) DETACH DELETE c", {"c": CHAPTER})
    for prefix in (f"{BOOK}:", f"hb:{SLUG}:"):
        session.run("MATCH (n) WHERE n.id STARTS WITH $p DETACH DELETE n", {"p": prefix})
    session.run("MATCH (m:Mention {campaign:$s}) DETACH DELETE m", {"s": SLUG})
    session.run(
        "MATCH (a:Alias) WHERE NOT (a)-[:ALIAS_OF]->() AND a.plane = $p DETACH DELETE a",
        {"p": CAMPAIGN_PLANE},
    )


@pytest.fixture
def table(tmp_path):
    """A four-section adventure, a campaign over it, chained in book order."""
    with neo4j_session() as session:
        _clean(session)
        session.run(
            "CREATE (:Book {slug:$b, plane:'canon', display_name:'Acceptance Book'})",
            {"b": BOOK},
        )
        session.run(
            "CREATE (:Chapter {slug:$c, plane:'canon', index:0, title:'Ch'})",
            {"c": CHAPTER},
        )
        session.run(
            "MATCH (b:Book {slug:$b}), (c:Chapter {slug:$c}) MERGE (b)-[:HAS_CHAPTER]->(c)",
            {"b": BOOK, "c": CHAPTER},
        )
        for index, section_id in enumerate(SECTIONS):
            session.run(
                """
                CREATE (s:Section {id:$id, index:$i, plane:'canon', heading:$h, text:$t})
                WITH s MATCH (c:Chapter {slug:$c}) MERGE (c)-[:HAS_SECTION]->(s)
                """,
                {
                    "id": section_id, "i": index, "h": f"Section {index}",
                    "t": VOYAGE_TEXT if section_id == VOYAGE else "Other prose.",
                    "c": CHAPTER,
                },
            )
        session.execute_write(
            lambda tx: store.create(
                tx, Campaign(slug=SLUG, name="Acceptance", books=(BOOK,))
            )
        )
        session.execute_write(
            lambda tx: store.apply_rewire(
                tx, SLUG, seed_plan(SECTIONS), frozenset(SECTIONS),
                log_path=tmp_path / "log.jsonl",
            )
        )
        session.log_path = tmp_path / "log.jsonl"
        yield session
        _clean(session)


@pytest.fixture
def approved(table):
    """The DM rejects the bosun and renames the ship, then stores."""
    with neo4j_session() as session:
        aliases = store.canon_aliases(session, [BOOK])

    plan = plan_cluster(
        campaign=SLUG,
        elements=[
            {**e, "name": "The Kraken's Purse" if e["name"] == "The Kraken's Purse" else e["name"]}
            for e in DECLARED
        ],
        edges=[{"source": "Captain Soldreth", "target": "The Kraken's Purse",
                "rel_type": "LOCATED_IN"}],
        canon_aliases=aliases,
        approved=frozenset(
            {"The Kraken's Purse", "Captain Soldreth", "The Sealed Strongbox"}
        ),
    )
    result = table.execute_write(
        lambda tx: homebrew.write_cluster(
            tx,
            plan=plan,
            kind="scene",
            title="The Corsair Runs Us Down",
            body=BODY,
            generated_body=BODY,
            from_canon=[{"claim": "the crossing takes days", "cite": "[1]"}],
            invented=["the corsairs"],
            from_context=["the party chartered passage"],
            sources=[{"source": VOYAGE, "citation": "[1]", "type": "canon"}],
            manifest={"elements": DECLARED},
            anchor=VOYAGE,
            log_path=table.log_path,
        )
    )
    return table, result


class TestTheSceneLandsWhereTheDMPutIt:
    def test_it_follows_the_voyage_in_the_running_order(self, approved):
        session, result = approved
        order = store.running_order(session, SLUG)
        assert order.index(result["section_id"]) == order.index(VOYAGE) + 1

    def test_the_rest_of_the_book_is_untouched_around_it(self, approved):
        session, _ = approved
        order = [s for s in store.running_order(session, SLUG) if not s.startswith("hb:")]
        assert order == SECTIONS


class TestEveryApprovedElementIsInTheGraph:
    def test_three_kept_one_rejected(self, approved):
        _, result = approved
        assert len(result["elements"]) == 3
        assert result["dropped"] == {"rejected by the DM": 1}

    def test_each_wears_the_type_the_book_uses(self, approved):
        session, result = approved
        labels = {
            dict(r)["id"]: set(dict(r)["labels"])
            for r in session.run(
                "MATCH (e:Entity) WHERE e.id IN $ids RETURN e.id AS id, labels(e) AS labels",
                {"ids": result["elements"]},
            )
        }
        assert "LOCATION" in labels[f"hb:{SLUG}:the-kraken-s-purse"]
        assert "NPC" in labels[f"hb:{SLUG}:captain-soldreth"]
        assert "ITEM" in labels[f"hb:{SLUG}:the-sealed-strongbox"]

    def test_each_is_authored_and_on_the_campaign_plane(self, approved):
        session, result = approved
        rows = [
            dict(r)
            for r in session.run(
                "MATCH (e:Entity) WHERE e.id IN $ids RETURN e.plane AS p, e.status AS s",
                {"ids": result["elements"]},
            )
        ]
        assert all(r["p"] == CAMPAIGN_PLANE and r["s"] == AUTHORED for r in rows)

    def test_each_answers_to_its_own_name(self, approved):
        """The whole point of minting a node rather than leaving prose: three
        sessions later the DM asks about the captain by name."""
        session, _ = approved
        result = CanonRetriever(book=BOOK, limit=6, campaign=SLUG).retrieve(
            "tell me about Captain Soldreth"
        )
        assert any(a.entity_id == f"hb:{SLUG}:captain-soldreth" for a in result.anchors)
        assert any(p.origin == "campaign" for p in result.passages)

    def test_the_rejected_one_is_nowhere(self, approved):
        session, _ = approved
        found = session.run(
            "MATCH (e:Entity {id:$id}) RETURN count(e) AS c",
            {"id": f"hb:{SLUG}:pell-the-bosun"},
        ).single()["c"]
        assert found == 0


class TestProvenanceSurvivesTheWholeTrip:
    def test_the_scene_keeps_its_three_lists(self, approved):
        session, result = approved
        row = dict(
            session.run(
                "MATCH (s:Section {id:$id}) RETURN s.from_canon AS c, s.invented AS i, "
                "s.from_context AS x",
                {"id": result["section_id"]},
            ).single()
        )
        assert json.loads(row["x"]) == ["the party chartered passage"]
        assert json.loads(row["c"])[0]["cite"] == "[1]"

    def test_an_element_keeps_its_own(self, approved):
        session, _ = approved
        row = dict(
            session.run(
                "MATCH (e:Entity {id:$id}) RETURN e.invented AS i",
                {"id": f"hb:{SLUG}:the-kraken-s-purse"},
            ).single()
        )
        assert json.loads(row["i"]) == ["her name", "her black sails"]

    def test_the_citation_became_a_queryable_edge(self, approved):
        session, result = approved
        found = session.run(
            "MATCH (:Section {id:$s})-[:DERIVED_FROM]->(c:Section) RETURN c.id AS id",
            {"s": result["section_id"]},
        ).single()
        assert dict(found)["id"] == VOYAGE

    def test_the_model_s_original_manifest_is_kept(self, approved):
        """Four declared, three approved. What the DM overrode stays answerable."""
        session, result = approved
        row = dict(
            session.run(
                "MATCH (s:Section {id:$id}) RETURN s.manifest AS m, s.generated_manifest AS g",
                {"id": result["section_id"]},
            ).single()
        )
        assert len(json.loads(row["m"])) == 3
        assert len(json.loads(row["g"])["elements"]) == 4

    def test_the_declared_edge_is_written_and_carries_its_provenance(self, approved):
        """It survived the type check, so it is real structure now -- and it is
        stamped `authored` on the campaign plane, because an edge nobody can
        tell from canon is the defect this whole two-axis scheme prevents."""
        session, result = approved
        assert result["edges"] == 1
        row = session.run(
            "MATCH (:Entity {id:$a})-[r]->(:Entity {id:$b}) "
            "RETURN r.plane AS plane, r.status AS status, r.campaign AS campaign",
            {"a": f"hb:{SLUG}:captain-soldreth", "b": f"hb:{SLUG}:the-kraken-s-purse"},
        ).single()
        assert dict(row) == {"plane": "campaign", "status": "authored", "campaign": SLUG}


class TestTheBookIsByteIdentical:
    """The acceptance bar. A cluster feature that moved canon has leaked."""

    def _canon(self, session):
        return [
            dict(r)
            for r in session.run(
                """
                MATCH (s:Section) WHERE s.id IN $ids
                RETURN s.id AS id, properties(s) AS props
                ORDER BY s.id
                """,
                {"ids": SECTIONS},
            )
        ]

    def test_canon_sections_are_unchanged_by_the_write(self, table):
        before = self._canon(table)
        plan = plan_cluster(campaign=SLUG, elements=DECLARED)
        table.execute_write(
            lambda tx: homebrew.write_cluster(
                tx, plan=plan, kind="scene", title="A Scene", body=BODY,
                generated_body=BODY, from_canon=[], invented=["x"], from_context=[],
                sources=[], manifest={}, anchor=VOYAGE, log_path=table.log_path,
            )
        )
        assert self._canon(table) == before

    def test_a_campaign_less_retriever_sees_none_of_it(self, approved):
        """Contamination, checked once more at the end of the whole flow."""
        session, _ = approved
        result = CanonRetriever(book=BOOK, limit=8).retrieve(
            "tell me about Captain Soldreth and the Kraken's Purse"
        )
        assert not any(p.origin == "campaign" for p in result.passages)
        assert not any(a.entity_id.startswith("hb:") for a in result.anchors)


class TestRemovingItAll:
    def test_deleting_the_root_refuses_while_elements_hang_off_it(self, approved):
        session, result = approved
        with pytest.raises(homebrew.ClusterHasElements) as raised:
            session.execute_write(
                lambda tx: homebrew.delete_cluster(
                    tx, slug=SLUG, entity_id=result["entity_id"]
                )
            )
        assert len(raised.value.members) == 3

    def test_cascade_leaves_the_book_exactly_as_it_was(self, approved):
        session, result = approved
        session.execute_write(
            lambda tx: homebrew.delete_cluster(
                tx, slug=SLUG, entity_id=result["entity_id"], cascade=True
            )
        )
        assert store.running_order(session, SLUG) == SECTIONS
        left = session.run(
            "MATCH (n) WHERE n.id STARTS WITH $p RETURN count(n) AS c",
            {"p": f"hb:{SLUG}:"},
        ).single()["c"]
        assert left == 0
