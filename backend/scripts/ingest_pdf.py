#!/usr/bin/env python3
"""CLI script for ingesting PDF documents into the RAG system."""

import argparse
import asyncio
import sys
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.core.config import settings
from backend.ingestion.pdf_processor import PDFProcessor
from backend.ingestion.embeddings import EmbeddingPipeline


async def ingest_pdf(
    pdf_path: Path,
    batch_size: int = 50,
    verbose: bool = False,
) -> dict:
    """Ingest a single PDF file.

    Args:
        pdf_path: Path to PDF file
        batch_size: Chunks to process at once
        verbose: Print progress info

    Returns:
        Ingestion statistics
    """
    if verbose:
        print(f"Processing: {pdf_path.name}")

    # Process PDF into chunks
    processor = PDFProcessor()
    chunks = processor.process(pdf_path)

    if verbose:
        print(f"  Created {len(chunks)} chunks")

    # Embed and store
    pipeline = EmbeddingPipeline()
    chunk_ids = await pipeline.embed_and_store_batch(chunks, batch_size=batch_size)

    if verbose:
        print(f"  Stored {len(chunk_ids)} chunks in ChromaDB")

    return {
        "file": pdf_path.name,
        "chunks": len(chunks),
        "stored": len(chunk_ids),
    }


async def ingest_directory(
    directory: Path,
    batch_size: int = 50,
    verbose: bool = False,
) -> list[dict]:
    """Ingest all PDFs in a directory.

    Args:
        directory: Directory containing PDFs
        batch_size: Chunks to process at once
        verbose: Print progress info

    Returns:
        List of ingestion statistics per file
    """
    pdf_files = list(directory.glob("*.pdf"))

    if not pdf_files:
        print(f"No PDF files found in {directory}")
        return []

    if verbose:
        print(f"Found {len(pdf_files)} PDF files")

    results = []
    for pdf_path in pdf_files:
        try:
            result = await ingest_pdf(pdf_path, batch_size, verbose)
            results.append(result)
        except Exception as e:
            print(f"Error processing {pdf_path.name}: {e}")
            results.append({
                "file": pdf_path.name,
                "error": str(e),
            })

    return results


def main():
    """Main entry point for CLI."""
    parser = argparse.ArgumentParser(
        description="Ingest PDF documents into the D&D DM Assistant RAG system"
    )
    parser.add_argument(
        "path",
        type=str,
        nargs="?",
        default=None,
        help="Path to PDF file or directory (default: data/pdfs/)",
    )
    parser.add_argument(
        "-b", "--batch-size",
        type=int,
        default=50,
        help="Number of chunks to process at once (default: 50)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Print detailed progress",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Show collection statistics after ingestion",
    )

    args = parser.parse_args()

    # Determine path
    if args.path:
        path = Path(args.path)
    else:
        path = settings.pdf_dir

    if not path.exists():
        print(f"Error: Path does not exist: {path}")
        sys.exit(1)

    # Run ingestion
    if path.is_file():
        if not path.suffix.lower() == ".pdf":
            print("Error: File must be a PDF")
            sys.exit(1)
        results = asyncio.run(ingest_pdf(path, args.batch_size, args.verbose))
        results = [results]
    else:
        results = asyncio.run(ingest_directory(path, args.batch_size, args.verbose))

    # Print summary
    print("\n=== Ingestion Summary ===")
    total_chunks = 0
    errors = 0
    for result in results:
        if "error" in result:
            print(f"  {result['file']}: ERROR - {result['error']}")
            errors += 1
        else:
            print(f"  {result['file']}: {result['chunks']} chunks")
            total_chunks += result["chunks"]

    print(f"\nTotal: {len(results)} files, {total_chunks} chunks, {errors} errors")

    # Show stats if requested
    if args.stats:
        pipeline = EmbeddingPipeline()
        stats = pipeline.get_collection_stats()
        print(f"\nCollection '{stats['name']}' now has {stats['count']} total chunks")


if __name__ == "__main__":
    main()
