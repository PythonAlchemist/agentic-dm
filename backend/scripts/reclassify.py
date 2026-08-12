#!/usr/bin/env python3
"""Re-type an artifact's LLM edges with stage B, and measure what changed.

AN EXPERIMENT, DELIBERATELY NOT WIRED INTO `extract_canon.py`. It reads an
artifact that already exists and writes a new one, so the baseline stays
untouched and the comparison isolates exactly one variable: same pairs, same
evidence, different typing. No extraction is re-run, and nothing writes to Neo4j.

WHAT IS RE-TYPED, AND WHAT IS NOT. Only the LLM edges. The derived structural
edges (`evidence == STRUCTURAL_EVIDENCE`) pass through untouched: they are a
deterministic function of the section keys, they are the one layer a fabrication
check found clean, and they violate the type table at 3.6% against the LLM
layer's 30.6%. Re-deciding them would spend money to put the clean layer at risk
of a model's opinion.

THE METRIC THAT WOULD LIE. Stage B offers only type-legal relations, so the
constraint-violation rate of its output is ZERO BY CONSTRUCTION. It is printed
here only as the tautology it is, labelled as such. The numbers that mean
something are golden recall before and after, the decline rate, and the
four-way agreement split.

WHY THE SPLIT IS FOUR-WAY. "Agreed" is not one number: keeping the type but
flipping the direction is a different event from changing the type, and both are
different from declining. Reporting a single agreement rate would hide which of
the two things stage B was built to re-decide it actually re-decided.
"""

import argparse
import asyncio
import json
import logging
import sys
from collections import Counter
from dataclasses import asdict, replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import yaml

from backend.canon.classify import (
    BATCH_SIZE,
    MAX_RELATIONS,
    NO_ANSWER,
    NONE_RELATION,
    Decision,
    RelationClassifier,
    is_self_pair,
    offered_options,
    pairs_from_edges,
)
from backend.canon.constraints import format_report, report_edges
from backend.canon.extract import EXTRACTION_MODEL
from backend.canon.grade import grade
from backend.canon.models import CandidateEdge, CandidateNode
from backend.canon.seed_loader import SEED_DIR, extractable_subset
from backend.canon.structure import STRUCTURAL_EVIDENCE
from backend.graph.schema import LAYER_MAP, RelationshipType

logger = logging.getLogger(__name__)

# gpt-4o-mini list price, USD per token, at the time of the run. Recorded as a
# constant rather than folded into a printed number so a later reader can see
# what the cost figure was computed from.
INPUT_USD_PER_TOKEN = 0.150 / 1_000_000
OUTPUT_USD_PER_TOKEN = 0.600 / 1_000_000

#: The four ways stage B can respond to an edge, plus the three non-answers.
KEPT = "kept"
FLIPPED = "flipped direction"
CHANGED = "changed type"
DECLINED = "NONE"
NO_RELATION_LEGAL = "NONE (no legal relation)"
SELF_LOOP = "NONE (self-loop)"
FAILED = "no answer"

#: Relations whose gloss states no asymmetry, so swapping their endpoints
#: changes the stored tuple and nothing about the claim. `grade.py` matches
#: edges direction-sensitively, so a flip on one of these costs recall without
#: being wrong -- reported, never silently corrected.
SYMMETRIC_RELATIONS = frozenset({
    "RELATED_TO", "KNOWS", "ALLIED_WITH", "CONNECTED_TO", "IDENTITY_OF", "ENEMY_OF",
})

#: Two relations that cannot both hold of one pair: one being under two names
#: cannot also be its own kin. The live graph holds both for Ireena/Tatyana.
#: Detected and REPORTED here, never repaired -- a mutual-exclusion check in
#: `constraints.py` is separate work, and this experiment's job is to say
#: whether allowing several relations per pair produces the contradiction.
CONTRADICTORY_PAIRS = frozenset({frozenset({"IDENTITY_OF", "RELATED_TO"})})


def load_artifact(path: Path) -> tuple[dict, list[CandidateNode], list[CandidateEdge]]:
    payload = json.loads(path.read_text())
    nodes = [CandidateNode(**n) for n in payload.get("nodes", [])]
    edges = [CandidateEdge(**e) for e in payload.get("edges", [])]
    return payload, nodes, edges


def split_edges(edges: list[CandidateEdge]) -> tuple[list[int], list[int]]:
    """`(llm_indices, derived_indices)`, by the structural evidence marker."""
    llm = [i for i, e in enumerate(edges) if e.evidence != STRUCTURAL_EVIDENCE]
    derived = [i for i, e in enumerate(edges) if e.evidence == STRUCTURAL_EVIDENCE]
    return llm, derived


