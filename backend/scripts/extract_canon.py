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
from backend.canon.consensus import Sample, consense, format_votes, vote_histograms
from backend.canon.constraints import enforce, format_report
from backend.canon.extract import (
    EXTRACTION_MODEL,
    EXTRACTION_SEED,
    CandidateExtractor,
    anchor_quests,
    merge_edges,
)
from backend.canon.grade import grade
from backend.canon.models import Chapter, Section
from backend.canon.page_extractor import PageExtractor
from backend.canon.sections import (
    EXTRACTION_BUDGET_TOKENS,
    SPLITTERS,
    split_chapter,
    units_from_sections,
)
from backend.canon.seed_loader import DEFAULT_SOURCE, EXTRACTABLE_FROM, SEED_DIR, extractable_subset
from backend.canon.structure import derive_structure, place_of_section
from backend.core.config import settings
from backend.graph.schema import Layer

DEFAULT_PDF = Path("data/cos.pdf")

CORPORA = ("ddb", "transcription")
DEFAULT_CORPUS = "ddb"

_CHAPTER_PREFIX = re.compile(r"^(chapter\s+\d+|appendix\s+[a-z])\s*[:.]\s*", re.IGNORECASE)

# The document's own title line. D&D Beyond opens every chapter with exactly one.
_H1 = re.compile(r"^#\s+(?!#)(.+?)\s*$", re.MULTILINE)


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


def _load_ddb_chapters(root: Path, book_slug: str) -> list[Chapter]:
    """Read the harvested D&D Beyond cache: one markdown file per chapter.

    No model in the loop and no PDF -- this is a directory walk. The manifest
    fixes the order, because it is the book's order and the filesystem's is
    alphabetical: `castle-ravenloft` sorts before `introduction`.

    The title comes from the document's own H1 rather than the manifest, which
    carries D&D Beyond's table-of-contents label ("Ch. 3: The Village of
    Barovia"). `find_chapter` matches on "Chapter 3" and `chapter_place` strips
    `^chapter \\d+[:.]`; the label would satisfy neither, and the chapter place
    would silently become the literal string "Ch. 3: The Village of Barovia" on
    every derived edge.
    """
    book = root / book_slug
    manifest = book / "manifest.json"
    if not manifest.exists():
        raise FileNotFoundError(
            f"no harvested corpus at {book}. Run "
            f"`uv run python -m backend.scripts.harvest_ddb` to build it, or pass "
            f"--corpus transcription."
        )

    chapters: list[Chapter] = []
    for entry in json.loads(manifest.read_text())["chapters"]:
        path = book / f"{entry['slug']}.md"
        if not path.exists():
            continue
        markdown = path.read_text()
        heading = _H1.search(markdown)
        chapters.append(
            Chapter(
                slug=entry["slug"],
                title=heading.group(1).strip() if heading else entry["title"],
                # The DDB reader has no page numbers to report. Nothing
                # downstream of the splitter reads them.
                start_page=0,
                end_page=0,
                markdown=markdown,
            )
        )
    return chapters


def _load_transcription_chapters(pdf_path: Path, book_slug: str) -> list[Chapter]:
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


