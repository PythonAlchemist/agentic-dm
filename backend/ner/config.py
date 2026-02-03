"""NER-specific configuration."""

from pathlib import Path

from pydantic import BaseModel


class NERConfig(BaseModel):
    """NER pipeline configuration."""

    # Paths
    canonical_gazetteer_dir: Path = Path("data/gazetteers/canonical")
    campaign_gazetteer_dir: Path = Path("data/gazetteers/campaign")

    # SpaCy
    spacy_model: str = "en_core_web_sm"

    # Matching thresholds
    fuzzy_threshold: int = 85  # Minimum similarity score (0-100)
    confidence_threshold: float = 0.5  # Minimum confidence to include entity

    # Confidence values for different sources
    spacy_confidence: float = 0.6
    gazetteer_exact_confidence: float = 0.95
    gazetteer_fuzzy_confidence: float = 0.75
    llm_confidence: float = 0.8

    # LLM settings
    use_llm_extraction: bool = True
    llm_chunk_size: int = 2000  # Characters per LLM call

    # Performance
    batch_size: int = 10
    cache_ttl: int = 300  # Entity cache TTL in seconds

    # Pipeline stages
    use_spacy: bool = True
    use_gazetteer: bool = True
    link_to_graph: bool = True
    create_missing_entities: bool = False


# Default configuration
default_config = NERConfig()
