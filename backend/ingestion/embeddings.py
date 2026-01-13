"""Embedding generation and storage pipeline."""

from typing import Optional

from openai import AsyncOpenAI

from backend.core.config import settings
from backend.core.database import get_chroma_collection
from backend.ingestion.pdf_processor import DocumentChunk


class EmbeddingPipeline:
    """Generate embeddings and store in ChromaDB."""

    def __init__(self, collection_name: Optional[str] = None):
        """Initialize the embedding pipeline.

        Args:
            collection_name: ChromaDB collection name (default from settings)
        """
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)
        self.model = settings.openai_embedding_model
        self.collection = get_chroma_collection(collection_name)

    async def embed_text(self, text: str) -> list[float]:
        """Generate embedding for a single text.

        Args:
            text: Text to embed

        Returns:
            Embedding vector as list of floats
        """
        response = await self.client.embeddings.create(
            model=self.model,
            input=text,
        )
        return response.data[0].embedding

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts.

        Args:
            texts: List of texts to embed

        Returns:
            List of embedding vectors
        """
        if not texts:
            return []

        response = await self.client.embeddings.create(
            model=self.model,
            input=texts,
        )
        return [item.embedding for item in response.data]

    async def embed_and_store(self, chunk: DocumentChunk) -> str:
        """Generate embedding for a chunk and store in ChromaDB.

        Args:
            chunk: DocumentChunk to embed and store

        Returns:
            The chunk ID
        """
        embedding = await self.embed_text(chunk.content)

        # Prepare metadata (ChromaDB requires flat structure)
        metadata = {
            "source": chunk.source,
            "page": chunk.page,
            "chunk_index": chunk.chunk_index,
            "chunk_type": chunk.chunk_type,
        }
        # Add any extra metadata
        metadata.update(chunk.metadata)

        # Store in ChromaDB
        self.collection.upsert(
            ids=[chunk.chunk_id],
            embeddings=[embedding],
            documents=[chunk.content],
            metadatas=[metadata],
        )

        return chunk.chunk_id

    async def embed_and_store_batch(
        self,
        chunks: list[DocumentChunk],
        batch_size: int = 100,
    ) -> list[str]:
        """Embed and store multiple chunks efficiently.

        Args:
            chunks: List of DocumentChunks to process
            batch_size: Number of chunks to process at once

        Returns:
            List of chunk IDs
        """
        all_ids = []

        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]

            # Get embeddings for batch
            texts = [c.content for c in batch]
            embeddings = await self.embed_batch(texts)

            # Prepare data for ChromaDB
            ids = [c.chunk_id for c in batch]
            documents = texts
            metadatas = [
                {
                    "source": c.source,
                    "page": c.page,
                    "chunk_index": c.chunk_index,
                    "chunk_type": c.chunk_type,
                    **c.metadata,
                }
                for c in batch
            ]

            # Upsert batch
            self.collection.upsert(
                ids=ids,
                embeddings=embeddings,
                documents=documents,
                metadatas=metadatas,
            )

            all_ids.extend(ids)

        return all_ids

    def get_collection_stats(self) -> dict:
        """Get statistics about the collection."""
        return {
            "name": self.collection.name,
            "count": self.collection.count(),
        }
