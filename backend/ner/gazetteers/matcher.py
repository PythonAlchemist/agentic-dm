"""Gazetteer matching with exact and fuzzy search."""

import re
from typing import Optional

import ahocorasick
from rapidfuzz import fuzz, process

from backend.graph.schema import EntityType
from backend.ner.config import default_config
from backend.ner.models import GazetteerEntry


class GazetteerMatch:
    """A match from the gazetteer."""

    def __init__(
        self,
        entry: GazetteerEntry,
        matched_text: str,
        start: int,
        end: int,
        confidence: float,
        match_type: str,  # "exact", "fuzzy", "pattern"
    ):
        self.entry = entry
        self.matched_text = matched_text
        self.start = start
        self.end = end
        self.confidence = confidence
        self.match_type = match_type


class GazetteerMatcher:
    """Efficient gazetteer matching with exact and fuzzy support."""

    def __init__(self, fuzzy_threshold: int = None):
        self.fuzzy_threshold = fuzzy_threshold or default_config.fuzzy_threshold
        self.exact_automaton = ahocorasick.Automaton()
        self.entries: dict[str, GazetteerEntry] = {}  # id -> entry
        self.name_to_id: dict[str, str] = {}  # lowercase name -> entry id
        self.patterns: list[tuple[re.Pattern, str]] = []  # (compiled pattern, entry_id)
        self._built = False

    def load_entries(self, entries: list[GazetteerEntry]) -> None:
        """Load gazetteer entries and build search structures."""
        for entry in entries:
            self.entries[entry.id] = entry

            # Add main name
            name_lower = entry.name.lower()
            self.name_to_id[name_lower] = entry.id
            self.exact_automaton.add_word(name_lower, (entry.id, entry.name))

            # Add aliases
            for alias in entry.aliases:
                alias_lower = alias.lower()
                self.name_to_id[alias_lower] = entry.id
                self.exact_automaton.add_word(alias_lower, (entry.id, alias))

            # Compile regex patterns
            for pattern in entry.patterns:
                try:
                    compiled = re.compile(pattern, re.IGNORECASE)
                    self.patterns.append((compiled, entry.id))
                except re.error:
                    pass  # Skip invalid patterns

        # Build the automaton
        self.exact_automaton.make_automaton()
        self._built = True

    def find_all(self, text: str) -> list[GazetteerMatch]:
        """Find all matches in text using all methods."""
        if not self._built:
            return []

        matches = []

        # Exact matches (Aho-Corasick)
        matches.extend(self._find_exact(text))

        # Pattern matches
        matches.extend(self._find_patterns(text))

        # Deduplicate overlapping matches
        matches = self._deduplicate_matches(matches)

        return matches

    def _find_exact(self, text: str) -> list[GazetteerMatch]:
        """Find all exact matches using Aho-Corasick automaton."""
        matches = []
        text_lower = text.lower()

        for end_idx, (entry_id, matched_name) in self.exact_automaton.iter(text_lower):
            start_idx = end_idx - len(matched_name) + 1
            end_pos = end_idx + 1  # Convert to exclusive end position
            entry = self.entries[entry_id]

            # Check word boundaries to avoid partial matches
            if self._check_word_boundary(text_lower, start_idx, end_pos):
                matches.append(
                    GazetteerMatch(
                        entry=entry,
                        matched_text=text[start_idx : end_idx + 1],
                        start=start_idx,
                        end=end_idx + 1,
                        confidence=default_config.gazetteer_exact_confidence,
                        match_type="exact",
                    )
                )

        return matches

    def _find_patterns(self, text: str) -> list[GazetteerMatch]:
        """Find all pattern matches."""
        matches = []

        for pattern, entry_id in self.patterns:
            entry = self.entries[entry_id]
            for match in pattern.finditer(text):
                matches.append(
                    GazetteerMatch(
                        entry=entry,
                        matched_text=match.group(),
                        start=match.start(),
                        end=match.end(),
                        confidence=default_config.gazetteer_fuzzy_confidence,
                        match_type="pattern",
                    )
                )

        return matches

    def find_fuzzy(self, candidate: str, entity_type: Optional[EntityType] = None) -> Optional[GazetteerMatch]:
        """Find best fuzzy match for a candidate string."""
        if not self._built:
            return None

        candidate_lower = candidate.lower()

        # Filter names by entity type if specified
        if entity_type:
            search_names = {
                name: eid
                for name, eid in self.name_to_id.items()
                if self.entries[eid].entity_type == entity_type
            }
        else:
            search_names = self.name_to_id

        if not search_names:
            return None

        # Use rapidfuzz for efficient fuzzy matching
        result = process.extractOne(
            candidate_lower,
            search_names.keys(),
            scorer=fuzz.ratio,
            score_cutoff=self.fuzzy_threshold,
        )

        if result:
            matched_name, score, _ = result
            entry_id = search_names[matched_name]
            entry = self.entries[entry_id]

            return GazetteerMatch(
                entry=entry,
                matched_text=candidate,
                start=0,
                end=len(candidate),
                confidence=min(
                    default_config.gazetteer_fuzzy_confidence,
                    score / 100.0,
                ),
                match_type="fuzzy",
            )

        return None

    def _check_word_boundary(self, text: str, start: int, end: int) -> bool:
        """Check if match is at word boundaries."""
        # Check start boundary
        if start > 0 and text[start - 1].isalnum():
            return False
        # Check end boundary
        if end < len(text) and text[end].isalnum():
            return False
        return True

    def _deduplicate_matches(self, matches: list[GazetteerMatch]) -> list[GazetteerMatch]:
        """Remove overlapping matches, keeping highest confidence."""
        if not matches:
            return []

        # Sort by start position, then by confidence (descending)
        sorted_matches = sorted(
            matches,
            key=lambda m: (m.start, -m.confidence),
        )

        result = []
        last_end = -1

        for match in sorted_matches:
            # Skip if this match overlaps with a previous one
            if match.start < last_end:
                continue

            result.append(match)
            last_end = match.end

        return result

    def get_entry(self, entry_id: str) -> Optional[GazetteerEntry]:
        """Get a gazetteer entry by ID."""
        return self.entries.get(entry_id)

    def get_entries_by_type(self, entity_type: EntityType) -> list[GazetteerEntry]:
        """Get all entries of a specific type."""
        return [e for e in self.entries.values() if e.entity_type == entity_type]
