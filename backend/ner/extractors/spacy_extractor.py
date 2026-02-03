"""SpaCy-based entity extraction."""

import spacy
from spacy.language import Language

from backend.graph.schema import EntityType
from backend.ner.config import default_config
from backend.ner.models import ExtractedEntity, ExtractionSource


class SpacyExtractor:
    """Extract entities using SpaCy NER."""

    # Map SpaCy entity labels to our EntityType
    LABEL_MAP = {
        "PERSON": EntityType.NPC,  # Will be refined by context
        "GPE": EntityType.LOCATION,  # Geopolitical entity
        "LOC": EntityType.LOCATION,  # Non-GPE location
        "FAC": EntityType.LOCATION,  # Facility (buildings, etc.)
        "ORG": EntityType.FACTION,  # Organization
        "PRODUCT": EntityType.ITEM,  # Products (sometimes works for items)
        "EVENT": EntityType.EVENT,  # Named events
    }

    def __init__(self, model_name: str = None):
        """Initialize SpaCy with the specified model.

        Args:
            model_name: SpaCy model to load. Defaults to config value.
        """
        model = model_name or default_config.spacy_model
        self.nlp = self._load_model(model)
        self.confidence = default_config.spacy_confidence

    def _load_model(self, model_name: str) -> Language:
        """Load SpaCy model, downloading if necessary."""
        try:
            return spacy.load(model_name)
        except OSError:
            # Model not found, try to download it
            from spacy.cli import download

            download(model_name)
            return spacy.load(model_name)

    def extract(self, text: str) -> list[ExtractedEntity]:
        """Extract entities from text using SpaCy.

        Args:
            text: The text to process.

        Returns:
            List of extracted entities.
        """
        doc = self.nlp(text)
        entities = []

        for ent in doc.ents:
            if ent.label_ not in self.LABEL_MAP:
                continue

            entity_type = self.LABEL_MAP[ent.label_]

            # Clean up the text
            entity_text = ent.text.strip()
            if not entity_text:
                continue

            entities.append(
                ExtractedEntity(
                    text=entity_text,
                    normalized_name=self._normalize_name(entity_text),
                    entity_type=entity_type,
                    span=(ent.start_char, ent.end_char),
                    confidence=self.confidence,
                    source=ExtractionSource.SPACY,
                    metadata={
                        "spacy_label": ent.label_,
                        "spacy_label_description": spacy.explain(ent.label_) or "",
                    },
                )
            )

        return entities

    def _normalize_name(self, name: str) -> str:
        """Normalize an entity name.

        Args:
            name: The raw entity name.

        Returns:
            Normalized name with proper capitalization.
        """
        # Title case, but preserve certain patterns
        words = name.split()
        normalized = []

        for word in words:
            # Keep acronyms uppercase
            if word.isupper() and len(word) <= 4:
                normalized.append(word)
            # Keep words that start with lowercase (like "the")
            elif word[0].islower() and word.lower() in ("the", "of", "and", "or", "a", "an"):
                normalized.append(word.lower())
            else:
                normalized.append(word.capitalize())

        return " ".join(normalized)

    def extract_noun_chunks(self, text: str) -> list[str]:
        """Extract noun chunks that might be entity candidates.

        Useful for fuzzy matching against gazetteers.

        Args:
            text: The text to process.

        Returns:
            List of noun chunk strings.
        """
        doc = self.nlp(text)
        chunks = []

        for chunk in doc.noun_chunks:
            chunk_text = chunk.text.strip()
            if len(chunk_text) > 2:  # Filter out very short chunks
                chunks.append(chunk_text)

        return chunks
