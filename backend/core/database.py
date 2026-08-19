"""Database connection management for Neo4j and ChromaDB."""

from contextlib import contextmanager
from functools import lru_cache
from typing import Generator

import chromadb
from chromadb.config import Settings as ChromaSettings
from neo4j import READ_ACCESS, Driver, GraphDatabase

from backend.core.config import settings


@lru_cache
def get_neo4j_driver() -> Driver:
    """Get cached Neo4j driver instance."""
    return GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )


@contextmanager
def neo4j_session() -> Generator:
    """Context manager for Neo4j sessions. FULL WRITE ACCESS.

    Everything that builds the graph uses this. Anything that merely reads it
    on behalf of a model should use `read_only_session` instead -- see there
    for why that is not simply a matter of discipline.
    """
    driver = get_neo4j_driver()
    session = driver.session()
    try:
        yield session
    finally:
        session.close()


class ReadOnlySession:
    """A session that can run a query and nothing else.

    `run` ONLY, and the omissions are the point. The underlying session is
    opened in read access mode, which Neo4j enforces SERVER-SIDE: a write
    inside it is rejected with `Neo.ClientError.Statement.AccessMode`, not
    quietly allowed. Verified against 5.26 Community rather than assumed --
    an earlier draft of the design doc asserted that read access mode "routes,
    it does not forbid", and that is wrong.

    BUT THE ACCESS MODE IS A DEFAULT, AND `execute_write` OVERRIDES IT. Probed
    on the live database: a `CREATE` inside `session.execute_read(...)` is
    blocked, a `CREATE` run directly on a read-mode session is blocked, and a
    `CREATE` inside `session.execute_write(...)` on that same read-mode session
    GOES THROUGH. So a correctly configured session handed to a caller is not a
    guarantee; it is a guarantee with a documented bypass one method call away.

    Hence a wrapper rather than a configured session. What cannot be reached
    cannot be called by a caller who has not read this docstring, or by a model
    composing a query, or by a refactor six months from now.

    Community edition is why this shape at all. Role-based access control --
    `CREATE USER ... GRANT MATCH` -- is an Enterprise feature, so a genuinely
    read-only DATABASE USER is not available and enforcement has to come from
    the session and the API surface together.
    """

    def __init__(self, session) -> None:
        self._session = session

    def run(self, query: str, parameters: dict | None = None):
        """Run a read query. A write raises rather than being silently dropped."""
        return self._session.run(query, parameters or {})


@contextmanager
def read_only_session() -> Generator[ReadOnlySession, None, None]:
    """A session that cannot write, for anything a model's query reaches.

    The first of the four invariants the conversational-subgraph design rests
    on. The other three -- `status` on every edge, `plane` always filtered, a
    row cap -- belong to the query runner above this, because they are about
    what a query must PROJECT rather than about what it may DO.
    """
    driver = get_neo4j_driver()
    session = driver.session(default_access_mode=READ_ACCESS)
    try:
        yield ReadOnlySession(session)
    finally:
        session.close()


@lru_cache
def get_chroma_client() -> chromadb.PersistentClient:
    """Get cached ChromaDB client instance."""
    return chromadb.PersistentClient(
        path=str(settings.chroma_dir),
        settings=ChromaSettings(
            anonymized_telemetry=False,
            allow_reset=True,
        ),
    )


def get_chroma_collection(name: str | None = None) -> chromadb.Collection:
    """Get or create a ChromaDB collection."""
    client = get_chroma_client()
    collection_name = name or settings.chroma_collection_name
    return client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )
