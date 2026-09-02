"""Score where a generated scene would be filed, against hand-authored cases.

    uv run python -m backend.scripts.eval_anchor
    uv run python -m backend.scripts.eval_anchor --verbose
    uv run python -m backend.scripts.eval_anchor --save evals/baselines/x.json
    uv run python -m backend.scripts.eval_anchor --compare before.json after.json
    uv run python -m backend.scripts.eval_anchor --model gpt-4o-mini   # SPENDS

COSTS NOTHING BY DEFAULT, like `eval_retrieval` and unlike `eval_answers`:
retrieval is deterministic and `suggest_anchor` is a pure function over it.

TEN CASES IS TEN CASES. A model run over them moves on resampling, and this
harness reports no interval -- the answer eval's warning applies here in
spirit: a two-case difference is not a result. What it can settle is a
difference of the size actually seen, 4 of 10 against 8 of 10, where the four
that flipped are exactly the four the deterministic rule is documented to get
wrong.

`--model` SCORES THE OTHER RULE, and spends. Every path that drafts something
now refines the deterministic guess with `place_it`, which asks a model which
beat the material comes after over the closed list of passages it was written
against. Wiring that in on the strength of its docstring would have been faith;
this is how the two are compared on the same ten cases.

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


def _with_model(cases, retrievers, model: str) -> list[dict]:
    """The same cases, scored through `place_it`.

    SEQUENTIAL AND UNCONCURRENT, deliberately: ten cheap calls, and a harness
    that raced them would be harder to read than the thing it measures.
    """
    import asyncio

    from openai import AsyncOpenAI

    from backend.agents.canon_context import place_it, sources, suggest_anchor
    from backend.canon.retrieval import CanonRetriever  # noqa: F401
    from backend.core.config import settings

    client = AsyncOpenAI(api_key=settings.openai_api_key)

    async def one(case):
        retrieval = retrievers[case.get("book", "cos")].retrieve(case["subject"])
        chosen = await place_it(
            client, subject=case["subject"], body="",
            shown=sources(retrieval), model=model,
        )
        # FALLS BACK EXACTLY AS THE APP DOES. `place_it` returns "" when it
        # cannot answer and every caller keeps the deterministic guess, so
        # scoring the empty string would measure a path nothing takes.
        deterministic, chapters = suggest_anchor(retrieval)
        return score(case, chosen or deterministic, chapters)

    async def run():
        return [await one(case) for case in cases]

    return asyncio.run(run())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--verbose", action="store_true",
                        help="print the cases that passed as well")
    parser.add_argument("--save", type=Path, metavar="PATH")
    parser.add_argument("--label", default="")
    parser.add_argument("--compare", nargs=2, type=Path,
                        metavar=("BEFORE", "AFTER"))
    parser.add_argument(
        "--model", default="",
        help="also score `place_it` with this model. SPENDS: one cheap call "
             "per case.",
    )
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
    placed_rows = _with_model(cases, retrievers, args.model) if args.model else []
    print(f"anchor suggestions over {len(cases)} hand-authored cases")
    print()
    print(render(rows, found, verbose=args.verbose))
    if placed_rows:
        placed = summarize(placed_rows)
        print()
        print(f"  with `place_it` ({args.model}), on the same cases:")
        print(render(placed_rows, placed, verbose=args.verbose))
        print()
        moved = [
            (a["id"], a["hit"], b["hit"])
            for a, b in zip(rows, placed_rows) if a["hit"] != b["hit"]
        ]
        print(f"  {found['hits']}/{found['cases']} -> "
              f"{placed['hits']}/{placed['cases']}")
        for cid, was, now in moved:
            print(f"    {cid:5} {'hit' if was else 'miss'} -> "
                  f"{'hit' if now else 'miss'}")
    if args.save:
        # WHEN A MODEL RAN, THAT IS THE RUN WORTH RECORDING -- it is the rule
        # the app actually files by. The deterministic number is still printed
        # above as the floor it has to beat.
        keep = placed_rows or rows
        _save(args.save, args.label, keep, summarize(keep))
        print(f"\n  saved to {args.save}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
