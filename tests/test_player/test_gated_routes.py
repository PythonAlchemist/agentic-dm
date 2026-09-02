"""The gate holding over HTTP, for a reader who is really a player.

The unit tests cover the queries. This covers the thing that actually ships: a
player holding a valid token, hitting the endpoints directly rather than
through a screen, because a token reaches every route whether or not any screen
calls it.
"""

import pytest
from fastapi.testclient import TestClient

from backend.api import auth
from backend.api.main import app
from backend.campaign import roles
from backend.core.config import settings
from backend.core.database import neo4j_session
from backend.player import reader as visibility

PREFIX = "pytest-gate"
SLUG = f"{PREFIX}-camp"
STRAHD = f"{PREFIX}:strahd"
SECRET = f"{PREFIX}:the-twist"

DM_TOKEN = "gate-dm-token-for-tests"
PLAYER_TOKEN = "gate-player-token-for-tests"


@pytest.fixture
def table(monkeypatch):
    monkeypatch.setattr(
        settings, "access_tokens",
        f"ana:{auth.fingerprint(DM_TOKEN)},ben:{auth.fingerprint(PLAYER_TOKEN)}")
    with neo4j_session() as session:
        def clean(s):
            s.run("MATCH (n) WHERE n.campaign = $c DETACH DELETE n",
                  {"c": SLUG}).consume()
            s.run("MATCH (n) WHERE n.id STARTS WITH $p DETACH DELETE n",
                  {"p": PREFIX}).consume()
            s.run("MATCH (c:Campaign {slug:$c}) DETACH DELETE c",
                  {"c": SLUG}).consume()

        clean(session)
        session.run(
            "CREATE (:Campaign {slug:$slug, name:'Gate', campaign:$slug, "
            "  owner:'ana'}) "
            "CREATE (:Entity:NPC {id:$s, plane:'canon', "
            "  name:'Strahd von Zarovich'}) "
            "CREATE (:Section {id:$twist, heading:'The Twist', "
            "  text:'Ireena is his lost bride.', plane:'canon'})",
            {"slug": SLUG, "s": STRAHD, "twist": SECRET}).consume()
        session.execute_write(lambda tx: roles.seat(
            tx, slug=SLUG, reader="ben", role=roles.PLAYER))
        yield session
        clean(session)


def _as(token: str) -> TestClient:
    client = TestClient(app)
    client.headers["Authorization"] = f"Bearer {token}"
    return client


class TestAPlayerHittingTheEndpointsDirectly:
    def test_an_unrevealed_entity_is_not_there(self, table):
        got = _as(PLAYER_TOKEN).get("/api/homebrew/entity", params={
            "entity_id": STRAHD, "campaign": SLUG})
        assert got.status_code == 404

    def test_an_unrevealed_scene_is_not_there(self, table):
        got = _as(PLAYER_TOKEN).get("/api/homebrew/section", params={
            "section_id": SECRET, "campaign": SLUG})
        assert got.status_code == 404

    def test_the_prose_is_not_in_the_refusal(self, table):
        """A 404 that quotes the thing it is refusing has refused nothing."""
        got = _as(PLAYER_TOKEN).get("/api/homebrew/section", params={
            "section_id": SECRET, "campaign": SLUG})
        assert "lost bride" not in got.text

    def test_search_does_not_confirm_a_name_exists(self, table):
        """Every screen can be gated and the search box still answers "does an
        entity called Strahd exist" with a yes."""
        found = _as(PLAYER_TOKEN).get("/api/table/search", params={
            "campaign": SLUG, "q": "strahd"}).json()["found"]
        assert found == []

    def test_the_assistant_is_closed_to_them(self, table):
        """It reads the whole book and cannot yet be seeded from the revealed
        closure, so it is refused rather than filtered."""
        got = _as(PLAYER_TOKEN).post("/api/lab/chat", json={
            "message": "who is Strahd?", "campaign": SLUG,
            "session_id": f"{PREFIX}-session"})
        assert got.status_code == 403
        assert "Strahd" not in got.json()["detail"]

    def test_a_player_may_not_reveal_things_to_themselves(self, table):
        got = _as(PLAYER_TOKEN).post("/api/table/reveal", json={
            "campaign": SLUG, "target": STRAHD})
        assert got.status_code == 403


