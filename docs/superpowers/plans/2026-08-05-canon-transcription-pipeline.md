# Canon Transcription Pipeline (Stages 0–3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `data/cos.pdf` — 509 page images with no text layer — into chapter-organized markdown embedded in ChromaDB, so the existing RAG pipeline has a real Curse of Strahd corpus.

**Architecture:** Four stages in a new `backend/canon/` module. Extract embedded page images from the PDF, transcribe each to markdown with a vision model (cached by content hash so re-runs are free), group pages into chapters by detected headings, then chunk and embed through the existing `backend/ingestion/` pipeline. Each stage is a separate module with a dataclass interface between them.

**Tech Stack:** Python 3.12, pymupdf (fitz), OpenAI `gpt-4o` vision + `text-embedding-3-small`, ChromaDB, pytest + pytest-asyncio.

## Global Constraints

- Python `>=3.12`. Type hints use builtin generics (`list[str]`, `str | None`), not `typing.List`.
- Async OpenAI calls use `AsyncOpenAI`, matching `backend/ingestion/embeddings.py:21`.
- Async tests require an explicit `@pytest.mark.asyncio` decorator — pytest-asyncio 1.3.0 runs in strict mode and there is no `asyncio_mode` config in `pyproject.toml`.
- Ruff config: `line-length = 100`, `target-version = "py312"`, lint rules `["E", "F", "I", "UP"]`.
- Transcription model is `gpt-4o`, **not** `gpt-4o-mini`. Per the spec, transcription errors propagate into every downstream extraction pass and into the RAG chunks; this is the one stage where quality compounds.
- Vision transcription runs **once per page**. Never re-send page images for multiple extraction passes.
- Book slug for Curse of Strahd is `cos`. Cache root is `data/canon/<book_slug>/`.
- `data/` is gitignored — never commit transcripts or page images.
- No network calls in tests. All OpenAI clients are mocked.

---

## File Structure

**Created:**
- `backend/canon/__init__.py` — module exports
- `backend/canon/models.py` — `PageImage`, `PageTranscript`, `Chapter` dataclasses; the interface between stages
- `backend/canon/page_extractor.py` — Stage 0: PDF → page images
- `backend/canon/cache.py` — hash-validated transcript cache
- `backend/canon/transcriber.py` — Stage 1: page image → markdown
- `backend/canon/assembler.py` — Stage 2: pages → chapters
- `backend/canon/ingest.py` — Stage 3: chapters → ChromaDB
- `backend/scripts/ingest_canon.py` — CLI orchestrating stages 0–3
- `tests/test_canon/__init__.py`
- `tests/test_canon/test_page_extractor.py`
- `tests/test_canon/test_cache.py`
- `tests/test_canon/test_transcriber.py`
- `tests/test_canon/test_assembler.py`
- `tests/test_canon/test_ingest.py`

**Modified:**
- `backend/core/config.py` — add `openai_vision_model` and `canon_dir` settings
- `backend/ingestion/pdf_processor.py` — add a public `chunk_text()` wrapper so canon can reuse chunking without calling a private method

---

### Task 1: Page image extraction (Stage 0)

Extracts one image per PDF page. Pages in `cos.pdf` each carry exactly one embedded image at ~1278×1800; when a page has zero or several images, render the page instead so the output is always exactly one image per page.

**Files:**
- Create: `backend/canon/__init__.py`
- Create: `backend/canon/models.py`
- Create: `backend/canon/page_extractor.py`
- Create: `tests/test_canon/__init__.py`
- Create: `tests/test_canon/test_page_extractor.py`
- Modify: `backend/core/config.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `PageImage(page_number: int, image_bytes: bytes, ext: str, width: int, height: int, sha256: str)` — `page_number` is 1-indexed
  - `PageExtractor(pdf_path: str | Path)` with `.page_count -> int` and `.extract(pages: range | None = None) -> Iterator[PageImage]`

- [ ] **Step 1: Write the failing test**

Create `tests/test_canon/__init__.py` as an empty file, then `tests/test_canon/test_page_extractor.py`:

```python
"""Tests for canon page image extraction."""

import fitz
import pytest

from backend.canon.page_extractor import PageExtractor


@pytest.fixture
def pdf_with_images(tmp_path):
    """A 3-page PDF where each page has one embedded image."""
    doc = fitz.open()
    for _ in range(3):
        page = doc.new_page(width=200, height=300)
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 100, 150))
        pix.clear_with(128)
        page.insert_image(fitz.Rect(0, 0, 100, 150), pixmap=pix)
    path = tmp_path / "with_images.pdf"
    doc.save(path)
    doc.close()
    return path


@pytest.fixture
def pdf_without_images(tmp_path):
    """A 2-page PDF with text only and no embedded images."""
    doc = fitz.open()
    for _ in range(2):
        page = doc.new_page(width=200, height=300)
        page.insert_text((50, 50), "hello")
    path = tmp_path / "no_images.pdf"
    doc.save(path)
    doc.close()
    return path


class TestPageExtractor:
    def test_yields_one_image_per_page(self, pdf_with_images):
        extractor = PageExtractor(pdf_with_images)
        pages = list(extractor.extract())

        assert extractor.page_count == 3
        assert len(pages) == 3
        assert [p.page_number for p in pages] == [1, 2, 3]
        assert all(p.image_bytes for p in pages)
        assert all(p.width > 0 and p.height > 0 for p in pages)

    def test_sha256_is_stable_across_runs(self, pdf_with_images):
        first = list(PageExtractor(pdf_with_images).extract())
        second = list(PageExtractor(pdf_with_images).extract())

        assert [p.sha256 for p in first] == [p.sha256 for p in second]
        assert all(len(p.sha256) == 64 for p in first)

    def test_renders_page_when_no_embedded_image(self, pdf_without_images):
        pages = list(PageExtractor(pdf_without_images).extract())

        assert len(pages) == 2
        assert all(p.image_bytes for p in pages)
        assert all(p.ext == "png" for p in pages)

    def test_page_range_selects_subset(self, pdf_with_images):
        pages = list(PageExtractor(pdf_with_images).extract(pages=range(2, 3)))

        assert [p.page_number for p in pages] == [2]

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            PageExtractor(tmp_path / "nope.pdf")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_canon/test_page_extractor.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.canon'`

