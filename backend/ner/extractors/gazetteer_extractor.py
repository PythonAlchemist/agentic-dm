"""Gazetteer-based entity extraction."""

from typing import Optional

from backend.ner.config import default_config
from backend.ner.gazetteers.loader import GazetteerLoader
from backend.ner.gazetteers.matcher import GazetteerMatcher, GazetteerMatch
from backend.ner.models import ExtractedEntity, ExtractionSource, GazetteerEntry


class GazetteerExtractor:
    """Extract entities by matching against gazetteers."""

    def __init__(
        self,
        loader: Optional[GazetteerLoader] = None,
        fuzzy_threshold: int = None,
    ):
        """Initialize the gazetteer extractor.

        Args:
            loader: GazetteerLoader instance. If None, creates default.
            fuzzy_threshold: Minimum fuzzy match score (0-100).
        """
        self.loader = loader or GazetteerLoader()
        self.matcher = GazetteerMatcher(
            fuzzy_threshold=fuzzy_threshold or default_config.fuzzy_threshold
        )
        self._loaded = False

    def load_gazetteers(self, entries: Optional[list[GazetteerEntry]] = None) -> int:
        """Load gazetteers into the matcher.

        Args:
            entries: List of gazetteer entries. If None, loads from files.

        Returns:
            Number of entries loaded.
        """
        if entries is None:
            entries = self.loader.load_all()

        self.matcher.load_entries(entries)
        self._loaded = True
        return len(entries)

    def extract(self, text: str) -> list[ExtractedEntity]:
        """Extract entities from text using gazetteer matching.

        Args:
            text: The text to process.

        Returns:
            List of extracted entities.
        """
        if not self._loaded:
            self.load_gazetteers()

        matches = self.matcher.find_all(text)
        entities = []

        for match in matches:
            entity = self._match_to_entity(match)
            entities.append(entity)

        return entities

    def extract_with_fuzzy(
        self,
        text: str,
        candidates: list[str],
    ) -> list[ExtractedEntity]:
        """Extract entities using fuzzy matching on candidate strings.

        Use this when you have noun chunks or other candidates from SpaCy
        that might match gazetteer entries.

        Args:
            text: Original text (for reference).
            candidates: List of candidate strings to fuzzy match.

        Returns:
            List of extracted entities.
        """
        if not self._loaded:
            self.load_gazetteers()

        entities = []
        seen_ids = set()

        for candidate in candidates:
            match = self.matcher.find_fuzzy(candidate)
            if match and match.entry.id not in seen_ids:
                entity = self._match_to_entity(match)
                entities.append(entity)
                seen_ids.add(match.entry.id)

        return entities

    def _match_to_entity(self, match: GazetteerMatch) -> ExtractedEntity:
        """Convert a gazetteer match to an extracted entity.

        Args:
            match: The gazetteer match.

        Returns:
            Extracted entity.
        """
        return ExtractedEntity(
            text=match.matched_text,
            normalized_name=match.entry.name,
            entity_type=match.entry.entity_type,
            span=(match.start, match.end),
            confidence=match.confidence,
            source=ExtractionSource.GAZETTEER,
            gazetteer_id=match.entry.id,
            metadata={
                "match_type": match.match_type,
                "gazetteer_metadata": match.entry.metadata,
            },
        )

    def get_entry_by_id(self, entry_id: str) -> Optional[GazetteerEntry]:
        """Get a gazetteer entry by its ID.

        Args:
            entry_id: The entry ID.

        Returns:
            The gazetteer entry or None.
        """
        return self.matcher.get_entry(entry_id)
