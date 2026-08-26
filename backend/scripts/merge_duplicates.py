"""Fold one place's duplicate nodes together, book-wide.

    uv run python -m backend.scripts.merge_duplicates                      # plan
    uv run python -m backend.scripts.merge_duplicates --apply
    uv run python -m backend.scripts.merge_duplicates --globals kftgv      # plan
    uv run python -m backend.scripts.merge_duplicates --globals kftgv --apply

TWO QUESTIONS, ONE APPLY. The default asks "is this one place minted twice",
which `duplicates.plan_merges` answers. `--globals` asks "did the anthology
rule scope a name the book uses book-wide", which `duplicates.plan_globals`
answers by reading that book's own exception list. They plan differently and
move nodes identically, and the moving is the part that deletes things -- so it
is written once here rather than twice in two scripts.

WHAT `--globals` DOES NOT DO: re-scan. A rescoped name becomes scannable in
every chapter (`spine.scannable_in`, keyed on the id having one colon), so a
fresh ingest would find mentions in chapters neither half held. This moves what
is already there. Re-run it after a full re-ingest, not instead of one.

`backend/canon/duplicates.py` decides WHAT is a duplicate and why, and is the
file to read first; this one only carries the plan into Neo4j.

DRY-RUN IS THE DEFAULT and `--apply` is spelled out, because this deletes
nodes. Everything it deletes is regenerable by a re-write from the extraction
artifacts, but "regenerable" is a thing to know before rather than after.

WHY A REPAIR AND NOT A WRITE-PATH FIX. The two halves of a duplicate are minted
by different chapters -- the unkeyed node by whichever chapter's extraction
first named the place, the keyed one by the chapter that heads it as an area --
so the chapter doing the writing cannot see the collision it is half of. A
book-level pass is the only place both are visible at once, which puts this
beside `sync_authored_aliases` and `backfill_display_names`: re-run after a
full re-ingest.

WHAT MOVES. Every edge of a loser is repointed at the survivor and the loser's
name becomes an alias, so a question spelling it the old way still resolves.
Mentions move rather than being re-scanned: a mention records that a SECTION
named an entity, and that fact does not change because two nodes turned out to
be one.
"""

from __future__ import annotations

import argparse

from backend.canon.aliases import normalize as normalize_alias
from backend.canon.books import SEEDS, load as load_book
from backend.canon.duplicates import Merge, plan_globals, plan_merges
from backend.canon.lookup import CANON_PLANE
from backend.core.database import neo4j_session, read_only_session
from backend.graph.schema import RelationshipType

_ENTITIES = "MATCH (e:Entity {plane:$plane}) RETURN e.id AS id, e.name AS name"

#: The same entities with how often the book actually names each, which is how
#: `plan_globals` picks which half survives. Scoped to one book because the
#: exception list is one book's.
_BOOK_ENTITIES = """
MATCH (e:Entity {plane:$plane}) WHERE e.id STARTS WITH $prefix + ':'
OPTIONAL MATCH (e)<-[:REFERS_TO]-(m:Mention)
RETURN e.id AS id, e.name AS name, count(m) AS mentions
"""

#: The mention triangle and the alias edges, which have fixed types and so can
#: be written once. `CO_OCCURS_WITH` is skipped where the mention already
#: refers to the survivor: a sentence naming both halves of a duplicate named
#: ONE entity, and carrying the pair over would make the graph say the place
#: was named alongside itself.
_MOVE_FIXED = """
MATCH (loser:Entity {id:$loser}), (survivor:Entity {id:$survivor})
CALL (loser, survivor) {
  MATCH (m:Mention)-[r:REFERS_TO]->(loser)
  MERGE (m)-[:REFERS_TO]->(survivor)
  DELETE r
  RETURN count(*) AS mentions
}
CALL (loser, survivor) {
  MATCH (m:Mention)-[r:CO_OCCURS_WITH]->(loser)
  WHERE NOT (m)-[:REFERS_TO]->(survivor)
  MERGE (m)-[:CO_OCCURS_WITH]->(survivor)
  DELETE r
  RETURN count(*) AS pairs
}
CALL (loser, survivor) {
  MATCH (a:Alias)-[r:ALIAS_OF]->(loser)
  MERGE (a)-[:ALIAS_OF]->(survivor)
  DELETE r
  RETURN count(*) AS aliases
}
RETURN mentions, pairs, aliases
"""

