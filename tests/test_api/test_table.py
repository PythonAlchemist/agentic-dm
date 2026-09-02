"""The table's API, and the one thing it must not get wrong.

A CLIENT DOES NOT GET TO SAY WHO IT IS TO THE MAP. It says who it is to the
gate; the graph says what chair that is; the route picks the query. Most of
what follows is that sentence taken apart -- a player asking for the DM view
gets the player view, and a seat that was never granted gets the narrow one
rather than the wide one.
"""

import io

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.campaign import assets, roles
from backend.core.database import neo4j_session

PREFIX = "pytest-table"
SLUG = f"{PREFIX}-camp"
PLACE = f"{PREFIX}:barovia"
NPC = f"{PREFIX}:strahd"

client = TestClient(app)


@pytest.fixture
def table():
    with neo4j_session() as session:
        def clean(s):
            s.run("MATCH (n) WHERE n.campaign = $c DETACH DELETE n",
                  {"c": SLUG}).consume()
            s.run("MATCH (n) WHERE n.id STARTS WITH $p DETACH DELETE n",
                  {"p": PREFIX}).consume()
            s.run("MATCH (b:Book {slug:$p}) DETACH DELETE b",
                  {"p": PREFIX}).consume()

        clean(session)
        # A TABLE DRAWS ON A BOOK, which is what scopes every search: the
        # entity ids below carry the book's prefix, exactly as a real harvest
        # writes them.
        session.run(
            "CREATE (b:Book {slug:$book, id:$book, plane:'canon'}) "
            "CREATE (c:Campaign {slug:$slug, name:'Table', campaign:$slug}) "
            "CREATE (c)-[:DRAWS_ON]->(b) "
            "CREATE (:Entity:LOCATION {id:$p, plane:'canon', name:'Barovia'}) "
            "CREATE (:Entity:NPC {id:$n, plane:'canon', name:'Strahd'})",
            {"slug": SLUG, "book": PREFIX, "p": PLACE, "n": NPC},
        ).consume()
        yield session
        clean(session)


def _map(table) -> str:
    """A map with one hidden pin on it, which is the state every visibility
    test below starts from."""
    stored = table.execute_write(lambda tx: assets.store_upload(
        tx, sha256="pytesttable", media_type="image/png", campaign=SLUG,
        uploaded_by="dm", created_at="2026-09-02T00:00:00Z"))
    made = client.post("/api/table/map", json={
        "campaign": SLUG, "name": "Barovia", "place": PLACE,
        "asset": stored["id"]})
    assert made.status_code == 200, made.text
    map_id = made.json()["id"]
    pinned = client.post("/api/table/map/pin", json={
        "campaign": SLUG, "map": map_id, "entity": NPC, "x": 0.5, "y": 0.5})
    assert pinned.status_code == 200, pinned.text
    return map_id


class TestSeats:
    def test_a_reader_can_be_seated(self, table):
        got = client.post("/api/table/seat", json={
            "campaign": SLUG, "reader": "ana", "role": "player"})
        assert got.status_code == 200 and got.json()["role"] == "player"

    def test_a_chair_that_is_not_a_chair_is_refused(self, table):
        got = client.post("/api/table/seat", json={
            "campaign": SLUG, "reader": "ana", "role": "gm"})
        assert got.status_code == 400

    def test_a_typo_in_a_slug_does_not_conjure_a_table(self, table):
        """`roles.seat` MATCHes the campaign rather than MERGEing it, the same
        ruling `ownership.claim` makes."""
        got = client.post("/api/table/seat", json={
            "campaign": f"{PREFIX}-typo", "reader": "ana", "role": "player"})
        assert got.status_code == 404

    def test_the_seats_are_listed(self, table):
        client.post("/api/table/seat", json={
            "campaign": SLUG, "reader": "ana", "role": "player"})
        found = client.get("/api/table/seats", params={"campaign": SLUG}).json()
        assert [s["reader"] for s in found["seats"]] == ["ana"]

    def test_a_seat_can_be_taken_away(self, table):
        client.post("/api/table/seat", json={
            "campaign": SLUG, "reader": "ana", "role": "player"})
        got = client.request("DELETE", "/api/table/seat",
                             params={"campaign": SLUG, "reader": "ana"})
        assert got.json()["removed"] == 1


