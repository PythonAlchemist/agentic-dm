#!/usr/bin/env python3
"""CLI script for processing session transcripts."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.ner import NERConfig
from backend.transcript import TranscriptProcessor


async def process_transcript(
    filepath: Path,
    session_number: int | None,
    campaign_id: str | None,
    speakers_file: Path | None,
    use_llm: bool,
    create_entities: bool,
    verbose: bool,
) -> None:
    """Process a transcript file."""
    print("=== Transcript Processing ===")
    print(f"File: {filepath.name}")
    print(f"Session: {session_number or 'Not specified'}")
    print(f"Campaign: {campaign_id or 'Default'}")
    print(f"LLM extraction: {'enabled' if use_llm else 'disabled'}")
    print(f"Create entities: {'yes' if create_entities else 'no'}")
    print()

    # Load speaker definitions if provided
    speakers = None
    if speakers_file and speakers_file.exists():
        with open(speakers_file) as f:
            speakers = json.load(f)
        if verbose:
            print(f"Loaded {len(speakers)} speaker definitions")

    # Configure and create processor
    config = NERConfig(
        use_llm_extraction=use_llm,
        link_to_graph=True,
        create_missing_entities=create_entities,
    )

    processor = TranscriptProcessor(
        ner_config=config,
        create_entities=create_entities,
    )

    print("Processing transcript...")
    print()

    # Process the file
    result = await processor.process_file(
        filepath=filepath,
        session_number=session_number,
        campaign_id=campaign_id,
        speakers=speakers,
    )

    # Print results
    print("=== Results ===")
    print(f"Session ID: {result.session_id}")
    print(f"Segments processed: {result.segments_processed}")
    print(f"Entities extracted: {result.entities_extracted}")
    print(f"Entities created in graph: {result.entities_created}")
    print(f"Relationships extracted: {result.relationships_extracted}")
    print(f"Relationships created in graph: {result.relationships_created}")
    print(f"Processing time: {result.processing_time_ms:.2f}ms")
    print()

    if result.entity_counts:
        print("Entity breakdown:")
        for entity_type, count in sorted(result.entity_counts.items()):
            print(f"  {entity_type}: {count}")
        print()

    if verbose and result.all_entities:
        print("Extracted entities:")
        for entity in result.all_entities[:20]:  # Limit output
            print(f"  [{entity.entity_type.value}] {entity.normalized_name} ({entity.confidence:.2f})")
        if len(result.all_entities) > 20:
            print(f"  ... and {len(result.all_entities) - 20} more")
        print()

    if result.errors:
        print("Errors:")
        for error in result.errors:
            print(f"  - {error}")
        print()

    print("Done!")


def main():
    """Main entry point for CLI."""
    parser = argparse.ArgumentParser(
        description="Process D&D session transcripts and extract entities to knowledge graph"
    )
    parser.add_argument(
        "transcript",
        type=str,
        help="Path to transcript file (.txt or .json)",
    )
    parser.add_argument(
        "-s", "--session",
        type=int,
        help="Session number",
    )
    parser.add_argument(
        "-c", "--campaign",
        type=str,
        help="Campaign identifier",
    )
    parser.add_argument(
        "--speakers",
        type=str,
        help="Path to JSON file with speaker definitions",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Disable LLM-based extraction (faster but less accurate)",
    )
    parser.add_argument(
        "--no-create",
        action="store_true",
        help="Don't create new entities in the graph (extraction only)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Print detailed progress and extracted entities",
    )

    args = parser.parse_args()

    # Validate file exists
    path = Path(args.transcript)
    if not path.exists():
        print(f"Error: File does not exist: {path}")
        sys.exit(1)

    # Parse speakers file path
    speakers_path = Path(args.speakers) if args.speakers else None

    # Run processing
    try:
        asyncio.run(
            process_transcript(
                filepath=path,
                session_number=args.session,
                campaign_id=args.campaign,
                speakers_file=speakers_path,
                use_llm=not args.no_llm,
                create_entities=not args.no_create,
                verbose=args.verbose,
            )
        )
    except KeyboardInterrupt:
        print("\nProcessing cancelled.")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
