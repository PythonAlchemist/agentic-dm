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


class TestAnAliasThatAlreadyExistsDoesNotCrash:
    """`Alias.name` is globally unique, across every plane and book.

    THE DEFECT THIS CLOSES. The write merged on `{name, plane}`, found no
    campaign-plane node for a name canon already used, tried to create a second
    one, and died on the constraint with a raw driver error. Storing anything
    named like an existing canon entity was unsurvivable.

    Merging on `name` alone with `ON CREATE SET` fixes it without mutating
    canon: an existing alias keeps its own plane and normalized form and merely
    gains a second `ALIAS_OF`. `BY_ALIAS` already calls that legitimate -- "one
    name, several entities, and the ambiguity travels" -- and the entity-plane
    filter keeps the campaign entity out of canon reads.
    """

    def test_storing_under_an_existing_alias_succeeds(self, table):
        table.run(
            "CREATE (:Alias {name:'The Sea Battle', normalized:'the sea battle', "
            "plane:'canon'})"
        )
        try:
            stored = _store(table, anchor=ANCHOR)
            assert stored.entity_id.startswith("hb:")
        finally:
            table.run("MATCH (a:Alias {name:'The Sea Battle'}) DETACH DELETE a")

    def test_and_the_existing_alias_is_not_rewritten(self, table):
        """The canon-never-mutated rule reaching one node further than
        entities: an alias the book owns keeps its plane."""
        table.run(
            "CREATE (:Alias {name:'The Sea Battle', normalized:'the sea battle', "
            "plane:'canon'})"
        )
        try:
            _store(table, anchor=ANCHOR)
            row = dict(
                table.run(
                    "MATCH (a:Alias {name:'The Sea Battle'}) RETURN a.plane AS plane"
                ).single()
            )
            assert row["plane"] == "canon"
        finally:
            table.run("MATCH (a:Alias {name:'The Sea Battle'}) DETACH DELETE a")


class TestWritingACluster:
    """One prose section, many typed things, in one transaction."""

    ELEMENTS = [
        {"name": "Captain Saltmarrow", "kind": "npc", "role": "the corsair captain",
         "from_canon": [], "invented": ["his name", "his scar"]},
        {"name": "The Red Barge", "kind": "location", "role": "the prison barge",
         "from_canon": [{"claim": "the voyage is by sea", "cite": "[1]"}],
         "invented": ["her name"]},
        {"name": "The Sealed Strongbox", "kind": "item", "role": "what they want",
         "from_canon": [], "invented": ["its lock"]},
    ]

    def _plan(self, **kw):
        from backend.campaign.cluster import plan_cluster

        return plan_cluster(campaign=SLUG, elements=self.ELEMENTS, **kw)

    def _write(self, session, plan, **overrides):
        payload = {**PAYLOAD, **overrides}
        payload.pop("slug", None)
        return session.execute_write(
            lambda tx: homebrew.write_cluster(
                tx, plan=plan, manifest={"elements": self.ELEMENTS},
                log_path=session.log_path, anchor=ANCHOR, **payload
            )
        )

    def test_every_element_becomes_a_typed_entity(self, table):
        result = self._write(table, self._plan())
        rows = {
            dict(r)["id"]: dict(r)["labels"]
            for r in table.run(
                "MATCH (e:Entity) WHERE e.id IN $ids RETURN e.id AS id, labels(e) AS labels",
                {"ids": result["elements"]},
            )
        }
        assert len(rows) == 3
        assert "NPC" in rows["hb:pytest-hb:captain-saltmarrow"]
        assert "LOCATION" in rows["hb:pytest-hb:the-red-barge"]
        assert "ITEM" in rows["hb:pytest-hb:the-sealed-strongbox"]

    def test_every_element_resolves_by_name(self, table):
        result = self._write(table, self._plan())
        found = table.run(
            "MATCH (a:Alias)-[:ALIAS_OF]->(e:Entity) WHERE e.id IN $ids RETURN count(a) AS c",
            {"ids": result["elements"]},
        ).single()["c"]
        assert found == 3

    def test_every_element_is_retrievable_through_the_shared_section(self, table):
        """One section, three mentions. The triangle is what makes a passage."""
        result = self._write(table, self._plan())
        found = table.run(
            """
            MATCH (e:Entity)<-[:REFERS_TO]-(m:Mention)-[:IN_SECTION]->(s:Section {id:$s})
            WHERE e.id IN $ids RETURN count(m) AS c
            """,
            {"s": result["section_id"], "ids": result["elements"]},
        ).single()["c"]
        assert found == 3

    def test_an_element_carries_its_own_provenance(self, table):
        self._write(table, self._plan())
        row = dict(
            table.run(
                "MATCH (e:Entity {id:$id}) RETURN e.invented AS i, e.role AS r",
                {"id": "hb:pytest-hb:captain-saltmarrow"},
            ).single()
        )
        assert json.loads(row["i"]) == ["his name", "his scar"]
        assert row["r"] == "the corsair captain"

    def test_the_model_s_original_manifest_is_kept_beside_the_approved_one(self, table):
        """`generated_body`'s rule: what the DM overrode stays answerable."""
        result = self._write(table, self._plan(approved=frozenset({"The Red Barge"})))
        row = dict(
            table.run(
                "MATCH (s:Section {id:$id}) RETURN s.manifest AS m, s.generated_manifest AS g",
                {"id": result["section_id"]},
            ).single()
        )
        assert len(json.loads(row["m"])) == 1
        assert len(json.loads(row["g"])["elements"]) == 3

    def test_a_rejected_element_is_not_written_and_is_counted(self, table):
        result = self._write(table, self._plan(approved=frozenset({"The Red Barge"})))
        assert result["elements"] == ["hb:pytest-hb:the-red-barge"]
        assert result["dropped"] == {"rejected by the DM": 2}

    def test_deferred_edges_are_reported(self, table):
        result = self._write(
            table, self._plan(edges=[{"source": "a", "target": "b", "rel_type": "GUARDS"}])
        )
        assert result["edges_deferred"] == 1

    def test_an_unstorable_plan_is_refused_before_anything_is_written(self, table):
        plan = self._plan(
            canon_aliases=frozenset({("captain saltmarrow", "kftgv:someone")})
        )
        with pytest.raises(homebrew.AlreadyStored):
            self._write(table, plan)
        left = table.run(
            "MATCH (e:Entity) WHERE e.id STARTS WITH 'hb:pytest-hb:' RETURN count(e) AS c"
        ).single()["c"]
        assert left == 0

    def test_canon_is_untouched(self, table):
        before = dict(
            table.run("MATCH (s:Section {id:$i}) RETURN properties(s) AS p",
                      {"i": ANCHOR}).single()
        )["p"]
        self._write(table, self._plan())
        after = dict(
            table.run("MATCH (s:Section {id:$i}) RETURN properties(s) AS p",
                      {"i": ANCHOR}).single()
        )["p"]
        assert before == after


