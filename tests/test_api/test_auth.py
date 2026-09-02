"""The gate, shown holding for every route rather than for one.

WHAT IS BEHIND IT: 1,378 canon sections holding 1.6 million characters of
prose from two published books. A test that pokes one endpoint and finds a 401
proves that endpoint is covered and says nothing about the twenty beside it,
which is exactly the shape of mistake that leaves one route open. So the
central test here enumerates the app's own routing table and asserts every
`/api` path is refused -- a route added later is covered the day it is added,
or this fails.
"""

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from starlette.routing import WebSocketRoute

from backend.api import auth
from backend.api.main import app
from backend.core.config import settings

ALICE = "dm-alice-token-for-tests"
BOB = "dm-bob-token-for-tests"


@pytest.fixture
def gated(monkeypatch):
    """Two readers configured, as a real deployment has."""
    monkeypatch.setattr(
        settings,
        "access_tokens",
        f"alice:{auth.fingerprint(ALICE)},bob:{auth.fingerprint(BOB)}",
    )
    return TestClient(app)


@pytest.fixture
def open_(monkeypatch):
    """No tokens configured -- local development, and the test suite's own
    default. Every other test in the repo depends on this staying open."""
    monkeypatch.setattr(settings, "access_tokens", "")
    return TestClient(app)


def api_paths() -> list[tuple[str, str]]:
    """Every `/api` HTTP route the app serves, read off the app itself.

    FROM `openapi()`, which is the app's own public description of its
    surface, so a router added later is covered the day it is added. Walking
    `app.routes` looked more direct and was wrong: this FastAPI wraps each
    included router in an opaque object whose `path` is `None`, so the sweep
    silently enumerated nothing and passed -- caught only because
    `test_there_are_routes_to_check` sits below it.

    WEBSOCKETS ARE NOT IN THE DOCUMENT and are tested by name instead, in
    `TestTheWebsocketIsClosed`. Discovering them meant reassembling prefixes
    through those same opaque wrappers, which is a worse thing for this test to
    depend on than one hardcoded path with a test that proves it still exists.
    """
    found = []
    for path, operations in app.openapi().get("paths", {}).items():
        if not path.startswith("/api"):
            continue
        for method in operations:
            if method.upper() in ("GET", "POST", "PUT", "DELETE", "PATCH"):
                # One verb per path is enough; the gate never looks at it.
                found.append((method.upper(), path))
                break
    return found


#: The one WebSocket the app serves. Spelled out because the OpenAPI document
#: does not describe it; `test_the_websocket_still_exists` fails if it moves.
WEBSOCKET_PATH = "/api/chat/ws/{session_id}"


class TestEveryApiRouteIsGated:
    """The property the deployment rests on, checked exhaustively."""

    def test_there_are_routes_to_check(self):
        """A guard on the guard: if `api_paths` silently returned nothing, the
        sweep below would pass by testing zero routes and read as green."""
        assert len(api_paths()) > 20, api_paths()

    def test_no_api_route_answers_without_a_token(self, gated):
        """NOT ONE 401, ALL OF THEM. Placeholders are filled with a value that
        matches nothing, so a 404 would mean the route was reached -- which is
        itself a failure, since the gate should refuse before routing."""
        leaked = []
        for method, path in api_paths():
            url = path.replace("{", "").replace("}", "")
            response = gated.request(method, url)
            if response.status_code != 401:
                leaked.append(f"{method} {path} -> {response.status_code}")
        assert not leaked, "reachable without a token:\n" + "\n".join(leaked)

    def test_a_bad_token_is_refused_too(self, gated):
        """The failure that matters is a WRONG credential, not a missing one:
        a gate that only checks for the header's presence reads as working."""
        for method, path in api_paths():
            url = path.replace("{", "").replace("}", "")
            response = gated.request(
                method, url, headers={"Authorization": "Bearer dm-not-one-of-ours"}
            )
            assert response.status_code == 401, f"{method} {path}"


