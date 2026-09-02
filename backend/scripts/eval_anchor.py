"""Score where a generated scene would be filed, against hand-authored cases.

    uv run python -m backend.scripts.eval_anchor
    uv run python -m backend.scripts.eval_anchor --verbose
    uv run python -m backend.scripts.eval_anchor --save evals/baselines/x.json
    uv run python -m backend.scripts.eval_anchor --compare before.json after.json

COSTS NOTHING, like `eval_retrieval` and unlike `eval_answers`: retrieval is
deterministic and `suggest_anchor` is a pure function over it. No model runs.

WHY THIS EXISTS. `evals/anchor-cases.yaml` was written carefully -- multi-accept
semantics, a `why` on every case -- and nothing read it. A measurement that
never runs is a design document, and this one describes the weakest link in the
store flow: `suggest_anchor` answers "which section does the subject name most",
which comes apart from "which beat is this" on any scene about GETTING
somewhere. A fight on the voyage to Revel's End scores the prison at seven
mentions and the voyage at two, so the suggestion lands after the party has
already arrived.

EVERY DEFENSIBLE ANSWER COUNTS, which is the seed's own rule and not a
softening. A beat can honestly sit in more than one place -- a scene of the
party arriving at a camp is defensible after the beat that sends them or after
the one where they get there -- and a measurement insisting on a single id
would score good suggestions as failures and teach whoever reads it to distrust
the number.

THE MISS IS PRINTED WITH ITS `why`. A bare "6/10" says nothing about which way
the suggestion was wrong, and the two ways matter differently: landing in the
right chapter and the wrong beat is a ranking problem, landing in another
adventure entirely is the anthology rule failing.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

DEFAULT_CASES = Path("evals/anchor-cases.yaml")


def score(case: dict, suggested: str, chapters: tuple[str, ...]) -> dict:
    """One case's outcome. Pure, so it can be tested against strings."""
    accept = list(case.get("accept") or ())
    hit = suggested in accept
    wanted_chapters = {a.split("#")[0] for a in accept}
    return {
        "id": case["id"],
        "subject": case.get("subject", ""),
        "why": case.get("why", ""),
        "accept": accept,
        "suggested": suggested,
        "hit": hit,
        # RIGHT CHAPTER, WRONG BEAT is a different failure from another
        # adventure entirely: one is ranking inside a chapter, the other is the
        # anthology rule not holding. A single pass rate hides which.
        "right_chapter": bool(suggested) and suggested.split("#")[0] in wanted_chapters,
        "chapters": list(chapters),
    }


def summarize(rows: list[dict]) -> dict:
    total = len(rows)
    hits = [r for r in rows if r["hit"]]
    near = [r for r in rows if not r["hit"] and r["right_chapter"]]
    return {
        "cases": total,
        "hits": len(hits),
        "rate": len(hits) / total if total else 0.0,
        # Counted apart, never folded into the rate: a near miss is still a
        # miss to a DM, who has to move the card.
        "right_chapter_wrong_beat": len(near),
        "elsewhere": total - len(hits) - len(near),
        "missed": [r["id"] for r in rows if not r["hit"]],
    }


def render(rows: list[dict], found: dict, verbose: bool = False) -> str:
    lines = [
        f"  {found['hits']}/{found['cases']} anchored where a DM would put it "
        f"({found['rate']:.0%})",
        f"  {found['right_chapter_wrong_beat']} in the right chapter, wrong beat",
        f"  {found['elsewhere']} somewhere else entirely",
    ]
    misses = [r for r in rows if not r["hit"]]
    if misses:
        lines.append("")
        for row in misses:
            where = "right chapter" if row["right_chapter"] else "ANOTHER CHAPTER"
            lines.append(f"    {row['id']}  {row['subject']!r}")
            lines.append(f"      wanted {row['accept']} -- {row['why']}")
            lines.append(f"      got    {row['suggested'] or '(nothing)'}  [{where}]")
    if verbose:
        lines.append("")
        for row in rows:
            if row["hit"]:
                lines.append(f"    {row['id']}  ok  {row['suggested']}")
    return "\n".join(lines)


def _save(path: Path, label: str, rows: list[dict], found: dict) -> None:
    """Case ids and outcomes only -- no prose, so this can be committed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "label": label,
        **{k: v for k, v in found.items() if k != "missed"},
        "outcomes": {
            r["id"]: ("hit" if r["hit"]
                      else "near" if r["right_chapter"] else "elsewhere")
            for r in rows
        },
    }, indent=1, sort_keys=True) + "\n")


def _compare(before: Path, after: Path) -> int:
    """What moved, by case. Exact: nothing here runs a model."""
    a = json.loads(before.read_text())
    b = json.loads(after.read_text())
    print(f"  {a['hits']}/{a['cases']} -> {b['hits']}/{b['cases']}")
    moved = {
        cid: (a["outcomes"].get(cid, "absent"), b["outcomes"].get(cid, "absent"))
        for cid in sorted(set(a["outcomes"]) | set(b["outcomes"]))
        if a["outcomes"].get(cid) != b["outcomes"].get(cid)
    }
    if not moved:
        print("  no case changed outcome. Deterministic, so this is identical "
              "rather than indistinguishable.")
        return 0
    for cid, (was, now) in moved.items():
        print(f"    {cid:5} {was} -> {now}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--verbose", action="store_true",
                        help="print the cases that passed as well")
    parser.add_argument("--save", type=Path, metavar="PATH")
    parser.add_argument("--label", default="")
    parser.add_argument("--compare", nargs=2, type=Path,
                        metavar=("BEFORE", "AFTER"))
    args = parser.parse_args()

    if args.compare:
        return _compare(*args.compare)

    from backend.agents.canon_context import suggest_anchor
    from backend.canon.retrieval import CanonRetriever

    cases = yaml.safe_load(args.cases.read_text())["cases"]
    # ONE RETRIEVER PER BOOK, and the book comes from the CASE -- the same rule
    # `eval_retrieval` follows, and for the same reason: a suite spanning two
    # books cannot be run against the wrong one by forgetting a flag.
    retrievers: dict[str, CanonRetriever] = {}
    rows = []
    for case in cases:
        book = case.get("book", "cos")
        if book not in retrievers:
            retrievers[book] = CanonRetriever(book=book)
        retrieval = retrievers[book].retrieve(case["subject"])
        suggested, chapters = suggest_anchor(retrieval)
        rows.append(score(case, suggested, chapters))

    found = summarize(rows)
    print(f"anchor suggestions over {len(cases)} hand-authored cases")
    print()
    print(render(rows, found, verbose=args.verbose))
    if args.save:
        _save(args.save, args.label, rows, found)
        print(f"\n  saved to {args.save}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
