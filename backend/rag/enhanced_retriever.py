"""Enhanced hybrid retriever with entity-aware retrieval."""

import asyncio
from typing import Optional

from pydantic import BaseModel, Field

from backend.core.config import settings
from backend.core.database import get_chroma_collection
from backend.graph.operations import CampaignGraphOps
from backend.graph.schema import EntityType
from backend.ner import ExtractedEntity
from backend.rag.query_planner import QueryPlanner, QueryPlan, RetrievalStrategy

from openai import AsyncOpenAI


class RetrievalResult(BaseModel):
    """Result from retrieval."""

    # Vector results
    vector_results: list[dict] = Field(default_factory=list)

    # Graph results
    graph_entities: list[dict] = Field(default_factory=list)
    graph_relationships: list[dict] = Field(default_factory=list)

    # Metadata
    query_plan: Optional[QueryPlan] = None
    total_results: int = 0


class EnhancedRetriever:
    """Enhanced retriever with entity-aware hybrid search."""

    def __init__(self, use_query_planning: bool = True):
        """Initialize the enhanced retriever.

        Args:
            use_query_planning: Whether to use query planning/classification.
        """
        self.openai = AsyncOpenAI(api_key=settings.openai_api_key)
        self.collection = get_chroma_collection()
        self.graph_ops = CampaignGraphOps()

        self.use_query_planning = use_query_planning
        if use_query_planning:
            self.query_planner = QueryPlanner(use_ner=True)
        else:
            self.query_planner = None

    async def retrieve(
        self,
        query: str,
        strategy: Optional[RetrievalStrategy] = None,
    ) -> RetrievalResult:
        """Retrieve context for a query.

        Args:
            query: The user's query.
            strategy: Optional retrieval strategy (auto-planned if None).

        Returns:
            RetrievalResult with all retrieved context.
        """
        # Plan query if no strategy provided
        query_plan = None
        if strategy is None:
            if self.query_planner:
                query_plan = await self.query_planner.plan(query)
                strategy = query_plan.strategy
            else:
                strategy = RetrievalStrategy()  # Default

        result = RetrievalResult(query_plan=query_plan)

        # Run retrieval tasks
        tasks = []

        if strategy.use_vector:
            tasks.append(self._search_vector(
                query,
                top_k=strategy.vector_k,
                sources=strategy.vector_sources,
            ))
        else:
            tasks.append(asyncio.coroutine(lambda: [])())

        if strategy.use_graph:
            # If we have extracted entities, use them for targeted search
            entities = query_plan.extracted_entities if query_plan else []
            tasks.append(self._search_graph_enhanced(
                query,
                entities=entities,
                entity_types=strategy.entity_types,
                depth=strategy.graph_depth,
                limit=strategy.graph_k,
            ))
        else:
            tasks.append(asyncio.coroutine(lambda: ([], []))())

        # Execute in parallel
        vector_results, graph_results = await asyncio.gather(*tasks)

        result.vector_results = vector_results
        if graph_results:
            result.graph_entities = graph_results[0]
            result.graph_relationships = graph_results[1]

        result.total_results = (
            len(result.vector_results) +
            len(result.graph_entities)
        )

        return result

    async def _get_embedding(self, text: str) -> list[float]:
        """Generate embedding for search query."""
        response = await self.openai.embeddings.create(
            model=settings.openai_embedding_model,
            input=text,
        )
        return response.data[0].embedding

    async def _search_vector(
        self,
        query: str,
        top_k: int = 5,
        sources: Optional[list[str]] = None,
    ) -> list[dict]:
        """Search vector database.

        Args:
            query: Search query.
            top_k: Number of results.
            sources: Filter to specific sources.

        Returns:
            List of vector search results.
        """
        query_embedding = await self._get_embedding(query)

        # Build where clause
        where = None
        if sources:
            # ChromaDB $in filter
            where = {"source": {"$in": sources}}

        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=where,
            include=["documents", "metadatas", "distances"],
        )

        formatted = []
        if results["ids"] and results["ids"][0]:
            for i, chunk_id in enumerate(results["ids"][0]):
                formatted.append({
                    "id": chunk_id,
                    "content": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i],
                    "score": 1 - results["distances"][0][i],
                    "source_type": "vector",
                })

        return formatted

    async def _search_graph_enhanced(
        self,
        query: str,
        entities: list[ExtractedEntity],
        entity_types: list[EntityType],
        depth: int = 2,
        limit: int = 10,
    ) -> tuple[list[dict], list[dict]]:
        """Enhanced graph search using extracted entities.

        Args:
            query: Original query.
            entities: Extracted entities from query.
            entity_types: Types to search for.
            depth: Graph traversal depth.
            limit: Maximum results.

        Returns:
            Tuple of (entities, relationships).
        """
        all_entities = []
        all_relationships = []
        seen_ids = set()

        # First: Search for extracted entities by name
        for entity in entities:
            results = self.graph_ops.search(
                query=entity.normalized_name,
                entity_types=[entity.entity_type.value],
                limit=3,
            )

            for result in results:
                if result["id"] not in seen_ids:
                    seen_ids.add(result["id"])
                    all_entities.append({
                        **result,
                        "match_type": "entity_name",
                        "matched_query": entity.normalized_name,
                    })

                    # Get neighbors for context
                    if depth > 0:
                        neighbors = self.graph_ops.get_neighbors(
                            entity_id=result["id"],
                            max_hops=depth,
                        )
                        for neighbor in neighbors[:5]:  # Limit neighbors
                            if neighbor["id"] not in seen_ids:
                                seen_ids.add(neighbor["id"])
                                all_entities.append({
                                    **neighbor,
                                    "match_type": "neighbor",
                                    "related_to": result["name"],
                                })

        # Second: General text search if we need more results
        if len(all_entities) < limit:
            type_values = [t.value for t in entity_types] if entity_types else None
            text_results = self.graph_ops.search(
                query=query,
                entity_types=type_values,
                limit=limit - len(all_entities),
            )

            for result in text_results:
                if result["id"] not in seen_ids:
                    seen_ids.add(result["id"])
                    all_entities.append({
                        **result,
                        "match_type": "text_search",
                    })

        return all_entities[:limit], all_relationships

    async def get_entity_context(
        self,
        entity_name: str,
        max_hops: int = 2,
    ) -> Optional[dict]:
        """Get full context for a specific entity.

        Args:
            entity_name: Name of entity to find.
            max_hops: Graph traversal depth.

        Returns:
            Entity with its full neighborhood context.
        """
        results = self.graph_ops.search(query=entity_name, limit=1)
        if not results:
            return None

        entity = results[0]
        context = self.graph_ops.get_entity_context(
            entity_id=entity["id"],
            max_hops=max_hops,
        )

        return context

    def format_context(self, result: RetrievalResult) -> str:
        """Format retrieval results into a context string.

        Args:
            result: RetrievalResult to format.

        Returns:
            Formatted context string.
        """
        parts = []

        # Format vector results
        if result.vector_results:
            vector_parts = []
            for r in result.vector_results:
                source = r["metadata"].get("source", "Unknown")
                page = r["metadata"].get("page", "?")
                content = r["content"]
                vector_parts.append(f"[Source: {source}, Page {page}]\n{content}")

            parts.append("=== Reference Materials ===\n" + "\n\n---\n\n".join(vector_parts))

        # Format graph entities
        if result.graph_entities:
            entity_parts = []
            for e in result.graph_entities:
                entity_type = e.get("entity_type", "Entity")
                name = e.get("name", "Unknown")
                description = e.get("description", "")
                match_type = e.get("match_type", "")

                line = f"[{entity_type}] {name}"
                if description:
                    line += f": {description}"
                if match_type == "neighbor":
                    related = e.get("related_to", "")
                    line += f" (related to {related})"

                entity_parts.append(line)

            parts.append("=== Campaign Knowledge ===\n" + "\n".join(entity_parts))

        return "\n\n".join(parts) if parts else ""
