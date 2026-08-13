#!/usr/bin/env python3
"""Write one chapter's extracted canon candidates into Neo4j.

Deliberately NOT folded into `extract_canon.py`. Extraction costs real API
spend; this costs nothing. If a write fails -- bad credentials, a constraint
bug, Neo4j restarting -- re-running it must not re-extract, so the expensive
half runs once and the cheap half runs as often as it needs to.

    uv run python -m backend.scripts.extract_canon "Chapter 3" -o ch3.json
    uv run python -m backend.scripts.write_canon ch3.json --chapter the-village-of-barovia

Every candidate that does not reach the graph is counted and printed. Silent
filtering has twice hidden a defect in this project for weeks.
"""

import argparse
import json
import sys
from collections import Counter
from dataclasses import fields
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.canon.gazetteer import load_gazetteer
from backend.canon.models import CandidateEdge, CandidateNode
from backend.canon.seed_loader import LOCATION_SUBTYPE_SEED, load_location_subtypes
from backend.canon.structure import place_from_chapter_title
from backend.canon.writer import (
    CampaignDataAttached,
    ChapterAlreadyWritten,
    FilterReport,
    WriteEdge,
    WriteNode,
    ensure_schema,
    plan_write,
    restrict_to_accepted,
    write_chapter,
)
from backend.core.database import neo4j_session
from backend.graph.schema import EntityType

DEFAULT_GAZETTEER = Path("data/gazetteer/curse-of-strahd.json")
#: Where the verifier looks for the run artifact. `data/` is gitignored, and
#: stays that way -- the corpus this is derived from is copyrighted.
DEFAULT_RUNS_DIR = Path("data/canon/runs")

#: How many of each drop kind to print. The COUNTS are always complete; this
#: caps only the examples, which exist so a reader can see what a filter is
#: actually removing rather than trusting the number.
EXAMPLES = 8


def _only_known(raw: dict, cls) -> dict:
    """Keep the keys the dataclass declares.

    Artifacts written by later pipeline stages carry extra keys (stage B
    records its decisions alongside each candidate), and an unknown key must not
    make a perfectly good candidate set unloadable.
    """
    known = {f.name for f in fields(cls)}
    return {k: v for k, v in raw.items() if k in known}


def parse_artifact(document: dict) -> tuple[list[CandidateNode], list[CandidateEdge], dict]:
    """An extraction artifact's candidates plus its `run` block."""
    nodes = [CandidateNode(**_only_known(n, CandidateNode)) for n in document.get("nodes", [])]
    edges = [CandidateEdge(**_only_known(e, CandidateEdge)) for e in document.get("edges", [])]
    return nodes, edges, document.get("run", {})


def chapter_place_of_run(extraction_run: dict) -> str | None:
    """The place the chapter is about, re-derived from the title it recorded.

    Every chapter-level CONTAINS edge in the artifact names this string as its
    source, so the writer has to arrive at exactly the same one or the edges
    dangle -- which is what they did, for every chapter, until this existed.
    `place_from_chapter_title` is therefore the extractor's own function rather
    than a second implementation of the same rule.

    Re-derived rather than read from a `chapter_place` field, because the `run`
    block is the EXTRACTION's record of what was paid for and this stage may not
    rewrite it -- and because the chapters already extracted carry no such
    field, so a stored copy would need this fallback anyway.

    Not guarded here on whether the chapter keys anything: `plan_write` applies
    that guard, in the same place as every other anti-fabrication rule.
    """
    title = extraction_run.get("chapter") or ""
    return place_from_chapter_title(title)


