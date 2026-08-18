"""Score canon retrieval against the hand-authored question set.

    uv run python -m backend.scripts.eval_retrieval
    uv run python -m backend.scripts.eval_retrieval --limit 3 --verbose

Costs nothing: retrieval is deterministic and no model runs. Re-run it after
every chapter the loop writes -- the question set is a regression suite, not a
one-off measurement.

WHAT IS SCORED, AND WHAT DELIBERATELY IS NOT. Gold is the SECTION a DM would
have to read. Whether retrieval put that section in front of them is a fact:
mechanically checkable, no judge, no fuzzy string matching, no model marking its
own homework. Whether an answer written from that section would be any good is a
different question and is not asked here.

THE SPLIT THAT MATTERS IS `no-anchor` VS `missed`. A question naming nothing the
graph knows failed BEFORE retrieval ranked anything, and no amount of ranking
work would fix it -- it needs an alias, or an entity that was never extracted.
A question that anchored fine and still missed is a ranking or coverage problem.
One recall number blurs the two and points every reader at the wrong repair.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from backend.canon.retrieval import DEFAULT_LIMIT, CanonRetriever, Retrieval

DEFAULT_QUESTIONS = Path("evals/canon-questions.yaml")


def reciprocal_rank(retrieved: tuple[str, ...], gold: list[str]) -> float:
    """1/rank of the first gold section, or 0.

    Rank over what was RETURNED, so a gold section cut by the budget scores 0
    rather than scoring by where it would have sat in an unbounded list. The
    budget is part of the system being measured.
    """
    for position, section_id in enumerate(retrieved, start=1):
        if section_id in gold:
            return 1.0 / position
    return 0.0


def hit_path(result: Retrieval, gold: list[str]) -> str:
    """Which path produced the FIRST gold passage, or empty if none did.

    Not `result.path`. A result that anchored on a name now also carries text
    passages -- `TEXT_SLOTS` reserves room for them -- so grouping hits by how
    the QUESTION resolved credited the graph for answers Lucene found. That
    reporting said "by name 26/31" on a run where several of the 26 were text.
    Crediting the wrong path is exactly the conclusion this harness exists to
    make impossible, so the credit follows the passage.
    """
    for passage in result.passages:
        if passage.section_id in gold:
            return passage.path
    return ""


def score(question: dict, result: Retrieval) -> dict:
    gold = list(question.get("sections") or [])
    retrieved = result.section_ids
    hit = any(section_id in gold for section_id in retrieved)
    return {
        "hit_path": hit_path(result, gold),
        # The author's PREDICTION about which path should answer, written from
        # the book before anything was run. Empty for set one, which predates
        # the field -- and deliberately NOT backfilled, because assigning a
        # label to a question whose result you have already seen produces a
        # prediction that cannot be wrong.
        "needs": question.get("needs", ""),
        "id": question["id"],
        "question": question["question"],
        "gold": gold,
        "retrieved": list(retrieved),
        "anchored": bool(result.anchors),
        "anchors": [f"{a.surface}->{a.name}" for a in result.anchors],
        "hit": hit,
        "rr": reciprocal_rank(retrieved, gold),
        "dropped": result.dropped,
        "ambiguous": list(result.ambiguous),
        "miss_reason": result.miss_reason,
        "path": result.path or "-",
        "terms": list(result.terms),
    }


def summarize(rows: list[dict]) -> dict:
    total = len(rows)
    anchored = [r for r in rows if r["anchored"]]
    hits = [r for r in rows if r["hit"]]
    return {
        "total": total,
        "anchored": len(anchored),
        "hits": len(hits),
        # Recall over ANCHORED questions only, reported beside overall recall.
        # Retrieval cannot be blamed for ranking a question it never got a
        # handle on, and cannot be credited for the ones it did get.
        "recall_overall": len(hits) / total if total else 0.0,
        # Hits AMONG THE ANCHORED, not all hits over the anchored count. With a
        # text fallback answering questions that never anchored, the latter
        # divides one population by another and reported 111%.
        "recall_anchored": (
            sum(1 for r in anchored if r["hit"]) / len(anchored) if anchored else 0.0
        ),
        "mrr": sum(r["rr"] for r in rows) / total if total else 0.0,
        "no_anchor": [r["id"] for r in rows if not r["anchored"]],
        "anchored_but_missed": [r["id"] for r in rows if r["anchored"] and not r["hit"]],
        # How the QUESTION resolved: on a name, or on nothing. This is about
        # anchoring, and says nothing about which path then answered.
        "by_path": {
            path: {
                "n": len(group),
                "hits": sum(1 for r in group if r["hit"]),
            }
            for path in ("graph", "text", "-")
            if (group := [r for r in rows if r["path"] == path])
        },
        # Which path produced the answer, never merged. A graph hit resolved a
        # name the book wrote; a text hit is a Lucene score agreeing with a
        # guess. Averaging them into one recall makes the fallback look like an
        # improvement to the graph, which is the one conclusion this harness
        # must not support -- and since a graph-anchored result now CARRIES text
        # passages, this is the only place that distinction survives.
        "by_answer": {
            path: sum(1 for r in rows if r["hit_path"] == path)
            for path in ("graph", "text")
        },
        # The prediction against the outcome. `needs: graph` claims the question
        # names something the graph holds and that a resolved name will answer
        # it; `needs: text` claims it names nothing and the index must. Each
        # disagreement is a fact no aggregate recall shows -- a `graph` question
        # answered by Lucene means the name bought nothing, and a `text`
        # question that anchored means the graph holds a name I did not think
        # it had.
        "by_needs": {
            needs: {
                "n": len(group),
                "hits": sum(1 for r in group if r["hit"]),
                "answered_by_graph": sum(1 for r in group if r["hit_path"] == "graph"),
                "answered_by_text": sum(1 for r in group if r["hit_path"] == "text"),
                "anchored": sum(1 for r in group if r["anchored"]),
            }
            for needs in ("graph", "text", "either")
            if (group := [r for r in rows if r["needs"] == needs])
        },
    }


def render(rows: list[dict], summary: dict, *, verbose: bool) -> str:
    out: list[str] = []
    out.append(f"  {'id':<5} {'path':<6} {'hit':<5} {'rr':<5} question")
    out.append(f"  {'-'*5} {'-'*6} {'-'*5} {'-'*5} {'-'*44}")
    for row in rows:
        out.append(
            f"  {row['id']:<5} {row['path']:<6} "
            f"{'yes' if row['hit'] else 'NO':<5} {row['rr']:<5.2f} {row['question'][:44]}"
        )

    out.append("")
    out.append("  questions, by how they anchored")
    for path, stat in summary["by_path"].items():
        label = {
            "graph": "on a name",
            "text": "on nothing",
            "-": "no answer at all",
        }[path]
        out.append(f"    {label:<18} {stat['hits']}/{stat['n']} hit")
    out.append("")
    out.append("  hits, by the passage that answered")
    out.append(f"    {'a resolved name':<18} {summary['by_answer']['graph']}")
    out.append(f"    {'a Lucene score':<18} {summary['by_answer']['text']}")
    if summary["by_needs"]:
        out.append("  the prediction against the outcome")
        out.append(
            f"    {'needs':<8} {'n':>3} {'hit':>5} {'anchored':>9} "
            f"{'ans:graph':>10} {'ans:text':>9}"
        )
        for needs, stat in summary["by_needs"].items():
            out.append(
                f"    {needs:<8} {stat['n']:>3} {stat['hits']:>5} "
                f"{stat['anchored']:>9} {stat['answered_by_graph']:>10} "
                f"{stat['answered_by_text']:>9}"
            )
        out.append("")

    out.append(f"  questions            {summary['total']}")
    out.append(f"  anchored             {summary['anchored']}/{summary['total']}")
    out.append(f"  recall (all)         {summary['recall_overall']:.0%}")
    out.append(f"  recall (anchored)    {summary['recall_anchored']:.0%}")
    out.append(f"  MRR                  {summary['mrr']:.2f}")
    out.append("")
    out.append(f"  no anchor            {summary['no_anchor'] or '-'}")
    out.append(f"  anchored but missed  {summary['anchored_but_missed'] or '-'}")

    if verbose:
        out.append("")
        out.append("  -- misses in detail ------------------------------------")
        for row in rows:
            if row["hit"]:
                continue
            out.append(f"  {row['id']}  {row['question']}")
            out.append(f"       gold      {row['gold']}")
            out.append(f"       retrieved {row['retrieved'] or '(nothing)'}")
            out.append(f"       anchors   {row['anchors'] or '(none)'}")
            if row["miss_reason"]:
                out.append(f"       reason    {row['miss_reason']}")
            if row["ambiguous"]:
                out.append(f"       ambiguous {row['ambiguous']}")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument(
        "--limit", type=int, default=DEFAULT_LIMIT,
        help="passages per question; defaults to what the retriever ships with",
    )
    parser.add_argument("--verbose", action="store_true", help="print every miss in full")
    args = parser.parse_args()

    questions = yaml.safe_load(args.questions.read_text())["questions"]
    retriever = CanonRetriever(limit=args.limit)
    rows = [score(q, retriever.retrieve(q["question"])) for q in questions]
    summary = summarize(rows)

    print(f"canon retrieval @ limit={args.limit}, {len(questions)} questions")
    print()
    print(render(rows, summary, verbose=args.verbose))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
