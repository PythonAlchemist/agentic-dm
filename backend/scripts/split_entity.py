"""Pull one entity back out of another it was wrongly merged into.

    uv run python -m backend.scripts.split_entity \
        --from kftgv:prisoner-13:axebreaker-dwarves \
        --name "Varrin Axebreaker" --label NPC \
        --aliases Varrin --aliases "Varrin Axebreaker" \
        --relate MEMBER_OF --move-edge GAVE_QUEST                 # plan
    uv run python -m backend.scripts.split_entity ... --apply

THE INVERSE OF `merge_duplicates`, AND THE REASON IT HAS TO EXIST. That script
folds two nodes together and the survivor keeps the loser's aliases; when the
fold was wrong there is nothing left to un-fold, because the node that should
have survived is gone. `Varrin`, `Varrin Axebreaker`, `Clan Axebreaker` and
`Axebreaker dwarves` reached the coreference model in one block and came back
as one thing, so the dwarf who hires the party became his own clan: seven
mentions of a person filed under a faction, and asking the graph about Varrin
answered with the clan.

WHY NOT JUST RE-WRITE THE CHAPTER. That is the honest repair and it is refused,
correctly: `write_canon --replace` will not delete canon nodes while campaign
data hangs off them, and forcing past it re-seeds the running order -- which
destroys every insertion, skip and move the DM made in it. Trading a table's
session prep for one alias is not a trade. This deletes only the mentions that
were mis-attributed.

IT READS THE SECTION TEXT, NOT `display_name`. A mention is one node per
(entity, section), so a section naming both the man and the clan kept only one
of the two spellings -- and four of the twelve did exactly that. Deciding from
the stored spelling would have moved seven sections and left four behind.
A SECTION THAT NAMES BOTH KEEPS BOTH: the person gains a mention there, and
the clan does not lose the one it already had.

DRY-RUN IS THE DEFAULT and `--apply` is spelled out, as in `merge_duplicates`.
This one deletes less than that one does, but it deletes.

`--move-edge` IS NOT OPTIONAL POLISH, and leaving it out the first time made
this tool ship half-finished. Aliases and mentions say what a node is CALLED
and where it is NAMED; the typed edges say what it DOES, and a merge folded
those in too. Varrin resolved to a person and still did not hire anybody,
because `GAVE_QUEST` was left on the clan -- and "who hires the party" is the
first question a DM asks about a heist.

WHICH EDGES MOVE IS A HUMAN'S CALL, by type, and that is the point. Nothing
here can read a book and know whether the clan or the dwarf hires the party.
The convention this repo already keeps -- a model proposes, a human reads, a
script applies -- puts that decision on the command line rather than in a
heuristic.

WHAT IT DOES NOT DO: fix the seed. `data/aliases/<book>.yaml` still carries the
grouping that caused the merge, and re-applying it would undo this. Correct the
seed first; `coreference._partition` keeps the next proposal from making the
same one, by never offering a FACTION in the same block as anything else.
"""

from __future__ import annotations

import argparse
import re
import sys

from backend.canon.assembler import slugify
from backend.core.database import neo4j_session, read_only_session
from backend.graph.schema import LAYER_MAP, RelationshipType

#: The source's typed edges, read out before any are moved. Neo4j cannot
#: parameterise a relationship type, so the type reaches the query as text --
#: and it is checked against `RelationshipType` first, so what is interpolated
#: is a member of a fixed enum rather than a string out of the database.
_TYPED_EDGES = """
MATCH (src:Entity {id:$source})-[r]->(far:Entity)
WHERE type(r) IN $types
RETURN type(r) AS rel_type, properties(r) AS props, far.id AS far, 'out' AS direction
UNION
MATCH (far:Entity)-[r]->(src:Entity {id:$source})
WHERE type(r) IN $types
RETURN type(r) AS rel_type, properties(r) AS props, far.id AS far, 'in' AS direction
"""

_MENTIONS = """
MATCH (m:Mention)-[:REFERS_TO]->(:Entity {id:$source})
MATCH (m)-[:IN_SECTION]->(sec:Section)
RETURN m.id AS mid, properties(m) AS props, sec.id AS sec, sec.text AS text
ORDER BY sec.id
"""