class TestTheGateLetsTheRightPeopleThrough:
    def test_a_good_token_is_not_401(self, gated):
        """PAST THE GATE, not necessarily a 200 -- these endpoints want a graph
        this test has no business touching. Anything other than 401 means the
        credential was accepted, which is the only thing under test here."""
        response = gated.get("/api/lab/config", headers={"Authorization": f"Bearer {ALICE}"})
        assert response.status_code != 401

    def test_health_answers_without_one(self, gated):
        """A platform must be able to see the process is up without holding a
        credential, and `/health` returns no book text."""
        assert gated.get("/health").status_code == 200
        assert gated.get("/").status_code == 200

    def test_preflight_is_not_gated(self, gated):
        """The browser sends `OPTIONS` without the header by design. Gating it
        would fail every cross-origin call before the real one was sent."""
        response = gated.options(
            "/api/lab/config",
            headers={
                "Origin": "https://example.vercel.app",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert response.status_code != 401

    def test_a_401_still_carries_cors_headers(self, gated):
        """Otherwise the browser reports an opaque CORS failure and the login
        screen cannot tell a bad token from the API being down."""
        response = gated.get(
            "/api/lab/config", headers={"Origin": "https://example.vercel.app"}
        )
        assert response.status_code == 401
        assert "access-control-allow-origin" in response.headers


class TestOpenWhenNothingIsConfigured:
    """What keeps local development and the other 2,281 tests working."""

    def test_no_tokens_means_no_gate(self, open_):
        assert open_.get("/api/lab/config").status_code != 401


class TestTokens:
    def test_a_minted_token_identifies_its_owner(self, monkeypatch):
        token = auth.mint_token()
        monkeypatch.setattr(settings, "access_tokens", f"carol:{auth.fingerprint(token)}")
        assert auth.identify(token) == "carol"

    def test_two_mints_differ(self):
        assert auth.mint_token() != auth.mint_token()

    def test_the_plaintext_is_not_in_the_configured_value(self, monkeypatch):
        """The point of hashing: a leaked environment is not a set of working
        credentials."""
        token = auth.mint_token()
        configured = f"carol:{auth.fingerprint(token)}"
        assert token not in configured

    def test_an_unknown_token_identifies_nobody(self, monkeypatch):
        monkeypatch.setattr(settings, "access_tokens", f"carol:{auth.fingerprint('x')}")
        assert auth.identify("y") == ""

    def test_an_empty_token_identifies_nobody(self, monkeypatch):
        """Guarded explicitly because `fingerprint("")` is a real hash, and an
        entry accidentally configured from an empty string would match every
        caller who sent no credential at all."""
        monkeypatch.setattr(settings, "access_tokens", f"carol:{auth.fingerprint('')}")
        assert auth.identify("") == ""

    def test_malformed_entries_are_skipped_not_crashed(self, monkeypatch):
        """A stray comma in the environment must not take the API down, and
        must not accidentally open it either."""
        monkeypatch.setattr(
            settings, "access_tokens", f",,junk,carol:{auth.fingerprint('ok')},"
        )
        assert auth.readers() and auth.identify("ok") == "carol"
        assert auth.identify("junk") == ""


class TestTheWebsocketIsGatedToo:
    """The failure mode worth testing is a WebSocket quietly bypassing a gate
    written for HTTP -- which is why the gate is raw ASGI, where both scopes
    look the same.

    A VALID TOKEN PASSES, and this class first asserted it did not. That was
    wrong about the server: what a browser cannot do is SET the header on a
    handshake, so the route is unreachable from `web/` while gated. That is a
    client limitation, not a refusal, and nothing in `web/` opens it anyway."""

    def test_the_websocket_still_exists(self):
        """If the route moves, the gate test below silently tests nothing."""
        found = []

        def walk(routes):
            for route in routes or []:
                if isinstance(route, WebSocketRoute):
                    found.append(route.path)
                inner = getattr(route, "original_router", None)
                if inner is not None:
                    walk(getattr(inner, "routes", []))

        walk(app.routes)
        assert any(WEBSOCKET_PATH.endswith(p) for p in found), found

    def test_it_refuses_a_connection_without_a_token(self, gated):
        with pytest.raises(Exception):
            with gated.websocket_connect(WEBSOCKET_PATH.replace("{session_id}", "s1")):
                pass

    def test_it_accepts_a_connection_carrying_one(self, gated):
        """Proving the refusal above is the GATE and not the route being
        broken -- without this, a websocket that never connected for unrelated
        reasons would read as a working gate."""
        with gated.websocket_connect(
            WEBSOCKET_PATH.replace("{session_id}", "s1"),
            headers={"Authorization": f"Bearer {ALICE}"},
        ) as ws:
            assert ws is not None


class TestAMalformedConfigDoesNotOpenTheGate:
    """The one failure the open-when-unset rule does not cover.

    `require_reader` is open when NOTHING is configured, and the argument is
    that a deployment which forgets tokens is one nobody can reach -- the
    frontend would have no token to send either. That does not hold for a
    MALFORMED value: a quoting mishap leaves `ACCESS_TOKENS` set, every entry
    dropped, the gate open, and the frontend's stored token still working, so
    nobody notices two published books being served to anyone at all.
    """

    def _set(self, monkeypatch, value):
        from backend.core.config import settings
        monkeypatch.setattr(settings, "access_tokens", value)

    def test_unset_is_still_open(self, monkeypatch):
        self._set(monkeypatch, "")
        assert auth.readers() == {}

    def test_a_well_formed_value_parses(self, monkeypatch):
        self._set(monkeypatch, "alice:" + auth.fingerprint("t"))
        assert list(auth.readers().values()) == ["alice"]

    def test_a_value_that_parses_to_nothing_refuses(self, monkeypatch):
        self._set(monkeypatch, "alice=abc;bob=def")
        with pytest.raises(auth.MisconfiguredTokens):
            auth.readers()

    def test_one_good_entry_is_enough(self, monkeypatch):
        """Refusing on ANY unparseable entry would turn a typo in the second
        name into an outage; the rule is that nothing at all parses."""
        self._set(monkeypatch, "alice:" + auth.fingerprint("t") + ",garbage")
        assert list(auth.readers().values()) == ["alice"]


class TestTheGateSaysWhoItLetThrough:
    """`identify` returns WHO and the middleware discarded it, so the
    per-person-token design's payoff -- "a leaked token says whose it was" --
    never reached a request."""

    def test_the_name_is_on_the_scope(self, gated):
        found = {}

        @app.get("/api/_pytest_reader")
        def _who(request: Request) -> dict:
            return {"reader": auth.reader_of(request)}

        try:
            body = gated.get(
                "/api/_pytest_reader",
                headers={"Authorization": f"Bearer {ALICE}"},
            ).json()
            found.update(body)
        finally:
            app.router.routes = [
                r for r in app.router.routes
                if getattr(r, "path", "") != "/api/_pytest_reader"
            ]
        assert found["reader"] == "alice"

    def test_reader_of_is_empty_when_nobody_was_identified(self):
        class _Req:
            scope: dict = {}

        assert auth.reader_of(_Req()) == ""