def classify_outcome(
    edge: CandidateEdge,
    decisions: list[Decision],
    *,
    was_asked: bool,
    is_self_loop: bool = False,
) -> str:
    """Which of the four ways stage B answered this edge.

    The three `NONE`-shaped buckets are kept apart because they are decisions by
    three different authorities: the model declined, the type TABLE admitted
    nothing, or the two endpoints were the same entity. Folding any of them into
    the decline rate would credit the model with declines it never made, which
    is precisely how this experiment could report a precision mechanism it does
    not have.

    A type change and a direction flip are separate outcomes even though both
    are "disagreement": they are the two different things stage B was built to
    re-decide, and one number could not say which of them it did.

    WITH SEVERAL RELATIONS PER PAIR, `KEPT` MEANS "THE ORIGINAL SURVIVES AMONG
    THE ANSWERS", which is a WEAKER bar than the previous run's "the single
    answer was the original". More answers means more chances to contain it, so
    `kept` and `flipped` can rise for mechanical reasons alone. Any comparison
    with the one-relation run has to be read with the answers-per-pair
    distribution beside it, which `run` prints for exactly this reason.
    """
    if any(d.rel_type == NO_ANSWER for d in decisions):
        return FAILED
    if all(d.rel_type == NONE_RELATION for d in decisions):
        if is_self_loop:
            return SELF_LOOP
        return DECLINED if was_asked else NO_RELATION_LEGAL
    same_type = [d for d in decisions if d.rel_type == edge.rel_type]
    if any(
        (d.source_name, d.target_name) == (edge.source_name, edge.target_name)
        for d in same_type
    ):
        return KEPT
    if same_type:
        return FLIPPED
    return CHANGED


def retyped_edge(edge: CandidateEdge, decision: Decision) -> CandidateEdge:
    """The edge as stage B decided it.

    `layer` is recomputed from LAYER_MAP: a spatial-pass edge re-typed SERVES is
    a social edge now, and leaving the old label would make the layer field
    describe which PASS found the pair rather than what the edge is -- silently
    wrong for anything that groups by layer.

    `votes` is deliberately preserved. It records how many EXTRACTION samples
    found the pair, which re-typing does not change and must not appear to.
    """
    layer = LAYER_MAP.get(RelationshipType(decision.rel_type))
    return replace(
        edge,
        source_name=decision.source_name,
        target_name=decision.target_name,
        rel_type=decision.rel_type,
        layer=layer.value if layer else "",
    )


def golden_subset(source: str) -> dict:
    data = yaml.safe_load((SEED_DIR / "village-of-barovia.yaml").read_text())
    subset = extractable_subset(data, source)
    if not subset["nodes"] and not subset["edges"]:
        raise ValueError(f"--grade {source!r} matches no golden entries in this seed")
    return subset


def print_recall(label: str, nodes: list[CandidateNode], edges: list[CandidateEdge],
                 golden: dict) -> dict:
    report = grade(nodes, edges, golden)
    print(
        f"  {label:9s} node {report.node_recall:.3f} "
        f"(unambiguous {report.node_recall_unambiguous:.3f})   "
        f"edge {report.edge_recall:.3f} (unambiguous {report.edge_recall_unambiguous:.3f})"
    )
    return {
        "node_recall": report.node_recall,
        "node_recall_unambiguous": report.node_recall_unambiguous,
        "edge_recall": report.edge_recall,
        "edge_recall_unambiguous": report.edge_recall_unambiguous,
        "missing_edges": report.missing_edges,
    }