- [ ] **Step 3: Add settings**

In `backend/core/config.py`, add `canon_dir` immediately after the `audio_dir` line (currently line 24):

```python
    canon_dir: Path = data_dir / "canon"
```

And add a vision model setting immediately after `openai_embedding_model` (currently line 29):

```python
    openai_vision_model: str = "gpt-4o"
```

- [ ] **Step 4: Write the models**

Create `backend/canon/__init__.py`:

```python
"""Canon ingestion: turn published sourcebooks into text and graph data."""

from backend.canon.models import Chapter, PageImage, PageTranscript

__all__ = ["Chapter", "PageImage", "PageTranscript"]
```

Create `backend/canon/models.py`:

```python
"""Dataclasses passed between canon pipeline stages."""

from dataclasses import dataclass


@dataclass
class PageImage:
    """One rendered or extracted page image from a source PDF."""

    page_number: int  # 1-indexed
    image_bytes: bytes
    ext: str  # "png" or "jpeg"
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
```

- [ ] **Step 5: Write the extractor**

Create `backend/canon/page_extractor.py`:

```python
"""Stage 0: extract one image per page from a source PDF."""

import hashlib
from collections.abc import Iterator
from pathlib import Path

import fitz  # pymupdf

from backend.canon.models import PageImage

RENDER_DPI = 150


class PageExtractor:
    """Yield exactly one image per page of a PDF.

    Pages in scanned flipbook PDFs carry a single embedded image, which is
    extracted directly to avoid a lossy re-encode. Pages with zero or several
    images are rendered instead, so callers always get one image per page.
    """

    def __init__(self, pdf_path: str | Path):
        self.pdf_path = Path(pdf_path)
        if not self.pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {self.pdf_path}")
        self._doc = fitz.open(self.pdf_path)

    @property
    def page_count(self) -> int:
        return self._doc.page_count

    def extract(self, pages: range | None = None) -> Iterator[PageImage]:
        """Yield a PageImage for each requested page.

        Args:
            pages: 1-indexed page numbers to extract. Defaults to every page.
        """
        wanted = pages if pages is not None else range(1, self.page_count + 1)

        for page_number in wanted:
            page = self._doc[page_number - 1]
            images = page.get_images(full=True)

            if len(images) == 1:
                info = self._doc.extract_image(images[0][0])
                data, ext = info["image"], info["ext"]
                width, height = info["width"], info["height"]
            else:
                pix = page.get_pixmap(dpi=RENDER_DPI)
                data, ext = pix.tobytes("png"), "png"
                width, height = pix.width, pix.height

            yield PageImage(
                page_number=page_number,
                image_bytes=data,
                ext=ext,
                width=width,
                height=height,
                sha256=hashlib.sha256(data).hexdigest(),
            )

    def close(self) -> None:
        self._doc.close()
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_canon/test_page_extractor.py -v`
Expected: 5 passed

- [ ] **Step 7: Verify against the real book**

Run:

```bash
uv run python -c "
from backend.canon.page_extractor import PageExtractor
e = PageExtractor('data/cos.pdf')
print('pages:', e.page_count)
p = next(e.extract(pages=range(61, 62)))
print(p.page_number, p.ext, p.width, p.height, p.sha256[:12])
"
```

Expected: `pages: 509` and a page 61 image around 1278×1800. If dimensions are far off, stop — the cost model in the spec assumed this size.

- [ ] **Step 8: Commit**

```bash
git add backend/canon/__init__.py backend/canon/models.py backend/canon/page_extractor.py \
        backend/core/config.py tests/test_canon/
git commit -m "feat(canon): extract one image per PDF page"
```

---

### Task 2: Hash-validated transcript cache

Transcription is ~90% of pipeline cost and its input never changes. This cache is what makes re-running downstream stages cost cents instead of dollars.

**Files:**
- Create: `backend/canon/cache.py`
- Create: `tests/test_canon/test_cache.py`

**Interfaces:**
- Consumes: `PageTranscript` from Task 1
- Produces: `TranscriptCache(root: Path)` with `.get(page_number: int, sha256: str) -> PageTranscript | None`, `.put(transcript: PageTranscript) -> None`, `.page_path(page_number: int) -> Path`

- [ ] **Step 1: Write the failing test**

Create `tests/test_canon/test_cache.py`:

```python
"""Tests for the canon transcript cache."""

import pytest

from backend.canon.cache import TranscriptCache
from backend.canon.models import PageTranscript


@pytest.fixture
def transcript():
    return PageTranscript(
        page_number=61,
        markdown="# Village of Barovia\n\nText.",
        image_sha256="a" * 64,
        model="gpt-4o",
        input_tokens=1105,
        output_tokens=900,
    )


class TestTranscriptCache:
    def test_get_returns_none_on_miss(self, tmp_path):
        cache = TranscriptCache(tmp_path)
        assert cache.get(61, "a" * 64) is None

    def test_put_then_get_roundtrip(self, tmp_path, transcript):
        cache = TranscriptCache(tmp_path)
        cache.put(transcript)

        got = cache.get(61, "a" * 64)
        assert got is not None
        assert got.markdown == transcript.markdown
        assert got.page_number == 61
        assert got.model == "gpt-4o"

    def test_hash_mismatch_is_a_miss(self, tmp_path, transcript):
        """A changed source image must invalidate the cached page."""
        cache = TranscriptCache(tmp_path)
        cache.put(transcript)

        assert cache.get(61, "b" * 64) is None

    def test_writes_human_readable_markdown(self, tmp_path, transcript):
        cache = TranscriptCache(tmp_path)
        cache.put(transcript)

        assert cache.page_path(61).read_text() == transcript.markdown

    def test_failed_transcripts_are_not_cached(self, tmp_path):
        """A failure must not poison the cache and block a later retry."""
        cache = TranscriptCache(tmp_path)
        cache.put(
            PageTranscript(
                page_number=7,
                markdown="",
                image_sha256="c" * 64,
                model="gpt-4o",
                status="failed",
                error="timeout",
            )
        )

        assert cache.get(7, "c" * 64) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_canon/test_cache.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.canon.cache'`