class TestTheDMIsUnaffected:
    def test_the_owner_reads_everything(self, table):
        got = _as(DM_TOKEN).get("/api/homebrew/section", params={
            "section_id": SECRET, "campaign": SLUG})
        assert got.status_code == 200 and "lost bride" in got.json()["text"]

    def test_the_owner_can_reveal(self, table):
        assert _as(DM_TOKEN).post("/api/table/reveal", json={
            "campaign": SLUG, "target": STRAHD}).status_code == 200


class TestAfterARevealTheDoorOpens:
    def test_the_entity_arrives(self, table):
        _as(DM_TOKEN).post("/api/table/reveal",
                           json={"campaign": SLUG, "target": STRAHD})
        got = _as(PLAYER_TOKEN).get("/api/homebrew/entity", params={
            "entity_id": STRAHD, "campaign": SLUG})
        assert got.status_code == 200
        assert got.json()["name"] == "Strahd von Zarovich"

    def test_the_scene_stays_shut_until_it_too_is_given(self, table):
        """Knowing somebody exists is not having read the book about them."""
        _as(DM_TOKEN).post("/api/table/reveal",
                           json={"campaign": SLUG, "target": STRAHD})
        assert _as(PLAYER_TOKEN).get("/api/homebrew/section", params={
            "section_id": SECRET, "campaign": SLUG}).status_code == 404

    def test_concealing_shuts_it_again(self, table):
        _as(DM_TOKEN).post("/api/table/reveal",
                           json={"campaign": SLUG, "target": STRAHD})
        _as(DM_TOKEN).request("DELETE", "/api/table/reveal", params={
            "campaign": SLUG, "target": STRAHD})
        assert _as(PLAYER_TOKEN).get("/api/homebrew/entity", params={
            "entity_id": STRAHD, "campaign": SLUG}).status_code == 404


class TestTheShapeThatKeepsItTrue:
    """Not what the queries return -- what they are ALLOWED to be.

    Every leak this layer can have is a player query that selects a row before
    checking a grant, so the check is that no player query exists which is not
    anchored on one.
    """

    def _queries(self) -> dict:
        import backend.api.routes.table as table_routes

        return {
            "ENTITY_PLAYER": visibility.ENTITY_PLAYER,
            "SECTION_PLAYER": visibility.SECTION_PLAYER,
            "SEARCH_PLAYER": table_routes.SEARCH_PLAYER,
        }

    def test_every_player_query_gates_before_it_returns(self):
        """The rule survived the rulebook, in a stronger form.

        It used to be "the first line matches REVEALED", which stopped holding
        when public material gave the selection a second legitimate branch. The
        thing that actually matters is unchanged: the gate is part of choosing
        the rows, not something applied to rows already chosen. So everything
        before the first RETURN must carry BOTH branches -- the grant and the
        rulebook -- and a query that gained a third would fail here until
        somebody wrote it down.
        """
        for name, cypher in self._queries().items():
            selection = cypher.split("RETURN")[0]
            assert "REVEALED" in selection, f"{name} does not check a grant"
            assert "b.reference = true" in selection, (
                f"{name} does not check for a rulebook")

    def test_no_player_query_takes_its_visibility_from_a_parameter(self):
        """An argument a caller can get wrong is one they can get wrong in the
        widening direction. `['']` would make the whole graph public, since
        every id starts with the empty string."""
        for name, cypher in self._queries().items():
            selection = cypher.split("RETURN")[0]
            assert "$public" not in selection, f"{name} is told what is public"
            assert "$prefixes" not in selection, f"{name} is told what is public"

    def test_there_are_player_queries_to_check(self):
        """Without this the sweep above passes by finding nothing, which is how
        the auth sweep once enumerated zero routes and went green."""
        assert visibility.ENTITY_PLAYER and visibility.SECTION_PLAYER


