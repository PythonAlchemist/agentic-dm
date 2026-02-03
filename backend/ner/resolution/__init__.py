"""Entity resolution and graph linking."""

from backend.ner.resolution.resolver import EntityResolver
from backend.ner.resolution.linker import GraphLinker

__all__ = ["EntityResolver", "GraphLinker"]
