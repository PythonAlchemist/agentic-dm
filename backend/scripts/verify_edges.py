"""Measure how often a proposed edge is supported by the sentence it cites.

    uv run python -m backend.scripts.verify_edges --book cos --per-stratum 40
    uv run python -m backend.scripts.verify_edges --book kftgv --per-stratum 60

READS AND REPORTS. Nothing here writes to the graph: the output is a rate and a
list of failures a person can check, and what to do about them is a separate
decision made with that number in hand.

WHY STRATIFIED BY VOTE COUNT. Curse of Strahd was extracted with five samples
and an edge kept only if three found it; the heist anthology was extracted once
and keeps everything. If consensus works, the supported-rate should climb with
the vote count -- and that is the question that decides whether re-extracting a
book at five samples is worth its cost. It has never been measured. The figure
this project quotes about itself, "roughly a third are wrong", comes from one
hand read of thirty edges in a single chapter.

`backend/canon/edge_check.py` holds the rules a verdict is checked against and
is the file to read first.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

from openai import AsyncOpenAI

from backend.canon.edge_check import PROMPT, parse, precision, render
from backend.core.config import settings
from backend.core.database import read_only_session

MODEL = "gpt-4o-mini"
SEED = 20260824
CONCURRENCY = 8
#: Edges per call. Small enough that every one gets read, large enough that the
#: instructions are not re-sent per edge.
BATCH = 10

_EDGES = """
MATCH (a:Entity {plane:'canon'})-[r]->(b:Entity {plane:'canon'})
WHERE a.id STARTS WITH $prefix AND r.status <> 'accepted'
  AND r.evidence IS NOT NULL AND r.evidence <> ''
RETURN elementId(r) AS eid, a.name AS source, type(r) AS rel_type, b.name AS target,
       r.evidence AS evidence, coalesce(r.votes, 0) AS votes
"""

#: The verdict, stamped on the edge it is about. ADDITIVE: nothing is deleted
#: and nothing is hidden here, so a wrong verdict costs a property and not an
#: edge. What the read path does with it is a separate decision, made after
#: somebody has looked at the numbers.
_STAMP = """
MATCH ()-[r]->() WHERE elementId(r) = $eid
SET r.evidence_check = $verdict, r.evidence_check_why = $why
"""


async def _judge(client, batch):
    keys = [e["key"] for e in batch]
    try:
        response = await client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": PROMPT.format(items=render(batch))}],
            response_format={"type": "json_object"},
            temperature=0.0,
            seed=SEED,
        )
        return parse(response.choices[0].message.content or "", keys)
    except Exception as exc:  # noqa: BLE001 - one bad batch must not lose the run
        return [], [f"call failed: {type(exc).__name__}: {exc}"]


async def run(sample: list[dict]):
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    semaphore = asyncio.Semaphore(CONCURRENCY)
    batches = [sample[i : i + BATCH] for i in range(0, len(sample), BATCH)]

    async def one(batch):
        async with semaphore:
            return await _judge(client, batch)

    results = await asyncio.gather(*(one(b) for b in batches))
    verdicts, refusals = [], []
    for got, refused in results:
        verdicts.extend(got)
        refusals.extend(refused)
    return verdicts, refusals


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--book", required=True)
    parser.add_argument("--per-stratum", type=int, default=40)
    parser.add_argument(
        "--all", action="store_true",
        help="judge every proposed edge rather than a stratified sample",
    )
    parser.add_argument(
        "--write", action="store_true",
        help="stamp each verdict on its edge. Additive -- nothing is deleted.",
    )
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    with read_only_session() as session:
        edges = [dict(r) for r in session.run(_EDGES, {"prefix": f"{args.book}:"})]
    for i, edge in enumerate(edges):
        edge["key"] = f"e{i}"

    by_votes = defaultdict(list)
    for edge in edges:
        by_votes[edge["votes"]].append(edge)

    # Seeded, so two runs judge the same edges and a change in the rate is a
    # change in the edges rather than in which ones got looked at.
    if args.all:
        sample = edges
    else:
        rng = random.Random(SEED)
        sample = []
        for votes in sorted(by_votes):
            group = by_votes[votes]
            sample.extend(rng.sample(group, min(args.per_stratum, len(group))))

    print(f"{len(edges)} proposed edges in {args.book}")
    for votes in sorted(by_votes):
        print(f"   votes={votes}: {len(by_votes[votes])} edges")
    print(f"judging a sample of {len(sample)}\n")

    verdicts, refusals = asyncio.run(run(sample))
    for refusal in refusals[:10]:
        print(f"  REFUSED {refusal}")
    if len(refusals) > 10:
        print(f"  ... and {len(refusals) - 10} more refusals")

    by_key = {e["key"]: e for e in sample}
    per_stratum = defaultdict(list)
    for verdict in verdicts:
        per_stratum[by_key[verdict.key]["votes"]].append(verdict)

    print(f"\n  {'votes':<7}{'judged':<8}{'supported':<11}{'rate':<8}reversed  unsupported")
    for votes in sorted(per_stratum):
        t = precision(per_stratum[votes])
        rate = f"{t['supported_rate']:.0%}" if t["supported_rate"] is not None else "--"
        print(f"  {votes:<7}{len(per_stratum[votes]):<8}{t['supported']:<11}{rate:<8}"
              f"{t['reversed']:<10}{t['unsupported']}")
    overall = precision(verdicts)
    rate = f"{overall['supported_rate']:.0%}" if overall["supported_rate"] is not None else "--"
    print(f"\n  overall supported: {rate} of {overall['decided']} decided "
          f"({overall['unclear']} unclear, excluded)")

    if args.write:
        from backend.core.database import neo4j_session

        with neo4j_session() as session:
            for verdict in verdicts:
                session.run(_STAMP, {
                    "eid": by_key[verdict.key]["eid"],
                    "verdict": verdict.verdict,
                    "why": verdict.why,
                })
        print(f"\nstamped {len(verdicts)} edges with `evidence_check`")
        unjudged = len(sample) - len(verdicts)
        if unjudged:
            # Left unstamped rather than defaulted: an edge nobody judged is
            # not an edge that passed, and a reader must be able to tell those
            # apart.
            print(f"  {unjudged} edge(s) got no verdict and were left unstamped")

    if args.out:
        args.out.write_text(json.dumps(
            [{"key": v.key, "verdict": v.verdict, "why": v.why,
              "claim": f"{by_key[v.key]['source']} -{by_key[v.key]['rel_type']}-> "
                       f"{by_key[v.key]['target']}",
              "votes": by_key[v.key]["votes"]}
             for v in verdicts], indent=2))
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
