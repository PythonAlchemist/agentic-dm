"""Score the ANSWER, not the retrieval.

    uv run python -m backend.scripts.eval_answers --dry-run
    uv run python -m backend.scripts.eval_answers
    uv run python -m backend.scripts.eval_answers --model gpt-4o-mini --only a06

THIS ONE COSTS MONEY. `eval_retrieval` is deterministic and free; every question
here is a model call. `--dry-run` renders exactly what would be sent and spends
nothing, and the real run prints the running total after every question so a
surprise is caught at question three rather than question forty.

WHY IT EXISTS. `eval_retrieval` scores whether the right SECTION came back and
says outright that it does not ask whether an answer written from that section
would be any good. At 83% section recall, that unasked question is the binding
one -- and the specific worry is measurable: asked "who is Strahd's
chamberlain", the agent receives zero derived relationships and forty-three
guessed ones, roughly a third of which are false, while the answer arrives only
through the text path.

NO MODEL GRADES ANOTHER MODEL. Every check is a case-insensitive substring test
against hand-authored strings, the same rule the retrieval set follows. The one
exception is `refuses`, which cannot be checked that way -- and it is therefore
never scored silently: every refusal question prints its full answer, so the
verdict is a human's and the harness only sorts the reading queue.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
from pathlib import Path

import yaml

DEFAULT_QUESTIONS = Path("evals/canon-answers.yaml")

#: Phrasings that suggest the model declined. A HEURISTIC, and the only fuzzy
#: match in either evaluation harness.
#:
#: It is deliberately not trusted. A `refuses` question always prints its answer
#: in full and its verdict is reported as `read it` rather than as a pass, so
#: this list decides what a human looks at and never what the score is. Written
#: down anyway, rather than left to a reader's eye, so that "did it decline?" is
#: asked the same way of every answer.
_REFUSAL_MARKERS = (
    "does not cover",
    "doesn't cover",
    "not covered",
    "did not return",
    "didn't return",
    "does not appear",
    "doesn't appear",
    "no information",
    "not in the canon",
    "canon does not",
    "canon doesn't",
    "nothing in the retrieved",
    "not mentioned",
)

#: A citation as `canon_context` asks the model to write one.
_CITATION = "["


def check(question: dict, answer: str) -> dict:
    """What the hand-authored expectations say about one answer.

    Pure: no model, no database, no I/O. The whole scoring rule is here so it
    can be tested against strings rather than against a live agent.
    """
    lowered = answer.lower()
    missing = [s for s in question.get("must", ()) if s.lower() not in lowered]
    tripped = [s for s in question.get("must_not", ()) if s.lower() in lowered]
    wants_citation = bool(question.get("cites"))
    cited = _CITATION in answer

    return {
        "id": question["id"],
        "missing": missing,
        "tripped": tripped,
        "uncited": wants_citation and not cited,
        # Reported, never scored. See `_REFUSAL_MARKERS`.
        "refusal_expected": bool(question.get("refuses")),
        "refusal_looks_present": any(m in lowered for m in _REFUSAL_MARKERS),
    }


def verdict(row: dict) -> str:
    """`pass`, `FAIL`, or `read it` for anything a human has to judge."""
    if row["refusal_expected"]:
        return "read it"
    if row["missing"] or row["tripped"] or row["uncited"]:
        return "FAIL"
    return "pass"


def why(row: dict) -> str:
    reasons = []
    if row["missing"]:
        reasons.append(f"missing {row['missing']}")
    if row["tripped"]:
        reasons.append(f"tripwire {row['tripped']}")
    if row["uncited"]:
        reasons.append("no citation")
    if row["refusal_expected"]:
        reasons.append(
            "declined (looks like it)"
            if row["refusal_looks_present"]
            else "DID NOT decline"
        )
    return "; ".join(reasons) or "-"


def compare(before: dict, after: dict) -> str:
    """Two saved runs, and whether the difference is bigger than the noise.

    THE POINT OF THE WHOLE FILE. A prompt change was made, two runs were read,
    a regression was reported, the change was reverted, and the baseline came
    back at the same number -- the suite had never had the power to see it.
    This says so before a reader draws the same wrong conclusion.

    A two-proportion interval rather than a p-value: the question is not "is
    there any effect" but "how big could it be", and an interval that spans
    zero answers both.
    """
    a_pass, a_n = before["passes"], before["samples"]
    b_pass, b_n = after["passes"], after["samples"]
    a_rate, b_rate = a_pass / max(1, a_n), b_pass / max(1, b_n)
    delta = b_rate - a_rate
    # Standard error of a difference of proportions, then a 95% band.
    spread = 1.96 * math.sqrt(
        a_rate * (1 - a_rate) / max(1, a_n) + b_rate * (1 - b_rate) / max(1, b_n)
    )
    low, high = delta - spread, delta + spread

    lines = [
        f"  before   {a_pass}/{a_n} = {a_rate:.0%}   {before.get('label', '')}",
        f"  after    {b_pass}/{b_n} = {b_rate:.0%}   {after.get('label', '')}",
        "",
        f"  change   {delta:+.0%}   95% CI {low:+.0%} to {high:+.0%}",
    ]
    if low <= 0 <= high:
        lines.append("")
        lines.append("  ZERO IS INSIDE THE INTERVAL. This run does not show a change.")
        lines.append("  It does not show the absence of one either -- a real effect")
        lines.append(f"  smaller than {max(abs(low), abs(high)):.0%} would look exactly like this.")
    else:
        lines.append("")
        lines.append(
            f"  Zero is outside the interval: a {'gain' if delta > 0 else 'loss'} "
            "this run can actually support."
        )

    # Per question, so a moved number can be traced to what moved it.
    lines += ["", f"  {'id':<5} before  after   moved"]
    for qid in sorted(set(before["by_id"]) | set(after["by_id"])):
        was = before["by_id"].get(qid)
        now = after["by_id"].get(qid)
        if was is None or now is None:
            lines.append(f"  {qid:<5} {'--' if was is None else was:<7} "
                         f"{'--' if now is None else now:<7} only in one run")
            continue
        mark = "" if was == now else "  <-"
        lines.append(f"  {qid:<5} {was:<7} {now:<7}{mark}")
    return "\n".join(lines)


def summarise(rows: list[dict], label: str) -> dict:
    """A run, reduced to what `compare` needs. Small enough to commit."""
    by_id: dict[str, list[dict]] = {}
    for row in rows:
        by_id.setdefault(row["id"], []).append(row)
    scored = {k: v for k, v in by_id.items() if not v[0]["refusal_expected"]}
    samples = [r for rs in scored.values() for r in rs]
    return {
        "label": label,
        "samples": len(samples),
        "passes": sum(1 for r in samples if verdict(r) == "pass"),
        "by_id": {
            qid: f"{sum(1 for r in rs if verdict(r) == 'pass')}/{len(rs)}"
            for qid, rs in scored.items()
        },
    }


def wilson(passes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """A 95% interval for a pass rate. Wilson, not passes/total +- 1.96*sqrt(...).

    The normal approximation is wrong exactly where this suite lives -- small
    n, rates near 0 and 1 -- where it produces intervals running below 0 or
    above 1 and is far too narrow at the ends. Wilson stays inside [0, 1] and
    is honest at 45 samples, which is what a repeat-5 run of nine scored
    questions actually has.
    """
    if total == 0:
        return (0.0, 1.0)
    rate = passes / total
    denominator = 1 + z * z / total
    centre = (rate + z * z / (2 * total)) / denominator
    spread = (
        z
        * math.sqrt(rate * (1 - rate) / total + z * z / (4 * total * total))
        / denominator
    )
    return (max(0.0, centre - spread), min(1.0, centre + spread))


def resolvable(total: int, rate: float = 0.8) -> float:
    """Roughly the smallest change in pass rate this many samples can see.

    The half-width of the interval on the DIFFERENCE between two runs, which is
    about sqrt(2) times one run's half-width. Printed because the number a
    reader needs is not "how wide is my error bar" but "was I entitled to
    believe that prompt change did anything" -- and at 45 samples the answer is
    usually no.

    Stated for a rate near 0.8, where this suite sits. Near 0.5 it is wider.
    """
    if total == 0:
        return 1.0
    low, high = wilson(round(rate * total), total)
    return math.sqrt(2) * (high - low) / 2


def render(rows: list[dict], *, repeat: int = 1) -> str:
    """A pass RATE per question, not a verdict.

    ONE RUN OF THIS SUITE IS NOT A MEASUREMENT, and the suite found that out
    about itself on its first two runs. Asked "who is Strahd's chamberlain"
    twice, the model produced the same correct answer and cited it once; asked
    for a beholder's stat block twice, it declined both times and recited
    challenge rating and Antimagic Cone from the Monster Manual on one of them.
    Both failures are real and neither is reliable, so a binary verdict from a
    single call reports a coin toss as a fact.
    """
    by_id: dict[str, list[dict]] = {}
    for row in rows:
        by_id.setdefault(row["id"], []).append(row)

    out = [f"  {'id':<5} {'passed':<9} why (worst run)", f"  {'-'*5} {'-'*9} {'-'*46}"]
    for qid, runs in by_id.items():
        verdicts = [verdict(r) for r in runs]
        if runs[0]["refusal_expected"]:
            declined = sum(1 for r in runs if r["refusal_looks_present"])
            out.append(f"  {qid:<5} {'read it':<9} declined {declined}/{len(runs)}")
            continue
        passed = sum(1 for v in verdicts if v == "pass")
        worst = next((r for r, v in zip(runs, verdicts) if v != "pass"), runs[0])
        flag = "" if passed in (0, len(runs)) else "   <- INCONSISTENT"
        out.append(f"  {qid:<5} {passed}/{len(runs):<7} {why(worst)}{flag}")

    scored = [rs for rs in by_id.values() if not rs[0]["refusal_expected"]]
    samples = [r for rs in scored for r in rs]
    passes = sum(1 for r in samples if verdict(r) == "pass")
    low, high = wilson(passes, len(samples))
    margin = resolvable(len(samples))

    out.append("")
    # THE HEADLINE IS A RATE OVER SAMPLES, not a count of questions that passed
    # every run. That count was a MINIMUM: it can only fall as repeats are
    # added, and one flaky question sets it for the whole suite -- so it read
    # 6/9 and 5/9 on runs of identical code and could not have told anyone
    # apart. A rate over every (question, repeat) sample is what carries an
    # interval, and the interval is what makes two runs comparable.
    out.append(
        f"  pass rate            {passes}/{len(samples)} = {passes / max(1, len(samples)):.0%}"
        f"   95% CI {low:.0%}-{high:.0%}"
    )
    out.append(
        f"  can resolve          a change of about {margin:.0%} or more"
        f"   ({len(samples)} samples)"
    )
    if margin > 0.10:
        # Said out loud, because the failure this suite had was somebody --
        # me -- reading two runs and reporting a regression it had no power to
        # see.
        out.append(
            "  A SMALLER DIFFERENCE THAN THAT IS NOISE. Raise --repeat, or add"
        )
        out.append("  questions, before believing a change moved this number.")
    always = sum(1 for rs in scored if all(verdict(r) == "pass" for r in rs))
    out.append(f"  passed every run     {always}/{len(scored)}   (a minimum, not a score)")
    out.append(f"  needing a reading    {len(by_id) - len(scored)}")

    # PER BOOK whenever the suite spans more than one, for the reason
    # `eval_retrieval` prints it: a headline over a mixed set is an average of
    # two books and comparable to neither on its own, and reporting one book's
    # figure as the system's is the defect this suite was just extended to fix.
    books = {r.get("book", "cos") for r in samples}
    if len(books) > 1:
        out.append("")
        out.append("  by book")
        for book in sorted(books):
            subset = [r for r in samples if r.get("book", "cos") == book]
            hits = sum(1 for r in subset if verdict(r) == "pass")
            lo, hi = wilson(hits, len(subset))
            out.append(
                f"    {book:8} {hits:3}/{len(subset):<3} = {hits / max(1, len(subset)):.0%}"
                f"   95% CI {lo:.0%}-{hi:.0%}"
            )
    return "\n".join(out)


#: The base draw. Repeat i uses ANSWER_SEED + i, so the SET of draws is fixed
#: across runs while the draws within a run stay different from each other.
#: Any constant works; this one is pinned so a result is reproducible by
#: someone who was not here when it was measured.
ANSWER_SEED = 20260821


async def _answer(
    question: str, model: str | None, attempt: int = 0,
    only_supported: bool = False, book: str = "cos",
) -> tuple[str, dict | None]:
    """One grounded turn from a FRESH agent.

    Fresh per question, never a shared session: history would let question four
    be answered out of question three's context, and two identical runs would
    then differ for reasons nobody could see. The same reason `/lab/generate`
    builds its own agent.
    """
    from backend.agents import canon_context
    from backend.agents.dm_agent import DMAgent
    from backend.canon.retrieval import CanonRetriever

    # temperature 0 and a seed that VARIES BY REPEAT. Pinning both would make
    # every repeat the same draw, which reads as perfect stability and measures
    # nothing; leaving both loose is what made a10 read 5/5, 4/5, 3/5, 1/5 and
    # 0/5 on identical questions in one afternoon. Repeat i is a different
    # DRAW, deliberately, and the same draw as repeat i of any other run -- so
    # two runs are compared sample against matching sample rather than as two
    # clouds.
    # THE BOOK IS THE QUESTION'S, not a default. This built its own retriever
    # and therefore always read Curse of Strahd, which is how ten Barovia
    # questions came to be reported as the system's answer quality while a
    # campaign was being run out of the heist anthology.
    #
    # No campaign, ever: a DM's own material must not reach a measurement of
    # what the BOOK supports. `test_the_eval_harnesses_are_campaign_less` pins
    # the absence of the word here.
    agent = DMAgent(
        model=model, temperature=0.0, seed=ANSWER_SEED + attempt,
        depth=canon_context.Depth(only_supported_edges=only_supported),
        canon=CanonRetriever(book=book),
    )
    response = await agent.process_message(
        user_input=question, use_canon=True
    )
    return response.message, response.cost


def spend_of(cost: dict | None) -> float | None:
    """Dollars for one call, or `None` when nobody can say.

    The key is `usd` and it is legitimately `None` -- `pricing.estimate`
    returns that for a model its table does not list, on the stated grounds
    that a fabricated number is wrong in a direction nobody can see. The first
    version of this function read a key called `total`, found nothing, and fell
    back to 0.0, so a run that had genuinely spent money reported `$0.0000`.
    That is precisely the failure the pricing module exists to prevent,
    reintroduced by the thing consuming it.
    """
    if not cost:
        return None
    return cost.get("usd")


#: Calls in flight. The suite needs a couple of hundred samples to resolve
#: anything (see `resolvable`), and 220 sequential calls took eighteen minutes
#: -- long enough that the honest answer to "just raise --repeat" was "nobody
#: will". Each sample builds its OWN agent over its own question, so there is
#: no shared state to race; the cap is the provider's rate limit, not
#: correctness. `extract.py` bounds its fan-out the same way and for the same
#: reason.
CONCURRENCY = 8


async def run(
    questions: list[dict], model: str | None, *, show: bool, repeat: int = 1,
    only_supported: bool = False,
) -> list[dict]:
    semaphore = asyncio.Semaphore(CONCURRENCY)
    done = 0
    total = len(questions) * repeat

    async def one(question: dict, attempt: int) -> dict:
        nonlocal done
        async with semaphore:
            answer, cost = await _answer(
                question["question"], model, attempt, only_supported,
                question.get("book", "cos"),
            )
        row = check(question, answer)
        row["answer"] = answer
        row["attempt"] = attempt
        row["book"] = question.get("book", "cos")
        row["usd"] = spend_of(cost)
        done += 1
        print(f"  [{done}/{total}] {row['id']:<5} {verdict(row)}")
        return row

    # Gathered, so results come back in a FIXED order however they finished.
    # A summary whose rows depended on which call the network returned first
    # would differ between two runs of identical code, which is the whole
    # defect this file is being repaired for.
    rows = list(
        await asyncio.gather(
            *(one(q, a) for a in range(1, repeat + 1) for q in questions)
        )
    )

    spent = sum(r["usd"] for r in rows if r["usd"] is not None)
    unpriced = sum(1 for r in rows if r["usd"] is None)
    for row in rows:
        if show or row["refusal_expected"] or verdict(row) == "FAIL":
            print(f"\n  {row['id']} ({row['attempt']}) {verdict(row)}")
            print(f"        {row['answer'].strip()[:600]}")
    print(f"\n  total spent          ${spent:.4f}")
    if unpriced:
        # Never folded into the total as zero. A run that cannot price itself
        # has to say so, or "$0.0000" reads as "this was free".
        print(f"  calls with no rate   {unpriced} of {len(questions)} — total is a FLOOR")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--model", default=None, help="defaults to the configured one")
    parser.add_argument("--only", nargs="*", help="question ids to run")
    parser.add_argument("--show", action="store_true", help="print every answer")
    parser.add_argument(
        "--repeat", type=int, default=3,
        help="runs per question. 1 reports a coin toss as a fact; "
             "45 samples resolve about 16 points, 200 about 8",
    )
    parser.add_argument(
        "--save", type=Path, help="write this run's summary, for --compare"
    )
    parser.add_argument("--label", default="", help="what this run is testing")
    parser.add_argument(
        "--only-supported-edges", action="store_true",
        help="withhold a guessed edge whose cited sentence does not support it",
    )
    parser.add_argument(
        "--compare", nargs=2, type=Path, metavar=("BEFORE", "AFTER"),
        help="two saved runs: is the difference bigger than the noise? "
             "Spends nothing.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print what would be asked and spend nothing",
    )
    args = parser.parse_args()

    if args.compare:
        before, after = (json.loads(path.read_text()) for path in args.compare)
        print(compare(before, after))
        return 0

    questions = yaml.safe_load(args.questions.read_text())["questions"]
    if args.only:
        questions = [q for q in questions if q["id"] in set(args.only)]

    if args.dry_run:
        print(f"{len(questions)} questions, no model call, nothing spent\n")
        for q in questions:
            print(f"  {q['id']:<5} {q['question']}")
            for field in ("must", "must_not"):
                if q.get(field):
                    print(f"        {field:<9} {q[field]}")
            for flag in ("cites", "refuses"):
                if q.get(flag):
                    print(f"        {flag:<9} required")
        return 0

    rows = asyncio.run(
        run(questions, args.model, show=args.show, repeat=args.repeat,
            only_supported=args.only_supported_edges)
    )
    print()
    print(render(rows, repeat=args.repeat))
    if args.save:
        args.save.write_text(json.dumps(summarise(rows, args.label), indent=2))
        print(f"\n  saved to {args.save}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