- [ ] **Step 3: Write the cache**

Create `backend/canon/cache.py`:

```python
"""Content-hash-validated cache for page transcriptions."""

import json
from pathlib import Path

from backend.canon.models import PageTranscript


class TranscriptCache:
    """Store page transcripts on disk, keyed by page and validated by image hash.

    Files are written per page rather than per hash so the output stays
    human-browsable. The sidecar records the source image hash; a mismatch is
    treated as a miss, so changing the source PDF re-transcribes automatically.
    """

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.pages_dir = self.root / "pages"

    def page_path(self, page_number: int) -> Path:
        return self.pages_dir / f"{page_number:04d}.md"

    def _meta_path(self, page_number: int) -> Path:
        return self.pages_dir / f"{page_number:04d}.json"

    def get(self, page_number: int, sha256: str) -> PageTranscript | None:
        """Return the cached transcript, or None on miss or hash mismatch."""
        md_path = self.page_path(page_number)
        meta_path = self._meta_path(page_number)
        if not md_path.exists() or not meta_path.exists():
            return None

        meta = json.loads(meta_path.read_text())
        if meta.get("image_sha256") != sha256:
            return None

        return PageTranscript(
            page_number=page_number,
            markdown=md_path.read_text(),
            image_sha256=sha256,
            model=meta.get("model", ""),
            status="ok",
            input_tokens=meta.get("input_tokens", 0),
            output_tokens=meta.get("output_tokens", 0),
        )

    def put(self, transcript: PageTranscript) -> None:
        """Persist a successful transcript. Failures are intentionally not cached."""
        if transcript.status != "ok":
            return

        self.pages_dir.mkdir(parents=True, exist_ok=True)
        self.page_path(transcript.page_number).write_text(transcript.markdown)
        self._meta_path(transcript.page_number).write_text(
            json.dumps(
                {
                    "image_sha256": transcript.image_sha256,
                    "model": transcript.model,
                    "input_tokens": transcript.input_tokens,
                    "output_tokens": transcript.output_tokens,
                },
                indent=2,
            )
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_canon/test_cache.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add backend/canon/cache.py tests/test_canon/test_cache.py
git commit -m "feat(canon): add hash-validated transcript cache"
```

---

### Task 3: Vision transcriber (Stage 1)

Transcribes page images to markdown, cache-first, with per-page failure isolation so one bad page cannot abort a 509-page run.

**Files:**
- Create: `backend/canon/transcriber.py`
- Create: `tests/test_canon/test_transcriber.py`

**Interfaces:**
- Consumes: `PageImage` (Task 1), `TranscriptCache` (Task 2)
- Produces: `PageTranscriber(cache: TranscriptCache, client=None, model: str | None = None, concurrency: int = 8)` with `async .transcribe_page(page: PageImage) -> PageTranscript` and `async .transcribe_pages(pages: Iterable[PageImage]) -> list[PageTranscript]` (returned list is sorted by `page_number`)

- [ ] **Step 1: Write the failing test**

Create `tests/test_canon/test_transcriber.py`:

```python
"""Tests for vision page transcription."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.canon.cache import TranscriptCache
from backend.canon.models import PageImage, PageTranscript
from backend.canon.transcriber import PageTranscriber


def make_page(page_number: int = 61, sha: str = "a" * 64) -> PageImage:
    return PageImage(
        page_number=page_number,
        image_bytes=b"fake-image-bytes",
        ext="png",
        width=1278,
        height=1800,
        sha256=sha,
    )


def make_client(markdown: str = "# Heading\n\nBody.") -> MagicMock:
    """A mock AsyncOpenAI whose completion returns `markdown`."""
    message = MagicMock()
    message.content = markdown
    choice = MagicMock()
    choice.message = message
    usage = MagicMock()
    usage.prompt_tokens = 1105
    usage.completion_tokens = 900
    response = MagicMock()
    response.choices = [choice]
    response.usage = usage

    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=response)
    return client


class TestPageTranscriber:
    @pytest.mark.asyncio
    async def test_transcribes_a_page(self, tmp_path):
        client = make_client("# Village of Barovia\n\nProse.")
        transcriber = PageTranscriber(TranscriptCache(tmp_path), client=client)

        result = await transcriber.transcribe_page(make_page())

        assert result.status == "ok"
        assert result.markdown == "# Village of Barovia\n\nProse."
        assert result.page_number == 61
        assert result.input_tokens == 1105
        assert result.output_tokens == 900

    @pytest.mark.asyncio
    async def test_result_is_cached(self, tmp_path):
        cache = TranscriptCache(tmp_path)
        client = make_client()
        await PageTranscriber(cache, client=client).transcribe_page(make_page())

        assert cache.get(61, "a" * 64) is not None

    @pytest.mark.asyncio
    async def test_cache_hit_skips_the_api(self, tmp_path):
        cache = TranscriptCache(tmp_path)
        cache.put(
            PageTranscript(
                page_number=61,
                markdown="cached",
                image_sha256="a" * 64,
                model="gpt-4o",
            )
        )
        client = make_client()
        transcriber = PageTranscriber(cache, client=client)

        result = await transcriber.transcribe_page(make_page())

        assert result.markdown == "cached"
        client.chat.completions.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_failure_is_isolated_not_raised(self, tmp_path):
        client = MagicMock()
        client.chat.completions.create = AsyncMock(side_effect=RuntimeError("boom"))
        transcriber = PageTranscriber(TranscriptCache(tmp_path), client=client)

        result = await transcriber.transcribe_page(make_page())

        assert result.status == "failed"
        assert "boom" in result.error
        assert result.markdown == ""

    @pytest.mark.asyncio
    async def test_one_failure_does_not_abort_the_batch(self, tmp_path):
        ok = make_client().chat.completions.create.return_value
        client = MagicMock()
        client.chat.completions.create = AsyncMock(
            side_effect=[ok, RuntimeError("boom"), ok]
        )
        transcriber = PageTranscriber(TranscriptCache(tmp_path), client=client)

        results = await transcriber.transcribe_pages(
            [make_page(1, "a" * 64), make_page(2, "b" * 64), make_page(3, "c" * 64)]
        )

        assert [r.page_number for r in results] == [1, 2, 3]
        assert [r.status for r in results] == ["ok", "failed", "ok"]

    @pytest.mark.asyncio
    async def test_sends_image_as_data_url(self, tmp_path):
        client = make_client()
        await PageTranscriber(TranscriptCache(tmp_path), client=client).transcribe_page(
            make_page()
        )

        kwargs = client.chat.completions.create.call_args.kwargs
        content = kwargs["messages"][0]["content"]
        image_part = next(p for p in content if p["type"] == "image_url")
        assert image_part["image_url"]["url"].startswith("data:image/png;base64,")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_canon/test_transcriber.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.canon.transcriber'`