#: Typed entity-to-entity edges, read out before they are rewritten. Neo4j
#: cannot parameterise a relationship type, so the type has to reach the query
#: as text -- and it is checked against `RelationshipType` first, so what is
#: interpolated is a member of a fixed enum rather than a string that came out
#: of the database.
_TYPED_EDGES = """
MATCH (loser:Entity {id:$loser})-[r]->(far:Entity)
RETURN type(r) AS rel_type, properties(r) AS props, far.id AS far, 'out' AS direction
UNION
MATCH (far:Entity)-[r]->(loser:Entity {id:$loser})
RETURN type(r) AS rel_type, properties(r) AS props, far.id AS far, 'in' AS direction
"""


def _move_typed(tx, loser: str, survivor: str) -> int:
    """Repoint the loser's typed edges. Returns how many moved.

    A SELF-EDGE IS DROPPED, NOT MOVED. The loser and the survivor are one
    place, so `Village of Barovia CONTAINS Village of Barovia` is what carrying
    an edge between them over would assert.
    """
    rows = [dict(r) for r in tx.run(_TYPED_EDGES, {"loser": loser})]
    moved = 0
    for row in rows:
        if row["far"] == survivor:
            continue
        rel = RelationshipType(row["rel_type"])  # raises on an unknown type
        if row["direction"] == "out":
            pattern = "(s)-[new:%s]->(f)" % rel.value
        else:
            pattern = "(f)-[new:%s]->(s)" % rel.value
        tx.run(
            f"""
            MATCH (s:Entity {{id:$survivor}}), (f:Entity {{id:$far}})
            MERGE {pattern}
            SET new += $props
            """,
            {"survivor": survivor, "far": row["far"], "props": row["props"]},
        )
        moved += 1
    return moved


#: Two mentions of ONE entity in ONE section, which is what repointing
#: `REFERS_TO` leaves behind: the section named the place twice, once under each
#: spelling, and each spelling had its own mention node.
#:
#: A `:Mention` is one per (entity, section) by construction -- `mention_id` is
#: exactly that pair -- so two of them is not a state the scan can produce and
#: not one the read path expects. Left alone it double-counts: `MENTIONS`
#: returns the section twice, so retrieval sees it twice and its occurrence
#: count reads as double what the book says.
_DOUBLED_MENTIONS = """
MATCH (e:Entity {plane:$plane})<-[:REFERS_TO]-(m:Mention)-[:IN_SECTION]->(sec:Section)
WITH e, sec, collect(m) AS ms WHERE size(ms) > 1
RETURN e.id AS entity, sec.id AS section,
       [x IN ms | {id: x.id, offsets: x.offsets}] AS mentions
"""


def _fold_mentions(tx, entity: str, section: str, mentions: list[dict]) -> int:
    """Fold a section's duplicate mentions into one. Returns how many went.

    OFFSETS ARE UNIONED rather than one node's being kept, though on this
    corpus every observed pair carried IDENTICAL offsets -- both spellings
    matched the same runs of text, because the scan attributes a run once
    however many recorded forms match it. Unioning is what makes that an
    observation rather than an assumption.
    """
    keep_id = f"{entity}@{section}"
    keep = next((m for m in mentions if m["id"] == keep_id), None) or min(
        mentions, key=lambda m: m["id"]
    )
    offsets = sorted({o for m in mentions for o in (m["offsets"] or [])})
    dropped = 0
    for mention in mentions:
        if mention["id"] == keep["id"]:
            continue
        tx.run(
            """
            MATCH (loser:Mention {id:$loser}), (keep:Mention {id:$keep})
            CALL (loser, keep) {
              MATCH (loser)-[r:CO_OCCURS_WITH]->(far:Entity)
              MERGE (keep)-[:CO_OCCURS_WITH]->(far)
              DELETE r
              RETURN count(*) AS moved
            }
            CALL (loser, keep) {
              MATCH (loser)-[r:USES_ALIAS]->(a:Alias)
              MERGE (keep)-[:USES_ALIAS]->(a)
              DELETE r
              RETURN count(*) AS spellings
            }
            RETURN moved, spellings
            """,
            {"loser": mention["id"], "keep": keep["id"]},
        )
        tx.run("MATCH (m:Mention {id:$loser}) DETACH DELETE m", {"loser": mention["id"]})
        dropped += 1
    tx.run(
        "MATCH (m:Mention {id:$keep}) SET m.offsets = $offsets, m.occurrences = $n",
        {"keep": keep["id"], "offsets": offsets, "n": len(offsets)},
    )
    # A mention that co-occurs with its OWN entity is what folding can leave:
    # the two spellings were named in one sentence, and they are one place.
    tx.run(
        """
        MATCH (m:Mention {id:$keep})-[r:CO_OCCURS_WITH]->(e:Entity {id:$entity})
        DELETE r
        """,
        {"keep": keep["id"], "entity": entity},
    )
    return dropped


