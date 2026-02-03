"""Gazetteer loading and matching."""

from backend.ner.gazetteers.loader import GazetteerLoader
from backend.ner.gazetteers.matcher import GazetteerMatcher

__all__ = ["GazetteerLoader", "GazetteerMatcher"]
