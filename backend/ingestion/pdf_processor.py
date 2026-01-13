"""PDF processing with intelligent chunking for D&D content."""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import fitz  # pymupdf
import tiktoken

from backend.core.config import settings


@dataclass
class DocumentChunk:
    """A chunk of document content with metadata."""

    content: str
    chunk_id: str
    source: str
    page: int
    chunk_index: int
    chunk_type: str = "text"  # text, stat_block, table, spell, item
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            "content": self.content,
            "chunk_id": self.chunk_id,
            "source": self.source,
            "page": self.page,
            "chunk_index": self.chunk_index,
            "chunk_type": self.chunk_type,
            **self.metadata,
        }


class PDFProcessor:
    """Process PDF documents into chunks for embedding."""

    # Patterns for D&D content detection
    STAT_BLOCK_PATTERN = re.compile(
        r"(?:^|\n)((?:Tiny|Small|Medium|Large|Huge|Gargantuan)\s+\w+.*?"
        r"(?:AC|Armor Class)\s*\d+.*?"
        r"(?:HP|Hit Points)\s*\d+)",
        re.DOTALL | re.IGNORECASE,
    )

    SPELL_PATTERN = re.compile(
        r"(?:^|\n)([A-Z][a-z]+(?:\s+[A-Z]?[a-z]+)*)\n"
        r"(\d+(?:st|nd|rd|th)-level\s+\w+|[Cc]antrip)",
        re.MULTILINE,
    )

    SECTION_HEADERS = re.compile(
        r"^(Chapter\s+\d+|Part\s+\d+|Appendix\s+[A-Z]|[A-Z][A-Z\s]+)$",
        re.MULTILINE,
    )

    def __init__(
        self,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
    ):
        """Initialize the PDF processor.

        Args:
            chunk_size: Maximum tokens per chunk (default from settings)
            chunk_overlap: Token overlap between chunks (default from settings)
        """
        self.chunk_size = chunk_size or settings.chunk_size
        self.chunk_overlap = chunk_overlap or settings.chunk_overlap
        self.tokenizer = tiktoken.encoding_for_model("gpt-4")

    def process(self, pdf_path: str | Path) -> list[DocumentChunk]:
        """Process a PDF file into chunks.

        Args:
            pdf_path: Path to the PDF file

        Returns:
            List of DocumentChunk objects
        """
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        source_name = pdf_path.stem

        doc = fitz.open(pdf_path)
        chunks: list[DocumentChunk] = []
        chunk_index = 0

        for page_num in range(len(doc)):
            page = doc[page_num]
            page_text = page.get_text()

            if not page_text.strip():
                continue

            # Extract different content types
            page_chunks = self._process_page(
                text=page_text,
                source=source_name,
                page=page_num + 1,  # 1-indexed
                start_index=chunk_index,
            )

            chunks.extend(page_chunks)
            chunk_index += len(page_chunks)

        doc.close()

        return chunks

    def _process_page(
        self,
        text: str,
        source: str,
        page: int,
        start_index: int,
    ) -> list[DocumentChunk]:
        """Process a single page into chunks."""
        chunks = []

        # First, try to extract special content blocks
        special_chunks, remaining_text = self._extract_special_content(
            text=text,
            source=source,
            page=page,
            start_index=start_index,
        )
        chunks.extend(special_chunks)

        # Then chunk the remaining text
        if remaining_text.strip():
            text_chunks = self._chunk_text(
                text=remaining_text,
                source=source,
                page=page,
                start_index=start_index + len(special_chunks),
            )
            chunks.extend(text_chunks)

        return chunks

    def _extract_special_content(
        self,
        text: str,
        source: str,
        page: int,
        start_index: int,
    ) -> tuple[list[DocumentChunk], str]:
        """Extract stat blocks, spells, and other special content."""
        chunks = []
        remaining = text
        chunk_idx = start_index

        # Extract stat blocks
        for match in self.STAT_BLOCK_PATTERN.finditer(text):
            stat_block = match.group(1).strip()
            if len(stat_block) > 100:  # Minimum reasonable stat block
                chunks.append(
                    DocumentChunk(
                        content=stat_block,
                        chunk_id=f"{source}_p{page}_c{chunk_idx}",
                        source=source,
                        page=page,
                        chunk_index=chunk_idx,
                        chunk_type="stat_block",
                        metadata={"content_type": "monster_stat_block"},
                    )
                )
                chunk_idx += 1
                remaining = remaining.replace(match.group(0), "\n", 1)

        return chunks, remaining

    def _chunk_text(
        self,
        text: str,
        source: str,
        page: int,
        start_index: int,
    ) -> list[DocumentChunk]:
        """Chunk text content with token-aware splitting."""
        chunks = []
        chunk_idx = start_index

        # Clean text
        text = self._clean_text(text)

        if not text.strip():
            return chunks

        # Split into sentences/paragraphs first
        paragraphs = self._split_into_paragraphs(text)

        current_chunk = []
        current_tokens = 0

        for para in paragraphs:
            para_tokens = len(self.tokenizer.encode(para))

            # If paragraph alone exceeds chunk size, split it
            if para_tokens > self.chunk_size:
                # Flush current chunk first
                if current_chunk:
                    chunks.append(
                        self._create_chunk(
                            content="\n\n".join(current_chunk),
                            source=source,
                            page=page,
                            chunk_index=chunk_idx,
                        )
                    )
                    chunk_idx += 1
                    current_chunk = []
                    current_tokens = 0

                # Split large paragraph
                sub_chunks = self._split_large_text(para, source, page, chunk_idx)
                chunks.extend(sub_chunks)
                chunk_idx += len(sub_chunks)
                continue

            # Check if adding this paragraph exceeds limit
            if current_tokens + para_tokens > self.chunk_size:
                # Save current chunk
                if current_chunk:
                    chunks.append(
                        self._create_chunk(
                            content="\n\n".join(current_chunk),
                            source=source,
                            page=page,
                            chunk_index=chunk_idx,
                        )
                    )
                    chunk_idx += 1

                    # Keep overlap
                    overlap_text = self._get_overlap_text(current_chunk)
                    if overlap_text:
                        current_chunk = [overlap_text]
                        current_tokens = len(self.tokenizer.encode(overlap_text))
                    else:
                        current_chunk = []
                        current_tokens = 0

            current_chunk.append(para)
            current_tokens += para_tokens

        # Don't forget the last chunk
        if current_chunk:
            chunks.append(
                self._create_chunk(
                    content="\n\n".join(current_chunk),
                    source=source,
                    page=page,
                    chunk_index=chunk_idx,
                )
            )

        return chunks

    def _create_chunk(
        self,
        content: str,
        source: str,
        page: int,
        chunk_index: int,
        chunk_type: str = "text",
    ) -> DocumentChunk:
        """Create a DocumentChunk instance."""
        return DocumentChunk(
            content=content,
            chunk_id=f"{source}_p{page}_c{chunk_index}",
            source=source,
            page=page,
            chunk_index=chunk_index,
            chunk_type=chunk_type,
        )

    def _split_into_paragraphs(self, text: str) -> list[str]:
        """Split text into paragraphs."""
        # Split on double newlines or section breaks
        paragraphs = re.split(r"\n\s*\n", text)
        return [p.strip() for p in paragraphs if p.strip()]

    def _split_large_text(
        self,
        text: str,
        source: str,
        page: int,
        start_index: int,
    ) -> list[DocumentChunk]:
        """Split text that exceeds chunk size by sentences."""
        chunks = []
        sentences = re.split(r"(?<=[.!?])\s+", text)

        current_chunk = []
        current_tokens = 0
        chunk_idx = start_index

        for sentence in sentences:
            sent_tokens = len(self.tokenizer.encode(sentence))

            if current_tokens + sent_tokens > self.chunk_size:
                if current_chunk:
                    chunks.append(
                        self._create_chunk(
                            content=" ".join(current_chunk),
                            source=source,
                            page=page,
                            chunk_index=chunk_idx,
                        )
                    )
                    chunk_idx += 1
                    current_chunk = []
                    current_tokens = 0

            current_chunk.append(sentence)
            current_tokens += sent_tokens

        if current_chunk:
            chunks.append(
                self._create_chunk(
                    content=" ".join(current_chunk),
                    source=source,
                    page=page,
                    chunk_index=chunk_idx,
                )
            )

        return chunks

    def _get_overlap_text(self, chunks: list[str]) -> Optional[str]:
        """Get text for overlap from previous chunk."""
        if not chunks:
            return None

        # Take last paragraph(s) up to overlap token count
        overlap_parts = []
        overlap_tokens = 0

        for para in reversed(chunks):
            para_tokens = len(self.tokenizer.encode(para))
            if overlap_tokens + para_tokens <= self.chunk_overlap:
                overlap_parts.insert(0, para)
                overlap_tokens += para_tokens
            else:
                break

        return "\n\n".join(overlap_parts) if overlap_parts else None

    def _clean_text(self, text: str) -> str:
        """Clean and normalize text."""
        # Remove excessive whitespace
        text = re.sub(r"[ \t]+", " ", text)
        # Remove page numbers and headers (common pattern)
        text = re.sub(r"^\d+\s*$", "", text, flags=re.MULTILINE)
        # Normalize newlines
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