def names_present(text: str, surfaces: list[str], kept: list[str]) -> tuple[bool, bool]:
    """Which side's names this text actually uses, longest name winning.

    LONGEST MATCH FIRST, because a plain substring test makes a short name
    match inside a long one. `Xeluan` is contained in `Order of Xeluan` and in
    `Shard of Xeluan`, so splitting the giant out of his own order claimed all
    twenty of the order's sections -- including the ones that only ever write
    the order's name. Both sides are matched against ONE scan of the text with
    the longer name taking the position, so a name is only credited where no
    longer name already covers it.
    """
    ordered = sorted(
        [(s, True) for s in surfaces] + [(k, False) for k in kept],
        key=lambda pair: -len(pair[0]),
    )
    if not ordered:
        return False, False
    lookup = {s.casefold(): mine for s, mine in ordered}
    pattern = re.compile(
        "|".join(re.escape(s) for s, _ in ordered), re.IGNORECASE
    )
    mine = theirs = False
    for match in pattern.finditer(text or ""):
        if lookup.get(match.group(0).casefold(), False):
            mine = True
        else:
            theirs = True
    return mine, theirs


def plan(rows: list[dict], surfaces: list[str], kept: list[str]) -> dict:
    """Which sections name the thing being split out, which name what is left.

    `kept` is what the ORIGINAL entity still answers to. A section naming
    neither is left alone rather than guessed at -- it is a mention some other
    spelling put there, and this pass has no opinion about it.
    """
    out: dict[str, list[dict]] = {"moves": [], "stays": [], "both": [], "neither": []}
    for row in rows:
        mine, theirs = names_present(row["text"] or "", surfaces, kept)
        key = ("both" if mine and theirs
               else "moves" if mine
               else "stays" if theirs else "neither")
        out[key].append(row)
    return out


