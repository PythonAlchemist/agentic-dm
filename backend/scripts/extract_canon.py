#!/usr/bin/env python3
"""Extract canon candidates from a chapter and score them against the golden set.

Nothing here writes to Neo4j. The output is a candidate set on disk plus a
score, which keeps a tuning run from being able to corrupt anything.
"""

import argparse
import asyncio
import json
import logging
import re
import sys
from dataclasses import asdict
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.canon.assembler import assemble_chapters
from backend.canon.cache import TranscriptCache
from backend.canon.extract import CandidateExtractor, anchor_quests
from backend.canon.grade import grade
from backend.canon.models import Chapter, Section
from backend.canon.page_extractor import PageExtractor
from backend.canon.sections import split_sections, units_from_sections
from backend.canon.seed_loader import DEFAULT_SOURCE, EXTRACTABLE_FROM, SEED_DIR, extractable_subset
from backend.canon.structure import place_of_section, structural_edges
from backend.core.config import settings
from backend.graph.schema import Layer

DEFAULT_PDF = Path("data/cos.pdf")

_CHAPTER_PREFIX = re.compile(r"^(chapter\s+\d+|appendix\s+[a-z])\s*[:.]\s*", re.IGNORECASE)


def _known_sources(data: dict) -> list[str]:
    """Every `--grade` value this seed can actually answer.

    DEFAULT_SOURCE (unmarked entries) is always answerable. Beyond that, only
    the `extractable_from` markers actually present in the seed -- not the
    full schema-valid set in `EXTRACTABLE_SOURCES`, some of which may not yet
    have any entries -- so the error message never claims a source is usable
    when it would itself return empty.
    """
    markers = {
        entry.get(EXTRACTABLE_FROM)
        for entry in [*data.get("nodes", []), *data.get("edges", [])]
        if entry.get(EXTRACTABLE_FROM)
    }
    return sorted({DEFAULT_SOURCE, *markers})


def _gradeable_subset(data: dict, source: str) -> dict:
    """The golden subset for `source`, or a clear error naming what exists.

    `extractable_subset` silently returns an empty subset for any unmatched
    source marker, and an empty subset scores a perfect (and meaningless)
    1.00 recall for both nodes and edges -- `_recall`'s empty-denominator
    behavior is deliberate and untouched here (see grade.py), but a bad
    --grade value must not be allowed to reach it silently. Measured:
    `--grade ch4`, `--grade appendix-d`, and `--grade typo-source` all
    printed a perfect score after a paid extraction run.
    """
    subset = extractable_subset(data, source)
    if not subset["nodes"] and not subset["edges"]:
        available = ", ".join(_known_sources(data))
        raise ValueError(
            f"--grade {source!r} matches no golden entries in this seed. "
            f"Available sources: {available}"
        )
    return subset


def chapter_place(chapter: Chapter, sections: list[Section]) -> str | None:
    """The place a chapter is about, or None if it demonstrably has no rooms.

    A title alone is not evidence: Chapter 1, "Into the Mists", keys its
    sections to Tarokka card results ("1. The Tome of Strahd"), not rooms, and
    treating its title as a containing place would invent one. Only a chapter
    with at least one letter-keyed section -- see `place_of_section` -- is
    trusted to be about a physical place.
    """
    if not any(place_of_section(s) for s in sections):
        return None
    stripped = _CHAPTER_PREFIX.sub("", chapter.title).strip()
    return stripped or None


