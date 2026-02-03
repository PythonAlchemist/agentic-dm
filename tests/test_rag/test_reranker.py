"""Tests for result reranker."""

import pytest

from backend.ner import ExtractedEntity
from backend.graph.schema import EntityType
from backend.rag.reranker import Reranker, RankedResult


class TestReranker:
    """Test result reranking."""

    @pytest.fixture
    def reranker(self):
        """Create a reranker."""
        return Reranker()

    def test_basic_reranking(self, reranker):
        """Test basic reranking of results."""
        results = [
            {"content": "Some content about spells", "score": 0.5},
            {"content": "Another piece about magic", "score": 0.6},
            {"content": "Fireball does fire damage", "score": 0.4},
        ]

        ranked = reranker.rerank(results, "How does fireball damage work?")

        # Results should be RankedResult objects
        assert all(isinstance(r, RankedResult) for r in ranked)
        # Should be sorted by final_score
        scores = [r.final_score for r in ranked]
        assert scores == sorted(scores, reverse=True)

    def test_entity_boost(self, reranker):
        """Test that entity mentions get boosted."""
        results = [
            {"content": "Generic magic information", "score": 0.5},
            {"content": "Fireball is a powerful spell", "score": 0.5},
        ]

        entities = [
            ExtractedEntity(
                text="Fireball",
                normalized_name="Fireball",
                entity_type=EntityType.SPELL,
                span=(0, 8),
                confidence=0.9,
            )
        ]

        ranked = reranker.rerank(results, "Tell me about Fireball", entities)

        # Result mentioning Fireball should rank higher
        fireball_result = next(r for r in ranked if "Fireball" in r.content)
        generic_result = next(r for r in ranked if "Generic" in r.content)
        assert fireball_result.final_score > generic_result.final_score

    def test_source_weight_boost(self, reranker):
        """Test that authoritative sources get boosted."""
        results = [
            {
                "content": "Combat rules",
                "score": 0.5,
                "metadata": {"source": "PHB", "page": 192},
            },
            {
                "content": "Combat rules",
                "score": 0.5,
                "metadata": {"source": "session_notes"},
            },
        ]

        ranked = reranker.rerank(results, "How does combat work?")

        # PHB should rank higher than session notes
        phb_result = next(r for r in ranked if r.metadata.get("source") == "PHB")
        session_result = next(
            r for r in ranked if r.metadata.get("source") == "session_notes"
        )
        assert phb_result.final_score > session_result.final_score

    def test_query_term_overlap(self, reranker):
        """Test that query term overlap boosts results."""
        results = [
            {"content": "Saving throws are important", "score": 0.5},
            {"content": "Combat is fun", "score": 0.5},
        ]

        ranked = reranker.rerank(results, "How do saving throws work?")

        # Result with matching terms should rank higher
        saving_result = next(r for r in ranked if "Saving" in r.content)
        combat_result = next(r for r in ranked if "Combat" in r.content)
        assert saving_result.final_score > combat_result.final_score

    def test_merge_results(self, reranker):
        """Test merging vector and graph results."""
        vector_results = [
            {"content": "Spell rules from PHB", "score": 0.8},
            {"content": "More spell info", "score": 0.6},
        ]
        graph_results = [
            {"name": "Fireball", "description": "Evocation spell", "score": 0.7},
        ]

        merged = reranker.merge_results(
            vector_results=vector_results,
            graph_results=graph_results,
            query="Tell me about Fireball",
            max_results=5,
        )

        # Should have results from both sources
        source_types = {r.source_type for r in merged}
        assert "vector" in source_types
        assert "graph" in source_types

    def test_boost_reasons_tracked(self, reranker):
        """Test that boost reasons are tracked."""
        results = [
            {
                "content": "Fireball causes fire damage",
                "score": 0.5,
                "metadata": {"source": "PHB"},
            }
        ]
        entities = [
            ExtractedEntity(
                text="Fireball",
                normalized_name="Fireball",
                entity_type=EntityType.SPELL,
                span=(0, 8),
                confidence=0.9,
            )
        ]

        ranked = reranker.rerank(results, "Fireball damage", entities)

        # Should have boost reasons
        assert len(ranked[0].boost_reasons) > 0

    def test_max_results_limit(self, reranker):
        """Test that max_results limits output."""
        vector_results = [{"content": f"Result {i}", "score": 0.5} for i in range(10)]

        merged = reranker.merge_results(
            vector_results=vector_results,
            graph_results=[],
            query="test",
            max_results=3,
        )

        assert len(merged) == 3

    def test_graph_entity_type_bonus(self, reranker):
        """Test graph entities get bonuses for campaign queries."""
        results = [
            {
                "name": "Gandalf",
                "description": "A wizard NPC",
                "score": 0.5,
                "source_type": "graph",
                "entity_type": "NPC",
            },
            {"content": "General info", "score": 0.5, "source_type": "vector"},
        ]

        ranked = reranker.rerank(results, "Tell me about Gandalf")

        # Graph NPC should get bonus
        npc_result = next(r for r in ranked if "Gandalf" in r.content)
        assert "campaign entity" in npc_result.boost_reasons

    def test_name_match_boost(self, reranker):
        """Test fuzzy name matching boosts results."""
        results = [
            {"content": "General magic info", "score": 0.5},
            {"name": "Fireball Spell", "content": "Fireball - evocation", "score": 0.5},
        ]

        ranked = reranker.rerank(results, "fireball")

        # Named result should rank higher
        named = next(r for r in ranked if "Fireball" in r.content)
        general = next(r for r in ranked if "General" in r.content)
        assert named.final_score > general.final_score
