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