def format_report(report: FilterReport) -> str:
    """Every drop count, printed whether or not it is zero.

    A silent pass is indistinguishable from a filter that never ran -- the same
    reason `constraints.format_report` prints when clean.
    """
    lines = [
        f"  candidates: {report.candidate_nodes} nodes, {report.candidate_edges} edges",
        "  nodes MINTED here (not candidates, not drops):",
        f"    the chapter's own place:                         {report.derived_nodes}",
        "      (the parent every top-level keyed area hangs from -- an extraction",
        "       candidate never names it, so it is written or the hierarchy is severed)",
        "  node drops:",
        f"    gazetteer (not a known name, not a keyed place): {report.gazetteer_dropped}",
        f"    unnameable (name slugifies to nothing):          {report.unnameable}",
        f"    undecidable keyed place (two keys, neither its):  {report.undecidable_keyed}",
        f"    duplicate (same id as an earlier candidate):     {report.duplicate_nodes}",
        "  edge drops:",
        f"    self-loops:                                      {report.self_loops}",
        f"    constraint violations (type-impossible):         {report.constraint_violations}",
        f"    dangling (an endpoint has no node):              {report.dangling_edges}",
        f"    ambiguous (endpoint name has two types):         {report.ambiguous_edges}",
        f"    duplicate (same source, type and target):        {report.duplicate_edges}",
        "  edges KEPT by endpoint resolution (not a drop):",
        f"    constraint-unique endpoint chosen:               {report.endpoint_resolved}",
        "      (the constraint check is vacuous on these -- they were CHOSEN to satisfy it,",
        "       and each carries endpoint_resolved='constraint' in the graph to say so)",
        "  contradictions KEPT (not a drop -- both halves are written):",
        f"    mutually exclusive pairs:                        {report.exclusive_conflicts}",
        f"    proposed edges demoted by an accepted one:       {report.conflicted_edges}",
        "      (which of two PROPOSED edges is right is not decided here: there is no oracle,",
        "       and a silent guess is how a wrong edge becomes indistinguishable from canon)",
        "  trust split:",
        f"    nodes:  {report.accepted_nodes} accepted, {report.proposed_nodes} proposed",
        f"    edges:  {report.accepted_edges} accepted, {report.proposed_edges} proposed"
        f" (of which {report.conflicted_edges} conflicted)",
        f"  to write: {report.written_nodes} nodes, {report.written_edges} edges",
    ]
    # Complete, not capped: a contradiction the graph now holds ON PURPOSE is
    # exactly what a human is here to read.
    for conflict in report.conflicts:
        lines.append(f"    - conflict: {conflict}")
    for label, dropped in (
        ("gazetteer", report.dropped_gazetteer),
        ("undecidable keyed", report.dropped_undecidable_keyed),
        ("self-loop", report.dropped_self_loops),
        ("violation", report.dropped_violations),
        ("dangling", report.dropped_dangling),
        ("ambiguous", report.dropped_ambiguous),
        ("resolved", report.resolved_endpoints),
    ):
        for item in dropped[:EXAMPLES]:
            lines.append(f"    - {label}: {item}")
        if len(dropped) > EXAMPLES:
            lines.append(f"    - {label}: ... and {len(dropped) - EXAMPLES} more")
    if report.ambiguous_names:
        lines.append(
            "  names carrying two entity types (disputed type, not two entities): "
            + ", ".join(report.ambiguous_names)
        )
    return "\n".join(lines)


def run_artifact(
    *,
    chapter_slug: str,
    source: Path,
    extraction_run: dict,
    candidate_nodes: list[dict],
    candidate_edges: list[dict],
    report: FilterReport,
    nodes: list[WriteNode],
    edges: list[WriteEdge],
    replaced: dict,
    accepted_only: bool = False,
) -> dict:
    """The document the verifier reads to tell a complete run from a truncated one.

    `run` is the EXTRACTION's block, carried through untouched: it is the only
    record of what was paid for, and rewriting any of it here would let this
    stage launder a run that lost 12 calls to a rate limit into a clean one.
    What this stage did goes under `write`, beside it.

    `nodes` and `edges` are the CANDIDATES, not the survivors: the verifier's
    band check compares what landed against what was proposed, and a file that
    listed only the survivors would score 100% by construction.
    """
    return {
        "run": extraction_run,
        "write": {
            "chapter_slug": chapter_slug,
            "source_artifact": str(source),
            "written_at": datetime.now(UTC).isoformat(),
            "filters": report.as_dict(),
            # Counted over EVERY type each node carries, so a node the samples
            # disputed appears under both -- these are label counts, and the
            # column no longer sums to the node count. `written_nodes` is the
            # figure that does.
            "written_nodes_by_type": dict(
                sorted(Counter(t for n in nodes for t in n.entity_types).items())
            ),
            "written_edges_by_type": dict(
                sorted(Counter(e.rel_type.value for e in edges).items())
            ),
            # The hierarchy census, read off `subtype_label` rather than
            # `location_subtype` so it counts what actually reached the graph.
            # Places with no rung are counted under `""`, deliberately visible:
            # "how many places did this chapter leave unclassified" is the
            # question the no-default rule exists to keep askable.
            "written_locations_by_subtype": dict(
                sorted(
                    Counter(
                        n.subtype_label
                        for n in nodes
                        if EntityType.LOCATION.value in n.labels
                    ).items()
                )
            ),
            "deleted_nodes": replaced.get("deleted_nodes", 0),
            "deleted_edges": replaced.get("deleted_edges", 0),
            "ambiguous_names": report.ambiguous_names,
            # The edges on which the verifier's constraint check proves nothing.
            "resolved_endpoints": report.resolved_endpoints,
            # What actually landed, split by trust. Read off the WRITTEN objects
            # rather than the plan's counts, because `--accepted-only` narrows
            # the write after planning and an artifact stating the plan's split
            # would describe a graph that was never written.
            "accepted_only": accepted_only,
            "written_nodes_by_status": dict(sorted(Counter(n.status for n in nodes).items())),
            "written_edges_by_status": dict(sorted(Counter(e.status for e in edges).items())),
            # The contradictions the graph now holds on purpose. A human at gate
            # G3 reads these; nothing automatic resolves them.
            "conflicts": report.conflicts,
        },
        "nodes": candidate_nodes,
        "edges": candidate_edges,
    }


