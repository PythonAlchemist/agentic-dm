"""Stage 1: transcribe page images to markdown with a vision model."""

import asyncio
import base64
import logging
from collections.abc import Iterable

from openai import AsyncOpenAI

from backend.canon.cache import TranscriptCache
from backend.canon.models import PageImage, PageTranscript
from backend.core.config import settings

logger = logging.getLogger(__name__)

TRANSCRIPTION_PROMPT = """\
Transcribe this page of a D&D sourcebook into clean Markdown.

Rules:
- Preserve the heading hierarchy. Chapter titles are H1, sections H2, subsections H3.
- Preserve tables as Markdown tables.
- Preserve stat blocks verbatim, keeping every field (AC, HP, speed, ability scores,
  saves, skills, senses, languages, CR, traits, actions, reactions).
- Preserve boxed read-aloud text as Markdown blockquotes.
- For maps and illustrations, do NOT invent text. Emit a single italic line describing
  what is shown, e.g. *[Map: Castle Ravenloft, ground floor]*.
- Omit page numbers, running headers, and footers.
- Output only the Markdown. No commentary, no code fences around the whole page.
"""


class PageTranscriber:
    """Transcribe page images to Markdown, cache-first, failure-isolated."""

    def __init__(
        self,
        cache: TranscriptCache,
        client: AsyncOpenAI | None = None,
        model: str | None = None,
        concurrency: int = 8,
    ):
        self.cache = cache
        self.client = client or AsyncOpenAI(api_key=settings.openai_api_key)
        self.model = model or settings.openai_vision_model
        self._semaphore = asyncio.Semaphore(concurrency)

    async def transcribe_page(self, page: PageImage) -> PageTranscript:
        """Transcribe one page. Never raises; failures come back as status='failed'."""
        cached = self.cache.get(page.page_number, page.sha256)
        if cached is not None:
            return cached

        try:
            async with self._semaphore:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": TRANSCRIPTION_PROMPT},
                                {
                                    "type": "image_url",
                                    "image_url": {"url": self._data_url(page)},
                                },
                            ],
                        }
                    ],
                )
        except Exception as exc:  # noqa: BLE001 - one page must not abort the run
            logger.warning("Page %s transcription failed: %s", page.page_number, exc)
            return PageTranscript(
                page_number=page.page_number,
                markdown="",
                image_sha256=page.sha256,
                model=self.model,
                status="failed",
                error=str(exc),
            )

        transcript = PageTranscript(
            page_number=page.page_number,
            markdown=(response.choices[0].message.content or "").strip(),
            image_sha256=page.sha256,
            model=self.model,
            status="ok",
            input_tokens=response.usage.prompt_tokens,
            output_tokens=response.usage.completion_tokens,
        )
        self.cache.put(transcript)
        return transcript

    async def transcribe_pages(self, pages: Iterable[PageImage]) -> list[PageTranscript]:
        """Transcribe many pages concurrently, ordered by page number."""
        results = await asyncio.gather(*(self.transcribe_page(p) for p in pages))
        return sorted(results, key=lambda t: t.page_number)

    @staticmethod
    def _data_url(page: PageImage) -> str:
        mime = "jpeg" if page.ext in ("jpg", "jpeg") else page.ext
        encoded = base64.b64encode(page.image_bytes).decode("ascii")
        return f"data:image/{mime};base64,{encoded}"