class TestTheQuieterLeaks:
    """Not the screens anybody thinks about -- the lists beside them."""

    def test_the_atlas_does_not_name_places_they_have_not_met(self, table):
        """Every pin can be hidden and the sidebar still says Castle Ravenloft
        exists."""
        maps = _as(PLAYER_TOKEN).get("/api/table/maps",
                                     params={"campaign": SLUG}).json()["maps"]
        assert maps == []

    def test_the_plan_for_tonight_is_the_dm_s(self, table):
        """What a DM MEANT to run is next session's plot in list form."""
        session = _as(DM_TOKEN).post("/api/table/session",
                                     json={"campaign": SLUG}).json()["id"]
        got = _as(PLAYER_TOKEN).get("/api/table/session/diff", params={
            "campaign": SLUG, "session_id": session})
        assert got.status_code == 403

    def test_the_transcript_suggestions_are_the_dm_s(self, table):
        got = _as(PLAYER_TOKEN).get("/api/table/session/touched", params={
            "campaign": SLUG, "session_id": f"hb:{SLUG}:session-1"})
        assert got.status_code == 403


class TestWhatWeKnow:
    """The players' shared memory, which is the thing six people actually lose
    between sessions."""

    def test_an_untold_table_is_told_so(self, table):
        got = _as(PLAYER_TOKEN).get("/api/table/ask", params={
            "campaign": SLUG, "q": "who is Strahd?"}).json()
        assert got["passages"] == [] and "told about" in got["why"]

    def test_the_prose_is_not_in_the_answer_either(self, table):
        got = _as(PLAYER_TOKEN).get("/api/table/ask", params={
            "campaign": SLUG, "q": "tell me about the bride"})
        assert "lost bride" not in got.text

    def test_a_revealed_scene_is_quoted_back(self, table):
        for target in (STRAHD, SECRET):
            _as(DM_TOKEN).post("/api/table/reveal",
                               json={"campaign": SLUG, "target": target})
        got = _as(PLAYER_TOKEN).get("/api/table/ask", params={
            "campaign": SLUG, "q": "what about the twist?"}).json()
        assert [p["heading"] for p in got["passages"]] == ["The Twist"]

    def test_an_empty_question_asks_nothing(self, table):
        got = _as(PLAYER_TOKEN).get("/api/table/ask", params={
            "campaign": SLUG, "q": "  "}).json()
        assert got["passages"] == []


class TestTheScreensThatAreTheDMsWhole:
    """Not a narrowed view -- no view. A running order is the plot of
    everything the table has not reached, listed in order."""

    def test_the_running_order_is_refused(self, table):
        got = _as(PLAYER_TOKEN).get("/api/homebrew/running-order",
                                    params={"campaign": SLUG})
        assert got.status_code == 403

    def test_the_cast_is_refused(self, table):
        """It names every NPC, place and quest this table invented, including
        the ones nobody has met."""
        got = _as(PLAYER_TOKEN).get("/api/homebrew/elements",
                                    params={"campaign": SLUG})
        assert got.status_code == 403

    def test_the_dm_still_reads_both(self, table):
        for path in ("running-order", "elements"):
            got = _as(DM_TOKEN).get(f"/api/homebrew/{path}",
                                    params={"campaign": SLUG})
            assert got.status_code == 200, path


