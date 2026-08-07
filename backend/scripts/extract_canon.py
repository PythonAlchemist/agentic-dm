#!/usr/bin/env python3
"""Extract canon candidates from a chapter and score them against the golden set.

Nothing here writes to Neo4j. The output is a candidate set on disk plus a
score, which keeps a tuning run from being able to corrupt anything.
"""

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.canon.assembler import assemble_chapters
from backend.canon.cache import TranscriptCache
from backend.canon.extract import CandidateExtractor
from backend.canon.grade import grade
from backend.canon.models import Chapter
from backend.canon.page_extractor import PageExtractor
from backend.canon.sections import pack_sections, split_sections
from backend.canon.seed_loader import SEED_DIR, extractable_subset
from backend.core.config import settings
from backend.graph.schema import Layer

DEFAULT_PDF = Path("data/cos.pdf")


def load_chapters(pdf_path: Path = DEFAULT_PDF, book_slug: str = "cos") -> list[Chapter]:
    """Rebuild chapters from the transcript cache. No API calls: cache only."""
    cache = TranscriptCache(settings.canon_dir / book_slug)
    extractor = PageExtractor(pdf_path)
    try:
        transcripts = [
            t
            for page in extractor.extract()
            if (t := cache.get(page.page_number, page.sha256)) is not None
        ]
    finally:
        extractor.close()
    return assemble_chapters(transcripts)


def find_chapter(chapters: list[Chapter], needle: str) -> Chapter:
    """Find one chapter by case-insensitive title prefix."""
    hits = [c for c in chapters if c.title.lower().startswith(needle.lower())]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise ValueError(
            f"no chapter matching {needle!r}. Available: "
            + ", ".join(c.title for c in chapters)
        )
    raise ValueError(
        f"{needle!r} is ambiguous: " + ", ".join(c.title for c in hits)
    )


async def run(
    chapter_title: str,
    grade_against: str | None,
    layers: list[Layer] | None,
    out_path: Path | None,
) -> dict:
    chapter = find_chapter(load_chapters(), chapter_title)
    units = pack_sections(split_sections(chapter))
    print(f"{chapter.title}: {len(units)} units")

    nodes, edges = await CandidateExtractor().extract_units(units, layers=layers)
    print(f"  {len(nodes)} candidate nodes, {len(edges)} candidate edges")

    if out_path:
        out_path.write_text(
            json.dumps(
                {"nodes": [asdict(n) for n in nodes], "edges": [asdict(e) for e in edges]},
                indent=2,
            )
        )
        print(f"  wrote {out_path}")

    summary: dict = {"nodes": len(nodes), "edges": len(edges)}

    if grade_against:
        data = yaml.safe_load((SEED_DIR / "village-of-barovia.yaml").read_text())
        report = grade(nodes, edges, extractable_subset(data, grade_against))
        print(f"\n  node recall: {report.node_recall:.2f}")
        print(f"  edge recall: {report.edge_recall:.2f}")
        if report.missing_nodes:
            print(f"  MISSING nodes ({len(report.missing_nodes)}): "
                  f"{', '.join(report.missing_nodes)}")
        if report.missing_edges:
            print(f"  MISSING edges ({len(report.missing_edges)}):")
            for m in report.missing_edges:
                print(f"    {m}")
        print(f"\n  unmatched candidates ({len(report.unmatched_nodes)}) "
              "-- NOT scored, spot-check for fabrication:")
        for name in report.unmatched_nodes:
            print(f"    {name}")
        if report.collisions:
            print(f"\n  COLLISIONS ({len(report.collisions)}):")
            for c in report.collisions:
                print(f"    {c}")
        summary["node_recall"] = report.node_recall
        summary["edge_recall"] = report.edge_recall

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("chapter", help="Chapter title prefix, e.g. 'Chapter 3'")
    parser.add_argument("--grade", dest="grade_against", metavar="SOURCE",
                        help="Grade against the seed subset for this source, e.g. ch3")
    parser.add_argument("--layer", action="append", dest="layers",
                        choices=[layer.value for layer in Layer],
                        help="Restrict to one layer; repeatable")
    parser.add_argument("-o", "--out", type=Path, help="Write candidates as JSON")
    args = parser.parse_args()

    layers = [Layer(v) for v in args.layers] if args.layers else None
    asyncio.run(run(args.chapter, args.grade_against, layers, args.out))


if __name__ == "__main__":
    main()
