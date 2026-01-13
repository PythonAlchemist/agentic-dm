"""Database connection management for Neo4j and ChromaDB."""

from contextlib import contextmanager
from functools import lru_cache
from typing import Generator

import chromadb
from chromadb.config import Settings as ChromaSettings
from neo4j import GraphDatabase, Driver

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
    """Context manager for Neo4j sessions."""
    driver = get_neo4j_driver()
    session = driver.session()
    try:
        yield session
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