def _write(tx, args, grouped: dict, edges: list[dict]) -> tuple[int, int, int]:
    tx.run(
        """
        MATCH (src:Entity {id:$source})
        MERGE (e:Entity {id:$new})
        ON CREATE SET e.name = $name, e.plane = src.plane,
                      e.chapter_slug = src.chapter_slug, e.status = src.status
        """,
        {"source": args.source, "new": args.new_id, "name": args.name},
    )
    # THE LABEL IS INTERPOLATED, so it is checked against the enum first and
    # what reaches the query is a member of a fixed set rather than a string
    # that came off the command line.
    tx.run(f"MATCH (e:Entity {{id:$new}}) SET e:{args.label}", {"new": args.new_id})
    for alias in args.aliases:
        tx.run(
            """
            MATCH (a:Alias {name:$alias})-[r:ALIAS_OF]->(:Entity {id:$source})
            MATCH (e:Entity {id:$new})
            DELETE r
            MERGE (a)-[:ALIAS_OF]->(e)
            """,
            {"alias": alias, "source": args.source, "new": args.new_id},
        )
    created = 0
    for row in grouped["moves"] + grouped["both"]:
        tx.run(
            """
            MATCH (e:Entity {id:$new}), (sec:Section {id:$sec})
            MERGE (m:Mention {id:$mid})
            SET m += $props, m.id = $mid, m.display_name = $name
            MERGE (m)-[:REFERS_TO]->(e)
            MERGE (m)-[:IN_SECTION]->(sec)
            """,
            {
                "new": args.new_id, "sec": row["sec"], "name": args.name,
                # `id` and `display_name` are set explicitly above; carrying the
                # source's would name the new mention after the old entity.
                "mid": f"{args.new_id}@{row['sec']}",
                "props": {k: v for k, v in row["props"].items()
                          if k not in ("id", "display_name")},
            },
        )
        created += 1
    removed = 0
    for row in grouped["moves"]:
        removed += tx.run(
            "MATCH (m:Mention {id:$mid}) DETACH DELETE m RETURN count(m) AS n",
            {"mid": row["mid"]},
        ).single()["n"]
    moved = 0
    for row in edges:
        # A SELF-EDGE IS DROPPED, NOT MOVED, as in `merge_duplicates`. An edge
        # already joining the two of them would become the new entity pointing
        # at itself.
        if row["far"] in (args.new_id, args.source):
            continue
        rel = RelationshipType(row["rel_type"])
        pattern = ("(e)-[new:%s]->(f)" if row["direction"] == "out"
                   else "(f)-[new:%s]->(e)") % rel.value
        tx.run(
            f"""
            MATCH (e:Entity {{id:$new}}), (f:Entity {{id:$far}})
            MERGE {pattern}
            SET new += $props
            """,
            {"new": args.new_id, "far": row["far"], "props": row["props"]},
        )
        # DELETED FROM THE SOURCE, not left beside the copy. A split that only
        # copied would leave the clan still hiring the party.
        direction = ("(src)-[r:%s]->(f)" if row["direction"] == "out"
                     else "(f)-[r:%s]->(src)") % rel.value
        tx.run(
            f"MATCH (src:Entity {{id:$source}}), (f:Entity {{id:$far}}) "
            f"MATCH {direction} DELETE r",
            {"source": args.source, "far": row["far"]},
        )
        moved += 1
    if args.relate:
        layer = LAYER_MAP.get(RelationshipType(args.relate))
        tx.run(
            f"""
            MATCH (e:Entity {{id:$new}}), (src:Entity {{id:$source}})
            MERGE (e)-[r:{args.relate}]->(src)
            ON CREATE SET r.plane = src.plane, r.chapter_slug = src.chapter_slug,
                          r.status = 'proposed', r.layer = $layer
            """,
            {"new": args.new_id, "source": args.source,
             "layer": layer.value if layer else ""},
        )
    return created, removed, moved


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="source", required=True,
                        help="Entity id the merge left everything in")
    parser.add_argument("--name", required=True, help="Name of the entity being pulled out")
    parser.add_argument("--id", dest="new_id", default="",
                        help="Id for it. Defaults to the source's prefix plus a slug of --name.")
    parser.add_argument("--label", required=True,
                        help="Its type: NPC, FACTION, LOCATION, ITEM, ...")
    parser.add_argument("--aliases", action="append", default=[],
                        help="A spelling that belongs to it, not the source. Repeatable.")
    parser.add_argument("--relate", default="",
                        help="Relationship to write from the new entity back to the source, "
                             "e.g. MEMBER_OF. Written `proposed`, like any derived edge.")
    parser.add_argument("--move-edge", action="append", default=[], metavar="TYPE",
                        help="Move the source's edges of this type to the new entity, "
                             "in both directions and with their properties. Repeatable. "
                             "Which edges belong to which is a human's call, not a "
                             "heuristic's.")
    parser.add_argument("--apply", action="store_true",
                        help="Actually split. Without it the plan is printed and nothing changes.")
    args = parser.parse_args()

    for rel in ([args.relate] if args.relate else []) + args.move_edge:
        try:
            RelationshipType(rel)
        except ValueError:
            sys.exit(f"{rel} is not a relationship this graph writes")
    if not args.new_id:
        # THE BOOK'S OWN SLUGIFY, not a local one. Splitting on whitespace left
        # the apostrophe in `wylie-van-timmel's-lyre`, which is an id no other
        # part of this graph could have minted.
        args.new_id = args.source.rsplit(":", 1)[0] + ":" + slugify(args.name)
    surfaces = args.aliases or [args.name]

    with read_only_session() as session:
        rows = [dict(r) for r in session.run(_MENTIONS, {"source": args.source})]
        edges = [
            dict(r)
            for r in session.run(
                _TYPED_EDGES, {"source": args.source, "types": args.move_edge}
            )
        ] if args.move_edge else []
        kept = [
            r["name"]
            for r in session.run(
                "MATCH (a:Alias)-[:ALIAS_OF]->(:Entity {id:$source}) RETURN a.name AS name",
                {"source": args.source},
            )
            if r["name"] not in surfaces
        ]
    if not rows:
        sys.exit(f"no mentions on {args.source} -- is that the right id?")

    grouped = plan(rows, surfaces, kept)
    print(f"  {args.source}")
    print(f"    still answers to: {kept}")
    print(f"  -> {args.new_id}  ({args.label})")
    print(f"    takes: {surfaces}")
    for key, label in (("moves", "sections naming only the new one"),
                       ("both", "naming both (the new one gains, the source keeps)"),
                       ("stays", "naming only the source"),
                       ("neither", "naming neither -- left alone")):
        rows_ = grouped[key]
        print(f"    {label:52} {len(rows_):3}  "
              f"{[r['sec'].split('#')[-1] for r in rows_]}")
    print(f"    mentions to create: {len(grouped['moves']) + len(grouped['both'])}, "
          f"to remove from the source: {len(grouped['moves'])}")
    for row in edges:
        arrow = "->" if row["direction"] == "out" else "<-"
        print(f"    moves edge: ({args.name}) -[{row['rel_type']}]{arrow} {row['far']}")
    if args.move_edge and not edges:
        print(f"    moves edge: none of type {args.move_edge} on the source")
    if args.relate:
        print(f"    edge: ({args.name}) -[{args.relate}]-> (the source), proposed")
    if not args.apply:
        print("\n  dry run: nothing written. Re-run with --apply.")
        return

    with neo4j_session() as session:
        created, removed, moved = session.execute_write(
            lambda tx: _write(tx, args, grouped, edges)
        )
    print(f"\n  wrote {args.name}: {created} mentions created, {removed} removed, "
          f"{moved} edges moved")


if __name__ == "__main__":
    main()