def load_chapters(
    corpus: str = DEFAULT_CORPUS,
    *,
    pdf_path: Path = DEFAULT_PDF,
    book_slug: str = "cos",
    ddb_root: Path | None = None,
) -> list[Chapter]:
    """Every chapter of the book, as objects carrying `.title` and `.markdown`.

    `ddb` is the default and the future: the user owns 35 books and wants one
    reader for all of them, which the transcription path -- a PDF renderer plus a
    vision model, per book -- can never be. `transcription` is kept reachable
    because legs A and B of the splitter measurement need it, and because a
    fallback is cheap insurance while the new path is young.
    """
    if corpus == "ddb":
        return _load_ddb_chapters(ddb_root or settings.ddb_dir, book_slug)
    if corpus == "transcription":
        return _load_transcription_chapters(pdf_path, book_slug)
    raise ValueError(f"unknown corpus {corpus!r}; expected one of {CORPORA}")


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
    limit: int | None = None,
    samples: int = 1,
    node_k: int = 1,
    edge_k: int = 1,
    reject_violations: bool = False,
    corpus: str = DEFAULT_CORPUS,
    splitter: str = "depth",
) -> dict:
    # Validated before the paid extraction call below: a bad --grade value
    # must fail fast, not silently score 1.00/1.00 after money is spent.
    golden: dict | None = None
    if grade_against:
        data = yaml.safe_load((SEED_DIR / "village-of-barovia.yaml").read_text())
        golden = _gradeable_subset(data, grade_against)

    chapter = find_chapter(load_chapters(corpus), chapter_title)
    split = split_chapter(chapter, splitter=splitter)
    sections = split.sections
    units = units_from_sections(sections)
    units_available = len(units)
    if limit is not None:
        units = units[:limit]
    print(f"{chapter.title} [{corpus} corpus, {splitter} splitter]: "
          f"{len(units)} of {units_available} units")
    if splitter == "depth":
        # Printed on every run, not hidden behind a diagnostic flag: the derived
        # area depth is the single assumption this splitter rests on, and a run
        # that silently derived the wrong one would look exactly like a run that
        # derived the right one.
        print(f"  area depth: h{split.area_depth}"
              f"{'' if split.depth_qualified else ' (NO DEPTH QUALIFIED -- deepest present)'}"
              f"; {split.before_refinement} sections before refinement, "
              f"{len(sections)} after, {split.subdivided} subdivided")
        if split.unsplittable:
            print(f"  !! {split.unsplittable} section(s) over the "
                  f"{EXTRACTION_BUDGET_TOKENS}-token budget with no deeper heading to "
                  "cut at -- left whole !!")

    # Sample i is drawn at EXTRACTION_SEED + i. Five draws at one seed would be
    # a vote on residual API nondeterminism, which is the thing being measured.
    seeds = [EXTRACTION_SEED + i for i in range(samples)]
    calls_per_sample = len(units) * len(layers or list(Layer))
    total_calls = calls_per_sample * samples

    drawn: list[Sample] = []
    sample_failures: list[int] = []
    rejected_entity_types = 0
    model = EXTRACTION_MODEL
    temperature = 0.0
    for i, seed in enumerate(seeds):
        extractor = CandidateExtractor(seed=seed)
        s_nodes, s_edges, s_failed = await extractor.extract_units(units, layers=layers)
        sample_failures.append(s_failed)
        model, temperature = extractor.model, extractor.temperature
        # A sample with any failed call is dropped from the vote, not counted
        # weakly: a truncated sample makes every candidate in it look rarer than
        # it is, which is a false negative dressed as evidence. One sample is
        # not a vote, so there is nothing to exclude it from -- a partial single
        # run still writes its candidates, flagged partial, exactly as it did
        # before consensus existed.
        votes = samples == 1 or s_failed == 0
        if samples > 1:
            if votes:
                print(
                    f"  sample {i + 1} (seed {seed}): "
                    f"{len(s_nodes)} nodes, {len(s_edges)} edges"
                )
            else:
                print(
                    f"  !! sample {i + 1} (seed {seed}): {s_failed} of {calls_per_sample} "
                    "calls FAILED -- excluded from the vote entirely !!"
                )
        if votes:
            drawn.append((s_nodes, s_edges))
            # Counted only for samples that vote. A rejected candidate in an
            # excluded sample never reached the output, so reporting it would
            # describe candidates this run did not produce.
            rejected_entity_types += extractor.rejected_entity_types
    failed = sum(sample_failures)

    if samples > 1:
        node_hist, edge_hist = vote_histograms(drawn)
        print(f"  nodes  by votes: {format_votes(node_hist)}")
        print(f"  edges  by votes: {format_votes(edge_hist)}")
        # Named per side, because they are separate knobs: node_k=1 with
        # edge_k=5 over 3 samples empties the edges and leaves the nodes alone,
        # and a warning that claimed the whole result was empty would overstate.
        for label, k in (("node_k", node_k), ("edge_k", edge_k)):
            if k > len(drawn):
                print(
                    f"  !! {label}={k} over {len(drawn)} voting sample(s): no candidate "
                    f"can reach it, so an empty {label[:4]} set below means the threshold, "
                    "not the chapter !!"
                )
        nodes, edges = consense(drawn, node_k, edge_k)
    else:
        nodes, edges = drawn[0]

    print(f"  {len(nodes)} candidate nodes, {len(edges)} candidate edges")
    if failed:
        print(
            f"\n  !! {failed} of {total_calls} extraction calls FAILED -- "
            "results below are incomplete, not a low-quality passage !!\n"
        )
    if rejected_entity_types:
        print(f"  rejected {rejected_entity_types} nodes with an unknown entity_type")

    # Derived AFTER the vote and ONCE, from the consensus node set. These edges
    # are a deterministic function of that set, so sampling them N times yields
    # N identical copies; voting on them would score one computation five times
    # and make the one layer that provably cannot hallucinate look like the
    # weakly-supported one. Their `votes` stays 0, meaning "never voted on".
    structure = derive_structure(sections, nodes, chapter_place(chapter, sections))
    derived = structure.edges
    print(f"  {len(derived)} derived structural edges "
          f"({structure.depth_derived} CONTAINS from depth, "
          f"{structure.key_derived} from the key stem, "
          f"{structure.chapter_derived} from the chapter, "
          f"{structure.located_in} LOCATED_IN)")
    before_dedup = len(edges) + len(derived)
    edges = merge_edges(edges, derived)
    if before_dedup != len(edges):
        print(f"  merged {before_dedup - len(edges)} duplicate edges")

    # Applied at chapter level, after all three layer passes are merged: a quest
    # coined by the narrative pass may be anchored by an entity the social pass
    # found, so a per-unit or per-layer filter would discard it wrongly.
    nodes, edges, dropped_quests, dropped_edges = anchor_quests(nodes, edges)
    if dropped_quests:
        print(
            f"  dropped {dropped_quests} unanchored QUEST nodes "
            f"and {dropped_edges} edge(s) with them"
        )

    # Same position as `anchor_quests`, and for the same reason: an endpoint's
    # type comes from a candidate node, and every node that will exist exists by
    # here. Reporting by default -- the table is new, and this project has twice
    # had silent filtering hide a defect for weeks.
    edges, constraints = enforce(nodes, edges, reject=reject_violations)
    print(format_report(constraints))
    if reject_violations and constraints.violations:
        print(f"  dropped {len(constraints.violations)} type-violating edges")

    # Provenance travels WITH the candidates, not just on stdout and the exit
    # code. A first-ever `--out ch4.json` whose run lost 12 of 180 calls to rate
    # limits cannot trip the no-clobber guard below -- there is nothing to
    # clobber -- and stage 2b consumes the artifact, not the exit code. Reading
    # this object must be enough to tell a complete run from a partial one.
    run_meta = {
        "chapter": chapter.title,
        "corpus": corpus,
        "splitter": splitter,
        "area_depth": split.area_depth,
        "area_depth_qualified": split.depth_qualified,
        "sections_before_refinement": split.before_refinement,
        "sections_subdivided": split.subdivided,
        "sections_over_budget_unsplittable": split.unsplittable,
        "derived_from_depth": structure.depth_derived,
        "derived_from_key": structure.key_derived,
        "derived_from_chapter": structure.chapter_derived,
        "model": model,
        "temperature": temperature,
        "seed": EXTRACTION_SEED,
        "samples": samples,
        "seeds": seeds,
        "node_k": node_k,
        "edge_k": edge_k,
        # Per sample, so a reader can tell a 5-sample vote from a 5-sample run
        # in which two samples were thrown away -- the vote counts below mean
        # something different in each case.
        "sample_failures": sample_failures,
        "samples_voting": len(drawn),
        "layers": [layer.value for layer in (layers or list(Layer))],
        "units": len(units),
        "units_available": units_available,
        "total_calls": total_calls,
        "failed": failed,
        "complete": failed == 0 and len(units) == units_available,
        # Both counts travel with the candidates, and the flag with them: a
        # consumer cannot otherwise tell an artifact whose violations were
        # dropped from one whose violations are still in the edge list.
        "reject_violations": reject_violations,
        "constraint_violations": len(constraints.violations),
        "constraint_unchecked": constraints.unchecked,
        # The evidence for whether an auto-repair pass is worth building. It is
        # the reason the check records reversals at all, so it travels with the
        # candidates rather than only across a terminal.
        "constraint_reversals_would_pass": constraints.reversals_would_pass,
    }

    # The guard asks whether THIS OUTPUT is truncated, not whether a call failed
    # somewhere. With `samples > 1` a failed sample is excluded from the vote, so
    # the candidates below came only from clean samples and are not truncated --
    # refusing to write them would throw away every paid call in the run to
    # protect the output from a sample that did not contribute to it. On chapter
    # 4 (147 units x 3 layers x 5 samples ~= 2,205 calls) at least one failure
    # somewhere is close to expected, so that refusal would be the normal case.
    # Every sample failing is different: there is nothing left to write, and an
    # empty artifact must not clobber a good one.
    output_truncated = failed > 0 if samples == 1 else not drawn

    if out_path:
        if output_truncated and out_path.exists():
            print(
                f"  NOT writing {out_path}: this run had failures and would "
                "clobber the last good output"
            )
        else:
            out_path.write_text(
                json.dumps(
                    {
                        "run": run_meta,
                        "nodes": [asdict(n) for n in nodes],
                        "edges": [asdict(e) for e in edges],
                    },
                    indent=2,
                )
            )
            print(f"  wrote {out_path}")

    summary: dict = {
        "nodes": len(nodes),
        "edges": len(edges),
        "units": len(units),
        "failed": failed,
        "samples": samples,
        "samples_voting": len(drawn),
        "node_k": node_k,
        "edge_k": edge_k,
        "rejected_entity_types": rejected_entity_types,
        "dropped_quests": dropped_quests,
        "dropped_edges": dropped_edges,
        "derived_edges": len(derived),
        "derived_from_depth": structure.depth_derived,
        "derived_from_key": structure.key_derived,
        "derived_from_chapter": structure.chapter_derived,
        "constraint_violations": len(constraints.violations),
        "constraint_unchecked": constraints.unchecked,
        "constraint_reversals_would_pass": constraints.reversals_would_pass,
    }

    if golden is not None:
        report = grade(nodes, edges, golden)
        # The ceiling is what the KEY admits at all. Printed next to every score
        # so a bar can never again be set above what is achievable.
        print(
            f"\n  node recall: {report.node_recall:.2f} "
            f"(unambiguous: {report.node_recall_unambiguous:.2f}, "
            f"ceiling: {report.node_ceiling:.2f})"
        )
        print(
            f"  edge recall: {report.edge_recall:.2f} "
            f"(unambiguous: {report.edge_recall_unambiguous:.2f}, "
            f"ceiling: {report.edge_ceiling:.2f})"
        )
        if report.node_ceiling < 1.0 or report.edge_ceiling < 1.0:
            print(
                "  !! a ceiling below 1.00 is a defect in the GOLDEN SET, not the "
                "extractor: some entries are indistinguishable under the matcher"
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
        summary["node_ceiling"] = report.node_ceiling
        summary["edge_ceiling"] = report.edge_ceiling

    return summary


def build_parser() -> argparse.ArgumentParser:
    """Built here rather than inline in `main` so the defaults are testable.

    `--reject-violations` defaulting off is a decision, not an accident, and a
    test has to be able to see it without spending a paid extraction run.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("chapter", help="Chapter title prefix, e.g. 'Chapter 3'")
    parser.add_argument("--grade", dest="grade_against", metavar="SOURCE",
                        help="Grade against the seed subset for this source, e.g. ch3")
    parser.add_argument("--layer", action="append", dest="layers",
                        choices=[layer.value for layer in Layer],
                        help="Restrict to one layer; repeatable")
    parser.add_argument("-o", "--out", type=Path, help="Write candidates as JSON")
    # The try-a-few-first valve on the only path that spends money: chapter 4
    # alone is 147 units x 3 layers = 441 calls. (It was ~84 units before
    # sections split on the key rather than on `##`.)
    parser.add_argument("--limit", type=int, metavar="N",
                        help="Process only the first N extraction units")
    # Default 1 keeps the present single-run behaviour, and keeps the money a
    # run costs proportional to what was asked for.
    parser.add_argument("--samples", type=int, default=1, metavar="N",
                        help="Draw N extraction samples (seed EXTRACTION_SEED+i) and vote")
    # Default 1 is "keep everything the vote saw", NOT a recommended threshold:
    # the k worth defaulting to is decided from the measured recall/precision
    # curve, not chosen here.
    parser.add_argument("--node-k", type=int, default=1, metavar="K",
                        help="Keep nodes found in at least K samples (default 1: no filtering)")
    parser.add_argument("--edge-k", type=int, default=1, metavar="K",
                        help="Keep edges found in at least K samples (default 1: no filtering)")
    # Off by default: the domain/range table is new and validated against one
    # chapter's golden set only, so it reports before it is trusted to filter.
    # The counts are printed and written to the artifact either way.
    parser.add_argument("--reject-violations", action="store_true",
                        help="Drop edges violating RELATIONSHIP_DOMAIN_RANGE (default: report)")
    # The pivot. `ddb` is the publisher's own markup for any of the 35 books the
    # user owns; `transcription` is the retired per-book vision pass, kept
    # reachable for the A/B and as a fallback while the new path is young.
    parser.add_argument("--corpus", choices=CORPORA, default=DEFAULT_CORPUS,
                        help=f"Which corpus to read (default {DEFAULT_CORPUS})")
    # `key` is Curse of Strahd-specific by construction and cannot serve a book
    # with no keyed rooms. It stays selectable because leg B of the measurement
    # -- DDB text through the OLD splitter -- is the only thing that separates a
    # corpus effect from a splitter effect.
    parser.add_argument("--splitter", choices=SPLITTERS, default="depth",
                        help="How to cut chapters into sections (default depth)")
    return parser


def main() -> None:
    # No handler is configured anywhere else in this chain, so without this
    # the extraction warnings logged on a swallowed exception (see extract.py)
    # depend on logging.lastResort rather than a deliberate, discoverable
    # configuration.
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    parser = build_parser()
    args = parser.parse_args()

    if args.samples < 1:
        parser.error("--samples must be at least 1")
    if args.node_k < 1 or args.edge_k < 1:
        parser.error("--node-k and --edge-k must be at least 1")

    layers = [Layer(v) for v in args.layers] if args.layers else None
    try:
        summary = asyncio.run(
            run(
                args.chapter, args.grade_against, layers, args.out, args.limit,
                samples=args.samples, node_k=args.node_k, edge_k=args.edge_k,
                reject_violations=args.reject_violations,
                corpus=args.corpus, splitter=args.splitter,
            )
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)

    sys.exit(1 if summary["failed"] else 0)


if __name__ == "__main__":
    main()
