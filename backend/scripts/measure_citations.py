"""Does a `from_canon` claim say what the passage it cites says?

    uv run python -m backend.scripts.measure_citations --dry-run
    uv run python -m backend.scripts.measure_citations --apply

THE LAST UNCHECKED LINK. `homebrew.py` has said so in its own docstring since
it was written: "Nothing here confirms that a `from_canon` claim is supported
by the passage it cites." Two links either side of it are now checked --
`cited_sections` refuses a citation pointing at a slot that was never shown,
and `split_by_origin` re-files a claim whose cite lands on the DM's own prose
rather than on the book. Both of those were written after a real failure. This
measures the one still standing on trust.

WHAT A CITATION IS FOR. The card says it in as many words: "Each cites a
passage. A pointer for you to check, not a proof." That framing is honest only
if the pointer usually points somewhere useful. A DM at a table does not chase
every `[6]`; they read the green list and believe it, and the citation's whole
job is to make that belief checkable rather than blind. So the number that
matters is how often the pointer survives being followed.

TWO FAILURES, NOT ONE, AND THEY ARE NOT WORTH THE SAME. A claim the book never
makes anywhere is an invention wearing a citation. A claim the book DOES make,
attached to the wrong passage, is a filing error -- the DM who follows it finds
nothing, but the fact is real and some other shown passage carries it. Reported
apart, because the first would mean the split is leaking and the second would
mean the numbering is.

THE JUDGE IS SHOWN THE PASSAGE AND THE CLAIM AND NOTHING ELSE. Not the body it
came from, not the subject, not the other passages -- those are what let a
judge reconstruct the writer's reasoning and agree with it. It is asked to
refute, and told to answer "no" when unsure, because a support measurement that
rounds uncertainty up is measuring its own agreeableness.

WHAT THE FIRST RUN SAID, so a later one has something to move against: 47
claims, 96% supported by the passage they cite (95% CI 86-99%), nothing citing
a slot that was never shown. All three gates passed, so no gate was built --
this link was the one still standing on trust and it turned out to be holding.

READ THE TWO FAILURES BEFORE TRUSTING THE 96%. One is a COMPOUND claim -- "the
Lords' Alliance controls Revel's End, and the prison has 75 guards on
eight-hour shifts" -- where the cite covers the first half and the second half
lives elsewhere. One citation was asked to carry two facts.

The other WAS an artifact of this script and is fixed here. `Castle Ravenloft
-CONTAINS-> Tower Roof` is a claim the model took from the graph EDGES in its
context, and the judge saw passages only -- so it could not be supported by
construction, and "unsupported anywhere" read high by however many edge-derived
claims a run turned up. The relationships a generation was shown are now part
of what the judge reads for that question, which is what the generation
actually had in front of it. The FIRST judgement is unchanged and still asks
only about the cited passage: a claim citing `[6]` is a claim about `[6]`, and
letting an edge elsewhere rescue it would measure something else.

COSTS MONEY, so `--dry-run` is the default and prints the plan, and the cap is
enforced in the loop rather than hoped for.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import re
from collections import Counter
from pathlib import Path

from openai import AsyncOpenAI

from backend.agents import canon_context, generator
from backend.campaign.homebrew import split_by_origin
from backend.canon.retrieval import CanonRetriever
from backend.core.config import settings
from backend.core.pricing import Usage, estimate

DEFAULT_REPORT = Path("evals/baselines/citation-measurement.json")

#: Twenty subjects rather than the ten `measure_manifest` uses, because this
#: counts CLAIMS and not generations -- three or so per card, so ten subjects
#: would resolve nothing. Half are reused verbatim from that file so the two
#: measurements can be read against each other; the rest are the same kind of
#: ask, and none was chosen for how well it is expected to go.
SUBJECTS = [
    ("kftgv", "scene", "a sea battle on the voyage to Revel's End"),
    ("kftgv", "scene", "a storm that scatters the crew during the trek to the prison"),
    ("kftgv", "quest", "a fence in Toadhop who wants the mandolin for himself"),
    ("kftgv", "quest", "a rival crew racing the party for the Murkmire Stone"),
    ("kftgv", "scene", "a bribe attempt at the casino's cashier window"),
    ("kftgv", "npc", "a guard at Revel's End who can be turned"),
    ("kftgv", "scene", "the moment the vault alarm goes off"),
    ("kftgv", "quest", "recovering the diadem before Vidorant notices"),
    ("kftgv", "npc", "a broker who fences what the Golden Vault will not touch"),
    ("kftgv", "scene", "an interrogation aboard the Concordant Express"),
    ("cos", "scene", "an ambush on the old road into Barovia"),
    ("cos", "quest", "a missing child in the village of Barovia"),
    ("cos", "scene", "a funeral at the church that the party interrupts"),
    ("cos", "quest", "a Vistani who offers to read the party's fortune for a price"),
    ("cos", "scene", "wolves circling the camp at dusk"),
    ("cos", "npc", "a Vallaki shopkeeper who knows more than they say"),
    ("cos", "scene", "a night in the Blood of the Vine Tavern"),
    ("cos", "quest", "returning Ireena to her brother"),
    ("cos", "npc", "a burgomaster's servant with a secret"),
    ("cos", "scene", "the party's first sight of Castle Ravenloft"),
]

#: Written down BEFORE the run. A threshold chosen after seeing the number is
#: not a threshold, and this file exists because an unmeasured assumption in
#: exactly this area shipped to a DM's table.
GATES = {
    "supported_rate": (
        0.90,
        "at least 90% of canon claims supported by the passage they cite -- "
        "below this the card's promise that a citation is 'a pointer for you "
        "to check' is one a DM would find broken by checking",
    ),
    "unsupported_anywhere_rate": (
        0.05,
        "at most 5% of claims that NO shown canon passage supports -- these "
        "are inventions wearing a citation, which is the failure the whole "
        "three-way split exists to prevent",
    ),
    "unresolvable_cite_rate": (
        0.02,
        "at most 2% of claims citing a slot that was never shown; "
        "`cited_sections` already refuses these at the write boundary, so a "
        "high rate here means DMs are meeting refusals rather than cards",
    ),
}

#: A hard stop, not a suggestion. Twenty generations plus a judge call per
#: claim, plus a second judge call per claim that fails the first.
DEFAULT_CAP_USD = 2.00

_CITE = re.compile(r"\[(\d+)\]")

_JUDGE = """A passage from a published book, and a claim someone made about it.

