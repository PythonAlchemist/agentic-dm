"""
Configuration file for the Agentic DM system.
"""

import os
from pathlib import Path


# Load environment variables from .env file if it exists
def load_env():
    """Load environment variables from .env file."""
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        print(f"📁 Loading environment from {env_path}")
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key.strip()] = value.strip()


# Load environment variables
load_env()

# Base paths
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
INDICES_DIR = BASE_DIR / "indices"
FRONTEND_DIR = BASE_DIR / "frontend"

# PDF files
PDF_FILES = {
    "armyofthedamned": DATA_DIR / "armyofthedamned.pdf",
    "basic_rules": DATA_DIR / "DnD_BasicRules_2018.pdf",
    "srd": DATA_DIR / "SRD-OGL_V5.1.pdf",
}

# OpenAI RAG Configuration
OPENAI_RAG_CONFIG = {
    "model": os.getenv("OPENAI_MODEL", "gpt-3.5-turbo"),
    "embedding_model": "text-embedding-3-small",
    "embedding_dimension": 1536,
    "max_chunk_size": 1000,
    "chunk_overlap": 200,
    "default_top_k": 5,
    "max_context_length": 4000,
    "include_surrounding_chunks": True,
    "max_tokens": int(os.getenv("MAX_TOKENS", "500")),
    "temperature": float(os.getenv("TEMPERATURE", "0.3")),
}

# Content Type Detection Keywords
CONTENT_KEYWORDS = {
    "combat": ["initiative", "attack", "damage", "hp", "ac", "dc", "saving throw"],
    "npc": ["npc", "character", "speaks", "says", "responds", "personality"],
    "location": ["location", "area", "room", "chamber", "passage", "dungeon"],
    "quest": ["quest", "mission", "objective", "goal", "adventure"],
    "rules": ["rule", "mechanic", "ability", "spell", "feature"],
    "treasure": ["treasure", "loot", "item", "magic", "weapon", "armor"],
    "encounter": ["encounter", "battle", "fight", "conflict", "challenge"],
}


# Ensure directories exist
def ensure_directories():
    """Create necessary directories if they don't exist."""
    DATA_DIR.mkdir(exist_ok=True)
    INDICES_DIR.mkdir(exist_ok=True)
    FRONTEND_DIR.mkdir(exist_ok=True)


# Get PDF path by name
def get_pdf_path(name: str) -> Path:
    """Get the path to a PDF file by name."""
    if name not in PDF_FILES:
        raise ValueError(f"Unknown PDF: {name}. Available: {list(PDF_FILES.keys())}")

    pdf_path = PDF_FILES[name]
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    return pdf_path


# Get index path by PDF name
def get_index_path(pdf_name: str) -> Path:
    """Get the path to an index by PDF name."""
    return INDICES_DIR / pdf_name


# Get RAG configuration
def get_rag_config():
    """Get the OpenAI RAG configuration."""
    return OPENAI_RAG_CONFIG
