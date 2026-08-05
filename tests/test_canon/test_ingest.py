"""Tests for chunking and embedding canon chapters."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.canon.ingest import chapter_to_chunks, clear_book_chunks, ingest_chapters
from backend.canon.models import Chapter


def make_chapter(markdown: str = "Some prose about Barovia.") -> Chapter:
    return Chapter(
        slug="chapter-3-the-village-of-barovia",
        title="Chapter 3: The Village of Barovia",
        start_page=43,
        end_page=52,
        markdown=markdown,
    )


class TestChapterToChunks:
    def test_produces_chunks_with_canon_metadata(self):
        chunks = chapter_to_chunks(make_chapter(), book_slug="cos")

        assert len(chunks) >= 1
        assert all(c.source == "cos" for c in chunks)
        assert all(c.metadata["book_slug"] == "cos" for c in chunks)
        assert all(
            c.metadata["chapter_slug"] == "chapter-3-the-village-of-barovia"
            for c in chunks
        )
        assert all(c.metadata["plane"] == "canon" for c in chunks)
        # `page` is stamped as the chapter's start page (see test_chunk_page_is_chapter_start),
        # which understates the true location for chunks from later in a long chapter. These
        # two carry the honest range alongside it until per-chunk page tracking exists.
        assert all(c.metadata["chapter_start_page"] == 43 for c in chunks)
        assert all(c.metadata["chapter_end_page"] == 52 for c in chunks)

    def test_chunk_page_is_chapter_start(self):
        chunks = chapter_to_chunks(make_chapter(), book_slug="cos")
        assert all(c.page == 43 for c in chunks)

    def test_chunk_ids_are_unique(self):
        long_markdown = "\n\n".join(f"Paragraph {i}. " * 200 for i in range(12))
        chunks = chapter_to_chunks(make_chapter(long_markdown), book_slug="cos")

        assert len(chunks) > 1
        assert len({c.chunk_id for c in chunks}) == len(chunks)

    def test_start_index_offsets_chunk_ids(self):
        first = chapter_to_chunks(make_chapter(), book_slug="cos", start_index=0)
        second = chapter_to_chunks(make_chapter(), book_slug="cos", start_index=50)

        assert first[0].chunk_id != second[0].chunk_id

    def test_empty_chapter_produces_no_chunks(self):
        assert chapter_to_chunks(make_chapter("   "), book_slug="cos") == []


class TestIngestChapters:
    @pytest.mark.asyncio
    async def test_embeds_and_returns_ids(self):
        pipeline = MagicMock()
        pipeline.embed_and_store_batch = AsyncMock(return_value=["cos_p43_c0"])

        ids = await ingest_chapters([make_chapter()], book_slug="cos", pipeline=pipeline)

        assert ids == ["cos_p43_c0"]
        pipeline.embed_and_store_batch.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_chapters_makes_no_calls(self):
        pipeline = MagicMock()
        pipeline.embed_and_store_batch = AsyncMock()

        ids = await ingest_chapters([], book_slug="cos", pipeline=pipeline)

        assert ids == []
        pipeline.embed_and_store_batch.assert_not_awaited()


class TestClearBookChunks:
    @pytest.mark.asyncio
    async def test_deletes_existing_chunks_and_returns_count(self):
        pipeline = MagicMock()
        pipeline.collection.get = MagicMock(
            return_value={"ids": ["cos_p1_c0", "cos_p1_c1"]}
        )
        pipeline.collection.delete = MagicMock()

        removed = await clear_book_chunks("cos", pipeline=pipeline)

        assert removed == 2
        pipeline.collection.get.assert_called_once_with(where={"source": "cos"})
        pipeline.collection.delete.assert_called_once_with(
            ids=["cos_p1_c0", "cos_p1_c1"]
        )

    @pytest.mark.asyncio
    async def test_no_delete_call_when_nothing_stored(self):
        pipeline = MagicMock()
        pipeline.collection.get = MagicMock(return_value={"ids": []})
        pipeline.collection.delete = MagicMock()

        removed = await clear_book_chunks("cos", pipeline=pipeline)

        assert removed == 0
        pipeline.collection.delete.assert_not_called()
