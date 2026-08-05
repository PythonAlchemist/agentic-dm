"""Stage 3: chunk canon chapters and embed them into ChromaDB."""

from backend.canon.models import Chapter
from backend.ingestion.embeddings import EmbeddingPipeline
from backend.ingestion.pdf_processor import DocumentChunk, PDFProcessor


def chapter_to_chunks(
    chapter: Chapter,
    book_slug: str,
    start_index: int = 0,
) -> list[DocumentChunk]:
    """Chunk one chapter, tagging every chunk with its canon provenance.

    The chapter's first page is recorded as the chunk page, so retrieved prose
    can be traced back to a location in the book.
    """
    if not chapter.markdown.strip():
        return []

    processor = PDFProcessor()
    chunks = processor.chunk_text(
        text=chapter.markdown,
        source=book_slug,
        page=chapter.start_page,
        start_index=start_index,
    )

    for chunk in chunks:
        chunk.metadata.update(
            {
                "book_slug": book_slug,
                "chapter_slug": chapter.slug,
                "chapter_title": chapter.title,
                "plane": "canon",
            }
        )

    return chunks


async def clear_book_chunks(
    book_slug: str,
    pipeline: EmbeddingPipeline | None = None,
) -> int:
    """Delete every stored chunk for a book. Returns how many were removed.

    Chunk IDs encode page and chunk index, both of which shift when chapter
    grouping changes. Without clearing first, a re-run upserts a new set beside
    the stale one and the collection holds two contradictory versions of the book.
    """
    pipeline = pipeline or EmbeddingPipeline()
    existing = pipeline.collection.get(where={"source": book_slug})
    ids = existing.get("ids", [])
    if ids:
        pipeline.collection.delete(ids=ids)
    return len(ids)


async def ingest_chapters(
    chapters: list[Chapter],
    book_slug: str,
    pipeline: EmbeddingPipeline | None = None,
    batch_size: int = 100,
) -> list[str]:
    """Chunk and embed every chapter. Returns the stored chunk IDs."""
    all_chunks: list[DocumentChunk] = []
    for chapter in chapters:
        all_chunks.extend(
            chapter_to_chunks(chapter, book_slug, start_index=len(all_chunks))
        )

    if not all_chunks:
        return []

    pipeline = pipeline or EmbeddingPipeline()
    return await pipeline.embed_and_store_batch(all_chunks, batch_size=batch_size)