class TestSessions:
    def test_opening_one_numbers_it_from_what_exists(self, table):
        first = client.post("/api/table/session", json={"campaign": SLUG}).json()
        second = client.post("/api/table/session", json={"campaign": SLUG}).json()
        assert (first["number"], second["number"]) == (1, 2)

    def test_a_session_of_no_table_is_a_404(self, table):
        got = client.post("/api/table/session",
                          json={"campaign": f"{PREFIX}-nope"})
        assert got.status_code == 404

    def test_planned_and_covered_are_separate_claims(self, table):
        """The diff is the reason sessions exist as nodes, and it is computed
        rather than stored."""
        table.run(
            "CREATE (:Section {id:$a, heading:'One'}) "
            "CREATE (:Section {id:$b, heading:'Two'})",
            {"a": f"{PREFIX}:sec-a", "b": f"{PREFIX}:sec-b"}).consume()
        session = client.post("/api/table/session",
                              json={"campaign": SLUG}).json()
        client.post("/api/table/session/plan", json={
            "campaign": SLUG, "session": session["id"],
            "section": f"{PREFIX}:sec-a"})
        client.post("/api/table/session/cover", json={
            "campaign": SLUG, "session": session["id"],
            "section": f"{PREFIX}:sec-b"})
        diff = client.get("/api/table/session/diff", params={
            "campaign": SLUG, "session_id": session["id"]}).json()
        assert [m["heading"] for m in diff["missed"]] == ["One"]
        assert [u["heading"] for u in diff["unplanned"]] == ["Two"]


class TestTheAudienceComesFromTheSeat:
    """The client never asserts which view it gets."""

    def test_an_unidentified_reader_is_the_dm(self, table):
        """`ACCESS_TOKENS` unset is the documented local case: one person at
        the machine, and they are running the game."""
        map_id = _map(table)
        got = client.get("/api/table/map/pins", params={
            "campaign": SLUG, "map_id": map_id}).json()
        assert got["as_player"] is False
        assert [p["name"] for p in got["pins"]] == ["Strahd"]

    def test_preview_narrows_the_dm_to_what_the_table_sees(self, table):
        """A DM checking before sharing a screen. The flag only ever narrows --
        there is no flag that widens."""
        map_id = _map(table)
        got = client.get("/api/table/map/pins", params={
            "campaign": SLUG, "map_id": map_id, "preview": True}).json()
        assert got["as_player"] is True and got["pins"] == []

    def test_a_revealed_pin_survives_the_preview(self, table):
        map_id = _map(table)
        client.post("/api/table/map/reveal", json={
            "campaign": SLUG, "map": map_id, "entity": NPC,
            "as_name": "the coachman"})
        got = client.get("/api/table/map/pins", params={
            "campaign": SLUG, "map_id": map_id, "preview": True}).json()
        assert [p["name"] for p in got["pins"]] == ["the coachman"]
        # THE TRUE NAME DOES NOT TRAVEL. Not in a field the client is trusted
        # to ignore -- not in the payload at all.
        assert "Strahd" not in str(got["pins"])


class TestPins:
    def test_a_pixel_coordinate_is_refused_at_the_boundary(self, table):
        """The API says 400 rather than storing a pin off the edge of the map
        where no click can reach it."""
        map_id = _map(table)
        got = client.post("/api/table/map/pin", json={
            "campaign": SLUG, "map": map_id, "entity": NPC,
            "x": 812.0, "y": 4.0})
        assert got.status_code == 400

    def test_revealing_a_pin_that_is_not_there_is_a_404(self, table):
        map_id = _map(table)
        got = client.post("/api/table/map/reveal", json={
            "campaign": SLUG, "map": map_id, "entity": PLACE})
        assert got.status_code == 404

    def test_a_map_of_a_person_is_refused(self, table):
        stored = table.execute_write(lambda tx: assets.store_upload(
            tx, sha256="pytesttable2", media_type="image/png", campaign=SLUG,
            uploaded_by="dm", created_at="2026-09-02T00:00:00Z"))
        got = client.post("/api/table/map", json={
            "campaign": SLUG, "name": "Strahd", "place": NPC,
            "asset": stored["id"]})
        assert got.status_code == 400


