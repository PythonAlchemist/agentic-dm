"""Result reranking for improved relevance."""

from typing import Optional

from pydantic import BaseModel, Field
from rapidfuzz import fuzz

from backend.ner import ExtractedEntity


class RankedResult(BaseModel):
    """A result with ranking score."""

    content: str
    metadata: dict = Field(default_factory=dict)
    original_score: float = 0.0
    rerank_score: float = 0.0
    final_score: float = 0.0
    source_type: str = "unknown"  # vector, graph
    boost_reasons: list[str] = Field(default_factory=list)


class Reranker:
    """Rerank retrieval results for better relevance."""

    def __init__(
        self,
        entity_boost: float = 0.2,
        recency_boost: float = 0.1,
        source_weights: Optional[dict[str, float]] = None,
    ):
        """Initialize the reranker.

        Args:
            entity_boost: Boost for results mentioning query entities.
            recency_boost: Boost for more recent results.
            source_weights: Weights for different sources.
        """
        self.entity_boost = entity_boost
        self.recency_boost = recency_boost
        self.source_weights = source_weights or {
            "phb": 1.2,  # Player's Handbook
            "dmg": 1.1,  # Dungeon Master's Guide
            "mm": 1.0,   # Monster Manual
            "session": 0.9,  # Session notes
        }

    def rerank(
        self,
        results: list[dict],
        query: str,
        query_entities: Optional[list[ExtractedEntity]] = None,
    ) -> list[RankedResult]:
        """Rerank results based on multiple signals.

        Args:
            results: Raw retrieval results.
            query: Original query.
            query_entities: Entities extracted from query.

        Returns:
            Sorted list of RankedResults.
        """
        ranked = []

        entity_names = set()
        if query_entities:
            entity_names = {e.normalized_name.lower() for e in query_entities}

        for result in results:
            ranked_result = self._score_result(
                result,
                query,
                entity_names,
            )
            ranked.append(ranked_result)

        # Sort by final score (descending)
        ranked.sort(key=lambda r: r.final_score, reverse=True)

        return ranked

    def _score_result(
        self,
        result: dict,
        query: str,
        entity_names: set[str],
    ) -> RankedResult:
        """Score a single result.

        Args:
            result: Raw result dict.
            query: Original query.
            entity_names: Set of entity names from query.

        Returns:
            RankedResult with scores.
        """
        # Extract content based on result type
        if "content" in result:
            content = result["content"]
        elif "description" in result:
            content = f"{result.get('name', '')} - {result['description']}"
        else:
            content = result.get("name", str(result))

        # Get original score
        original_score = result.get("score", 0.5)

        # Start with original score
        rerank_score = 0.0
        boost_reasons = []

        # 1. Entity mention boost
        content_lower = content.lower()
        for entity_name in entity_names:
            if entity_name in content_lower:
                rerank_score += self.entity_boost
                boost_reasons.append(f"mentions '{entity_name}'")

        # 2. Query term overlap boost
        query_terms = set(query.lower().split())
        content_terms = set(content_lower.split())
        overlap = len(query_terms & content_terms)
        if overlap > 0:
            term_boost = min(0.15, overlap * 0.03)
            rerank_score += term_boost
            if term_boost > 0.05:
                boost_reasons.append(f"{overlap} query terms")

        # 3. Source weight
        source = result.get("metadata", {}).get("source", "")
        source_lower = source.lower()
        for source_key, weight in self.source_weights.items():
            if source_key in source_lower:
                source_boost = (weight - 1.0) * 0.1
                rerank_score += source_boost
                if source_boost > 0:
                    boost_reasons.append(f"authoritative source")
                break

        # 4. Fuzzy title/name match
        if "name" in result:
            name_similarity = fuzz.partial_ratio(query.lower(), result["name"].lower())
            if name_similarity > 80:
                name_boost = (name_similarity - 80) / 200  # Max 0.1 boost
                rerank_score += name_boost
                boost_reasons.append("name match")

        # 5. Graph entity type bonus for campaign queries
        if result.get("source_type") == "graph":
            entity_type = result.get("entity_type", "")
            if entity_type in ["PC", "NPC", "LOCATION"]:
                rerank_score += 0.05
                boost_reasons.append("campaign entity")

        # Calculate final score
        final_score = (original_score * 0.7) + (rerank_score * 0.3)
        final_score = min(1.0, final_score)

        return RankedResult(
            content=content,
            metadata=result.get("metadata", {}),
            original_score=original_score,
            rerank_score=rerank_score,
            final_score=final_score,
            source_type=result.get("source_type", "unknown"),
            boost_reasons=boost_reasons,
        )

    def merge_results(
        self,
        vector_results: list[dict],
        graph_results: list[dict],
        query: str,
        query_entities: Optional[list[ExtractedEntity]] = None,
        max_results: int = 10,
    ) -> list[RankedResult]:
        """Merge and rerank results from multiple sources.

        Args:
            vector_results: Results from vector search.
            graph_results: Results from graph search.
            query: Original query.
            query_entities: Extracted entities.
            max_results: Maximum results to return.

        Returns:
            Merged and ranked results.
        """
        # Tag source types
        for r in vector_results:
            r["source_type"] = "vector"
        for r in graph_results:
            r["source_type"] = "graph"

        # Combine and rerank
        all_results = vector_results + graph_results
        ranked = self.rerank(all_results, query, query_entities)

        return ranked[:max_results]
