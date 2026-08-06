"""Regression tests for EnhancedRetriever's retrieval-leg fan-out.

The disabled legs of the `asyncio.gather` used to be built with `asyncio.coroutine`,
which was REMOVED in Python 3.11. On this project's 3.12 floor that raised AttributeError
whenever the query planner disabled either leg, abandoning the other leg's already-created
coroutine unawaited and 500ing the request. The failure was query-dependent, so it looked
intermittent rather than deterministic.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.rag.enhanced_retriever import (
    EnhancedRetriever,
    _no_graph_results,
    _no_vector_results,
)
from backend.rag.query_planner import RetrievalStrategy


@pytest.fixture
def retriever():
    with patch("backend.rag.enhanced_retriever.get_chroma_collection", MagicMock()), patch(
        "backend.rag.enhanced_retriever.AsyncOpenAI", MagicMock()
    ), patch("backend.rag.enhanced_retriever.CampaignGraphOps", MagicMock()):
        return EnhancedRetriever()


class TestDisabledLegPlaceholders:
    @pytest.mark.asyncio
    async def test_no_vector_results_is_awaitable(self):
        assert await _no_vector_results() == []

    @pytest.mark.asyncio
    async def test_no_graph_results_is_awaitable(self):
        assert await _no_graph_results() == ([], [])


class TestRetrieveWithDisabledLegs:
    @pytest.mark.asyncio
    async def test_graph_disabled_does_not_raise(self, retriever):
        """The exact shape that 500'd: vector on, graph off."""
        retriever._search_vector = AsyncMock(return_value=["chunk"])

        result = await retriever.retrieve(
            "what is the tone of my campaign?",
            strategy=RetrievalStrategy(use_vector=True, use_graph=False),
        )

        assert result.vector_results == ["chunk"]
        assert result.graph_entities == []

    @pytest.mark.asyncio
    async def test_vector_disabled_does_not_raise(self, retriever):
        retriever._search_graph_enhanced = AsyncMock(return_value=(["npc"], ["rel"]))

        result = await retriever.retrieve(
            "who does Ireena know?",
            strategy=RetrievalStrategy(use_vector=False, use_graph=True),
        )

        assert result.vector_results == []
        assert result.graph_entities == ["npc"]

    @pytest.mark.asyncio
    async def test_both_disabled_does_not_raise(self, retriever):
        result = await retriever.retrieve(
            "hello",
            strategy=RetrievalStrategy(use_vector=False, use_graph=False),
        )

        assert result.total_results == 0