class TestPictures:
    """`origin` is `plane` for pixels, and the route cannot name it."""

    def _upload(self, payload=b"\x89PNG\r\n\x1a\nfake", media="image/png"):
        return client.post(
            "/api/table/asset/upload", params={"campaign": SLUG},
            files={"file": ("portrait.png", io.BytesIO(payload), media)})

    def test_an_upload_can_only_ever_be_recorded_as_uploaded(self, table):
        got = self._upload()
        assert got.status_code == 200
        assert got.json()["origin"] == assets.UPLOADED

    def test_a_type_the_store_does_not_keep_is_refused(self, table):
        got = self._upload(b"#!/bin/sh\necho hi\n", "application/x-sh")
        assert got.status_code == 415

    def test_an_empty_file_is_not_a_picture(self, table):
        assert self._upload(b"").status_code == 400

    def test_the_same_picture_twice_is_one_asset(self, table):
        """Content-addressed, so a DM re-uploading the same portrait does not
        double the store."""
        first, second = self._upload().json(), self._upload().json()
        assert first["id"] == second["id"]

    def test_the_bytes_come_back(self, table):
        stored = self._upload().json()
        got = client.get(f"/api/table/asset/{stored['id']}")
        assert got.status_code == 200 and got.content.startswith(b"\x89PNG")

    def test_an_asset_id_carrying_a_path_reaches_nothing(self, table):
        """The id is a lookup key and never a path segment: the file is chosen
        by the hash the GRAPH holds."""
        got = client.get("/api/table/asset/..%2F..%2Fetc%2Fpasswd")
        assert got.status_code == 404

    def test_a_portrait_carries_where_it_came_from(self, table):
        stored = self._upload().json()
        client.post("/api/table/portray", json={
            "campaign": SLUG, "entity": NPC, "asset": stored["id"]})
        found = client.get("/api/table/portraits", params={
            "entity_id": NPC, "campaign": SLUG}).json()["portraits"]
        assert [p["caption"] for p in found] == [assets.CAPTION[assets.UPLOADED]]


class TestSearch:
    """A name belongs to the adventure that says it."""

    def test_it_finds_by_name(self, table):
        found = client.get("/api/table/search", params={
            "campaign": SLUG, "q": "stra"}).json()["found"]
        assert [f["name"] for f in found] == ["Strahd"]

    def test_a_prefix_match_comes_first(self, table):
        table.run(
            "CREATE (:Entity:NPC {id:$i, plane:'canon', name:'Ismark Straw'})",
            {"i": f"{PREFIX}:ismark"}).consume()
        found = client.get("/api/table/search", params={
            "campaign": SLUG, "q": "stra"}).json()["found"]
        assert found[0]["name"] == "Strahd"

    def test_it_can_be_narrowed_to_a_kind(self, table):
        """Pinning wants places; portraying wants people."""
        found = client.get("/api/table/search", params={
            "campaign": SLUG, "q": "a", "label": "LOCATION"}).json()["found"]
        assert [f["name"] for f in found] == ["Barovia"]

    def test_an_empty_query_returns_nothing_rather_than_everything(self, table):
        found = client.get("/api/table/search", params={
            "campaign": SLUG, "q": "  "}).json()["found"]
        assert found == []

    def test_the_cap_cannot_be_lifted(self, table):
        got = client.get("/api/table/search", params={
            "campaign": SLUG, "q": "a", "limit": 5000})
        assert got.status_code == 200 and len(got.json()["found"]) <= 50


class TestTranscripts:
    """The least reliable prose in the system, on the tightest write path."""

    LINES = "Ana: Strahd is waiting for us.\nBen: Then we ride at dawn.\n"

    def _session(self) -> str:
        return client.post("/api/table/session", json={"campaign": SLUG}).json()["id"]

    def test_it_stores_what_was_said(self, table):
        got = client.post("/api/table/session/transcript", json={
            "campaign": SLUG, "session": self._session(), "content": self.LINES})
        assert got.status_code == 200
        assert got.json()["sections"] == 1 and got.json()["turns"] == 2

    def test_a_name_the_graph_knows_becomes_a_mention(self, table):
        got = client.post("/api/table/session/transcript", json={
            "campaign": SLUG, "session": self._session(), "content": self.LINES})
        assert got.json()["mentions"] == 1

    def test_it_mints_no_entity(self, table):
        before = table.run("MATCH (e:Entity) RETURN count(e) AS n").single()["n"]
        client.post("/api/table/session/transcript", json={
            "campaign": SLUG, "session": self._session(),
            "content": "Ana: Then Gorbo the Unmentioned appeared.\n"})
        after = table.run("MATCH (e:Entity) RETURN count(e) AS n").single()["n"]
        assert after == before

    def test_an_empty_file_says_so(self, table):
        got = client.post("/api/table/session/transcript", json={
            "campaign": SLUG, "session": self._session(), "content": "   "})
        assert got.status_code == 400

    def test_a_session_that_is_not_this_table_s_is_a_404(self, table):
        got = client.post("/api/table/session/transcript", json={
            "campaign": SLUG, "session": f"hb:{SLUG}:session-99",
            "content": self.LINES})
        assert got.status_code == 404

    def test_the_touched_list_writes_nothing(self, table):
        session = self._session()
        client.post("/api/table/session/transcript", json={
            "campaign": SLUG, "session": session, "content": self.LINES})
        got = client.get("/api/table/session/touched", params={
            "campaign": SLUG, "session_id": session})
        assert got.status_code == 200
        covered = table.run(
            "MATCH (:Session {id:$s})-[r:COVERED]->() RETURN count(r) AS n",
            {"s": session}).single()["n"]
        assert covered == 0


