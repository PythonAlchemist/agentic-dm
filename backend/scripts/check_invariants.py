"""Check the things that must be true of the graph.

    uv run python -m backend.scripts.check_invariants

READS AND NEVER WRITES, so it is safe to point at a live table mid-session.
Exits non-zero when something is broken, which is what makes it usable as a
gate rather than only as a thing to run when suspicious.

WHY IT EXISTS: four times in one week the same defect appeared -- a
campaign-plane thing joining nodes the campaign does not own, outliving
whatever made it -- and each instance was invisible to the check written for
the one before it. Every one was found by hand, after the fact, in a graph
that already held it. `backend/campaign/invariants.py` states the rules and is
the file to read first; this one only prints them.
"""

from __future__ import annotations

import argparse
import sys

from backend.campaign import invariants
from backend.core.database import read_only_session


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Print only what is broken. Exit code says the rest.",
    )
    args = parser.parse_args()

    with read_only_session() as session:
        found = invariants.run(session)

    broken = 0
    for check, rows in found:
        if not rows:
            if not args.quiet:
                print(f"  ok      {check.name}")
            continue
        broken += 1
        # A CAPPED RESULT IS NOT A COUNT. The queries take `LIMIT ROW_LIMIT`,
        # so a full page means "at least this many" -- printing it as a total
        # told a reader 154 unsupported entities were 50.
        capped = "at least " if len(rows) >= invariants.ROW_LIMIT else ""
        print(f"  BROKEN  {check.name} -- {capped}{len(rows)} row(s)")
        # A HANDFUL, NOT ALL OF THEM. The rows are evidence a person reads, and
        # fifty lines of the same shape teaches them to skip the next run.
        for row in rows[:5]:
            campaign = row.get("campaign") or "-"
            print(f"            {campaign}  {row.get('id')}  ({row.get('why')})")
        if len(rows) > 5:
            print(f"            ... and {len(rows) - 5} more")
        print(f"            fix: {check.fix}")

    if broken:
        print(f"\n{broken} of {len(found)} invariants broken")
        return 1
    print(f"\nall {len(found)} invariants hold")
    return 0


if __name__ == "__main__":
    sys.exit(main())
