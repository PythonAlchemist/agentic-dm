"""Does a generation reliably declare its own contents? The gate on clusters.

    uv run python -m backend.scripts.measure_manifest --dry-run
    uv run python -m backend.scripts.measure_manifest --apply

WHY THIS EXISTS BEFORE ANYTHING IS BUILT ON IT. The cluster design asks ONE
call to produce coherent prose AND a valid typed graph fragment. If the model
is weak at the second half, the result is exactly the coherence a DM wanted
attached to edges nobody can trust -- and unlike the canon extraction path,
there is no multi-sample consensus here to absorb it. So the assumption is
measured first, cheaply, with the thresholds written down BEFORE the numbers
arrive and the fallback chosen in advance.

WHAT IT IS COMPARED AGAINST, because a number with nothing beside it decides
nothing:

  * `extract.py` records unique-edge Jaccard of 0.49 between two runs at
    temperature 0 with a pinned seed. That instability was a reason to reject
    generate-then-extract, so a declared manifest is owed the same test rather
    than being exempted from the one it won on.
  * The canon extractor's typed edges violated domain/range on 25 of 53 -- 47%
    -- on the Golden Vault Introduction, against roughly 30% documented
    elsewhere. A generator declaring its own edges ought to do better. That is
    a hypothesis, and this is what tests it.

TEMPERATURE IS MEASURED TWICE. 0.0 with a pinned seed is the apples-to-apples
floor against the extractor's own figure; 0.8 is what the lab actually ships,
and a stability number nobody will experience is not worth reporting alone.

COSTS MONEY, so `--dry-run` is the default and prints the plan, and the spend
cap is enforced in the loop rather than hoped for.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

from openai import AsyncOpenAI

from backend.agents import canon_context, generator
from backend.canon.constraints import CandidateEdge, CandidateNode, report_edges
from backend.canon.retrieval import CanonRetriever
from backend.core.config import settings

DEFAULT_REPORT = Path("evals/baselines/manifest-measurement.json")

#: Real questions a DM would ask, across both books and both cluster kinds,
#: including the sea battle this design was argued from. Deliberately not
#: chosen for how well they are expected to go.
SUBJECTS = [
    ("kftgv", "scene", "a sea battle on the voyage to Revel's End"),
    ("kftgv", "scene", "a storm that scatters the crew during the trek to the prison"),
    ("kftgv", "quest", "a fence in Toadhop who wants the mandolin for himself"),
    ("kftgv", "quest", "a rival crew racing the party for the Murkmire Stone"),
    ("kftgv", "scene", "a bribe attempt at the casino's cashier window"),
    ("cos", "scene", "an ambush on the old road into Barovia"),
    ("cos", "quest", "a missing child in the village of Barovia"),
    ("cos", "scene", "a funeral at the church that the party interrupts"),
    ("cos", "quest", "a Vistani who offers to read the party's fortune for a price"),
    ("cos", "scene", "wolves circling the camp at dusk"),
]

#: Written down BEFORE the run. A threshold chosen after seeing the number is
#: not a threshold.
GATES = {
    "parse_rate": (0.95, "at least 95% of responses carry a usable manifest"),
    "edge_violation_rate": (
        0.20,
        "at most 20% of declared edges type-impossible, against the canon "
        "extractor's 47% on the Introduction; target 10%",
    ),
    "jaccard_temp0": (
        0.75,
        "at least 0.75 edge agreement between paired temperature-0 runs, "
        "against the canon extractor's 0.49",
    ),
    "jaccard_elements_temp0": (
        0.75,
        "at least 0.75 ELEMENT agreement between paired temperature-0 runs -- "
        "the fallback to elements-only rests on this and nothing else",
    ),
    "unshown_endpoint_rate": (
        0.10,
        "at most 10% of canon-endpoint edges naming an id the generation was "
        "never shown",
    ),
}

#: A hard stop, not a suggestion. Two identical runs of ten subjects at two
#: temperatures is about forty calls.
DEFAULT_CAP_USD = 2.00


def _edge_key(edge: dict) -> tuple[str, str, str]:
    """`(source, target, rel_type)` folded, for comparing two runs.

    Folded and ORDER-INSENSITIVE on the endpoints: the same claim written in
    the other direction is the same claim for a stability measurement, and
    `check_edges` already reports separately on reversal. Measuring it the
    strict way would make a run look less stable than it is for a reason that
    has nothing to do with the model changing its mind.
    """
    a, b = edge["source"].casefold(), edge["target"].casefold()
    return (*sorted((a, b)), edge["rel_type"])


def jaccard(left: set, right: set) -> float:
    if not left and not right:
        return 1.0
    return len(left & right) / max(1, len(left | right))


def violations_of(result: generator.Generated, shown_types: dict[str, str]) -> dict:
    """Run the canon constraint checker over a declared manifest.

    REUSED, NOT RESTATED. `check_edges` and its domain/range table are the one
    authored answer to "can this relationship hold between these two types",
    and a cluster asking the question differently would be two answers free to
    disagree.
    """
    kinds = {e["name"].casefold(): e["kind"].upper() for e in result.elements}
    kinds.update(shown_types)

    nodes, edges, unknown = [], [], 0
    for name, entity_type in kinds.items():
        nodes.append(CandidateNode(name=name, entity_type=entity_type, description=""))
    for edge in result.edges:
        source, target = edge["source"].casefold(), edge["target"].casefold()
        if source not in kinds or target not in kinds:
            unknown += 1
            continue
        edges.append(
            CandidateEdge(
                source_name=source, target_name=target,
                rel_type=edge["rel_type"], evidence="",
            )
        )
    report = report_edges(nodes, edges)
    return {
        "checked": len(edges),
        "violations": len(report.violations),
        "unknown_endpoint": unknown,
        "reasons": Counter(v.reason for v in report.violations),
    }


async def one(client, retriever, kind: str, subject: str, temperature: float, seed: int):
    """One generation, with everything the report needs about it."""
    retrieval = retriever.retrieve(subject)
    shown = {
        (s.get("section") or "").casefold(): "LOCATION"
        for s in canon_context.sources(retrieval)
    }
    result = await generator.generate(
        client,
        kind=kind,
        subject=subject,
        retrieval=retrieval,
        depth=canon_context.Depth(),
        model=settings.openai_model,
        temperature=temperature,
        cluster=True,
        max_tokens=2500,
        seed=seed,
    )
    return {
        "kind": kind,
        "subject": subject,
        "temperature": temperature,
        "parsed": not result.error,
        "error": result.error,
        "elements": len(result.elements),
        "edges": len(result.edges),
        "dropped": dict(result.manifest_dropped),
        "edge_keys": sorted("|".join(_edge_key(e)) for e in result.edges),
        # ELEMENT STABILITY IS MEASURED SEPARATELY FROM EDGE STABILITY, because
        # the fallback ladder turns on the difference: "edges dirty, elements
        # clean" is a shippable outcome and "both dirty" is not, and one
        # Jaccard over edges cannot tell those apart.
        "element_keys": sorted(
            f"{e['name'].casefold()}|{e['kind']}" for e in result.elements
        ),
        "constraints": violations_of(result, shown),
        "usd": (result.cost or {}).get("usd"),
        "names_in_body": sum(
            1 for e in result.elements if e["name"].casefold() in result.body.casefold()
        ),
    }


def summarise(rows: list[dict]) -> dict:
    parsed = [r for r in rows if r["parsed"]]
    checked = sum(r["constraints"]["checked"] for r in parsed)
    violations = sum(r["constraints"]["violations"] for r in parsed)
    unknown = sum(r["constraints"]["unknown_endpoint"] for r in parsed)
    declared = sum(r["edges"] for r in parsed)

    def paired(field: str) -> list[float]:
        pairs: dict[str, list[set]] = {}
        for row in (r for r in rows if r["temperature"] == 0.0 and r["parsed"]):
            pairs.setdefault(row["subject"], []).append(set(row[field]))
        return [jaccard(*v) for v in pairs.values() if len(v) == 2]

    agreements = paired("edge_keys")
    element_agreements = paired("element_keys")

    elements = sum(r["elements"] for r in parsed)
    return {
        "runs": len(rows),
        "parse_rate": len(parsed) / max(1, len(rows)),
        "declared_edges": declared,
        "edges_checked": checked,
        "edge_violation_rate": violations / max(1, checked),
        "unshown_endpoint_rate": unknown / max(1, declared),
        "jaccard_temp0": sum(agreements) / max(1, len(agreements)) if agreements else None,
        "jaccard_pairs": len(agreements),
        "jaccard_elements_temp0": (
            sum(element_agreements) / max(1, len(element_agreements))
            if element_agreements
            else None
        ),
        "elements_per_run": elements / max(1, len(parsed)),
        "element_named_in_body_rate": (
            sum(r["names_in_body"] for r in parsed) / max(1, elements)
        ),
        "dropped": dict(sum((Counter(r["dropped"]) for r in rows), Counter())),
        "usd": round(sum(r["usd"] or 0 for r in rows), 4),
    }


def verdict(found: dict) -> tuple[bool, list[str]]:
    """Against thresholds fixed before the run. Returns `(passed, lines)`."""
    lines, passed = [], True
    for key, (threshold, why) in GATES.items():
        value = found.get(key)
        if value is None:
            lines.append(f"  {key:24} NOT MEASURED   ({why})")
            passed = False
            continue
        higher_is_better = key.startswith("parse") or "jaccard" in key
        ok = value >= threshold if higher_is_better else value <= threshold
        passed = passed and ok
        lines.append(
            f"  {key:24} {value:.2f}   {'PASS' if ok else 'FAIL'}   ({why})"
        )
    return passed, lines


async def run(cap: float, report_path: Path) -> int:
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    retrievers = {b: CanonRetriever(book=b) for b in {b for b, _, _ in SUBJECTS}}

    rows, spent = [], 0.0
    # THE SAME SEED TWICE at temperature 0 is the pairing: two draws that
    # should be identical if the model is deterministic under it, which is how
    # `extract.py` measured the 0.49 this is compared against.
    for temperature, seed in ((0.0, 20260826), (0.0, 20260826), (0.8, 1), (0.8, 2)):
        for book, kind, subject in SUBJECTS:
            if spent >= cap:
                print(f"\nSTOPPED at the ${cap:.2f} cap after {len(rows)} runs.")
                break
            row = await one(client, retrievers[book], kind, subject, temperature, seed)
            row["book"] = book
            rows.append(row)
            spent += row["usd"] or 0
            mark = "ok " if row["parsed"] else "BAD"
            print(
                f"  [{len(rows):>2}] {mark} t={temperature} {book:6} "
                f"{row['elements']:>2} elements {row['edges']:>2} edges  {subject[:44]}"
            )
        if spent >= cap:
            break

    found = summarise(rows)
    passed, lines = verdict(found)

    print(f"\n  {found['runs']} runs, ${found['usd']:.4f} spent")
    print(f"  {found['elements_per_run']:.1f} elements per run, "
          f"{found['declared_edges']} edges declared")
    print(f"  {found['element_named_in_body_rate']:.0%} of elements named in the body "
          "(reported, not gated)")
    if found["dropped"]:
        print("  manifest entries dropped:")
        for reason, n in sorted(found["dropped"].items(), key=lambda kv: -kv[1]):
            print(f"     {n:>3}  {reason}")
    print("\n  GATES, fixed before the run")
    for line in lines:
        print(line)
    print(f"\n  VERDICT: {'clusters are viable as designed' if passed else 'FALLBACK REQUIRED'}")
    if not passed:
        print("  See the ladder in the design: elements-only, then a two-call")
        print("  variant where the same model annotates its own prose. Extraction")
        print("  is NOT the fallback -- its 0.49 Jaccard is why it was rejected.")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps({"summary": found, "gates_passed": passed, "runs": rows}, indent=2)
    )
    print(f"\n  wrote {report_path}")
    return 0 if passed else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Actually spend money.")
    parser.add_argument("--cap", type=float, default=DEFAULT_CAP_USD)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    planned = len(SUBJECTS) * 4
    print(f"{len(SUBJECTS)} subjects x 2 temperatures x 2 runs = {planned} calls")
    print(f"cap ${args.cap:.2f}, model {settings.openai_model}")
    print("gates, fixed before any number arrives:")
    for key, (threshold, why) in GATES.items():
        print(f"  {key:24} {threshold:<5} {why}")
    if not args.apply:
        print("\n--dry-run: nothing called, nothing spent. Re-run with --apply.")
        return 0
    return asyncio.run(run(args.cap, args.report))


if __name__ == "__main__":
    sys.exit(main())