class TestInventory:
    ITEM = f"{PREFIX}:tome"

    def _item(self, table):
        table.run("MERGE (:Entity:ITEM {id:$i, plane:'canon', name:'Tome'})",
                  {"i": self.ITEM}).consume()

    def test_giving_and_reading_back(self, table):
        self._item(table)
        given = client.post("/api/table/inventory/give", json={
            "campaign": SLUG, "item": self.ITEM, "holder": NPC,
            "at_session": "1"})
        assert given.status_code == 200
        held = client.get("/api/table/inventory", params={
            "campaign": SLUG, "holder": NPC}).json()["held"]
        assert [h["name"] for h in held] == ["Tome"]

    def test_the_ledger_reads_by_holder(self, table):
        self._item(table)
        client.post("/api/table/inventory/give", json={
            "campaign": SLUG, "item": self.ITEM, "holder": NPC})
        found = client.get("/api/table/inventory",
                           params={"campaign": SLUG}).json()["held"]
        assert [(f["holder"], f["name"]) for f in found] == [("Strahd", "Tome")]

    def test_handing_over_leaves_one_open_holder(self, table):
        self._item(table)
        for holder in (NPC, PLACE):
            client.post("/api/table/inventory/give", json={
                "campaign": SLUG, "item": self.ITEM, "holder": holder})
        found = client.get("/api/table/inventory",
                           params={"campaign": SLUG}).json()["held"]
        assert len(found) == 1

    def test_the_history_survives_the_handover(self, table):
        self._item(table)
        for holder, at in ((NPC, "1"), (PLACE, "3")):
            client.post("/api/table/inventory/give", json={
                "campaign": SLUG, "item": self.ITEM, "holder": holder,
                "at_session": at})
        found = client.get("/api/table/inventory/provenance", params={
            "campaign": SLUG, "item": self.ITEM}).json()["held_by"]
        assert [f["holder"] for f in found] == ["Strahd", "Barovia"]

    def test_an_item_nobody_has_is_a_404(self, table):
        got = client.post("/api/table/inventory/give", json={
            "campaign": SLUG, "item": f"{PREFIX}:missing", "holder": NPC})
        assert got.status_code == 404


class TestScheduling:
    def _sitting(self) -> str:
        return client.post("/api/table/sitting", json={
            "campaign": SLUG, "on": "2026-09-14"}).json()["id"]

    def test_an_evening_goes_on_the_table(self, table):
        assert self._sitting().endswith("sitting-2026-09-14")

    def test_silence_comes_back_as_its_own_number(self, table):
        """"Two said no" and "two have not answered" lead to opposite
        decisions."""
        client.post("/api/table/seat", json={
            "campaign": SLUG, "reader": "ana", "role": "player"})
        self._sitting()
        found = client.get("/api/table/sittings",
                           params={"campaign": SLUG}).json()["sittings"][0]
        assert found["unanswered"] == 1 and found["no"] == []

    def test_an_unidentified_reader_cannot_answer_for_anybody(self, table):
        """The open deployment identifies nobody, and "everyone is free" is not
        a safe thing to guess."""
        got = client.post("/api/table/sitting/answer", json={
            "campaign": SLUG, "sitting": self._sitting(), "answer": "yes"})
        assert got.status_code == 401

    def test_withdrawing_removes_it(self, table):
        got = client.request("DELETE", "/api/table/sitting", params={
            "campaign": SLUG, "sitting": self._sitting()})
        assert got.json()["withdrawn"] == 1

    def test_a_session_can_be_pinned_to_an_evening(self, table):
        session = client.post("/api/table/session",
                              json={"campaign": SLUG}).json()["id"]
        got = client.post("/api/table/sitting/held", json={
            "campaign": SLUG, "session": session, "sitting": self._sitting()})
        assert got.json()["held_on"] == "2026-09-14"