async def run(
    in_path: Path,
    out_path: Path | None,
    grade_against: str | None,
    limit: int | None = None,
    batch_size: int = BATCH_SIZE,
    model: str = EXTRACTION_MODEL,
    max_relations: int = MAX_RELATIONS,
) -> dict:
    golden = golden_subset(grade_against) if grade_against else None

    payload, nodes, edges = load_artifact(in_path)
    llm_indices, derived_indices = split_edges(edges)
    if limit is not None:
        llm_indices = llm_indices[:limit]
    llm_edges = [edges[i] for i in llm_indices]
    print(
        f"{in_path.name}: {len(nodes)} nodes, {len(edges)} edges "
        f"({len(llm_edges)} LLM to re-type, {len(derived_indices)} derived untouched)"
    )

    pairs = pairs_from_edges(nodes, llm_edges)
    option_counts = [len(offered_options(p)) for p in pairs]
    if option_counts:
        ordered = sorted(option_counts)
        print(
            f"  offered options per pair: min {ordered[0]}, median "
            f"{ordered[len(ordered) // 2]}, max {ordered[-1]} "
            f"(out of 46 = 23 types x 2 directions)"
        )

    self_loops = [is_self_pair(p) for p in pairs]
    classifier = RelationClassifier(
        model=model, batch_size=batch_size, max_relations=max_relations
    )
    decisions = await classifier.classify(pairs)

    outcomes = [
        classify_outcome(edge, decision, was_asked=count > 0, is_self_loop=loop)
        for edge, decision, count, loop in zip(
            llm_edges, decisions, option_counts, self_loops, strict=True
        )
    ]
    split = Counter(outcomes)
    kept_outcomes = (KEPT, FLIPPED, CHANGED)

    print(
        f"\n  {classifier.calls} calls, {classifier.failures} pairs with no answer "
        f"(call failed {classifier.call_failures}, unreadable {classifier.unanswered}, "
        f"every relation off the offered list {classifier.unusable})"
    )
    print(
        f"  {classifier.off_vocabulary} individual relations refused as not offered; "
        f"{classifier.self_loops} self-loops declined without a call"
    )
    print("  four-way agreement split:")
    for outcome in (KEPT, FLIPPED, CHANGED, DECLINED, NO_RELATION_LEGAL, SELF_LOOP, FAILED):
        count = split.get(outcome, 0)
        share = count / len(llm_edges) if llm_edges else 0.0
        print(f"    {outcome:26s} {count:5d}  {share:6.1%}")
    print(
        "    (`kept`/`flipped` mean the original survives AMONG the answers, a weaker\n"
        "     bar than the one-relation run -- read with the distribution below)"
    )

    # The decline rate is the model's own, over the pairs it was actually asked
    # about. A table decline, a self-loop and a failure are not evidence the
    # model declines -- all are reported, none are counted in.
    asked = (
        len(llm_edges)
        - split.get(NO_RELATION_LEGAL, 0)
        - split.get(SELF_LOOP, 0)
        - split.get(FAILED, 0)
    )
    decline_rate = split.get(DECLINED, 0) / asked if asked else 0.0
    print(f"\n  DECLINE RATE: {split.get(DECLINED, 0)}/{asked} = {decline_rate:.1%} "
          "of pairs the model was asked about")

    # Whether the CAP or the EVIDENCE is deciding how many relations a pair
    # carries. If nearly every answered pair uses every slot, the cap is doing
    # the work and the number below is about the cap, not about the corpus.
    answered = [d for d, o in zip(decisions, outcomes, strict=True) if o in kept_outcomes]
    per_pair = Counter(len(d) for d in answered)
    multi = sum(n for size, n in per_pair.items() if size > 1)
    print(
        f"  relations per surviving pair: {dict(sorted(per_pair.items()))} "
        f"-- {multi}/{len(answered) or 1} = "
        f"{(multi / len(answered) if answered else 0):.1%} used more than one slot"
    )
    print(f"  pairs where the model named MORE than the cap of {max_relations}: "
          f"{classifier.capped}")

    # Does allowing several relations produce the known contradiction? Reported,
    # never repaired: the mutual-exclusion check belongs in constraints.py.
    contradictions = [
        (edge, decision)
        for edge, decision, outcome in zip(llm_edges, decisions, outcomes, strict=True)
        if outcome in kept_outcomes
        and any({d.rel_type for d in decision} >= banned for banned in CONTRADICTORY_PAIRS)
    ]
    print(f"  CONTRADICTORY relation sets emitted for one pair: {len(contradictions)}")
    for edge, decision in contradictions[:10]:
        print(f"    {edge.source_name} / {edge.target_name}: "
              f"{sorted(d.rel_type for d in decision)}")

    confidences = Counter(d.confidence for decision in answered for d in decision)
    print(f"  confidence on surviving edges: {dict(confidences)}")

    # Symmetric flips cost golden recall without being wrong (see
    # SYMMETRIC_RELATIONS). Counted so the recall delta can be read honestly.
    symmetric_flips = sum(
        1
        for decision, outcome in zip(decisions, outcomes, strict=True)
        if outcome == FLIPPED and any(d.rel_type in SYMMETRIC_RELATIONS for d in decision)
    )
    print(f"  of {split.get(FLIPPED, 0)} direction flips, {symmetric_flips} are on a "
          "symmetric relation (a grader artifact, not a change of claim)")

    surviving = [
        retyped_edge(edge, single)
        for edge, decision, outcome in zip(llm_edges, decisions, outcomes, strict=True)
        if outcome in kept_outcomes
        for single in decision
    ]
    derived_edges = [edges[i] for i in derived_indices]
    new_edges = surviving + derived_edges

    before_report = report_edges(nodes, edges)
    after_report = report_edges(nodes, new_edges)
    print("\n  constraint violations BEFORE:")
    print(format_report(before_report))
    print("  constraint violations AFTER (ZERO BY CONSTRUCTION on the re-typed")
    print("  edges -- this is the design, NOT a result; see the module docstring):")
    print(format_report(after_report))

    cost = (
        classifier.input_tokens * INPUT_USD_PER_TOKEN
        + classifier.output_tokens * OUTPUT_USD_PER_TOKEN
    )
    print(
        f"\n  tokens: {classifier.input_tokens} in, {classifier.output_tokens} out "
        f"-> ${cost:.4f} at {model} list price"
    )

    recall: dict = {}
    if golden is not None:
        print("\n  golden recall (chapter 3 subset):")
        recall["before"] = print_recall("BEFORE", nodes, edges, golden)
        recall["after"] = print_recall("AFTER", nodes, new_edges, golden)

    summary = {
        "artifact": str(in_path),
        "model": model,
        "batch_size": batch_size,
        "llm_edges": len(llm_edges),
        "derived_edges": len(derived_edges),
        "surviving_llm_edges": len(surviving),
        "calls": classifier.calls,
        "failures": classifier.failures,
        "call_failures": classifier.call_failures,
        "unanswered": classifier.unanswered,
        "unusable": classifier.unusable,
        "off_vocabulary": classifier.off_vocabulary,
        "capped": classifier.capped,
        "self_loops": classifier.self_loops,
        "no_legal_relation": classifier.no_legal_relation,
        "max_relations": max_relations,
        "relations_per_surviving_pair": dict(sorted(per_pair.items())),
        "multi_relation_pairs": multi,
        "contradictions": len(contradictions),
        "symmetric_flips": symmetric_flips,
        "split": dict(split),
        "decline_rate": decline_rate,
        "asked": asked,
        "confidence": dict(confidences),
        "input_tokens": classifier.input_tokens,
        "output_tokens": classifier.output_tokens,
        "cost_usd": cost,
        "violations_before": len(before_report.violations),
        "violations_after": len(after_report.violations),
        "recall": recall,
    }

    if out_path:
        # A run that lost calls must not silently replace a good artifact: the
        # missing answers would look like edges the model declined.
        if classifier.failures and out_path.exists():
            print(f"  NOT writing {out_path}: {classifier.failures} pairs had no answer")
        else:
            out_path.write_text(json.dumps({
                "run": {**payload.get("run", {}), "stage_b": summary},
                "nodes": [asdict(n) for n in nodes],
                "edges": [asdict(e) for e in new_edges],
                # Kept so the four-way split can be recomputed, and so a human
                # can read what stage B decided against what it replaced.
                "stage_b_decisions": [
                    {
                        "before": asdict(edge),
                        "after": [asdict(d) for d in decision],
                        "outcome": outcome,
                    }
                    for edge, decision, outcome in zip(
                        llm_edges, decisions, outcomes, strict=True
                    )
                ],
            }, indent=2))
            print(f"  wrote {out_path}")

    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path, help="Candidate artifact written by extract_canon")
    parser.add_argument("-o", "--out", type=Path, help="Write the re-typed artifact here")
    parser.add_argument("--grade", dest="grade_against", metavar="SOURCE",
                        help="Grade before and after against the seed subset for this source")
    parser.add_argument("--limit", type=int, metavar="N",
                        help="Re-type only the first N LLM edges (the try-it-first valve)")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE, metavar="N",
                        help=f"Pairs per call (default {BATCH_SIZE})")
    parser.add_argument("--max-relations", type=int, default=MAX_RELATIONS, metavar="N",
                        help=f"Relations one pair may carry (default {MAX_RELATIONS})")
    parser.add_argument("--model", default=EXTRACTION_MODEL)
    return parser


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    args = build_parser().parse_args()
    try:
        summary = asyncio.run(run(
            args.artifact, args.out, args.grade_against, args.limit,
            batch_size=args.batch_size, model=args.model,
            max_relations=args.max_relations,
        ))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
    sys.exit(1 if summary["failures"] else 0)


if __name__ == "__main__":
    main()