- [ ] **Step 3: Write the transcriber**

Create `backend/canon/transcriber.py`:

```python
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

    async def transcribe_pages(
        self, pages: Iterable[PageImage]
    ) -> list[PageTranscript]:
        """Transcribe many pages concurrently, ordered by page number."""
        results = await asyncio.gather(
            *(self.transcribe_page(p) for p in pages)
        )
        return sorted(results, key=lambda t: t.page_number)

    @staticmethod
    def _data_url(page: PageImage) -> str:
        mime = "jpeg" if page.ext in ("jpg", "jpeg") else page.ext
        encoded = base64.b64encode(page.image_bytes).decode("ascii")
        return f"data:image/{mime};base64,{encoded}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_canon/test_transcriber.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add backend/canon/transcriber.py tests/test_canon/test_transcriber.py
git commit -m "feat(canon): add vision page transcriber with cache and failure isolation"
```

---

### Task 4: Chapter assembler (Stage 2)

Groups consecutive page transcripts into chapters using H1 headings emitted by Task 3.

**Files:**
- Create: `backend/canon/assembler.py`
- Create: `tests/test_canon/test_assembler.py`

**Interfaces:**
- Consumes: `PageTranscript` (Task 3)
- Produces: `assemble_chapters(transcripts: list[PageTranscript]) -> list[Chapter]`, `slugify(title: str) -> str`

- [ ] **Step 1: Write the failing test**

Create `tests/test_canon/test_assembler.py`:

```python
"""Tests for grouping page transcripts into chapters."""

from backend.canon.assembler import assemble_chapters, slugify
from backend.canon.models import PageTranscript


def page(n: int, markdown: str) -> PageTranscript:
    return PageTranscript(
        page_number=n, markdown=markdown, image_sha256="x" * 64, model="gpt-4o"
    )


class TestSlugify:
    def test_lowercases_and_hyphenates(self):
        assert slugify("Chapter 3: The Village of Barovia") == "chapter-3-the-village-of-barovia"

    def test_strips_punctuation_and_collapses_separators(self):
        assert slugify("Appendix A -- Fortunes  of Ravenloft!") == "appendix-a-fortunes-of-ravenloft"


class TestAssembleChapters:
    def test_groups_pages_under_headings(self):
        chapters = assemble_chapters(
            [
                page(1, "# Introduction\n\nIntro text."),
                page(2, "More intro."),
                page(3, "# Chapter 1: Into the Mists\n\nMist text."),
                page(4, "More mist."),
            ]
        )

        assert [c.title for c in chapters] == ["Introduction", "Chapter 1: Into the Mists"]
        assert chapters[0].start_page == 1
        assert chapters[0].end_page == 2
        assert chapters[1].start_page == 3
        assert chapters[1].end_page == 4
        assert "More mist." in chapters[1].markdown

    def test_pages_before_first_heading_become_front_matter(self):
        chapters = assemble_chapters(
            [page(1, "Cover art."), page(2, "# Introduction\n\nText.")]
        )

        assert chapters[0].slug == "front-matter"
        assert chapters[0].start_page == 1
        assert chapters[1].title == "Introduction"

    def test_failed_pages_are_skipped(self):
        bad = page(2, "")
        bad.status = "failed"
        chapters = assemble_chapters([page(1, "# Intro\n\nA."), bad, page(3, "C.")])

        assert len(chapters) == 1
        assert chapters[0].end_page == 3
        assert "C." in chapters[0].markdown

    def test_empty_input_returns_empty_list(self):
        assert assemble_chapters([]) == []

    def test_duplicate_titles_get_distinct_slugs(self):
        chapters = assemble_chapters(
            [page(1, "# Areas of the Keep\n\nA."), page(2, "# Areas of the Keep\n\nB.")]
        )

        assert [c.slug for c in chapters] == ["areas-of-the-keep", "areas-of-the-keep-2"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_canon/test_assembler.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.canon.assembler'`

- [ ] **Step 3: Write the assembler**

Create `backend/canon/assembler.py`:

```python
"""Stage 2: group page transcripts into chapters by H1 headings."""

import re

from backend.canon.models import Chapter, PageTranscript

H1_PATTERN = re.compile(r"^#\s+(?!#)(.+?)\s*$", re.MULTILINE)


def slugify(title: str) -> str:
    """Turn a chapter title into a URL-safe slug."""
    slug = title.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")


def assemble_chapters(transcripts: list[PageTranscript]) -> list[Chapter]:
    """Group consecutive pages into chapters, splitting at each H1 heading.

    Pages appearing before the first heading are collected as "front-matter".
    Failed transcripts are skipped; their text is simply absent.
    """
    usable = [t for t in transcripts if t.status == "ok" and t.markdown.strip()]
    if not usable:
        return []

    chapters: list[Chapter] = []
    current: dict | None = None

    for transcript in usable:
        heading = H1_PATTERN.search(transcript.markdown)

        if heading is not None:
            if current is not None:
                chapters.append(_finish(current))
            current = {
                "title": heading.group(1).strip(),
                "start_page": transcript.page_number,
                "end_page": transcript.page_number,
                "parts": [transcript.markdown.strip()],
            }
            continue

        if current is None:
            current = {
                "title": "Front Matter",
                "start_page": transcript.page_number,
                "end_page": transcript.page_number,
                "parts": [transcript.markdown.strip()],
            }
            continue

        current["parts"].append(transcript.markdown.strip())
        current["end_page"] = transcript.page_number

    if current is not None:
        chapters.append(_finish(current))

    return _disambiguate(chapters)


def _finish(pending: dict) -> Chapter:
    return Chapter(
        slug=slugify(pending["title"]),
        title=pending["title"],
        start_page=pending["start_page"],
        end_page=pending["end_page"],
        markdown="\n\n".join(pending["parts"]),
    )


def _disambiguate(chapters: list[Chapter]) -> list[Chapter]:
    """Ensure slugs are unique by suffixing repeats with -2, -3, ..."""
    seen: dict[str, int] = {}
    for chapter in chapters:
        seen[chapter.slug] = seen.get(chapter.slug, 0) + 1
        if seen[chapter.slug] > 1:
            chapter.slug = f"{chapter.slug}-{seen[chapter.slug]}"
    return chapters
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_canon/test_assembler.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add backend/canon/assembler.py tests/test_canon/test_assembler.py
git commit -m "feat(canon): assemble page transcripts into chapters"
```

---

### Task 5: Chunk and embed chapters (Stage 3)

Bridges canon chapters into the existing embedding pipeline, tagging every chunk with book and chapter so later graph work can link nodes back to prose.

**Files:**
- Create: `backend/canon/ingest.py`
- Create: `tests/test_canon/test_ingest.py`
- Modify: `backend/ingestion/pdf_processor.py`

**Interfaces:**
- Consumes: `Chapter` (Task 4), `PDFProcessor` (`backend/ingestion/pdf_processor.py:39`), `EmbeddingPipeline` (`backend/ingestion/embeddings.py:12`)
- Produces: `chapter_to_chunks(chapter: Chapter, book_slug: str, start_index: int = 0) -> list[DocumentChunk]`, `async ingest_chapters(chapters: list[Chapter], book_slug: str, pipeline: EmbeddingPipeline | None = None, batch_size: int = 100) -> list[str]`

- [ ] **Step 1: Write the failing test**

Create `tests/test_canon/test_ingest.py`:

```python
"""Tests for chunking and embedding canon chapters."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.canon.ingest import chapter_to_chunks, ingest_chapters
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_canon/test_ingest.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.canon.ingest'`

- [ ] **Step 3: Add a public chunking entry point**

`PDFProcessor._chunk_text` already does token-aware chunking with overlap, but it is private. Add a public wrapper in `backend/ingestion/pdf_processor.py`, immediately after the `process()` method (which ends at line 115):

```python
    def chunk_text(
        self,
        text: str,
        source: str,
        page: int,
        start_index: int = 0,
    ) -> list[DocumentChunk]:
        """Chunk already-extracted text.

        Public entry point for callers that have text from somewhere other than a
        PDF text layer, such as vision-transcribed page markdown.

        Args:
            text: The text to chunk
            source: Source name recorded on each chunk
            page: Page number recorded on each chunk
            start_index: Starting chunk index, for unique IDs across calls

        Returns:
            List of DocumentChunk objects
        """
        return self._chunk_text(
            text=text, source=source, page=page, start_index=start_index
        )
```

- [ ] **Step 4: Write the ingest bridge**

Create `backend/canon/ingest.py`:

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_canon/test_ingest.py -v`
Expected: 7 passed

- [ ] **Step 6: Verify nothing regressed**

Run: `uv run pytest tests/test_pdf_processor.py -v`
Expected: all pass — `chunk_text` is additive and changes no existing behavior.

- [ ] **Step 7: Commit**

```bash
git add backend/canon/ingest.py tests/test_canon/test_ingest.py \
        backend/ingestion/pdf_processor.py
git commit -m "feat(canon): chunk and embed canon chapters into ChromaDB"
```

---

### Task 6: CLI orchestration and pilot run

Wires stages 0–3 into one command. The cost estimate and page-range flags exist so a small pilot validates transcription quality before spending a full run.

**Files:**
- Create: `backend/scripts/ingest_canon.py`
- Create: `tests/test_canon/test_cli.py`

**Interfaces:**
- Consumes: everything from Tasks 1–5
- Produces: `estimate_cost(page_count: int) -> dict`, `parse_page_range(spec: str) -> range`, `async run(pdf_path, book_slug, pages, concurrency, skip_embed) -> dict`

- [ ] **Step 1: Write the failing test**

Create `tests/test_canon/test_cli.py`:

```python
"""Tests for the canon ingestion CLI."""

import pytest

from backend.scripts.ingest_canon import estimate_cost, parse_page_range


