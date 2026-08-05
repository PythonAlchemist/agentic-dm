"""Canon ingestion: turn published sourcebooks into text and graph data."""

from backend.canon.models import Chapter, PageImage, PageTranscript

__all__ = ["Chapter", "PageImage", "PageTranscript"]
