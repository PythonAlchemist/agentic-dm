"""Compare a campaign's running order against the book it draws on, and repair.

    uv run python -m backend.scripts.reconcile_chain --slug p13-home
    uv run python -m backend.scripts.reconcile_chain --slug p13-home --apply

WHY THIS EXISTS. A campaign's chain is seeded from a book's spine and then
edited by a person. The book goes on changing underneath it: a chapter is
re-extracted, or one is harvested that was missed the first time -- which
happened to this repository the day the chain was designed, when Keys from the
Golden Vault turned out to be missing its Introduction. After that the chain is
correct about everything the DM decided and silent about everything new.

WHAT IT REPAIRS AND WHAT IT REFUSES TO. `--apply` inserts UNSEEDED sections
only -- ones in the book's spine that are neither in the chain nor recorded as
skipped, so the DM has expressed no opinion about them. They go at their
document-order position, between their nearest placed neighbours. Nothing the
DM placed is ever moved, and a broken chain (cycle, fork, severed) is REPORTED
AND LEFT ALONE: repairing pointer damage automatically means guessing which of
two orders the DM meant, and the campaign log exists so a person can replay the
answer instead of a script inventing one.

THE SKIP RECORD IS WHY THIS CAN WORK AT ALL. Without `SKIPPED`, a section
absent from the chain could equally be one the DM cut or one the book just
gained, and those want opposite repairs. That is why a skip is a recorded fact
rather than an inferred absence.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from backend.campaign import store
from backend.campaign.chain import insert_plan, integrity, position_for, walk
from backend.campaign.model import every_section_placed
from backend.core.database import neo4j_session, read_only_session


def survey(session, slug: str) -> dict:
    """Everything wrong with one campaign's running order. Pure report."""
    campaigns = {c.slug: c for c in store.read_campaigns(session)}
    campaign = campaigns.get(slug)
    if campaign is None:
        return {"missing": True}

    links, start = store.read_chain(session, slug)
    skipped = store.read_skipped(session, slug)
    spine = [s for book in campaign.books for s in store.spine_order(session, book)]

    found = walk(links, start, bound=len(links) + 2)
    in_chain = frozenset(found.order)
    chained_ids = {a for a, _ in links} | {b for _, b in links}

    return {
        "missing": False,
        "campaign": campaign,
        "spine": spine,
        "links": links,
        "start": start,
        "in_chain": in_chain,
        "order": found.order,
        "stopped": found.stopped,
        "problems": integrity(links, start),
        # In the book, in neither the chain nor the skip list: the DM has said
        # nothing about it, almost always because it is newer than the seed.
        "unseeded": [s for s in spine if s in every_section_placed(
            frozenset(spine), in_chain, skipped
        )],
        # Chained but no longer part of any drawn book -- a re-extraction that
        # renumbered sections leaves these behind.
        "orphaned": sorted(chained_ids - frozenset(spine) - {
            s for s in chained_ids if s.startswith("hb:")
        }),
        "skipped": sorted(skipped),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slug", help="one campaign; omit to survey every one")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Insert unseeded sections at their book position. Repairs nothing else.",
    )
    parser.add_argument("--log", type=Path, default=store.DEFAULT_LOG_PATH)
    args = parser.parse_args()

    with read_only_session() as session:
        slugs = (
            [args.slug] if args.slug else [c.slug for c in store.read_campaigns(session)]
        )
        reports = {slug: survey(session, slug) for slug in slugs}

    if not slugs:
        print("no campaigns")
        return 0

    exit_code = 0
    repairs: dict[str, list[str]] = {}
    for slug, report in reports.items():
        if report["missing"]:
            print(f"{slug}: NO SUCH CAMPAIGN")
            exit_code = 2
            continue

        campaign = report["campaign"]
        print(f"{slug} ({campaign.name}) — draws on {', '.join(campaign.books) or 'nothing'}")
        print(f"  {len(report['order'])} sections in the running order, "
              f"{len(report['skipped'])} skipped, {len(report['spine'])} in the book")

        if report["stopped"] != "end":
            print(f"  CHAIN DID NOT TERMINATE CLEANLY: stopped on {report['stopped']!r}")
            exit_code = 1
        for problem in report["problems"]:
            print(f"  BROKEN: {problem}")
            exit_code = 1
        if report["orphaned"]:
            print(f"  ORPHANED: {len(report['orphaned'])} chained section(s) are in no "
                  f"drawn book: {report['orphaned'][:3]}")
            exit_code = 1

        if report["unseeded"]:
            print(f"  UNSEEDED: {len(report['unseeded'])} section(s) are in the book and "
                  "in neither the chain nor the skip list")
            for section_id in report["unseeded"][:5]:
                print(f"     {section_id}")
            repairs[slug] = report["unseeded"]

        if not report["problems"] and not report["unseeded"] and not report["orphaned"]:
            print("  sound")

    if not repairs:
        return exit_code
    if not args.apply:
        print("\n--dry-run: nothing written. Re-run with --apply to insert the unseeded "
              "sections at their book positions.")
        return exit_code

    for slug, unseeded in repairs.items():
        report = reports[slug]
        if report["problems"]:
            # A chain that is already broken must not be edited: an insert into
            # a severed order silently commits to one of two readings.
            print(f"\n{slug}: REFUSING to repair a chain that is already broken.")
            exit_code = 1
            continue

        inserted = 0
        with neo4j_session() as session:
            for section_id in unseeded:
                links, start = store.read_chain(session, slug)
                in_chain = frozenset(walk(links, start, bound=len(links) + 2).order)
                after = position_for(report["spine"], in_chain, section_id)
                plan = insert_plan(links, start, section_id, after)
                if plan.noop:
                    continue
                expected = in_chain | {section_id}
                session.execute_write(
                    lambda tx, p=plan, e=expected: store.apply_rewire(
                        tx, slug, p, e, log_path=args.log
                    )
                )
                inserted += 1
        print(f"\n{slug}: inserted {inserted} unseeded section(s) at their book positions")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
