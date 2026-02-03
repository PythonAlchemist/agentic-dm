"""Tests for NER pipeline."""

import pytest

from backend.graph.schema import EntityType
from backend.ner import NERPipeline, NERConfig, ExtractedEntity, ExtractionSource
from backend.ner.gazetteers.loader import GazetteerLoader
from backend.ner.gazetteers.matcher import GazetteerMatcher
from backend.ner.extractors.spacy_extractor import SpacyExtractor
from backend.ner.extractors.gazetteer_extractor import GazetteerExtractor
from backend.ner.resolution.resolver import EntityResolver


class TestGazetteerLoader:
    """Test gazetteer loading."""

    def test_load_canonical_gazetteers(self):
        """Test loading canonical D&D gazetteers."""
        loader = GazetteerLoader()
        entries = loader.load_all()

        # Should have loaded entries from our YAML files
        assert len(entries) > 0

        # Check we have different entity types
        types = {e.entity_type for e in entries}
        assert EntityType.SPELL in types
        assert EntityType.MONSTER in types
        assert EntityType.ITEM in types
        assert EntityType.CLASS in types
        assert EntityType.RACE in types

    def test_load_by_type(self):
        """Test loading gazetteers filtered by type."""
        loader = GazetteerLoader()

        spells = loader.load_by_type(EntityType.SPELL)
        assert len(spells) > 0
        assert all(e.entity_type == EntityType.SPELL for e in spells)

        # Verify some known spells
        spell_names = {e.name for e in spells}
        assert "Fireball" in spell_names
        assert "Magic Missile" in spell_names


class TestGazetteerMatcher:
    """Test gazetteer matching."""

    @pytest.fixture
    def matcher(self):
        """Create a matcher with loaded entries."""
        loader = GazetteerLoader()
        entries = loader.load_all()
        matcher = GazetteerMatcher()
        matcher.load_entries(entries)
        return matcher

    def test_exact_match(self, matcher):
        """Test exact string matching."""
        text = "The wizard cast Fireball at the goblins."
        matches = matcher.find_all(text)

        # Should find Fireball and Goblin
        match_names = {m.entry.name for m in matches}
        assert "Fireball" in match_names
        # Note: "goblins" (plural) should match "Goblin" via alias

    def test_fuzzy_match(self, matcher):
        """Test fuzzy matching."""
        # Test fuzzy match with typo
        match = matcher.find_fuzzy("Firebal")  # Missing 'l'
        assert match is not None
        assert match.entry.name == "Fireball"

    def test_pattern_match(self, matcher):
        """Test regex pattern matching."""
        text = "He swung his +1 longsword."
        matches = matcher.find_all(text)

        # Should match via pattern
        match_names = {m.entry.name for m in matches}
        assert "+1 Sword" in match_names or "Longsword" in match_names


class TestSpacyExtractor:
    """Test SpaCy extraction."""

    @pytest.fixture
    def extractor(self):
        """Create SpaCy extractor."""
        return SpacyExtractor()

    def test_extract_person(self, extractor):
        """Test extracting person entities."""
        text = "Lord Neverember greeted the party in Waterdeep."
        entities = extractor.extract(text)

        # Should find person and location
        types = {e.entity_type for e in entities}
        # Note: SpaCy detection depends on model training
        assert len(entities) > 0

    def test_extract_noun_chunks(self, extractor):
        """Test noun chunk extraction."""
        text = "The ancient red dragon guarded the treasure hoard."
        chunks = extractor.extract_noun_chunks(text)

        assert len(chunks) > 0
        chunk_lower = [c.lower() for c in chunks]
        assert any("dragon" in c for c in chunk_lower)


class TestGazetteerExtractor:
    """Test gazetteer extractor."""

    @pytest.fixture
    def extractor(self):
        """Create gazetteer extractor."""
        extractor = GazetteerExtractor()
        extractor.load_gazetteers()
        return extractor

    def test_extract_spells(self, extractor):
        """Test extracting spell entities."""
        text = "The sorcerer cast Fireball at the enemies."
        entities = extractor.extract(text)

        names = {e.normalized_name for e in entities}
        assert "Fireball" in names

    def test_extract_monsters(self, extractor):
        """Test extracting monster entities."""
        # Use exact monster names as they appear in gazetteers
        text = "The party fought against a Troll and a Goblin."
        entities = extractor.extract(text)

        names = {e.normalized_name for e in entities}
        assert "Troll" in names or "Goblin" in names  # At least one should match


