"""Start a campaign, and seed its running order from the book it draws on.

    uv run python -m backend.scripts.create_campaign \
        --slug p13-home --name "Prisoner 13" --book kftgv
    uv run python -m backend.scripts.create_campaign \
        --slug p13-home --name "Prisoner 13" --book kftgv --apply

DRY-RUN IS THE DEFAULT and `--apply` is spelled out, as everywhere else here
that writes. Seeding is not destructive on a fresh campaign, but `--reseed` is:
it throws away every insertion, skip and move the DM has made, which is the one
thing in this system that cannot be recomputed from anything.

A CAMPAIGN NEEDS NO BOOK. `--book` may be omitted, and the campaign starts with
an empty chain that grows from its first insertion. That is a wholly invented
world, and it is the same mechanism with the seed step skipped -- not a second
code path.

ONE BOOK AT A TIME, for now. The model permits several and the API refuses
them, because a retriever that reads two books at once has never been measured
and the one time retrieval went book-blind, 45 of 96 evaluation questions took
a passage from the wrong book and MRR fell from 0.61 to 0.56. Refusing beats
blending and hoping.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from backend.campaign import store
from backend.campaign.chain import seed_plan
from backend.campaign.model import Campaign
from backend.core.database import neo4j_session, read_only_session


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slug", required=True, help="short id, e.g. p13-home")
    parser.add_argument("--name", default="", help="what the DM calls it")
    parser.add_argument(
        "--book",
        action="append",
        default=[],
        help="a book to draw on. Repeatable in the model; at most one is accepted today.",
    )
    parser.add_argument(
        "--reseed",
        action="store_true",
        help="Replace an existing chain. DESTROYS every insertion, skip and move.",
    )
    parser.add_argument("--apply", action="store_true", help="Actually write.")
    parser.add_argument("--log", type=Path, default=store.DEFAULT_LOG_PATH)
    args = parser.parse_args()

    if len(args.book) > 1:
        print(
            f"refusing {len(args.book)} books: a campaign reads one, the way a session does. "
            "Two books in one retrieval has never been measured and went badly the one time "
            "it happened by accident.",
            file=sys.stderr,
        )
        return 2

    campaign = Campaign(
        slug=args.slug, name=args.name or args.slug, books=tuple(args.book)
    )

    with read_only_session() as session:
        existing = {c.slug for c in store.read_campaigns(session)}
        links, start = store.read_chain(session, campaign.slug)
        spine = (
            store.spine_order(session, campaign.books[0]) if campaign.books else []
        )

    print(f"campaign {campaign.slug!r} ({campaign.name})")
    print(f"  draws on: {', '.join(campaign.books) or 'nothing -- a wholly invented world'}")
    if campaign.books and not spine:
        print(f"  BOOK NOT FOUND: nothing in the graph has slug {campaign.books[0]!r}")
        return 2

    if links and not args.reseed:
        print(
            f"  already has a running order of {len(links) + 1} sections. "
            "Re-seeding would destroy every insertion, skip and move in it; "
            "pass --reseed --apply if that is what you want."
        )
        return 1

    plan = seed_plan(spine)
    print(
        f"  seeding {len(spine)} sections"
        if spine
        else "  empty chain -- the first insertion will start it"
    )
    if campaign.slug in existing:
        print("  the campaign node already exists and will be updated in place")

    if not args.apply:
        print("\n--dry-run: nothing written. Re-run with --apply.")
        return 0

    with neo4j_session() as session:
        def write(tx):
            store.create(tx, campaign)
            if args.reseed:
                tx.run(
                    "MATCH (:Section)-[r:NEXT {campaign:$slug}]->(:Section) DELETE r",
                    {"slug": campaign.slug},
                )
            if plan.noop:
                return {"changed": 0, "noop": plan.noop}
            return store.apply_rewire(
                tx, campaign.slug, plan, frozenset(spine), log_path=args.log
            )

        result = session.execute_write(write)

    print(f"\nwrote {campaign.slug}: {result['changed']} chain link(s)")
    if result["noop"]:
        print(f"  chain: {result['noop']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