def load_chapters(pdf_path: Path = DEFAULT_PDF, book_slug: str = "cos") -> list[Chapter]:
    """Rebuild chapters from the transcript cache. No API calls: cache only.

    The source PDF repeats every page, so pages are grouped by image hash --
    preserving first-seen (page) order -- and the richer of each pair's two
    transcriptions is chosen with `get_best`. This yields one transcript per
    real page, in page order, ready for `assemble_chapters`.
    """
    cache = TranscriptCache(settings.canon_dir / book_slug)
    extractor = PageExtractor(pdf_path)
    try:
        pages_by_hash: dict[str, list[int]] = {}
        for page in extractor.extract(dedup=False):
            pages_by_hash.setdefault(page.sha256, []).append(page.page_number)

        transcripts = [
            t
            for sha256, numbers in pages_by_hash.items()
            if (t := cache.get_best(numbers, sha256)) is not None
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
    # Validated before the paid extraction call below: a bad --grade value
    # must fail fast, not silently score 1.00/1.00 after money is spent.
    golden: dict | None = None
    if grade_against:
        data = yaml.safe_load((SEED_DIR / "village-of-barovia.yaml").read_text())
        golden = _gradeable_subset(data, grade_against)

    chapter = find_chapter(load_chapters(), chapter_title)
    sections = split_sections(chapter)
    units = units_from_sections(sections)
    print(f"{chapter.title}: {len(units)} units")

    extractor = CandidateExtractor()
    nodes, edges, failed = await extractor.extract_units(units, layers=layers)
    print(f"  {len(nodes)} candidate nodes, {len(edges)} candidate edges")
    total_calls = len(units) * len(layers or list(Layer))
    if failed:
        print(
            f"\n  !! {failed} of {total_calls} extraction calls FAILED -- "
            "results below are incomplete, not a low-quality passage !!\n"
        )
    rejected_entity_types = extractor.rejected_entity_types
    if rejected_entity_types:
        print(f"  rejected {rejected_entity_types} nodes with an unknown entity_type")

    derived = structural_edges(sections, nodes, chapter_place(chapter, sections))
    print(f"  {len(derived)} derived structural edges")
    edges = edges + derived

    # Applied at chapter level, after all three layer passes are merged: a quest
    # coined by the narrative pass may be anchored by an entity the social pass
    # found, so a per-unit or per-layer filter would discard it wrongly.
    nodes, edges, dropped_quests = anchor_quests(nodes, edges)
    if dropped_quests:
        print(f"  dropped {dropped_quests} unanchored QUEST nodes")

    if out_path:
        if failed and out_path.exists():
            print(
                f"  NOT writing {out_path}: this run had failures and would "
                "clobber the last good output"
            )
        else:
            out_path.write_text(
                json.dumps(
                    {"nodes": [asdict(n) for n in nodes], "edges": [asdict(e) for e in edges]},
                    indent=2,
                )
            )
            print(f"  wrote {out_path}")

    summary: dict = {
        "nodes": len(nodes),
        "edges": len(edges),
        "failed": failed,
        "rejected_entity_types": rejected_entity_types,
        "dropped_quests": dropped_quests,
    }

    if golden is not None:
        report = grade(nodes, edges, golden)
        print(
            f"\n  node recall: {report.node_recall:.2f} "
            f"(unambiguous: {report.node_recall_unambiguous:.2f})"
        )
        print(
            f"  edge recall: {report.edge_recall:.2f} "
            f"(unambiguous: {report.edge_recall_unambiguous:.2f})"
        )
        if report.missing_nodes:
            print(f"  MISSING nodes ({len(report.missing_nodes)}): "
                  f"{', '.join(report.missing_nodes)}")
        if report.missing_edges:
            print(f"  MISSING edges ({len(report.missing_edges)}):")
            for m in report.missing_edges:
                print(f"    {m}")
        print(f"\n  unmatched candidate nodes ({len(report.unmatched_nodes)}) "
              "-- NOT scored, spot-check for fabrication:")
        for name in report.unmatched_nodes:
            print(f"    {name}")
        print(f"\n  unmatched candidate edges ({len(report.unmatched_edges)}) "
              "-- NOT scored, spot-check for fabrication:")
        for e in report.unmatched_edges:
            print(f"    {e}")
        if report.collisions:
            print(f"\n  NODE COLLISIONS ({len(report.collisions)}):")
            for c in report.collisions:
                print(f"    {c}")
        if report.edge_collisions:
            print(f"\n  EDGE COLLISIONS ({len(report.edge_collisions)}):")
            for c in report.edge_collisions:
                print(f"    {c}")
        summary["node_recall"] = report.node_recall
        summary["edge_recall"] = report.edge_recall
        summary["node_recall_unambiguous"] = report.node_recall_unambiguous
        summary["edge_recall_unambiguous"] = report.edge_recall_unambiguous

    return summary


def main() -> None:
    # No handler is configured anywhere else in this chain, so without this
    # the extraction warnings logged on a swallowed exception (see extract.py)
    # depend on logging.lastResort rather than a deliberate, discoverable
    # configuration.
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

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
    try:
        summary = asyncio.run(run(args.chapter, args.grade_against, layers, args.out))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)

    sys.exit(1 if summary["failed"] else 0)


if __name__ == "__main__":
    main()
