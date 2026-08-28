"""Shared fixtures. Neo4j-backed tests run against their OWN database.

THE SUITE USED TO WRITE TO THE DEVELOPMENT ONE, beside a real table's
campaign. Its fixtures clean up by hand-written id prefix -- `hb:<slug>:`,
`pytest:` -- and two of them got it wrong: one deleted a campaign by prefix
while its mentions are keyed on `campaign`, another created a mention with no
id at all for a prefix delete to find. 573 orphaned nodes accumulated next to
material nobody can regenerate, and the only reason it was noticed is that a
graph view drew them.

Prefix discipline is the wrong layer to solve that at. Every fixture has to get
it right forever, and the cost of one getting it wrong is the DM's campaign.
This points the whole suite somewhere else instead, so a wrong prefix destroys
a throwaway.

A SECOND INSTANCE RATHER THAN A SECOND DATABASE, because this is Neo4j
Community and multi-database is an Enterprise feature. `docker compose up -d
neo4j-test` starts it on 7688.

SET BEFORE ANY BACKEND IMPORT. `settings` is a module-level singleton that
reads the environment once, so the override has to happen above the imports
rather than in a fixture -- which is why this file has a statement before its
imports and a lint suppression to allow it.
"""

import os

#: The test instance, unless the environment already names one. Overridable so
#: CI can point somewhere else without editing this file.
os.environ.setdefault("NEO4J_URI", "bolt://localhost:7688")

import pytest  # noqa: E402

from backend.core.config import settings  # noqa: E402
from backend.core.database import neo4j_session  # noqa: E402

TEST_ID_PREFIX = "pytest:"

#: What a database has to NOT contain for this suite to write to it. A campaign
#: that is not a test's is somebody's game.
_DEV_URI = "bolt://localhost:7687"


@pytest.fixture(scope="session", autouse=True)
def _refuse_to_run_against_real_material():
    """Stop the suite before it writes, if it is pointed somewhere with a game in it.

    THE BELT TO THE COMPOSE FILE'S BRACES. Pointing the suite at a test
    instance is configuration and configuration drifts -- a stale `.env`, a
    shell that exports `NEO4J_URI`, a CI runner with its own idea. This checks
    the thing that actually matters at the moment it matters: whether the
    database about to be written to holds a campaign nobody can regenerate.

    Names what it found and how to fix it, because a refusal a reader cannot
    act on is just a broken suite.
    """
    try:
        with neo4j_session() as session:
            live = [
                row["slug"]
                for row in session.run(
                    "MATCH (c:Campaign) RETURN c.slug AS slug ORDER BY c.slug"
                )
                if row["slug"] and not row["slug"].startswith("pytest")
            ]
    except Exception:
        # No database at all is the Neo4j-marked tests' own problem to report;
        # this guard has nothing to say about it.
        return
    if live:
        pytest.exit(
            f"refusing to run: {settings.neo4j_uri} holds real campaigns "
            f"({', '.join(live)}). The suite writes and deletes by id prefix, and "
            "one wrong prefix takes a table's material with it.\n"
            "  Start the test instance:  docker compose up -d neo4j-test\n"
            "  Or point elsewhere:       NEO4J_URI=bolt://host:port uv run pytest",
            returncode=1,
        )


def pytest_collection_modifyitems(config, items):
    """Skip the corpus tests when there is no corpus to read.

    THEY WERE PASSING BY ACCIDENT. The suite ran against the development
    database, so tests named `TestTheRealBook` and `TestTheLabelsPointAtReal
    Sections` found a real book and real sections without ever saying they
    needed one. Pointed at an empty instance, twenty-six of them failed on
    `assert count > 0` -- which is not a regression, it is the dependency
    becoming visible.

    A SKIP RATHER THAN A FIXTURE THAT SEEDS ONE. What these assert is that the
    INGESTED book says what it says: Strahd named twice in one section, two
    corrected questions no longer pointing at dream pastries. A fixture could
    only seed a fake book, and then they would be testing the fixture.

    They only ever read, so pointing them at a populated database is safe --
    which is what makes the skip the right shape rather than a loss.
    """
    if not any(item.get_closest_marker("corpus") for item in items):
        return
    try:
        with neo4j_session() as session:
            loaded = session.run(
                "MATCH (s:Section {plane:'canon'}) RETURN count(s) AS n"
            ).single()["n"]
    except Exception:
        loaded = 0
    if loaded:
        return
    skip = pytest.mark.skip(
        reason=f"no canon in {settings.neo4j_uri}; these read an ingested book"
    )
    for item in items:
        if item.get_closest_marker("corpus"):
            item.add_marker(skip)


@pytest.fixture
def graph():
    """Yield a Neo4j session; delete every node this test created on teardown.

    Nodes are identified by an id starting with TEST_ID_PREFIX. That is still
    the rule, and it is no longer the only thing standing between a mistake and
    somebody's campaign.
    """
    with neo4j_session() as session:
        session.run(
            "MATCH (n:Entity) WHERE n.id STARTS WITH $p DETACH DELETE n",
            {"p": TEST_ID_PREFIX},
        )
        yield session
        session.run(
            "MATCH (n:Entity) WHERE n.id STARTS WITH $p DETACH DELETE n",
            {"p": TEST_ID_PREFIX},
        )
