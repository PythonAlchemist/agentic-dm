#!/usr/bin/env python3
"""CLI for transcribing a sourcebook PDF into canon chapter text."""

import argparse
import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.canon.assembler import assemble_chapters
from backend.canon.cache import TranscriptCache
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
) -> dict:
    """Run stages 0-3 and return a summary."""
    extractor = PageExtractor(pdf_path)
    try:
        cache = TranscriptCache(settings.canon_dir / book_slug)
        transcriber = PageTranscriber(cache, concurrency=concurrency)

        page_images = list(extractor.extract(pages=pages))
        print(f"Extracted {len(page_images)} page images")

        # Determine cache hits before transcribing so the cost sum below can
        # exclude them. Cached transcripts carry their *original* billed
        # token counts (see TranscriptCache.get()), so summing indiscriminately
        # would misreport a fully-cached re-run as costing money again.
        already_cached = {
            img.page_number
            for img in page_images
            if cache.get(img.page_number, img.sha256) is not None
        }

        transcripts = await transcriber.transcribe_pages(page_images)
        failed = [t.page_number for t in transcripts if t.status == "failed"]
        spent_in = sum(
            t.input_tokens for t in transcripts if t.page_number not in already_cached
        )
        spent_out = sum(
            t.output_tokens for t in transcripts if t.page_number not in already_cached
        )
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

        return {
            "pages": len(page_images),
            "failed_pages": failed,
            "chapters": len(chapters),
            "usd": actual_usd,
        }
    finally:
        extractor.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Transcribe a sourcebook PDF into canon chapter text"
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
    args = parser.parse_args()

    pages = parse_page_range(args.pages) if args.pages else None

    if args.estimate:
        if pages:
            count = len(pages)
        else:
            extractor = PageExtractor(args.pdf)
            try:
                count = extractor.page_count
            finally:
                extractor.close()
        estimate = estimate_cost(count)
        print(
            f"{estimate['pages']} pages -> ~${estimate['total_usd']} "
            f"({estimate['input_tokens']:,} in / {estimate['output_tokens']:,} out)"
        )
        print("Cached pages cost nothing; this is the worst case.")
        return

    summary = asyncio.run(
        run(
            pdf_path=args.pdf,
            book_slug=args.book_slug,
            pages=pages,
            concurrency=args.concurrency,
        )
    )
    sys.exit(1 if summary["failed_pages"] else 0)


if __name__ == "__main__":
    main()