class TestSetup:
    NEW = f"{PREFIX}-fresh"

    def test_a_table_can_be_made_from_the_product(self, table):
        """`store.create` had one caller and it was a script."""
        made = client.post("/api/table/create", json={
            "campaign": self.NEW, "name": "A Fresh Table", "book": PREFIX})
        assert made.status_code == 200
        assert made.json()["name"] == "A Fresh Table"
        assert made.json()["books"] == [PREFIX]
        table.run("MATCH (c:Campaign {slug:$c}) DETACH DELETE c",
                  {"c": self.NEW}).consume()

    def test_a_table_with_no_slug_is_refused(self, table):
        assert client.post("/api/table/create",
                           json={"campaign": "  "}).status_code == 400

    def test_the_settings_read_back(self, table):
        found = client.get("/api/table/settings",
                           params={"campaign": SLUG}).json()
        assert found["slug"] == SLUG and found["books"] == [PREFIX]

    def test_a_table_that_is_not_there_is_a_404(self, table):
        assert client.get("/api/table/settings",
                          params={"campaign": f"{PREFIX}-no"}).status_code == 404

    def test_a_premise_is_prose_the_graph_reads(self, table):
        """It is a section, so it is scanned. A premise naming Strahd connects
        the table to Strahd through machinery that already exists."""
        client.post("/api/table/settings", json={
            "campaign": SLUG, "premise": "The party owes Strahd a debt."})
        found = table.run(
            "MATCH (m:Mention)-[:IN_SECTION]->(:Section {id:$id}) "
            "RETURN count(m) AS n",
            {"id": f"hb:{SLUG}:the-premise"}).single()["n"]
        assert found == 1

    def test_dropping_a_book_keeps_the_prose(self, table):
        client.post("/api/table/settings", json={
            "campaign": SLUG, "premise": "A debt, and a long road."})
        client.request("DELETE", "/api/table/settings/book",
                       params={"campaign": SLUG, "book": PREFIX})
        found = client.get("/api/table/settings",
                           params={"campaign": SLUG}).json()
        assert found["books"] == []
        assert found["premise"] == "A debt, and a long road."


class TestImaginedPortraits:
    """The card is the gate: a model proposes, a person looks, one step
    applies. Nothing reaches the store until the DM presses keep."""

    #: A one-pixel PNG, base64. Small enough to inline, real enough to decode.
    PIXEL = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
             "z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")

    def test_keeping_one_stamps_it_as_imagined(self, table):
        got = client.post("/api/table/portrait/keep", json={
            "campaign": SLUG, "entity_id": NPC, "prompt": "a weary man",
            "generator": "gpt-image-1", "image": self.PIXEL})
        assert got.status_code == 200
        assert got.json()["origin"] == assets.GENERATED

    def test_it_carries_the_caption_that_says_so(self, table):
        client.post("/api/table/portrait/keep", json={
            "campaign": SLUG, "entity_id": NPC, "prompt": "a weary man",
            "generator": "gpt-image-1", "image": self.PIXEL})
        found = client.get("/api/table/portraits", params={
            "entity_id": NPC, "campaign": SLUG}).json()["portraits"]
        assert [p["caption"] for p in found] == [
            assets.CAPTION[assets.GENERATED]]

    def test_a_picture_that_will_not_say_what_made_it_is_refused(self, table):
        """The eighth invariant catches these; the boundary refuses them."""
        got = client.post("/api/table/portrait/keep", json={
            "campaign": SLUG, "entity_id": NPC, "prompt": "x",
            "generator": "", "image": self.PIXEL})
        assert got.status_code == 400

    def test_something_that_is_not_an_image_is_refused(self, table):
        got = client.post("/api/table/portrait/keep", json={
            "campaign": SLUG, "entity_id": NPC, "prompt": "x",
            "generator": "gpt-image-1", "image": "not base64!!"})
        assert got.status_code == 400

    def test_an_empty_draft_is_not_a_picture(self, table):
        got = client.post("/api/table/portrait/keep", json={
            "campaign": SLUG, "entity_id": NPC, "prompt": "x",
            "generator": "gpt-image-1", "image": ""})
        assert got.status_code == 400

    def test_a_draft_for_nobody_is_a_404(self, table):
        """Checked before any money is spent on a model call."""
        got = client.post("/api/table/portrait/draft", json={
            "campaign": SLUG, "entity_id": f"{PREFIX}:nobody"})
        assert got.status_code == 404