PASSAGE
{passage}

CLAIM
{claim}

Does the passage state this claim, or directly imply it? Try to REFUTE: if the
claim adds a name, a number, a motive or a detail the passage does not carry,
that is a no. If you are unsure, answer no.

Reply with JSON only: {{"supported": true or false, "why": "one short sentence"}}
"""


def wilson(hits: int, n: int) -> tuple[float, float]:
    """A 95% interval, so a rate arrives with its own uncertainty attached."""
    if n == 0:
        return (0.0, 0.0)
    z, p = 1.96, hits / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, centre - half), min(1.0, centre + half))


async def judge(client, model: str, passage: str, claim: str) -> tuple[bool, str, Usage]:
    """One claim against one passage. Returns `(supported, why, usage)`.

    A response that will not parse counts as UNSUPPORTED, not as a skip. The
    measurement is of how often a citation survives checking, and a check that
    could not be completed did not survive.
    """
    response = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": _JUDGE.format(passage=passage, claim=claim)}],
        temperature=0,
        max_tokens=200,
    )
    usage = Usage.from_response(response)
    text = (response.choices[0].message.content or "").strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```")
    try:
        parsed = json.loads(text)
        return bool(parsed.get("supported")), str(parsed.get("why", "")), usage
    except (json.JSONDecodeError, AttributeError):
        return False, f"judge response would not parse: {text[:80]}", usage


def by_slot(sources: list[dict]) -> dict[str, dict]:
    """`{"6": source}`, keyed the way a claim spells its cite."""
    slots: dict[str, dict] = {}
    for index, source in enumerate(sources, start=1):
        slots[str(index)] = source
        found = _CITE.search(str(source.get("citation") or ""))
        if found:
            slots[found.group(1)] = source
    return slots


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Actually spend money.")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--cap-usd", type=float, default=DEFAULT_CAP_USD)
    parser.add_argument("--model", default=settings.openai_model)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    print(f"{len(SUBJECTS)} subjects, ~3 canon claims each, judged one call per claim")
    print(f"model {args.model}, cap ${args.cap_usd:.2f}\n")
    for name, (threshold, why) in GATES.items():
        print(f"  gate {name} @ {threshold}: {why}")
    if not args.apply:
        print("\nNothing spent. Re-run with --apply to measure.")
        return

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    retrievers = {book: CanonRetriever(book=book) for book, _, _ in SUBJECTS}
    spent, rows = 0.0, []

    for book, kind, subject in SUBJECTS:
        if spent >= args.cap_usd:
            print(f"\ncap reached at ${spent:.2f}; stopping with {len(rows)} claims")
            break
        retrieval = retrievers[book].retrieve(subject)
        card = await generator.generate(
            client,
            kind=kind,
            subject=subject,
            retrieval=retrieval,
            depth=canon_context.Depth(),
            model=args.model,
        )
        spent += float(card.cost.get("usd") or 0.0)
        if card.error:
            print(f"  ! {subject[:44]}: {card.error}")
            continue

        shown = canon_context.apply(retrieval, canon_context.Depth())
        text_of = {p.section_id: p.text for p in shown.passages}
        slots = by_slot(list(card.sources))
        # Only what the split still calls canon. A claim it re-filed is not a
        # claim about the book, and judging it against a canon passage would
        # count a defect this project already fixed.
        canon_claims, _yours = split_by_origin(card.from_canon, card.sources)

        for claim in canon_claims:
            found = _CITE.search(str(claim.get("cite", "")))
            source = slots.get(found.group(1)) if found else None
            row = {
                "book": book,
                "subject": subject,
                "claim": str(claim.get("claim", "")),
                "cite": str(claim.get("cite", "")),
                "section": (source or {}).get("source", ""),
                "resolvable": source is not None,
            }
            if source is None:
                row.update(supported=False, anywhere=False, why="cite resolves to nothing")
                rows.append(row)
                continue

            passage = text_of.get(source.get("source", ""), "")
            supported, why, usage = await judge(client, args.model, passage, row["claim"])
            spent += estimate(args.model, usage).usd or 0.0
            row.update(supported=supported, why=why)

            # Only for a claim that failed: is the BOOK wrong about it, or just
            # the pointer? Two different defects and only one of them is the
            # split leaking.
            if supported:
                row["anywhere"] = True
            else:
                # THE EDGES TOO, because they were in the model's context and a
                # claim drawn from one is not an invention. What this asks is
                # "did the graph put this in front of it anywhere", and the
                # graph speaks in both prose and relationships.
                everything = "\n\n".join(
                    [p.text for p in shown.passages if p.origin == "canon"]
                    + [canon_context.render(shown, max_edges=canon_context.Depth().max_edges)]
                )
                anywhere, _why, usage2 = await judge(
                    client, args.model, everything, row["claim"]
                )
                spent += estimate(args.model, usage2).usd or 0.0
                row["anywhere"] = anywhere
            rows.append(row)
        print(f"  {book} {subject[:40]:42s} {len(canon_claims)} claims  ${spent:.2f}")

    total = len(rows)
    supported = sum(1 for r in rows if r["supported"])
    anywhere = sum(1 for r in rows if r.get("anywhere"))
    unresolvable = sum(1 for r in rows if not r["resolvable"])
    misfiled = sum(1 for r in rows if not r["supported"] and r.get("anywhere"))

    def line(label: str, hits: int, gate: str, higher_is_better: bool = True) -> str:
        rate = hits / total if total else 0.0
        low, high = wilson(hits, total)
        threshold = GATES[gate][0]
        passed = rate >= threshold if higher_is_better else rate <= threshold
        return (
            f"  {label:26s} {hits:3d}/{total:<3d} = {rate:.0%}  "
            f"95% CI {low:.0%}-{high:.0%}   {'PASS' if passed else 'FAIL'} "
            f"(gate {threshold:.0%})"
        )

    print(f"\n{total} canon claims judged, ${spent:.2f} spent\n")
    print(line("supported by its cite", supported, "supported_rate"))
    print(line("unsupported anywhere", total - anywhere, "unsupported_anywhere_rate", False))
    print(line("cite resolves nowhere", unresolvable, "unresolvable_cite_rate", False))
    print(f"  {'right fact, wrong pointer':26s} {misfiled:3d}/{total:<3d}")

    # EVERY FAILURE IS PRINTED, not summarised into a rate. A number decides
    # whether to act; the claims decide what to do, and this project has twice
    # found the useful thing by reading the cases rather than the total.
    failures = [r for r in rows if not r["supported"]]
    if failures:
        print(f"\n{len(failures)} to read by hand:")
        for r in failures:
            mark = "wrong pointer" if r.get("anywhere") else "UNSUPPORTED ANYWHERE"
            print(f"\n  [{mark}] {r['book']} · {r['cite']} → {r['section'] or '(nothing)'}")
            print(f"    claim: {r['claim'][:150]}")
            print(f"    judge: {r['why'][:150]}")

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(
            {
                "model": args.model,
                "claims": total,
                "supported": supported,
                "unsupported_anywhere": total - anywhere,
                "unresolvable": unresolvable,
                "misfiled": misfiled,
                "spent_usd": round(spent, 4),
                "gates": {k: v[0] for k, v in GATES.items()},
                "by_book": dict(Counter(r["book"] for r in rows)),
                "rows": rows,
            },
            indent=2,
        )
    )
    print(f"\nwritten to {args.report}")


if __name__ == "__main__":
    asyncio.run(main())
