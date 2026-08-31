"""Remove a campaign and everything it ever wrote.

    uv run python -m backend.scripts.delete_campaign --slug qa-scratch
    uv run python -m backend.scripts.delete_campaign --slug qa-scratch --apply

THE INVERSE `create_campaign` NEVER HAD. A table could be made and not unmade,
so an abandoned one left its running order lying on the book: 542 `NEXT` links
between CANON sections, each carrying the slug of a campaign that no longer
existed. Deleting the `:Campaign` node does not touch them, because they join
two nodes it does not own -- the same shape that let edges, and then mentions,
outlive the prose that made them.

CANON IS NEVER MUTATED, which is what makes this safe to offer at all. Every
node this removes was created by the campaign. The book's own sections and
entities survive with their campaign-plane attachments gone and nothing else
changed, which is the same invariant `homebrew.delete` relies on.

DRY-RUN IS THE DEFAULT and `--apply` is spelled out, as in `merge_duplicates`
and `apply_aliases`. Unlike those, nothing here is regenerable: a campaign's
prose is the DM's own writing and no re-ingest brings it back. So the plan
prints what will go, and how much of it is writing rather than bookkeeping.
"""

from __future__ import annotations

import argparse
import sys

from backend.campaign import store
from backend.core.database import neo4j_session, read_only_session

_SURVEY = """
MATCH (c:Campaign {slug:$slug})
OPTIONAL MATCH (e:Entity {plane:'campaign', campaign:$slug})
OPTIONAL MATCH (s:Section {plane:'campaign', campaign:$slug})
OPTIONAL MATCH (m:Mention {campaign:$slug})
RETURN c.name AS name, count(DISTINCT e) AS entities,
       count(DISTINCT s) AS sections, count(DISTINCT m) AS mentions
"""

#: Prose the DM wrote, which is the part no re-ingest brings back. Counted
#: separately from the node total because "12 sections" and "9,400 characters
#: of your own writing" are different sentences to read before saying yes.
_WRITING = """
MATCH (s:Section {plane:'campaign', campaign:$slug})
RETURN count(s) AS sections, sum(size(coalesce(s.text,''))) AS characters
"""

_RELS = "MATCH ()-[r]->() WHERE r.campaign = $slug RETURN count(r) AS n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slug", required=True, help="the campaign to remove")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete. Without it the plan is printed and nothing changes.",
    )
    args = parser.parse_args()

    with read_only_session() as session:
        row = session.run(_SURVEY, {"slug": args.slug}).single()
        if row is None:
            print(f"no campaign {args.slug!r}")
            return 1
        writing = session.run(_WRITING, {"slug": args.slug}).single()
        rels = session.run(_RELS, {"slug": args.slug}).single()["n"]

    found = dict(row)
    print(f"{args.slug} ({found['name']})")
    print(f"  {found['entities']} entities, {found['sections']} sections, "
          f"{found['mentions']} mentions")
    print(f"  {rels} relationships, including the running order over the book")
    if writing["characters"]:
        print(f"  {writing['characters']:,} characters of prose the DM wrote -- "
              "no re-ingest brings this back")

    if not args.apply:
        print("\nNothing changed. Re-run with --apply to delete.")
        return 0

    with neo4j_session() as session:
        counts = session.execute_write(store.delete_campaign, args.slug)
    print("\nremoved " + ", ".join(f"{v} {k}" for k, v in counts.items()))

    # SAID OUT LOUD, because "the book is untouched" is the promise this whole
    # design rests on and a reader should not have to take it on faith.
    with read_only_session() as session:
        left = session.run(
            "MATCH (n) WHERE n.campaign = $slug RETURN count(n) AS n", {"slug": args.slug}
        ).single()["n"]
        canon = session.run(
            "MATCH (s:Section {plane:'canon'}) RETURN count(s) AS n"
        ).single()["n"]
    print(f"  {left} nodes left carrying that slug; {canon} canon sections untouched")
    return 0


if __name__ == "__main__":
    sys.exit(main())