class TestTheAdventureLog:
    def test_a_player_may_read_it(self, table):
        """Safe by construction: it reports grants, and a grant is the
        permission."""
        _as(DM_TOKEN).post("/api/table/reveal",
                           json={"campaign": SLUG, "target": STRAHD})
        got = _as(PLAYER_TOKEN).get("/api/table/log", params={"campaign": SLUG})
        assert got.status_code == 200
        assert got.json()["log"][0]["learned"][0]["name"] == "Strahd von Zarovich"

    def test_it_holds_nothing_ungranted(self, table):
        _as(DM_TOKEN).post("/api/table/reveal",
                           json={"campaign": SLUG, "target": STRAHD})
        got = _as(PLAYER_TOKEN).get("/api/table/log", params={"campaign": SLUG})
        assert "lost bride" not in got.text and "The Twist" not in got.text

    def test_an_alias_is_what_the_log_remembers(self, table):
        _as(DM_TOKEN).post("/api/table/reveal", json={
            "campaign": SLUG, "target": STRAHD, "as_name": "the coachman"})
        got = _as(PLAYER_TOKEN).get("/api/table/log", params={"campaign": SLUG})
        assert "coachman" in got.text and "Strahd" not in got.text


class TestThePartysPockets:
    def test_a_player_does_not_read_an_npc_s_inventory(self, table):
        """The full ledger names every holder, so reading it would tell a
        player that somebody called Strahd is carrying a tome."""
        table.run(
            "MERGE (i:Entity:ITEM {id:$i, plane:'canon', name:'Tome'})",
            {"i": f"{PREFIX}:tome"}).consume()
        _as(DM_TOKEN).post("/api/table/inventory/give", json={
            "campaign": SLUG, "item": f"{PREFIX}:tome", "holder": STRAHD})
        got = _as(PLAYER_TOKEN).get("/api/table/inventory",
                                    params={"campaign": SLUG})
        assert got.json()["held"] == []
        assert "Strahd" not in got.text

    def test_but_does_read_the_party_s(self, table):
        table.run(
            "MERGE (i:Entity:ITEM {id:$i, plane:'canon', name:'Rope'})",
            {"i": f"{PREFIX}:rope"}).consume()
        _as(DM_TOKEN).post("/api/table/inventory/give", json={
            "campaign": SLUG, "item": f"{PREFIX}:rope",
            "holder": f"hb:{SLUG}:the-party"})
        got = _as(PLAYER_TOKEN).get("/api/table/inventory",
                                    params={"campaign": SLUG}).json()["held"]
        assert [h["name"] for h in got] == ["Rope"]

    def test_a_player_cannot_hand_things_around(self, table):
        got = _as(PLAYER_TOKEN).post("/api/table/inventory/give", json={
            "campaign": SLUG, "item": f"{PREFIX}:rope", "holder": STRAHD})
        assert got.status_code == 403


class TestARefusalSaysWhyItRefused:
    """One gate now guards three different things, and a message that explains
    the wrong one reads as a broken product rather than a closed door."""

    def test_the_running_order_talks_about_the_running_order(self, table):
        detail = _as(PLAYER_TOKEN).get("/api/homebrew/running-order",
                                       params={"campaign": SLUG}).json()["detail"]
        assert "running order" in detail and "assistant" not in detail

    def test_the_cast_talks_about_the_cast(self, table):
        detail = _as(PLAYER_TOKEN).get("/api/homebrew/elements",
                                       params={"campaign": SLUG}).json()["detail"]
        assert "not met" in detail and "assistant" not in detail

    def test_the_assistant_talks_about_the_assistant(self, table):
        detail = _as(PLAYER_TOKEN).post("/api/lab/chat", json={
            "message": "hello", "campaign": SLUG,
            "session_id": "t"}).json()["detail"]
        assert "assistant" in detail

    def test_no_refusal_names_what_it_is_hiding(self, table):
        """A 403 that quotes the secret has refused nothing."""
        for got in (
            _as(PLAYER_TOKEN).get("/api/homebrew/running-order",
                                  params={"campaign": SLUG}),
            _as(PLAYER_TOKEN).get("/api/homebrew/elements",
                                  params={"campaign": SLUG}),
        ):
            assert "Strahd" not in got.text and "lost bride" not in got.text
