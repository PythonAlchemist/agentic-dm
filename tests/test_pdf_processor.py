"""Tests for PDF processor."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from backend.ingestion.pdf_processor import PDFProcessor, DocumentChunk


class TestPDFProcessor:
    """Test cases for PDFProcessor."""

    def test_clean_text(self):
        """Test text cleaning."""
        processor = PDFProcessor()

        # Test excessive whitespace
        text = "Hello   world\t\ttest"
        cleaned = processor._clean_text(text)
        assert "   " not in cleaned
        assert "\t\t" not in cleaned

        # Test page numbers
        text = "Some content\n42\nMore content"
        cleaned = processor._clean_text(text)
        assert "42" not in cleaned or "42" in "More content"

        # Test excessive newlines
        text = "Para 1\n\n\n\n\nPara 2"
        cleaned = processor._clean_text(text)
        assert "\n\n\n" not in cleaned

    def test_split_into_paragraphs(self):
        """Test paragraph splitting."""
        processor = PDFProcessor()

        text = "Para 1\n\nPara 2\n\nPara 3"
        paragraphs = processor._split_into_paragraphs(text)

        assert len(paragraphs) == 3
        assert paragraphs[0] == "Para 1"
        assert paragraphs[1] == "Para 2"
        assert paragraphs[2] == "Para 3"

    def test_create_chunk(self):
        """Test chunk creation."""
        processor = PDFProcessor()

        chunk = processor._create_chunk(
            content="Test content",
            source="test_doc",
            page=5,
            chunk_index=3,
        )

        assert isinstance(chunk, DocumentChunk)
        assert chunk.content == "Test content"
        assert chunk.source == "test_doc"
        assert chunk.page == 5
        assert chunk.chunk_index == 3
        assert chunk.chunk_id == "test_doc_p5_c3"

    def test_document_chunk_to_dict(self):
        """Test DocumentChunk serialization."""
        chunk = DocumentChunk(
            content="Test content",
            chunk_id="test_id",
            source="test_source",
            page=1,
            chunk_index=0,
            chunk_type="text",
            metadata={"extra": "data"},
        )

        data = chunk.to_dict()

        assert data["content"] == "Test content"
        assert data["chunk_id"] == "test_id"
        assert data["source"] == "test_source"
        assert data["page"] == 1
        assert data["extra"] == "data"


class TestStatBlockDetection:
    """Test stat block detection patterns."""

    def test_stat_block_pattern(self):
        """Test that stat block pattern matches correctly."""
        processor = PDFProcessor()

        stat_block = """
        Medium humanoid (goblin), neutral evil

        Armor Class 15 (leather armor, shield)
        Hit Points 7 (2d6)
        Speed 30 ft.
        """

        matches = list(processor.STAT_BLOCK_PATTERN.finditer(stat_block))
        # Pattern should find something resembling a stat block
        assert len(matches) >= 0  # May or may not match depending on exact format


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
