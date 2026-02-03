"""NER (Named Entity Recognition) module for D&D campaign tracking.

This module provides entity extraction from D&D session transcripts:
- SpaCy-based NER for general entities (people, places, organizations)
- Gazetteer matching for D&D-specific entities (spells, monsters, items)
- LLM-based extraction for relationships and complex entities
- Entity resolution and graph linking
"""

from backend.ner.config import NERConfig, default_config
from backend.ner.models import (
    ExtractionResult,
    ExtractionSource,
    ExtractedEntity,
    ExtractedRelationship,
    GazetteerEntry,
)
from backend.ner.pipeline import NERPipeline

__all__ = [
    # Main pipeline
    "NERPipeline",
    # Configuration
    "NERConfig",
    "default_config",
    # Models
    "ExtractedEntity",
    "ExtractedRelationship",
    "ExtractionResult",
    "ExtractionSource",
    "GazetteerEntry",
]
