"""Fold the groupings in an alias seed into the graph.

    uv run python -m backend.scripts.apply_aliases --seed data/aliases/kftgv.yaml
    uv run python -m backend.scripts.apply_aliases --seed data/aliases/kftgv.yaml --apply

THE SECOND HALF OF `propose_aliases`, AND THE IRREVERSIBLE ONE. That script asks
a model which names are one thing and writes a file; this one carries the file
into Neo4j after a person has read it. The split is the whole design: a model
proposes, a human reads, a script applies.

DRY-RUN IS THE DEFAULT and `--apply` is spelled out, as in `merge_duplicates`.
Everything it deletes is regenerable by a re-write from the extraction
artifacts, but "regenerable" is a thing to know before rather than after.

IT MERGES THROUGH `merge_duplicates`, NOT THROUGH A SECOND IMPLEMENTATION. That
module already knows how to repoint every edge of an entity, move its mentions,
keep its spellings as aliases and fold the doubled mentions that repointing
leaves behind -- and it learned the last of those from a defect nobody caught
until they looked. A second merge here would be free to forget any of it.

A NAME THAT RESOLVES TO SEVERAL ENTITIES IS REFUSED, not guessed at. In an
anthology one name legitimately belongs to several adventures, and picking one
would silently move another adventure's mentions into a heist they have nothing
to do with. Refused whole, reported by name.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import yaml

from backend.canon.duplicates import Merge
from backend.canon.lookup import CANON_PLANE
from backend.core.database import neo4j_session, read_only_session
from backend.scripts.merge_duplicates import _DOUBLED_MENTIONS, _apply, _fold_mentions

_BY_NAME = """
MATCH (e:Entity {plane:$plane}) WHERE e.id STARTS WITH $prefix
RETURN e.name AS name, collect(e.id) AS ids
"""


def plan(groups: list[dict], by_name: dict[str, list[str]]) -> tuple[list[Merge], list[str]]:
    """Turn read groupings into merges. Returns `(merges, refusals)`.

    Pure over the name index, so what a seed WOULD do can be printed without a
    write transaction open.
    """
    merges: list[Merge] = []
    refused: list[str] = []
    for group in groups:
        canonical = group["canonical"]
        names = list(group["names"])

        missing = [n for n in names if n not in by_name]
        if missing:
            # The seed was written against a graph that has since changed --
            # an earlier merge already folded this name, or a re-write dropped
            # it. Not an error, but not something to apply blind either.
            refused.append(f"{canonical!r}: no entity named {missing!r}")
            continue
        ambiguous = {n: by_name[n] for n in names if len(by_name[n]) > 1}
        if ambiguous:
            refused.append(f"{canonical!r}: {ambiguous!r} names more than one entity")
            continue

        survivor = by_name[canonical][0]
        losers = tuple(sorted(by_name[n][0] for n in names if n != canonical))
        if not losers:
            continue
        merges.append(
            Merge(
                survivor=survivor,
                survivor_name=canonical,
                losers=losers,
                aliases=tuple(sorted(n for n in names if n != canonical)),
            )
        )
    return merges, refused


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=Path, required=True)
    parser.add_argument("--plane", default=CANON_PLANE)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually merge. Without it the plan is printed and nothing changes.",
    )
    args = parser.parse_args()

    seed = yaml.safe_load(args.seed.read_text())
    book, groups = seed["book"], seed.get("groups") or []

    by_name: dict[str, list[str]] = defaultdict(list)
    with read_only_session() as session:
        for record in session.run(
            _BY_NAME, {"plane": args.plane, "prefix": f"{book}:"}
        ):
            row = dict(record)
            by_name[row["name"]] = row["ids"]

    merges, refused = plan(groups, by_name)
    print(f"{args.seed} proposes {len(groups)} groupings for {book}")
    print(f"  {len(merges)} applicable, {sum(len(m.losers) for m in merges)} nodes to fold")
    for refusal in refused:
        print(f"  REFUSED {refusal}")

    if not args.apply:
        print("\nNothing changed. Re-run with --apply to merge.")
        return 0

    totals = {"mentions": 0, "pairs": 0, "aliases": 0, "typed": 0}
    with neo4j_session() as session:
        for merge in merges:
            tally = session.execute_write(_apply, merge, args.plane)
            for key, value in tally.items():
                totals[key] += value
        # After every merge, for the reason `merge_duplicates` gives: a section
        # only holds two mentions of one entity once its entities are folded.
        doubled = [
            dict(r) for r in session.run(_DOUBLED_MENTIONS, {"plane": args.plane})
        ]
        folded = sum(
            session.execute_write(
                _fold_mentions, row["entity"], row["section"], row["mentions"]
            )
            for row in doubled
        )
    print(
        f"\nmerged {len(merges)} groups: moved {totals['mentions']} mentions, "
        f"{totals['pairs']} co-occurrences, {totals['aliases']} aliases, "
        f"{totals['typed']} typed edges"
    )
    print(f"folded {folded} doubled mentions across {len(doubled)} sections")
    return 0


if __name__ == "__main__":
    sys.exit(main())