class TestParsePageRange:
    def test_parses_inclusive_range(self):
        assert list(parse_page_range("40-42")) == [40, 41, 42]

    def test_parses_single_page(self):
        assert list(parse_page_range("61")) == [61]

    def test_rejects_reversed_range(self):
        with pytest.raises(ValueError):
            parse_page_range("50-40")

    def test_rejects_garbage(self):
        with pytest.raises(ValueError):
            parse_page_range("abc")


class TestEstimateCost:
    def test_scales_with_page_count(self):
        one = estimate_cost(1)
        many = estimate_cost(509)

        assert many["total_usd"] > one["total_usd"]
        assert many["pages"] == 509

    def test_full_book_is_in_the_expected_range(self):
        """The spec budgets ~$6.75 for transcription of 509 pages."""
        estimate = estimate_cost(509)
        assert 5.0 < estimate["total_usd"] < 9.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_canon/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.scripts.ingest_canon'`

- [ ] **Step 3: Write the CLI**

Create `backend/scripts/ingest_canon.py`:

```python
#!/usr/bin/env python3
"""CLI for ingesting a sourcebook PDF into canon text and ChromaDB."""

import argparse
import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.canon.assembler import assemble_chapters
from backend.canon.cache import TranscriptCache
from backend.canon.ingest import ingest_chapters
from backend.canon.page_extractor import PageExtractor
from backend.canon.transcriber import PageTranscriber
from backend.core.config import settings

# gpt-4o rates, USD per 1M tokens
INPUT_RATE = 2.50
OUTPUT_RATE = 10.00

# Measured on data/cos.pdf at ~1278x1800 under OpenAI image tiling
IMAGE_TOKENS_PER_PAGE = 1105
PROMPT_TOKENS_PER_PAGE = 200
EXPECTED_OUTPUT_TOKENS_PER_PAGE = 1000

RANGE_PATTERN = re.compile(r"^(\d+)(?:-(\d+))?$")


def parse_page_range(spec: str) -> range:
    """Parse '40-60' or '61' into an inclusive 1-indexed range."""
    match = RANGE_PATTERN.match(spec.strip())
    if match is None:
        raise ValueError(f"Invalid page range: {spec!r}. Use '40-60' or '61'.")

    start = int(match.group(1))
    end = int(match.group(2)) if match.group(2) else start
    if end < start:
        raise ValueError(f"Range end before start: {spec!r}")

    return range(start, end + 1)


def estimate_cost(page_count: int) -> dict:
    """Estimate transcription cost. Excludes cache hits, which are free."""
    input_tokens = page_count * (IMAGE_TOKENS_PER_PAGE + PROMPT_TOKENS_PER_PAGE)
    output_tokens = page_count * EXPECTED_OUTPUT_TOKENS_PER_PAGE
    input_usd = input_tokens / 1_000_000 * INPUT_RATE
    output_usd = output_tokens / 1_000_000 * OUTPUT_RATE

    return {
        "pages": page_count,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_usd": round(input_usd + output_usd, 2),
    }


async def run(
    pdf_path: Path,
    book_slug: str,
    pages: range | None,
    concurrency: int,
    skip_embed: bool,
) -> dict:
    """Run stages 0-3 and return a summary."""
    extractor = PageExtractor(pdf_path)
    cache = TranscriptCache(settings.canon_dir / book_slug)
    transcriber = PageTranscriber(cache, concurrency=concurrency)

    page_images = list(extractor.extract(pages=pages))
    print(f"Extracted {len(page_images)} page images")

    transcripts = await transcriber.transcribe_pages(page_images)
    failed = [t.page_number for t in transcripts if t.status == "failed"]
    spent_in = sum(t.input_tokens for t in transcripts)
    spent_out = sum(t.output_tokens for t in transcripts)
    actual_usd = round(
        spent_in / 1_000_000 * INPUT_RATE + spent_out / 1_000_000 * OUTPUT_RATE, 2
    )
    print(f"Transcribed {len(transcripts) - len(failed)}/{len(transcripts)} pages")
    if failed:
        print(f"  FAILED pages (retry to fix): {failed}")
    print(f"  Billed this run: ${actual_usd} (cache hits are free)")

    chapters = assemble_chapters(transcripts)
    print(f"Assembled {len(chapters)} chapters")
    for chapter in chapters:
        print(f"  p{chapter.start_page}-{chapter.end_page}  {chapter.title}")

    stored: list[str] = []
    if not skip_embed:
        stored = await ingest_chapters(chapters, book_slug=book_slug)
        print(f"Embedded {len(stored)} chunks into ChromaDB")

    extractor.close()
    return {
        "pages": len(page_images),
        "failed_pages": failed,
        "chapters": len(chapters),
        "chunks": len(stored),
        "usd": actual_usd,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest a sourcebook PDF into canon text and ChromaDB"
    )
    parser.add_argument("pdf", type=Path, help="Path to the source PDF")
    parser.add_argument(
        "-b", "--book-slug", default="cos", help="Book slug (default: cos)"
    )
    parser.add_argument(
        "-p", "--pages", help="Page range, e.g. '40-60'. Default: every page"
    )
    parser.add_argument(
        "-c", "--concurrency", type=int, default=8, help="Concurrent API calls"
    )
    parser.add_argument(
        "--estimate", action="store_true", help="Print a cost estimate and exit"
    )
    parser.add_argument(
        "--skip-embed",
        action="store_true",
        help="Transcribe and assemble only; do not write to ChromaDB",
    )
    args = parser.parse_args()

    pages = parse_page_range(args.pages) if args.pages else None

    if args.estimate:
        count = len(pages) if pages else PageExtractor(args.pdf).page_count
        estimate = estimate_cost(count)
        print(
            f"{estimate['pages']} pages -> ~${estimate['total_usd']} "
            f"({estimate['input_tokens']:,} in / {estimate['output_tokens']:,} out)"
        )
        print("Cached pages cost nothing; this is the worst case.")
        return

    asyncio.run(
        run(
            pdf_path=args.pdf,
            book_slug=args.book_slug,
            pages=pages,
            concurrency=args.concurrency,
            skip_embed=args.skip_embed,
        )
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_canon/test_cli.py -v`
Expected: 6 passed

