"""Score canon retrieval against the hand-authored question set.

    uv run python -m backend.scripts.eval_retrieval
    uv run python -m backend.scripts.eval_retrieval --limit 3 --verbose
    uv run python -m backend.scripts.eval_retrieval --save evals/baselines/x.json
    uv run python -m backend.scripts.eval_retrieval --compare before.json after.json

Costs nothing: retrieval is deterministic and no model runs. Re-run it after
every chapter the loop writes -- the question set is a regression suite, not a
one-off measurement.

WHAT IS SCORED, AND WHAT DELIBERATELY IS NOT. Gold is the SECTION a DM would
have to read. Whether retrieval put that section in front of them is a fact:
mechanically checkable, no judge, no fuzzy string matching, no model marking its
own homework. Whether an answer written from that section would be any good is a
different question and is not asked here.

`--save` RECORDS A RUN, and the reason is the one `evals/baselines/README.md`
gives for the answer eval: without a recorded run there is nothing to compare
against except somebody's memory of a number. It happened here. A day of graph
repair -- 21 entities created, mentions repointed, dropped and marked -- was
checked against a remembered "85%/90%", and settling whether anything had moved
meant grepping commit messages for the last run that printed its figures.

WHAT IT DOES NOT NEED IS AN INTERVAL. The answer eval runs a model, so its
number moves between runs of identical code and a comparison has to say whether
zero sits inside the resolvable difference. Retrieval is deterministic: the same
graph and the same questions give the same rows every time, so a difference of
one question IS a difference, and `--compare` names the questions that changed
rather than reporting a range.

THE SPLIT THAT MATTERS IS `no-anchor` VS `missed`. A question naming nothing the
graph knows failed BEFORE retrieval ranked anything, and no amount of ranking
work would fix it -- it needs an alias, or an entity that was never extracted.
A question that anchored fine and still missed is a ranking or coverage problem.
One recall number blurs the two and points every reader at the wrong repair.
"""

from __future__ import annotations

import argparse
import json
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


def book_of(question: dict) -> str:
    """Which book holds this question's answer, read off its gold section.

    `cos:the-village-of-barovia#4` is a Curse of Strahd question. Derived
    rather than declared, so a question cannot disagree with itself about
    which book to search.
    """
    sections = question["sections"]
    first = sections[0] if isinstance(sections, list) else sections
    return str(first).split(":", 1)[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument(
        "--limit", type=int, default=DEFAULT_LIMIT,
        help="passages per question; defaults to what the retriever ships with",
    )
    parser.add_argument("--verbose", action="store_true", help="print every miss in full")
    parser.add_argument(
        "--book", help="run only the questions whose answers are in this book"
    )
    parser.add_argument(
        "--save", type=Path, metavar="PATH",
        help="record this run as JSON, for a later --compare",
    )
    parser.add_argument("--label", default="", help="what this run is testing")
    parser.add_argument(
        "--compare", nargs=2, type=Path, metavar=("BEFORE", "AFTER"),
        help="report what moved between two saved runs. Spends nothing and "
             "reads no graph.",
    )
    args = parser.parse_args()

    if args.compare:
        return _compare(*args.compare)

    questions = yaml.safe_load(args.questions.read_text())["questions"]
    if args.book:
        questions = [q for q in questions if book_of(q) == args.book]
        if not questions:
            print(f"no questions with gold sections in {args.book!r}")
            return 2

    # ONE RETRIEVER PER BOOK, and the book comes from the QUESTION rather than
    # from a flag: a question's gold section id already says which book holds
    # the answer, so a suite spanning two books needs nothing written down and
    # cannot be run against the wrong one by forgetting an argument. This was
    # `CanonRetriever(limit=...)` -- hardcoded to Curse of Strahd -- which is
    # why every number this project reported described one book.
    retrievers: dict[str, CanonRetriever] = {}
    rows = []
    for question in questions:
        book = book_of(question)
        if book not in retrievers:
            retrievers[book] = CanonRetriever(limit=args.limit, book=book)
        rows.append(score(question, retrievers[book].retrieve(question["question"])))

    books = sorted({book_of(q) for q in questions})
    print(f"canon retrieval @ limit={args.limit}, {len(questions)} questions")
    print()
    print(render(rows, summarize(rows), verbose=args.verbose))

    # PER BOOK TOO, whenever there is more than one. The headline number over a
    # mixed suite is an average of two different books and comparable to
    # neither on its own -- and the whole reason for adding a second book's
    # questions was to stop reporting one book's number as the system's.
    if len(books) > 1:
        print()
        print("  by book")
        for book in books:
            subset = [r for r, q in zip(rows, questions) if book_of(q) == book]
            found = summarize(subset)
            print(
                f"    {book:8} {len(subset):3} questions   "
                f"recall {found['recall_overall']:.0%} all, "
                f"{found['recall_anchored']:.0%} anchored   "
                f"anchored {found['anchored']}/{len(subset)}   "
                f"MRR {found['mrr']:.2f}"
            )
    if args.save:
        _save(args.save, args.label, args.limit, questions, rows, books)
        print(f"\n  saved to {args.save}")
    return 0


def _outcome(row) -> str:
    """One question's result, as the three states the report distinguishes."""
    if not row.get("anchored"):
        return "no-anchor"
    return "hit" if row.get("hit") else "missed"


def _save(path: Path, label: str, limit: int, questions, rows, books) -> None:
    """The run, per question, plus the headline figures.

    NO PROSE FROM EITHER BOOK, which is why these can be committed while
    everything under `data/` cannot -- question ids and outcomes only, the same
    rule the answer baselines keep.
    """
    found = summarize(rows)
    payload = {
        "label": label,
        "limit": limit,
        "questions": len(questions),
        "recall_overall": found["recall_overall"],
        "recall_anchored": found["recall_anchored"],
        "anchored": found["anchored"],
        "mrr": found["mrr"],
        "by_book": {
            book: summarize([r for r, q in zip(rows, questions)
                             if book_of(q) == book])
            for book in books
        },
        "outcomes": {q["id"]: _outcome(r) for q, r in zip(questions, rows)},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n")


def _compare(before: Path, after: Path) -> int:
    """What moved, by question. Exact, because retrieval is deterministic."""
    a = json.loads(before.read_text())
    b = json.loads(after.read_text())
    for name, was, now in (
        ("recall (all)", a["recall_overall"], b["recall_overall"]),
        ("recall (anchored)", a["recall_anchored"], b["recall_anchored"]),
        ("MRR", a["mrr"], b["mrr"]),
    ):
        arrow = "->" if was != now else "=="
        print(f"  {name:20} {was:.2%} {arrow} {now:.2%}" if name != "MRR"
              else f"  {name:20} {was:.2f} {arrow} {now:.2f}")
    moved = {
        qid: (a["outcomes"].get(qid, "absent"), b["outcomes"].get(qid, "absent"))
        for qid in sorted(set(a["outcomes"]) | set(b["outcomes"]))
        if a["outcomes"].get(qid) != b["outcomes"].get(qid)
    }
    if not moved:
        print("\n  no question changed outcome. Retrieval is deterministic, "
              "so this is identical rather than indistinguishable.")
        return 0
    print(f"\n  {len(moved)} question(s) changed outcome:")
    for qid, (was, now) in moved.items():
        print(f"    {qid:6} {was} -> {now}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