def _apply(tx, merge: Merge, plane: str) -> dict:
    """One group, one transaction.

    A half-merged group is not a state to leave a graph in: the loser's
    mentions would be gone and its node still there, which reads as a place the
    book never names.
    """
    tally = {"mentions": 0, "pairs": 0, "aliases": 0, "typed": 0}
    for loser in merge.losers:
        row = tx.run(_MOVE_FIXED, {"loser": loser, "survivor": merge.survivor}).single()
        if row:
            tally["mentions"] += row["mentions"]
            tally["pairs"] += row["pairs"]
            tally["aliases"] += row["aliases"]
        tally["typed"] += _move_typed(tx, loser, merge.survivor)

    tx.run(
        "MATCH (e:Entity {id:$survivor}) SET e.name = $name",
        {"survivor": merge.survivor, "name": merge.survivor_name},
    )
    # MERGE on `name`, which is what `alias_name` constrains. Keying on
    # (normalized, plane) instead tried to make a SECOND node for a spelling
    # that already had one and hit the constraint -- and it would have been
    # wrong even without the constraint, since most of these already exist:
    # every entity's own name is written as an alias, so a loser's name node is
    # usually already here and `_MOVE_FIXED` has just repointed it. What is
    # left for this loop is the spelling nobody recorded.
    for alias in merge.aliases:
        tx.run(
            """
            MATCH (survivor:Entity {id:$survivor})
            MERGE (a:Alias {name:$name})
              ON CREATE SET a.normalized = $normalized, a.plane = $plane
            MERGE (a)-[:ALIAS_OF]->(survivor)
            """,
            {
                "survivor": merge.survivor,
                "normalized": normalize_alias(alias),
                "name": alias,
                "plane": plane,
            },
        )
    for loser in merge.losers:
        tx.run("MATCH (e:Entity {id:$loser}) DETACH DELETE e", {"loser": loser})
    return tally


def _rescope(tx, old: str, new: str) -> int:
    """Move the survivor onto the id a fresh ingest would mint. Returns mentions
    renamed.

    THE MENTION IDS GO WITH IT. A mention's id is `<entity>@<section>` by
    construction, so leaving them behind would mean the next ingest minted a
    second mention for every pair this one already holds -- the repair quietly
    creating the duplicates it exists to remove.

    Called AFTER the doubled-mention fold, never before: two mentions of the
    two halves in one section become one id here, and `mention_id` is unique.
    """
    if tx.run("MATCH (e:Entity {id:$new}) RETURN e", {"new": new}).single():
        raise ValueError(f"{new} already exists; {old} cannot be renamed onto it")
    row = tx.run(
        """
        MATCH (e:Entity {id:$old}) SET e.id = $new
        WITH e
        OPTIONAL MATCH (e)<-[:REFERS_TO]-(m:Mention)-[:IN_SECTION]->(sec:Section)
        SET m.id = $new + '@' + sec.id
        RETURN count(m) AS mentions
        """,
        {"old": old, "new": new},
    ).single()
    return row["mentions"] if row else 0


