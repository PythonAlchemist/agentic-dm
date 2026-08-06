"""Tests for canon page image extraction."""

import fitz
import pytest

from backend.canon.page_extractor import PageExtractor


@pytest.fixture
def pdf_with_images(tmp_path):
    """A 3-page PDF where each page has one DISTINCT embedded image.

    The pages must differ: extract() skips repeated image hashes, because the
    real corpus is a flipbook export that renders every page twice. Identical
    fill values here would collapse to a single page and mask that.
    """
    doc = fitz.open()
    for shade in (40, 128, 220):
        page = doc.new_page(width=200, height=300)
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 100, 150))
        pix.clear_with(shade)
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
        page.insert_text((50, 50), f"page {doc.page_count}")
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

    def test_non_whitelisted_embedded_format_is_rendered_instead(self, pdf_with_images):
        """extract_image formats like jpx/jbig2/tiff must not reach the transcriber.

        The page has exactly one embedded image (extract branch would normally
        fire), but its format isn't one the vision API accepts as a MIME type, so
        the extractor must fall through to the render branch (png) instead.
        """
        extractor = PageExtractor(pdf_with_images)
        extractor._doc.extract_image = lambda xref: {
            "image": b"not-a-real-jpx-image",
            "ext": "jpx",
            "width": 999,
            "height": 999,
        }

        pages = list(extractor.extract(pages=range(1, 2)))

        assert len(pages) == 1
        assert pages[0].ext == "png"
        assert pages[0].image_bytes != b"not-a-real-jpx-image"


@pytest.fixture
def pdf_with_repeated_pages(tmp_path):
    """A flipbook-style PDF: every page image appears twice, consecutively."""
    doc = fitz.open()
    for _ in range(3):
        for _ in range(2):  # each page rendered twice, as AnyFlip exports do
            page = doc.new_page(width=200, height=300)
            pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 100, 150))
            pix.clear_with(128)
            page.insert_image(fitz.Rect(0, 0, 100, 150), pixmap=pix)
    path = tmp_path / "flipbook.pdf"
    doc.save(path)
    doc.close()
    return path


class TestDuplicatePageSkipping:
    def test_repeated_images_are_yielded_once(self, pdf_with_repeated_pages):
        """The real corpus is 509 PDF pages over 258 distinct images. Transcribing
        both halves doubles cost and double-counts every entity downstream."""
        pages = list(PageExtractor(pdf_with_repeated_pages).extract())

        assert len({p.sha256 for p in pages}) == len(pages), "duplicate image survived"

    def test_first_occurrence_wins(self, pdf_with_repeated_pages):
        pages = list(PageExtractor(pdf_with_repeated_pages).extract())

        # All six synthetic pages share one image, so exactly the first survives.
        assert [p.page_number for p in pages] == [1]

    def test_dedup_can_be_disabled(self, pdf_with_repeated_pages):
        pages = list(PageExtractor(pdf_with_repeated_pages).extract(dedup=False))

        assert [p.page_number for p in pages] == [1, 2, 3, 4, 5, 6]

    def test_distinct_pages_are_all_kept(self, pdf_without_images):
        """Rendered pages differ (they carry different text), so none are dropped."""
        pages = list(PageExtractor(pdf_without_images).extract())

        assert len(pages) == 2