def build_parser() -> argparse.ArgumentParser:
    """Built here rather than inline in `main` so the defaults are testable."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path, help="Candidate JSON from extract_canon")
    parser.add_argument(
        "--chapter",
        required=True,
        metavar="SLUG",
        help="Chapter slug to key the graph on, e.g. the-village-of-barovia",
    )
    # Refusing by default is gate G6: overwriting canon a human may already have
    # reviewed is a decision, not something a re-run does by accident.
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Delete this chapter's canon nodes and edges first, in the same transaction",
    )
    parser.add_argument("--gazetteer", type=Path, default=DEFAULT_GAZETTEER)
    parser.add_argument(
        "--location-subtypes",
        type=Path,
        default=LOCATION_SUBTYPE_SEED,
        help="Hand-authored REGION/SETTLEMENT/WILD seed. SITE and AREA are derived.",
    )
    parser.add_argument(
        "--runs-dir",
        type=Path,
        default=DEFAULT_RUNS_DIR,
        help="Where to write <slug>.json, the run artifact the verifier reads",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan and print every drop count; touch neither Neo4j nor the run artifact",
    )
    # OFF by default, and it has to stay that way. The loop's goal predicate
    # counts nodes, so an accepted-only write would tell it a chapter is done
    # while most of the chapter is gone -- and throwing the proposed set away
    # before a human has read it destroys the review queue this exists to build.
    parser.add_argument(
        "--accepted-only",
        action="store_true",
        help="Write only derived (accepted) edges and the nodes they need. Off by default.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()

    document = json.loads(args.artifact.read_text())
    nodes, edges, extraction_run = parse_artifact(document)

    # The slug the graph is keyed on is the CALLER's: the loop discovers
    # chapters from the corpus filenames, while the extractor derived its own
    # from the chapter title. They routinely differ -- and a silent override
    # would make a chapter's provenance impossible to trace back.
    artifact_slugs = {n.chapter_slug for n in nodes if n.chapter_slug} - {args.chapter}
    if artifact_slugs:
        print(
            f"  note: artifact says chapter_slug={', '.join(sorted(artifact_slugs))!r}; "
            f"writing as {args.chapter!r} (the requested slug wins)"
        )

    failed = extraction_run.get("failed")
    if failed != 0:
        print(
            "  !! the extraction artifact does not record a complete run "
            f"(run.failed={failed!r}) -- the verifier's check 6 will FAIL for this chapter !!"
        )

    gazetteer = load_gazetteer(args.gazetteer)
    print(f"  gazetteer: {len(gazetteer)} entries from {args.gazetteer}")

    subtypes = load_location_subtypes(args.location_subtypes)
    print(f"  location subtypes: {len(subtypes)} authored from {args.location_subtypes}")

    chapter_place = chapter_place_of_run(extraction_run)
    print(f"  chapter place: {chapter_place!r} (parent of this chapter's top-level areas)")

    write_nodes, write_edges, report = plan_write(
        nodes,
        edges,
        gazetteer,
        args.chapter,
        chapter_place=chapter_place,
        subtypes=subtypes,
    )
    print(format_report(report))

    if args.accepted_only:
        planned_nodes, planned_edges = len(write_nodes), len(write_edges)
        write_nodes, write_edges = restrict_to_accepted(write_nodes, write_edges)
        print(
            "  --accepted-only: dropped "
            f"{planned_edges - len(write_edges)} proposed edges and "
            f"{planned_nodes - len(write_nodes)} nodes left with nothing attached; "
            f"{len(write_nodes)} nodes and {len(write_edges)} edges remain"
        )

    if not write_nodes:
        print("  refusing to write: no node survived the filters", file=sys.stderr)
        sys.exit(1)

    if args.dry_run:
        print("  --dry-run: nothing written")
        return

    with neo4j_session() as session:
        ensure_schema(session)
        try:
            summary = write_chapter(
                session, args.chapter, write_nodes, write_edges, replace=args.replace
            )
        except ChapterAlreadyWritten as exc:
            print(f"  {exc}", file=sys.stderr)
            sys.exit(1)
        except CampaignDataAttached as exc:
            print(f"  {exc}", file=sys.stderr)
            sys.exit(1)

    if summary["deleted_nodes"] or summary["deleted_edges"]:
        print(
            f"  replaced: deleted {summary['deleted_nodes']} nodes "
            f"and {summary['deleted_edges']} edges"
        )
    print(f"  wrote {summary['nodes']} nodes and {summary['edges']} edges to {args.chapter}")

    args.runs_dir.mkdir(parents=True, exist_ok=True)
    out_path = args.runs_dir / f"{args.chapter}.json"
    out_path.write_text(
        json.dumps(
            run_artifact(
                chapter_slug=args.chapter,
                source=args.artifact,
                extraction_run=extraction_run,
                candidate_nodes=document.get("nodes", []),
                candidate_edges=document.get("edges", []),
                report=report,
                nodes=write_nodes,
                edges=write_edges,
                replaced=summary,
                accepted_only=args.accepted_only,
            ),
            indent=2,
        )
    )
    print(f"  wrote {out_path}")


if __name__ == "__main__":
    main()
