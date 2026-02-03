"""RAG (Retrieval-Augmented Generation) module.

This module provides:
- Query planning and classification
- Hybrid retrieval (vector + graph)
- Entity-aware search
- Result reranking
- Response generation with citations
"""

from backend.rag.retriever import HybridRetriever
from backend.rag.pipeline import RAGPipeline
from backend.rag.query_planner import QueryPlanner, QueryPlan, QueryType, RetrievalStrategy
from backend.rag.enhanced_retriever import EnhancedRetriever, RetrievalResult
from backend.rag.reranker import Reranker, RankedResult
from backend.rag.hybrid_pipeline import HybridRAGPipeline, HybridRAGResponse

__all__ = [
    # Core pipeline
    "RAGPipeline",
    # Retrievers
    "HybridRetriever",
    "EnhancedRetriever",
    # Query planning
    "QueryPlanner",
    "QueryPlan",
    "QueryType",
    "RetrievalStrategy",
    # Reranking
    "Reranker",
    "RankedResult",
    # Results
    "RetrievalResult",
    # Hybrid pipeline
    "HybridRAGPipeline",
    "HybridRAGResponse",
]
