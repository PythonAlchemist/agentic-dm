"""Tests for query planner and classifier."""

import pytest

from backend.rag.query_planner import QueryPlanner, QueryType


class TestQueryPlanner:
    """Test query planning and classification."""

    @pytest.fixture
    def planner(self):
        """Create a query planner without NER for faster tests."""
        return QueryPlanner(use_ner=False)

    @pytest.fixture
    def planner_with_ner(self):
        """Create a query planner with NER."""
        return QueryPlanner(use_ner=True)

    @pytest.mark.asyncio
    async def test_classify_rules_lookup(self, planner):
        """Test rules lookup classification."""
        queries = [
            "How does grappling work?",
            "What are the rules for concentration?",
            "Can I cast two spells in one turn?",
            "How do saving throws work?",
            "Explain the attack action",
        ]

        for query in queries:
            plan = await planner.plan(query)
            assert plan.query_type == QueryType.RULES_LOOKUP, f"Failed for: {query}"
            assert plan.strategy.use_vector is True
            assert plan.strategy.use_graph is False

    @pytest.mark.asyncio
    async def test_classify_campaign_state(self, planner):
        """Test campaign state classification."""
        queries = [
            "Where is Thorin right now?",
            "What is the current status of the party?",
            "Where are the players located?",
            "What does Gandalf have in his inventory?",
        ]

        for query in queries:
            plan = await planner.plan(query)
            assert plan.query_type == QueryType.CAMPAIGN_STATE, f"Failed for: {query}"
            assert plan.strategy.use_graph is True

    @pytest.mark.asyncio
    async def test_classify_campaign_history(self, planner):
        """Test campaign history classification."""
        queries = [
            "What happened last session?",
            "When did we fight the dragon?",
            "What happened to the artifact before?",
            "Did we visit this town previously?",
        ]

        for query in queries:
            plan = await planner.plan(query)
            assert plan.query_type == QueryType.CAMPAIGN_HISTORY, f"Failed for: {query}"

    @pytest.mark.asyncio
    async def test_classify_encounter_generation(self, planner):
        """Test encounter generation classification."""
        queries = [
            "Create a goblin ambush encounter",
            "Generate a combat encounter for level 5",
            "Design a dungeon fight",
            "Build an encounter with undead",
        ]

        for query in queries:
            plan = await planner.plan(query)
            assert plan.query_type == QueryType.ENCOUNTER_GENERATION, f"Failed for: {query}"

    @pytest.mark.asyncio
    async def test_classify_npc_generation(self, planner):
        """Test NPC generation classification."""
        queries = [
            "Create an NPC merchant",
            "Generate a mysterious innkeeper",
            "Make a villain for my campaign",
        ]

        for query in queries:
            plan = await planner.plan(query)
            assert plan.query_type == QueryType.NPC_GENERATION, f"Failed for: {query}"

    @pytest.mark.asyncio
    async def test_extract_keywords(self, planner):
        """Test keyword extraction."""
        query = "How does the fireball spell damage work?"
        plan = await planner.plan(query)

        keywords = plan.keywords
        assert "fireball" in keywords
        assert "spell" in keywords
        assert "damage" in keywords
        # Stop words should be removed
        assert "the" not in keywords
        assert "does" not in keywords

    @pytest.mark.asyncio
    async def test_plan_with_ner(self, planner_with_ner):
        """Test that NER extracts entities from query."""
        query = "Tell me about Fireball and Magic Missile"
        plan = await planner_with_ner.plan(query)

        # Should find spell entities
        entity_names = [e.normalized_name for e in plan.extracted_entities]
        assert "Fireball" in entity_names or "Magic Missile" in entity_names

    @pytest.mark.asyncio
    async def test_strategy_vector_sources(self, planner):
        """Test that rules queries filter to rulebook sources."""
        query = "What are the rules for stealth?"
        plan = await planner.plan(query)

        # Should prioritize rulebooks
        assert plan.strategy.use_vector is True
        assert len(plan.strategy.vector_sources) > 0

    @pytest.mark.asyncio
    async def test_strategy_graph_depth(self, planner):
        """Test graph depth configuration."""
        # Entity info queries should have deeper traversal
        query = "Tell me about the Harpers faction"
        plan = await planner.plan(query)

        assert plan.strategy.graph_depth >= 2

    @pytest.mark.asyncio
    async def test_confidence_score(self, planner):
        """Test confidence scoring."""
        # Clear rules question should have high confidence
        clear_query = "How does the attack action work in combat?"
        clear_plan = await planner.plan(clear_query)
        assert clear_plan.confidence > 0.5

        # Ambiguous query should have lower confidence
        ambiguous_query = "stuff about things"
        ambiguous_plan = await planner.plan(ambiguous_query)
        assert ambiguous_plan.confidence < clear_plan.confidence


class TestRetrievalStrategy:
    """Test retrieval strategy configuration."""

    @pytest.mark.asyncio
    async def test_rules_strategy(self):
        """Test rules lookup strategy."""
        planner = QueryPlanner(use_ner=False)
        plan = await planner.plan("How do opportunity attacks work?")

        strategy = plan.strategy
        assert strategy.use_vector is True
        assert strategy.use_graph is False
        assert strategy.vector_k > 0

    @pytest.mark.asyncio
    async def test_campaign_state_strategy(self):
        """Test campaign state strategy."""
        planner = QueryPlanner(use_ner=False)
        plan = await planner.plan("Where is my character now?")

        strategy = plan.strategy
        assert strategy.use_graph is True
        assert strategy.require_entities is True

    @pytest.mark.asyncio
    async def test_hybrid_strategy(self):
        """Test hybrid strategy for history queries."""
        planner = QueryPlanner(use_ner=False)
        plan = await planner.plan("What happened when we fought the dragon?")

        strategy = plan.strategy
        assert strategy.use_vector is True
        assert strategy.use_graph is True
