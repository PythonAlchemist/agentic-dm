"""Extract, write and verify every chapter, in the book's own order.

    uv run python -m backend.scripts.build_book --dry-run
    uv run python -m backend.scripts.build_book --max-spend 2.50

One chapter at a time, never in parallel: the write path replaces a chapter's
canon in a single transaction, and two of those interleaving is the one way this
pipeline could half-write a chapter.

WHY A DRIVER RATHER THAN A SHELL LOOP. Three things have to happen between
chapters and a `for` loop in bash does none of them: the verifier's exit code
has to HALT the run rather than be swallowed, spend has to accumulate against a
cap, and what happened to each chapter has to be recorded where a human can read
it afterwards. The loop's own gates say exactly this -- G2 halts on a verifier
anomaly, G5 halts on spend -- and a gate that only exists in a document is not a
gate.

IT HALTS, IT DOES NOT SKIP. A chapter that fails verification stops the run with
its output intact. The alternative -- carry on and report at the end -- means a
systematic fault discovered after twenty-four chapters instead of after one,
which is the cost this project has already written into its gate list.

COST IS ESTIMATED FROM THE ARTIFACT, not guessed. Each run records
`run.total_calls`; the price per call comes from the one measurement this
project has (chapter 3: 270 calls for roughly $0.05). It is an estimate and
prints as one.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

CANDIDATES = Path("data/canon/candidates")
RUNS = Path("data/canon/runs")
LOG = Path("data/canon/build-book.jsonl")

#: Chapter 3's artifact records 270 calls for roughly $0.05. The only
#: measurement available, and used as such rather than dressed up.
USD_PER_CALL = 0.05 / 270

#: The vote settings the knowledge skill fixes. Repeated here as explicit
#: arguments rather than relied on as defaults, so a reader of this file can see
#: what the book is being built with.
SAMPLES, NODE_K, EDGE_K = "5", "1", "3"

#: In-flight extraction calls. The book is 841 units x 3 layers x 5 samples =
#: 12,615 calls; at the historical 6 that is 21 hours, at 40 about 3. The
#: extractor's SDK backoff is raised to match, because a call that exhausts its
#: retries drops its whole sample from the vote and fails the chapter.
CONCURRENCY = "40"


def chapters() -> list[tuple[str, str]]:
    """(title, slug) in the book's own order."""
    from backend.scripts.extract_canon import load_chapters

    return [(c.title, c.slug) for c in load_chapters("ddb")]


def run(cmd: list[str]) -> tuple[int, str]:
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode, (result.stdout or "") + (result.stderr or "")


def spend_of(slug: str) -> tuple[int, float]:
    """Calls and estimated dollars, from the run artifact the write left."""
    path = RUNS / f"{slug}.json"
    if not path.exists():
        return 0, 0.0
    calls = int(json.loads(path.read_text()).get("run", {}).get("total_calls", 0) or 0)
    return calls, calls * USD_PER_CALL


def note(record: dict) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as handle:
        handle.write(json.dumps(record) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", action="append", default=[], metavar="SLUG",
                        help="Build just these chapters. Repeatable.")
    parser.add_argument("--start-at", metavar="SLUG",
                        help="Resume from this chapter, skipping earlier ones.")
    # `--start-at` only expresses a contiguous tail. A chapter already built at
    # the same settings sits wherever the book puts it, and re-extracting it is
    # paying twice for an identical artifact.
    parser.add_argument("--skip", action="append", default=[], metavar="SLUG",
                        help="Leave these chapters alone. Repeatable.")
    parser.add_argument("--max-spend", type=float, default=2.50,
                        help="Halt before a chapter that would cross this. G5's trigger.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the plan and spend nothing.")
    args = parser.parse_args()

    plan = chapters()
    if args.only:
        plan = [c for c in plan if c[1] in args.only]
    if args.skip:
        plan = [c for c in plan if c[1] not in args.skip]
    if args.start_at:
        slugs = [s for _, s in plan]
        if args.start_at not in slugs:
            parser.error(f"--start-at {args.start_at!r} is not a chapter slug")
        plan = plan[slugs.index(args.start_at):]

    print(f"  {len(plan)} chapters, cap ${args.max_spend:.2f}\n")
    if args.dry_run:
        for title, slug in plan:
            print(f"    {slug:<34} {title}")
        return 0

    CANDIDATES.mkdir(parents=True, exist_ok=True)
    spent = 0.0
    started = time.time()

    for index, (title, slug) in enumerate(plan, start=1):
        if spent >= args.max_spend:
            print(f"\n  HALT: spend ${spent:.2f} reached the cap before {slug}.")
            print("  Gate G5. Raise --max-spend and use --start-at to continue.")
            return 2

        print(f"  [{index}/{len(plan)}] {slug}")
        artifact = CANDIDATES / f"{slug}.json"

        code, output = run([
            "uv", "run", "python", "-m", "backend.scripts.extract_canon", title,
            "--samples", SAMPLES, "--node-k", NODE_K, "--edge-k", EDGE_K,
            "--concurrency", CONCURRENCY, "-o", str(artifact),
        ])
        if code != 0:
            print(f"      EXTRACT FAILED\n{output[-1500:]}")
            note({"slug": slug, "stage": "extract", "ok": False, "output": output[-2000:]})
            return 1

        # `--replace` on every chapter, including ones already written. The
        # instruction was to build the whole book the same way, and a chapter
        # left over from an earlier pipeline is exactly what that forbids.
        code, output = run([
            "uv", "run", "python", "-m", "backend.scripts.write_canon", str(artifact),
            "--chapter", slug, "--replace",
        ])
        if code != 0:
            # A chapter with nothing in it is not a failure, and telling the two
            # apart matters for exactly the chapters gate G2 was worried about.
            # Appendix A is backgrounds and trinket tables: 69 candidates, all
            # correctly rejected by the gazetteer, nothing in-world left. The
            # write path refuses to write an empty chapter -- rightly, since an
            # empty chapter is not a written one -- and the driver must not read
            # that refusal as a fault in the pipeline.
            if "no node survived the filters" in output:
                calls, usd = spend_of(slug)
                spent += usd
                print(f"      EMPTY  nothing in-world; skipped  (cumulative ${spent:.2f})")
                note({"slug": slug, "stage": "write", "ok": True, "empty": True,
                      "usd": round(usd, 4), "cumulative_usd": round(spent, 4)})
                continue
            print(f"      WRITE FAILED\n{output[-1500:]}")
            note({"slug": slug, "stage": "write", "ok": False, "output": output[-2000:]})
            return 1

        verifier = Path.home() / ".claude/skills/canon-to-neo4j/verifier.sh"
        code, output = run([str(verifier), slug])
        calls, usd = spend_of(slug)
        spent += usd
        ok = code == 0
        note({
            "slug": slug, "stage": "verify", "ok": ok, "calls": calls,
            "usd": round(usd, 4), "cumulative_usd": round(spent, 4),
            "output": output[-2000:],
        })
        status = "PASS" if ok else "FAIL"
        print(f"      {status}  {calls} calls  ~${usd:.3f}  (cumulative ${spent:.2f})")
        if not ok:
            # Gate G2: halt on a verifier anomaly, do not retry, do not carry on.
            print(f"\n  HALT: verifier failed on {slug}. Gate G2.\n{output[-1200:]}")
            return 1

    minutes = (time.time() - started) / 60
    print(f"\n  {len(plan)} chapters built, ~${spent:.2f}, {minutes:.0f} min")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