def _fold_one(tx, entity: str, plane: str) -> int:
    """Fold this entity's doubled mentions, section by section."""
    rows = [
        dict(r)
        for r in tx.run(
            """
            MATCH (e:Entity {id:$entity})<-[:REFERS_TO]-(m:Mention)-[:IN_SECTION]->(sec:Section)
            WITH sec, collect(m) AS ms WHERE size(ms) > 1
            RETURN sec.id AS section, [x IN ms | {id: x.id, offsets: x.offsets}] AS mentions
            """,
            {"entity": entity},
        )
    ]
    return sum(_fold_mentions(tx, entity, r["section"], r["mentions"]) for r in rows)


def _apply_global(tx, merge: Merge, plane: str) -> dict:
    """One rescoped name, one transaction: fold, de-double, then rename."""
    tally = _apply(tx, merge, plane)
    tally["doubled"] = _fold_one(tx, merge.survivor, plane)
    tally["renamed"] = _rescope(tx, merge.survivor, merge.rescope_to)
    return tally


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually merge. Without it the plan is printed and nothing changes.",
    )
    parser.add_argument("--plane", default=CANON_PLANE)
    parser.add_argument(
        "--globals",
        metavar="BOOK",
        default="",
        help="Rescope this book's `global_names` instead of merging duplicates.",
    )
    args = parser.parse_args()

    if args.globals:
        _run_globals(args)
        return

    with read_only_session() as session:
        entities = [dict(r) for r in session.run(_ENTITIES, {"plane": args.plane})]
    merges = plan_merges(entities)

    print(f"{len(entities)} entities on the {args.plane} plane")
    print(
        f"{len(merges)} groups to fold, "
        f"{sum(len(m.losers) for m in merges)} nodes to remove\n"
    )
    for merge in merges:
        print(f"  {merge.survivor_name}  ->  {merge.survivor}")
        for loser in merge.losers:
            print(f"      fold in  {loser}")
        for alias in merge.aliases:
            print(f"      alias    {alias!r}")

    if not args.apply:
        print("\nNothing changed. Re-run with --apply to merge.")
        return

    totals = {"mentions": 0, "pairs": 0, "aliases": 0, "typed": 0}
    with neo4j_session() as session:
        for merge in merges:
            tally = session.execute_write(_apply, merge, args.plane)
            for key, value in tally.items():
                totals[key] += value

        # AFTER every entity merge, not inside one. A section can name two
        # halves of a duplicate, and the second mention only becomes a
        # duplicate once its entity has been folded.
        doubled = [
            dict(r) for r in session.run(_DOUBLED_MENTIONS, {"plane": args.plane})
        ]
        folded = 0
        for row in doubled:
            folded += session.execute_write(
                _fold_mentions, row["entity"], row["section"], row["mentions"]
            )

    print(
        f"\nmerged {len(merges)} groups: moved {totals['mentions']} mentions, "
        f"{totals['pairs']} co-occurrences, {totals['aliases']} aliases, "
        f"{totals['typed']} typed edges"
    )
    print(f"folded {folded} doubled mentions across {len(doubled)} sections")


def _run_globals(args) -> None:
    scheme = load_book(SEEDS / f"{args.globals}.yaml")
    with read_only_session() as session:
        entities = [
            dict(r)
            for r in session.run(
                _BOOK_ENTITIES, {"plane": args.plane, "prefix": scheme.prefix}
            )
        ]
    merges = plan_globals(entities, scheme)

    print(f"{len(entities)} {scheme.prefix} entities, {len(scheme.global_names)} names")
    print(f"the book calls book-wide; {len(merges)} to rescope\n")
    for merge in merges:
        print(f"  {merge.survivor_name}  ->  {merge.rescope_to}")
        print(f"      keep     {merge.survivor}")
        for loser in merge.losers:
            print(f"      fold in  {loser}")

    if not args.apply:
        print("\nNothing changed. Re-run with --apply to rescope.")
        return

    totals = {"mentions": 0, "typed": 0, "doubled": 0, "renamed": 0}
    with neo4j_session() as session:
        for merge in merges:
            tally = session.execute_write(_apply_global, merge, args.plane)
            for key in totals:
                totals[key] += tally.get(key, 0)
    print(
        f"\nrescoped {len(merges)} names: moved {totals['mentions']} mentions and "
        f"{totals['typed']} typed edges, folded {totals['doubled']} doubled "
        f"mentions, renamed {totals['renamed']} mention ids"
    )


if __name__ == "__main__":
    main()
