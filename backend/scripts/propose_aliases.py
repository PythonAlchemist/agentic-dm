"""Ask a model which of a book's entity names are one thing said differently.

    uv run python -m backend.scripts.propose_aliases --book kftgv --dry-run
    uv run python -m backend.scripts.propose_aliases --book kftgv -o seed.yaml

WRITES A FILE, NEVER THE GRAPH. The output is a seed with the same standing as
`location-subtypes.yaml` and `structural-headings.yaml`: claims a person made,
which a reader can argue with, applied by a separate step after somebody has
read them. `backend/canon/coreference.py` holds the rules the model's answers
are checked against and is the file to read first.

`--dry-run` prints what would be asked and spends nothing, for the reason
`extract_canon` has one: a run that costs money should be inspectable before it
costs any.

EVERY REFUSAL IS PRINTED. A model that invented a name, or picked a canonical
outside its own group, is a fact about the prompt -- and a grouping silently
dropped is indistinguishable from one never proposed, which is the shape of
defect this package keeps finding in itself.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import yaml
from openai import AsyncOpenAI

from backend.canon.coreference import PROMPT, blocks, merge_overlapping, parse
from backend.core.config import settings
from backend.core.database import read_only_session

#: The extraction model, for the reason the extraction path chose it: this is a
#: bounded reading task over a short list, not a reasoning one.
MODEL = "gpt-4o-mini"

#: Pinned, so two runs over an unchanged book propose the same groupings and a
#: reader is reviewing a decision rather than a sample.
SEED = 20260824
CONCURRENCY = 8

_NAMES = """
MATCH (e:Entity {plane:'canon'}) WHERE e.id STARTS WITH $prefix
RETURN e.name AS name, [l IN labels(e) WHERE l <> 'Entity'] AS labels
"""


async def _ask(client: AsyncOpenAI, word: str, names: tuple[str, ...]):
    """One block. Never raises: a failed block is reported and the run goes on."""
    try:
        response = await client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": PROMPT.format(names="\n".join(names))}],
            response_format={"type": "json_object"},
            temperature=0.0,
            seed=SEED,
        )
        return word, parse(response.choices[0].message.content or "", names)
    except Exception as exc:  # noqa: BLE001 - one bad block must not lose the rest
        return word, ([], [f"call failed: {type(exc).__name__}: {exc}"])


async def propose(names, cap: int, kinds, family_cap: int):
    """Returns `(groups, refusals, blocks_asked)`."""
    work = blocks(names, cap=cap, kinds=kinds)
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    semaphore = asyncio.Semaphore(CONCURRENCY)

    async def one(word, group):
        async with semaphore:
            return await _ask(client, word, group)

    results = await asyncio.gather(*(one(w, g) for w, g in work))
    groups, refusals = [], []
    for word, (found, refused) in results:
        groups.extend(found)
        refusals.extend(f"[{word}] {r}" for r in refused)
    folded, runaway = merge_overlapping(groups, cap=family_cap)
    return folded, refusals + [f"[fold] {r}" for r in runaway], len(work)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--book", required=True, help="id prefix, e.g. kftgv")
    parser.add_argument("-o", "--out", type=Path, help="seed file to write")
    parser.add_argument("--cap", type=int, default=40, help="largest block to ask about")
    parser.add_argument(
        "--family-cap", type=int, default=6,
        help="largest folded alias family to accept. Bigger is a runaway "
             "transitive merge, not an answer.",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    kinds: dict[str, frozenset[str]] = {}
    with read_only_session() as session:
        for record in session.run(_NAMES, {"prefix": args.book}):
            row = dict(record)
            kinds.setdefault(row["name"], frozenset()) 
            kinds[row["name"]] = kinds[row["name"]] | frozenset(row["labels"])
    names = sorted(kinds)
    work = blocks(names, cap=args.cap, kinds=kinds)
    dropped = [
        (w, len(g)) for w, g in blocks(names, cap=10**9, kinds=kinds) if len(g) > args.cap
    ]

    print(f"{len(names)} entity names in {args.book}")
    print(f"{len(work)} blocks to ask about, {sum(len(g) for _, g in work)} name-slots")
    if dropped:
        # Loudly: an unasked block is a question nobody answered, not a no.
        print(f"  {len(dropped)} block(s) too large to ask, LEFT UNRESOLVED:")
        for word, size in sorted(dropped, key=lambda d: -d[1])[:8]:
            print(f"     {word!r} ({size} names) -- raise --cap to include it")

    if args.dry_run:
        print("\n--dry-run: nothing asked, nothing spent.")
        return 0

    groups, refusals, asked = asyncio.run(
        propose(names, args.cap, kinds, args.family_cap)
    )
    print(f"\nasked {asked} blocks, {len(groups)} groupings proposed")
    for refusal in refusals:
        print(f"  REFUSED {refusal}")

    print()
    for group in groups:
        print(f"  {group.canonical}")
        for other in group.others:
            print(f"      = {other}")

    if args.out:
        args.out.write_text(
            yaml.safe_dump(
                {
                    "book": args.book,
                    "groups": [
                        {"canonical": g.canonical, "names": list(g.names)}
                        for g in groups
                    ],
                },
                allow_unicode=True,
                sort_keys=False,
            )
        )
        print(f"\nwrote {args.out} -- READ IT before anything applies it")
    return 0


if __name__ == "__main__":
    sys.exit(main())
