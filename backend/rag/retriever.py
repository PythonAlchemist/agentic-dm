"""Hybrid retriever combining vector search and knowledge graph."""

from typing import Optional

from openai import AsyncOpenAI

from backend.core.config import settings
from backend.core.database import get_chroma_collection
from backend.graph.operations import CampaignGraphOps


class HybridRetriever:
    """Retriever that combines vector search with knowledge graph queries."""

    def __init__(self):
        """Initialize the hybrid retriever."""
        self.openai = AsyncOpenAI(api_key=settings.openai_api_key)
        self.collection = get_chroma_collection()
        self.graph_ops = CampaignGraphOps()

    async def _get_embedding(self, text: str) -> list[float]:
        """Generate embedding for search query."""
        response = await self.openai.embeddings.create(
            model=settings.openai_embedding_model,
            input=text,
        )
        return response.data[0].embedding

    async def search(
        self,
        query: str,
        top_k: int = 5,
        source_filter: Optional[str] = None,
        chunk_type_filter: Optional[str] = None,
    ) -> list[dict]:
        """Search the vector database.

        Args:
            query: Search query
            top_k: Number of results to return
            source_filter: Filter by document source
            chunk_type_filter: Filter by chunk type

        Returns:
            List of search results with content, metadata, and scores
        """
        # Generate query embedding
        query_embedding = await self._get_embedding(query)

        # Build where clause for filtering
        where = {}
        if source_filter:
            where["source"] = source_filter
        if chunk_type_filter:
            where["chunk_type"] = chunk_type_filter

        # Query ChromaDB
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=where if where else None,
            include=["documents", "metadatas", "distances"],
        )

        # Format results
        formatted = []
        if results["ids"] and results["ids"][0]:
            for i, chunk_id in enumerate(results["ids"][0]):
                formatted.append({
                    "id": chunk_id,
                    "content": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i],
                    "score": 1 - results["distances"][0][i],  # Convert distance to similarity
                })

        return formatted

    async def search_graph(
        self,
        query: str,
        entity_types: Optional[list[str]] = None,
        limit: int = 10,
    ) -> list[dict]:
        """Search the knowledge graph.

        Args:
            query: Search query
            entity_types: Filter by entity types
            limit: Maximum results

        Returns:
            List of matching entities
        """
        return self.graph_ops.search(
            query=query,
            entity_types=entity_types,
            limit=limit,
        )

    async def hybrid_search(
        self,
        query: str,
        vector_k: int = 5,
        graph_k: int = 5,
        entity_types: Optional[list[str]] = None,
    ) -> dict:
        """Perform hybrid search across vector DB and knowledge graph.

        Args:
            query: Search query
            vector_k: Number of vector results
            graph_k: Number of graph results
            entity_types: Entity types to search in graph

        Returns:
            Combined results from both sources
        """
        # Parallel search (simplified for now)
        vector_results = await self.search(query, top_k=vector_k)
        graph_results = await self.search_graph(query, entity_types, graph_k)

        return {
            "vector_results": vector_results,
            "graph_results": graph_results,
        }

    async def get_context_for_entity(
        self,
        entity_name: str,
        max_hops: int = 2,
    ) -> Optional[dict]:
        """Get full context for a named entity.

        Args:
            entity_name: Name of the entity to find
            max_hops: How many relationship hops to traverse

        Returns:
            Entity with its neighborhood context
        """
        # Search for the entity
        results = self.graph_ops.search(query=entity_name, limit=1)
        if not results:
            return None

        entity = results[0]
        return self.graph_ops.get_entity_context(
            entity_id=entity["id"],
            max_hops=max_hops,
        )

    async def list_sources(self) -> list[str]:
        """List all unique document sources.

        Returns:
            List of source names
        """
        # Get all unique sources from ChromaDB
        # Note: This is a simple implementation; for large collections,
        # you'd want to maintain a separate metadata store
        results = self.collection.get(
            include=["metadatas"],
            limit=10000,  # Adjust based on expected size
        )

        sources = set()
        for metadata in results["metadatas"]:
            if "source" in metadata:
                sources.add(metadata["source"])

        return sorted(list(sources))
