"""Application configuration using pydantic-settings."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Paths
    base_dir: Path = Path(__file__).parent.parent.parent
    data_dir: Path = base_dir / "data"
    pdf_dir: Path = data_dir / "pdfs"
    transcript_dir: Path = data_dir / "transcripts"
    audio_dir: Path = data_dir / "audio"
    #: Portraits and maps, keyed by content hash. Under , which is
    #: gitignored -- an uploaded map of somebody's homebrew dungeon is theirs,
    #: and the book's plates are the book's.
    asset_dir: Path = data_dir / "assets"
    canon_dir: Path = data_dir / "canon"
    # The harvested D&D Beyond markdown cache. Gitignored like everything under
    # `data/`: the text is copyrighted and must never be committed.
    ddb_dir: Path = data_dir / "ddb"

    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    openai_vision_model: str = "gpt-4o"
    embedding_dimensions: int = 1536

    # Neo4j
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "testpassword"


    # PDF Processing
    chunk_size: int = 1000  # tokens
    chunk_overlap: int = 200  # tokens

    # RAG
    retrieval_top_k: int = 5
    rerank_top_k: int = 3

    # Deepgram
    deepgram_api_key: str = ""

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8001
    debug: bool = False

    #: Who may read the graph. `"alice:<sha256>,bob:<sha256>"`, one entry per
    #: person, hashed -- `backend/api/auth.py` says why it is per-person and
    #: why the plaintext never lands here. EMPTY MEANS OPEN, which is what
    #: makes local development and the tests work unchanged; `main` says so
    #: loudly at startup rather than leaving it to be discovered.
    access_tokens: str = ""

    #: Origins the browser may call from, comma-separated. Empty means any,
    #: which was the old hardcoded behaviour and is right for local work.
    #: A deployment sets its one Vercel origin.
    allowed_origins: str = ""


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


settings = get_settings()