class TestDeletingACluster:
    def test_it_refuses_while_elements_would_be_orphaned(self, table):
        cluster = TestWritingACluster()
        result = cluster._write(table, cluster._plan())
        with pytest.raises(homebrew.ClusterHasElements) as raised:
            table.execute_write(
                lambda tx: homebrew.delete_cluster(
                    tx, slug=SLUG, entity_id=result["entity_id"]
                )
            )
        assert len(raised.value.members) == 3

    def test_cascade_removes_them_and_counts(self, table):
        cluster = TestWritingACluster()
        result = cluster._write(table, cluster._plan())
        removed = table.execute_write(
            lambda tx: homebrew.delete_cluster(
                tx, slug=SLUG, entity_id=result["entity_id"], cascade=True
            )
        )
        assert removed["elements"] == 3
        left = table.run(
            "MATCH (e:Entity) WHERE e.id STARTS WITH 'hb:pytest-hb:' RETURN count(e) AS c"
        ).single()["c"]
        assert left == 0


def test_every_generatable_kind_has_a_label():
    """A kind with no mapping is silently filed as LORE. Both closed sets are
    checked here so adding to either cannot leave a barge labelled folklore."""
    from backend.agents.generator import ELEMENT_KINDS, KINDS

    for kind in set(KINDS) | set(ELEMENT_KINDS):
        assert kind in homebrew.LABELS, kind


class TestTheClusterEndpointsReDeriveEverything:
    """The browser's word is worth nothing: the boundary re-plans."""

    def _payload(self, **overrides):
        return {
            "campaign": SLUG, "kind": "scene", "title": "Endpoint Scene",
            "body": "b", "generated_body": "b",
            "from_canon": [], "invented": ["x"], "from_context": [],
            "sources": [], "anchor": None,
            "elements": [{"name": "A Deckhand", "kind": "npc", "role": "",
                          "from_canon": [], "invented": ["his name"]}],
            "edges": [], **overrides,
        }

    def test_a_tampered_approval_cannot_smuggle_an_element_in(self, table):
        """A payload approving a name that is not in `elements` must not
        conjure one -- the plan is derived from the elements, never from the
        approval list."""
        from backend.api.routes.homebrew import ClusterRequest, _plan_for

        plan = _plan_for(ClusterRequest(**self._payload(approved=["Someone Else"])))
        assert plan.elements == ()
        assert plan.dropped == {"rejected by the DM": 1}

    def test_the_plan_route_writes_nothing(self, table):
        from backend.api.routes.homebrew import ClusterRequest, _plan_for

        _plan_for(ClusterRequest(**self._payload()))
        left = table.run(
            "MATCH (e:Entity) WHERE e.id = 'hb:pytest-hb:a-deckhand' RETURN count(e) AS c"
        ).single()["c"]
        assert left == 0

    def test_existing_ids_are_read_from_the_graph_not_the_payload(self, table):
        """A second cluster naming something already stored is refused, and the
        refusal comes from what the graph holds rather than what was posted."""
        from backend.api.routes.homebrew import ClusterRequest, _plan_for

        table.run(
            "CREATE (:Entity {id:'hb:pytest-hb:a-deckhand', plane:'campaign', "
            "campaign:$c, name:'A Deckhand'})",
            {"c": SLUG},
        )
        plan = _plan_for(ClusterRequest(**self._payload()))
        assert plan.dropped == {"already in this campaign": 1}