- [ ] **Step 5: Check the cost estimate before spending anything**

Run: `uv run python -m backend.scripts.ingest_canon data/cos.pdf --estimate`
Expected: 509 pages, roughly $6–7. If it prints a wildly different number, stop and re-check `IMAGE_TOKENS_PER_PAGE`.

- [ ] **Step 6: Pilot on five pages**

Run:

```bash
uv run python -m backend.scripts.ingest_canon data/cos.pdf --pages 60-64 --skip-embed
cat data/canon/cos/pages/0061.md
```

Read the output. Verify: headings are real markdown, prose is accurate, tables survived, no hallucinated content on art pages. **Do not proceed until the sample looks right** — every downstream stage inherits these errors, and a full run costs ~$7 to repeat.

- [ ] **Step 7: Confirm the cache works**

Run the same pilot command again.
Expected: `Billed this run: $0.0` — every page is a cache hit.

- [ ] **Step 8: Commit**

```bash
git add backend/scripts/ingest_canon.py tests/test_canon/test_cli.py
git commit -m "feat(canon): add CLI orchestrating transcription stages 0-3"
```

- [ ] **Step 9: Full run**

Only after the pilot looks right:

```bash
uv run python -m backend.scripts.ingest_canon data/cos.pdf
```

Expected: 509 pages, a chapter list resembling Curse of Strahd's actual structure, several thousand chunks embedded, ~$7 billed. Note any failed pages and re-run to retry them — cached pages are not re-billed.

- [ ] **Step 10: Verify the corpus is searchable**

Run:

```bash
uv run python -c "
import asyncio
from backend.rag.retriever import HybridRetriever

async def main():
    retriever = HybridRetriever()
    results = await retriever.search('Who is Ireena Kolyana?', top_k=3, source_filter='cos')
    for r in results:
        print(r)

asyncio.run(main())
"
```

Expected: three chunks of Curse of Strahd prose mentioning Ireena. The class is
`HybridRetriever` (`backend/rag/retriever.py:12`) and the parameter is `top_k`, not `k`.
`source_filter='cos'` matches the `source` set by `chapter_to_chunks` in Task 5.

---

### Task 7: Fix chapter boundary detection

**Why this exists.** The Task 6 boundary pilot (PDF pages 79–82, real API run) produced
three chapters from four pages:

```
p79-79  N. Town of Vallaki
p80-80  Chapter 3: The Village of Barovia
p81-82  Chapter 3: The Village of Barovia
```

Two distinct defects, both in `assemble_chapters`:

1. **Any H1 starts a chapter.** Page 79's `N. Town of Vallaki` is a location-key or map
   label, not a chapter — a false boundary.
2. **A repeated chapter title starts a second chapter.** Pages 80 and 81 both emitted
   `Chapter 3: The Village of Barovia`; page 81's is almost certainly a running header the
   transcription prompt failed to suppress. One real chapter became two.

Across 509 pages this fragments the book into many spurious chapters. `Chapter.slug` is
the retrieval metadata Task 5 writes to ChromaDB, so the corpus would be searchable but
its chapter grouping unusable.

This task fixes it in the assembler only — **no re-transcription, no API cost.** Pages are
already cached, so only Stage 2 re-runs.

**Files:**
- Modify: `backend/canon/assembler.py`
- Modify: `tests/test_canon/test_assembler.py`

**Interfaces:**
- Consumes: `PageTranscript`, `Chapter` (unchanged)
- Produces: `assemble_chapters()` and `slugify()` keep their exact signatures. New module-level `CHAPTER_HEADING_PATTERN` and private `_is_chapter_heading(title: str) -> bool`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_canon/test_assembler.py`:

```python
class TestChapterBoundaryDetection:
    def test_non_chapter_h1_does_not_start_a_chapter(self):
        """A location key or map label is not a chapter boundary."""
        chapters = assemble_chapters(
            [
                page(1, "# Chapter 2: The Lands of Barovia\n\nA."),
                page(2, "# N. Town of Vallaki\n\nB."),
                page(3, "C."),
            ]
        )

        assert len(chapters) == 1
        assert chapters[0].title == "Chapter 2: The Lands of Barovia"
        assert chapters[0].end_page == 3
        assert "N. Town of Vallaki" in chapters[0].markdown

    def test_repeated_chapter_title_is_a_continuation(self):
        """A running header repeating the current chapter must not split it."""
        chapters = assemble_chapters(
            [
                page(80, "# Chapter 3: The Village of Barovia\n\nA."),
                page(81, "# Chapter 3: The Village of Barovia\n\nB."),
                page(82, "C."),
            ]
        )

        assert len(chapters) == 1
        assert chapters[0].start_page == 80
        assert chapters[0].end_page == 82

    def test_different_consecutive_chapters_still_split(self):
        chapters = assemble_chapters(
            [
                page(1, "# Chapter 3: The Village of Barovia\n\nA."),
                page(2, "# Chapter 4: Castle Ravenloft\n\nB."),
            ]
        )

        assert [c.title for c in chapters] == [
            "Chapter 3: The Village of Barovia",
            "Chapter 4: Castle Ravenloft",
        ]

    def test_recognises_appendix_and_introduction(self):
        chapters = assemble_chapters(
            [
                page(1, "# Introduction\n\nA."),
                page(2, "# Appendix A: Fortunes of Ravenloft\n\nB."),
            ]
        )

        assert [c.title for c in chapters] == [
            "Introduction",
            "Appendix A: Fortunes of Ravenloft",
        ]

    def test_pilot_page_shape_yields_two_chapters(self):
        """Regression against the exact shape observed in the 79-82 boundary pilot."""
        chapters = assemble_chapters(
            [
                page(79, "# N. Town of Vallaki\n\nA."),
                page(80, "# Chapter 3: The Village of Barovia\n\nB."),
                page(81, "# Chapter 3: The Village of Barovia\n\nC."),
                page(82, "D."),
            ]
        )

        assert len(chapters) == 2
        assert chapters[0].slug == "front-matter"
        assert chapters[1].title == "Chapter 3: The Village of Barovia"
        assert chapters[1].start_page == 80
        assert chapters[1].end_page == 82
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_canon/test_assembler.py::TestChapterBoundaryDetection -v`
Expected: FAIL — the first test reports 2 chapters where 1 is expected, and the pilot-shape test reports 3 where 2 is expected. Capture that output; it is the evidence this task's fix is real.

- [ ] **Step 3: Add the chapter-heading pattern**

In `backend/canon/assembler.py`, add below the existing `H1_PATTERN`:

```python
CHAPTER_HEADING_PATTERN = re.compile(
    r"^(?:chapter\s+\d+|appendix\s+[a-z]\b|introduction|prologue|epilogue|foreword)",
    re.IGNORECASE,
)


