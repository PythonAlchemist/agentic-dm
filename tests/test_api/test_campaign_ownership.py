"""Who may write to a table, and the sweep that keeps every write covered.

`ReaderGate` decides whether a request is served AT ALL, and every reader who
got through was equal: `campaign` is a field in the request body, so any
token-holder could `/edit` another table's prose, `/rescan` it, or
`DELETE /store-cluster` out of it. The gate was doing authorisation work it was
only built to do authentication for.
"""

import ast
from pathlib import Path

import pytest

from backend.campaign.ownership import may_write

#: EVERY ROUTER THAT WRITES TO A TABLE, swept as one.
#:
#: This was a single path, and the sweep it powered was the reason ownership is
#: enforced at all -- so a second router carrying seats, sessions, maps and
#: pictures had to arrive in this tuple on the day it was written, not the day
#: somebody remembered. That is the same argument the sweep makes about routes.
ROUTES: tuple[Path, ...] = (
    Path("backend/api/routes/homebrew.py"),
    Path("backend/api/routes/table.py"),
)

#: Routes that POST and write NOTHING. `plan-cluster` is the dry run whose
#: whole point is that it is pure -- the card calls it on every edit -- and
#: `draft-expansion` returns a proposal the DM has not stored yet. Guarding
#: them would refuse a reader a preview of their own material.
READ_ONLY_POSTS = frozenset({"plan_cluster_route", "draft_expansion"})


def _handlers() -> list[ast.FunctionDef]:
    """Every route function in the module, with its HTTP verbs."""
    found = []
    for path in ROUTES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            verbs = {
                d.func.attr
                for d in node.decorator_list
                if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
            }
            if verbs:
                found.append((node, verbs))
    return found


class TestEveryWriteRouteIsGuarded:
    """The same shape as the auth sweep, and for the same reason: a route added
    later must be covered the day it is added, not the day somebody remembers."""

    def test_there_are_routes_to_check(self):
        """Without this the sweep below passes by finding nothing -- which is
        exactly how the auth sweep once enumerated zero routes and went green."""
        assert len(_handlers()) > 10

    def test_each_mutating_route_calls_the_guard(self):
        missing = []
        for node, verbs in _handlers():
            if not (verbs & {"post", "delete", "put", "patch"}):
                continue
            if node.name in READ_ONLY_POSTS:
                continue
            calls = {
                n.func.id for n in ast.walk(node)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            }
            if "guard" not in calls:
                missing.append(node.name)
        assert not missing, f"write routes with no ownership check: {missing}"

    def test_the_read_only_exemptions_still_exist(self):
        """A name left in the allowlist after the route is gone would silently
        exempt the next function that takes it."""
        names = {node.name for node, _ in _handlers()}
        assert READ_ONLY_POSTS <= names


class TestTheRule:
    """Three ways to be allowed, each a real state rather than a hole."""

    def test_an_unowned_campaign_is_open(self):
        """They predate this, and refusing would lock a DM out of their own
        table."""
        assert may_write("", "alice")

    def test_an_unidentified_reader_is_allowed(self):
        """`ACCESS_TOKENS` unset is the documented local case: nobody is
        identified, so there is nobody to check."""
        assert may_write("alice", "")

    def test_the_owner_may_write(self):
        assert may_write("alice", "alice")

    def test_another_reader_may_not(self):
        assert not may_write("alice", "bob")

    def test_nobody_at_all_is_allowed(self):
        assert may_write("", "")

    @pytest.mark.parametrize("owner,reader", [("Alice", "alice"), ("alice ", "alice")])
    def test_the_name_is_compared_exactly(self, owner, reader):
        """`mint_token` refuses a name with a comma or a colon and nothing
        else, so two readers CAN differ only by case -- folding here would let
        one write as the other."""
        assert not may_write(owner, reader)


class TestTheGuardActuallyRefuses:
    """The sweep above proves the guard is CALLED. This proves it says no --
    without which the sweep would be checking that every route runs a function
    that does nothing."""

    PREFIX = "pytest-own"

    @pytest.fixture
    def table(self):
        from backend.core.database import neo4j_session

        slug = f"{self.PREFIX}-camp"
        with neo4j_session() as session:
            session.run("MATCH (c:Campaign {slug:$s}) DETACH DELETE c",
                        {"s": slug}).consume()
            session.run("CREATE (:Campaign {slug:$s, name:'T', plane:'campaign'})",
                        {"s": slug}).consume()
            yield slug
            session.run("MATCH (c:Campaign {slug:$s}) DETACH DELETE c",
                        {"s": slug}).consume()

    def _request(self, reader):
        class _Req:
            scope = {"reader": reader} if reader else {}
        return _Req()

    def test_a_foreign_reader_is_refused(self, table):
        from fastapi import HTTPException

        from backend.api.routes.homebrew import guard

        guard(self._request("alice"), table)          # alice claims it
        with pytest.raises(HTTPException) as raised:
            guard(self._request("bob"), table)
        assert raised.value.status_code == 403

    def test_the_owner_is_let_through(self, table):
        from backend.api.routes.homebrew import guard

        guard(self._request("alice"), table)
        assert guard(self._request("alice"), table) == "alice"

    def test_the_first_identified_writer_claims_it(self, table):
        """Protection arrives without a migration, and without a DM losing a
        table they made before any of this existed."""
        from backend.core.database import neo4j_session

        from backend.api.routes.homebrew import guard

        assert guard(self._request("alice"), table) == "alice"
        with neo4j_session() as session:
            owner = session.run("MATCH (c:Campaign {slug:$s}) RETURN c.owner AS o",
                                {"s": table}).single()["o"]
        assert owner == "alice"

    def test_an_open_deployment_claims_nothing(self, table):
        """With `ACCESS_TOKENS` unset nobody is identified, so there is nobody
        to record and nothing to check."""
        from backend.core.database import neo4j_session

        from backend.api.routes.homebrew import guard

        assert guard(self._request(""), table) == ""
        with neo4j_session() as session:
            owner = session.run("MATCH (c:Campaign {slug:$s}) RETURN c.owner AS o",
                                {"s": table}).single()["o"]
        assert not owner

    def test_a_campaign_that_does_not_exist_is_not_conjured(self, table):
        """Claiming is a MATCH, not a MERGE: a typo in a slug must not create an
        empty table owned by whoever made the typo."""
        from backend.core.database import neo4j_session

        from backend.api.routes.homebrew import guard

        guard(self._request("alice"), f"{self.PREFIX}-typo")
        with neo4j_session() as session:
            n = session.run("MATCH (c:Campaign {slug:$s}) RETURN count(c) AS n",
                            {"s": f"{self.PREFIX}-typo"}).single()["n"]
        assert n == 0