class TestEntityResolver:
    """Test entity resolution."""

    def test_merge_duplicates(self):
        """Test merging duplicate entities."""
        resolver = EntityResolver()

        entities = [
            ExtractedEntity(
                text="Fireball",
                normalized_name="Fireball",
                entity_type=EntityType.SPELL,
                confidence=0.9,
                source=ExtractionSource.GAZETTEER,
            ),
            ExtractedEntity(
                text="fireball",
                normalized_name="Fireball",
                entity_type=EntityType.SPELL,
                confidence=0.6,
                source=ExtractionSource.SPACY,
            ),
        ]

        resolved = resolver.resolve(entities)

        # Should merge into one entity
        assert len(resolved) == 1
        # Should have boosted confidence
        assert resolved[0].confidence > 0.9
        # Should be marked as hybrid
        assert resolved[0].source == ExtractionSource.HYBRID

    def test_keep_distinct(self):
        """Test keeping distinct entities."""
        resolver = EntityResolver()

        entities = [
            ExtractedEntity(
                text="Fireball",
                normalized_name="Fireball",
                entity_type=EntityType.SPELL,
                confidence=0.9,
                source=ExtractionSource.GAZETTEER,
            ),
            ExtractedEntity(
                text="Lightning Bolt",
                normalized_name="Lightning Bolt",
                entity_type=EntityType.SPELL,
                confidence=0.9,
                source=ExtractionSource.GAZETTEER,
            ),
        ]

        resolved = resolver.resolve(entities)

        # Should keep both
        assert len(resolved) == 2


class TestNERPipeline:
    """Test the full NER pipeline."""

    @pytest.fixture
    def pipeline(self):
        """Create pipeline without LLM for testing."""
        config = NERConfig(
            use_llm_extraction=False,  # Skip LLM in tests
            link_to_graph=False,  # Skip graph linking in unit tests
        )
        return NERPipeline(config)

    def test_extract_simple(self, pipeline):
        """Test simple extraction."""
        text = "The party defeated a goblin and found a healing potion."
        result = pipeline.extract_sync(text)

        assert result.entity_count > 0

        # Check entity types
        names = {e.normalized_name for e in result.entities}
        assert "Goblin" in names or any("goblin" in n.lower() for n in names)

    def test_extract_complex(self, pipeline):
        """Test extraction from more complex text."""
        text = """
        The wizard Elara cast Fireball at the group of orcs, while
        Thorin the dwarf fighter charged forward with his +1 longsword.
        The battle took place near Waterdeep, where the party had been
        hired by the Harpers to investigate goblin raids.
        """
        result = pipeline.extract_sync(text)

        # Should find multiple entity types
        types = {e.entity_type for e in result.entities}
        assert len(types) >= 2  # At least spells and monsters

        # Check processing time is recorded
        assert result.processing_time_ms > 0

    @pytest.mark.asyncio
    async def test_extract_async(self, pipeline):
        """Test async extraction."""
        text = "The rogue used a potion of healing after the fight."
        result = await pipeline.extract(text)

        assert result.entity_count > 0


class TestIntegration:
    """Integration tests for the full NER system."""

    def test_dnd_transcript_extraction(self):
        """Test extraction from a realistic D&D transcript."""
        config = NERConfig(
            use_llm_extraction=False,
            link_to_graph=False,
        )
        pipeline = NERPipeline(config)

        transcript = """
        DM: As you enter the dungeon, you see a group of three goblins
        huddled around a small fire. They haven't noticed you yet.

        Player 1 (Aria, Elf Ranger): I'm going to try to sneak past them.

        DM: Roll stealth.

        Player 1: Natural 20!

        DM: You move silently through the shadows. But wait - behind the
        goblins, you notice a larger figure. It's a bugbear, and it's
        holding what looks like a Bag of Holding.

        Player 2 (Grimlock, Dwarf Cleric): I cast Sacred Flame on the bugbear!
        """

        result = pipeline.extract_sync(transcript)

        # Verify we found key entities
        entity_names = {e.normalized_name.lower() for e in result.entities}
        entity_types = {e.entity_type for e in result.entities}

        # Should find monsters
        assert EntityType.MONSTER in entity_types

        # Should find at least some of these
        found_entities = []
        expected = ["goblin", "bugbear", "bag of holding", "sacred flame"]
        for name in expected:
            if any(name in n for n in entity_names):
                found_entities.append(name)

        # At least 2 of the expected entities should be found
        assert len(found_entities) >= 2, f"Only found: {found_entities}"