class TestFleshingOutAStub:
    """A cluster mints names; this is how one becomes something to read from.

    The distinction that matters: `write` mints an entity and refuses a second
    of the same name; `expand` mints NOTHING and gives an existing one the
    prose it never had. Without it, fleshing out Captain Saltmarrow hits
    `AlreadyStored` -- correctly, and uselessly.
    """

    def _element(self, table):
        cluster = TestWritingACluster()
        result = cluster._write(table, cluster._plan())
        return result["elements"][0]

    def _expand(self, table, entity_id, **overrides):
        payload = dict(
            slug=SLUG, entity_id=entity_id,
            body="A weathered corsair with a missing ear.",
            generated_body="A weathered corsair with a missing ear.",
            from_canon=[], invented=["his ear"], from_context=[], sources=[],
            anchor=None, **overrides,
        )
        return table.execute_write(lambda tx: homebrew.expand(tx, **payload))

    def test_it_creates_the_section_the_entity_never_had(self, table):
        entity_id = self._element(table)
        stored = self._expand(table, entity_id)
        row = dict(
            table.run(
                "MATCH (s:Section {id:$id}) RETURN s.text AS text, s.expands AS e",
                {"id": stored.section_id},
            ).single()
        )
        assert "missing ear" in row["text"]
        assert row["e"] == entity_id

    def test_it_creates_no_second_entity(self, table):
        """The whole difference from `write`, and the reason this exists."""
        entity_id = self._element(table)
        before = table.run(
            "MATCH (e:Entity {plane:'campaign', campaign:$c}) RETURN count(e) AS c",
            {"c": SLUG},
        ).single()["c"]
        self._expand(table, entity_id)
        after = table.run(
            "MATCH (e:Entity {plane:'campaign', campaign:$c}) RETURN count(e) AS c",
            {"c": SLUG},
        ).single()["c"]
        assert after == before

    def test_the_prose_is_now_reachable_from_the_entity(self, table):
        entity_id = self._element(table)
        stored = self._expand(table, entity_id)
        found = table.run(
            """
            MATCH (:Entity {id:$e})<-[:REFERS_TO]-(m:Mention)-[:IN_SECTION]->(:Section {id:$s})
            RETURN count(m) AS c
            """,
            {"e": entity_id, "s": stored.section_id},
        ).single()["c"]
        assert found == 1

    def test_it_is_not_put_in_the_running_order_by_default(self, table):
        """A character's write-up is not an episode. Anchoring it would tell
        the table to play it."""
        entity_id = self._element(table)
        stored = self._expand(table, entity_id)
        assert stored.chain_changes == 0
        assert stored.section_id not in store.running_order(table, SLUG)

    def test_a_second_write_up_is_refused_rather_than_stacked(self, table):
        """Two descriptions of one thing leaves a DM unable to tell which is
        current. Delete and rewrite, deliberately."""
        entity_id = self._element(table)
        self._expand(table, entity_id)
        with pytest.raises(homebrew.AlreadyExpanded):
            self._expand(table, entity_id)

    def test_expanding_something_absent_is_refused(self, table):
        with pytest.raises(homebrew.NotStored):
            self._expand(table, f"hb:{SLUG}:never-existed")

    def test_it_cannot_reach_another_campaigns_element(self, table):
        """`campaign` is on the MATCH, not merely on the id, so a payload
        naming another table's node finds nothing."""
        entity_id = self._element(table)
        with pytest.raises(homebrew.NotStored):
            table.execute_write(
                lambda tx: homebrew.expand(
                    tx, slug="some-other-table", entity_id=entity_id,
                    body="x", generated_body="x", from_canon=[], invented=["y"],
                    from_context=[], sources=[], anchor=None,
                )
            )
