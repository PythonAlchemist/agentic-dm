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
    always = sum(1 for rs in scored if all(verdict(r) == "pass" for r in rs))
    ever = sum(1 for rs in scored if any(verdict(r) == "pass" for r in rs))
    out.append("")
    out.append(f"  passed every run     {always}/{len(scored)}")
    out.append(f"  passed at least one  {ever}/{len(scored)}   (the gap is flakiness)")
    out.append(f"  needing a reading    {len(by_id) - len(scored)}")
    return "\n".join(out)


async def _answer(question: str, model: str | None) -> tuple[str, dict | None]:
    """One grounded turn from a FRESH agent.

    Fresh per question, never a shared session: history would let question four
    be answered out of question three's context, and two identical runs would
    then differ for reasons nobody could see. The same reason `/lab/generate`
    builds its own agent.
    """
    from backend.agents.dm_agent import DMAgent

    agent = DMAgent(model=model)
    response = await agent.process_message(
        user_input=question, use_rag=False, use_canon=True
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


async def run(
    questions: list[dict], model: str | None, *, show: bool, repeat: int = 1
) -> list[dict]:
    rows: list[dict] = []
    spent = 0.0
    unpriced = 0
    for attempt in range(1, repeat + 1):
        for question in questions:
            answer, cost = await _answer(question["question"], model)
            usd = spend_of(cost)
            if usd is None:
                unpriced += 1
            else:
                spent += usd
            row = check(question, answer)
            row["answer"] = answer
            row["attempt"] = attempt
            rows.append(row)
            running = (
                f"${spent:.4f}" if not unpriced else f"${spent:.4f} + {unpriced} unpriced"
            )
            run_of = f" ({attempt}/{repeat})" if repeat > 1 else ""
            print(f"  {row['id']:<5} {verdict(row):<9}{run_of} {running} so far")
            # Printed whenever a human has to judge, and whenever something
            # failed. A failing answer nobody reads is a number with no defect
            # attached to it.
            if show or row["refusal_expected"] or verdict(row) == "FAIL":
                print(f"        {answer.strip()[:600]}")
                print()
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
        help="runs per question. 1 reports a coin toss as a fact",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print what would be asked and spend nothing",
    )
    args = parser.parse_args()

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
        run(questions, args.model, show=args.show, repeat=args.repeat)
    )
    print()
    print(render(rows, repeat=args.repeat))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
