"""Dataclasses passed between canon pipeline stages."""

from dataclasses import dataclass


@dataclass
class PageImage:
    """One rendered or extracted page image from a source PDF."""

    page_number: int  # 1-indexed
    image_bytes: bytes
    ext: str  # "png", "jpeg", or "jpg" -- the only formats the vision API accepts
    width: int
    height: int
    sha256: str


@dataclass
class PageTranscript:
    """Markdown transcription of a single page."""

    page_number: int
    markdown: str
    image_sha256: str
    model: str
    status: str = "ok"  # "ok" | "failed"
    error: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class Chapter:
    """A run of consecutive pages under one chapter heading."""

    slug: str
    title: str
    start_page: int
    end_page: int
    markdown: str