def _is_chapter_heading(title: str) -> bool:
    """True if an H1 names a real chapter rather than a section or map label.

    Transcribed pages emit H1s for things that are not chapters — location keys,
    area names, running headers. Only titles matching a book's chapter vocabulary
    start a new chapter.
    """
    return CHAPTER_HEADING_PATTERN.match(title.strip()) is not None
```

- [ ] **Step 4: Apply the boundary rule**

In `assemble_chapters`, replace the body of the per-transcript loop's heading branch. The
existing code reads:

```python
        heading = H1_PATTERN.search(transcript.markdown)

        if heading is not None:
```

Replace those two lines with:

```python
        heading = H1_PATTERN.search(transcript.markdown)
        title = heading.group(1).strip() if heading is not None else None
        starts_new_chapter = (
            title is not None
            and _is_chapter_heading(title)
            and (current is None or current["title"] != title)
        )

        if starts_new_chapter:
```

Then inside that branch, replace `"title": heading.group(1).strip(),` with `"title": title,`.

A page whose H1 is not a chapter heading, or which repeats the current chapter's title,
now falls through to the continuation path and its markdown is appended — so no text is
lost, it simply does not create a boundary.

- [ ] **Step 5: Run the new tests**

Run: `uv run pytest tests/test_canon/test_assembler.py::TestChapterBoundaryDetection -v`
Expected: 5 passed

- [ ] **Step 6: Confirm no regression in the existing assembler tests**

Run: `uv run pytest tests/test_canon/test_assembler.py -v`
Expected: 14 passed (9 existing + 5 new). All nine originals must pass unchanged. In
particular `test_pages_before_first_heading_become_front_matter` and
`test_duplicate_titles_get_distinct_slugs` still hold: the latter uses
`# Areas of the Keep`, which is *not* a chapter heading — so verify that test's fixture
still produces the two chapters it asserts, and if the new rule changes its meaning,
report that rather than editing the test to pass.

- [ ] **Step 7: Re-run the boundary pilot against cached pages (free)**

Run: `uv run python -m backend.scripts.ingest_canon data/cos.pdf --pages 79-82 --skip-embed`
Expected: `Billed this run: $0.0` (all four pages cached) and exactly two chapters, with
`Chapter 3: The Village of Barovia` spanning p80–82.

- [ ] **Step 8: Commit**

```bash
git add backend/canon/assembler.py tests/test_canon/test_assembler.py
git commit -m "fix(canon): only real chapter headings start a new chapter"
```

---

## Verification

Whole suite: `uv run pytest -q`
Expected: 168 existing tests still pass, plus 47 new canon tests
(Task 1: 5, Task 2: 5, Task 3: 9, Task 4: 14, Task 5: 7, Task 6: 7). Counts include tests
added during review fix rounds, so they exceed the per-task figures written in the steps
above; the step-level numbers describe the first green run, not the final state.

Neo4j must be running for the pre-existing `tests/test_discord/test_combat_manager.py` suite: `docker compose up -d`.

## Notes for the Implementer

- **Nothing here touches the graph.** Stages 4–6 (entity extraction into Neo4j) are a separate plan. This plan's deliverable is searchable prose.
- **The cache is load-bearing.** If transcription is re-run repeatedly during development without cache hits, the cost model in the spec no longer holds. Task 2's `test_hash_mismatch_is_a_miss` and Task 6's Step 7 both exist to protect this.
- **Failed pages are expected** on a 509-page run. They are reported, not fatal, and a re-run retries only them.

### Known follow-up: the cache ignores prompt and model changes

`TranscriptCache` validates only the **image** hash. The transcription prompt and the
model name are recorded in the sidecar but never checked, so **editing
`TRANSCRIPTION_PROMPT` or switching models does not invalidate cached pages** — the
improved prompt silently fails to apply to anything already transcribed.

This has not bitten yet because Task 7 deliberately fixes chapter detection in the
assembler rather than the prompt, precisely so cached pages stay valid. But it is a trap
for the next person who tries to improve transcription quality: they will edit the prompt,
re-run, see no change, and have no error to explain it.

The fix is small — hash `TRANSCRIPTION_PROMPT`, store it alongside `model` in the sidecar,
and treat a mismatch of either as a cache miss in `TranscriptCache.get()`. It costs a full
re-transcription (~$6.43) the first time it lands, which is why it is not bundled into
Task 7. Worth doing before any prompt tuning, and worth *not* doing before the full run.
