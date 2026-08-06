"""Stage 0: extract one image per page from a source PDF."""

import hashlib
from collections.abc import Iterator
from pathlib import Path

import fitz  # pymupdf

from backend.canon.models import PageImage

RENDER_DPI = 150

# Formats the vision API accepts as an `image/{ext}` MIME type. Embedded images in
# other formats (e.g. jpx, jbig2, tiff) are rendered instead of extracted verbatim.
ACCEPTED_EXTRACT_FORMATS = {"png", "jpeg", "jpg"}


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

    def extract(
        self,
        pages: range | None = None,
        dedup: bool = True,
    ) -> Iterator[PageImage]:
        """Yield a PageImage for each requested page, skipping repeated images.

        Flipbook exports repeat every page: `data/cos.pdf` has 509 PDF pages but
        only 258 distinct images, 251 of them exact consecutive pairs. Transcribing
        both halves costs twice as much and doubles every entity downstream, and
        because the vision model is non-deterministic the two transcriptions differ
        in wording -- so text-level dedup will not catch them. The image hash is
        exact, so this is the only layer where the duplicate is unambiguous.

        The first occurrence wins, keeping its PDF page number. Numbers therefore
        become non-contiguous, which is honest: they still index the source PDF.

        Args:
            pages: 1-indexed page numbers to extract. Defaults to every page.
            dedup: Skip a page whose image was already yielded by this call.
        """
        wanted = pages if pages is not None else range(1, self.page_count + 1)
        seen: set[str] = set()

        for page_number in wanted:
            page = self._doc[page_number - 1]
            images = page.get_images(full=True)

            extracted = None
            if len(images) == 1:
                info = self._doc.extract_image(images[0][0])
                if info["ext"] in ACCEPTED_EXTRACT_FORMATS:
                    extracted = info

            if extracted is not None:
                data, ext = extracted["image"], extracted["ext"]
                width, height = extracted["width"], extracted["height"]
            else:
                pix = page.get_pixmap(dpi=RENDER_DPI)
                data, ext = pix.tobytes("png"), "png"
                width, height = pix.width, pix.height

            digest = hashlib.sha256(data).hexdigest()
            if dedup:
                if digest in seen:
                    continue
                seen.add(digest)

            yield PageImage(
                page_number=page_number,
                image_bytes=data,
                ext=ext,
                width=width,
                height=height,
                sha256=digest,
            )

    def close(self) -> None:
        self._doc.close()
