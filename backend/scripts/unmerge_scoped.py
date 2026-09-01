"""Give back the rooms an alias merge took across adventure lines.

    uv run python -m backend.scripts.unmerge_scoped              # plan, keyed only
    uv run python -m backend.scripts.unmerge_scoped --apply
    uv run python -m backend.scripts.unmerge_scoped --unkeyed     # every scope violation
    uv run python -m backend.scripts.unmerge_scoped --unkeyed \
        --label kftgv:heart-of-ashes:mage-s-guild=FACTION --apply


`Prison Tower` in Fire and Darkness holds four mentions in Heart of Ashes,
every one of them spelled `Mage Tower`. The anthology rule says a keyed room is
scannable only inside its own chapter, so the scan cannot have put them there:
an alias group spanning two adventures did, and the entity that should have
kept them stopped existing.

SPLIT, NOT DELETE. The foreign mentions are real textual facts -- Heart of Ashes
really does write `Mage Tower` -- about a room that was merged away. Deleting
them would lose the fact; this recreates the room in its own chapter and gives
its mentions back.

THE SURFACE IS THE NAME. Each foreign group spells itself consistently, and
that spelling is what the vanished entity was called: `Prison Tower` held
`Mage Tower` in one chapter and `Vault Tower` in another, and those are two
different towers.

RUN `audit_scope` FIRST. By default this handles only the KEYED rooms, which
need no judgement on the book's own terms: it keys rooms per adventure, so
`C10` in one heist and `C10` in another are different rooms and a foreign
mention of one is always a bad merge.

`--unkeyed` TAKES THE REST, and it is a DM's ruling that makes that safe rather
than anything in the text. Asked whether a stone golem guarding Paliset Hall
and one in Fire and Darkness are one monster or two, the answer was two -- the
same answer `kftgv.yaml` already records for loot ("two piles of amethysts are
two piles"), extended to creatures and gear. With that settled, every row
`audit_scope` reports is a per-adventure instance and none of them is a
judgement call any more. A name the book really does use book-wide is not
reachable from here: `global_names` rescopes those to two-segment ids, which
carry no chapter and so never appear as a violation.

THE LABEL IS INHERITED AND SOMETIMES WRONG, so `--label <new-id>=<LABEL>`
overrides it. The new node copies the label of the entity it is being pulled
out of, which is right whenever the merge folded two things of a kind and wrong
whenever it did not: `Erinyes Statuette` is an ITEM and `Erinyes Barracks` is a
room, `Guild Task Force` is an EVENT and `Mage's Guild` is a FACTION. Three of
nineteen needed correcting by hand on the run this was written for, which is
three too many to leave to whoever reads the output next. Take the id from the
dry run, which prints it.

IT MOVES BY SCOPE, NOT BY NAME, which is why it reaches cases `split_entity`
cannot. That script separates two things by what the section calls them, and
gives up when the source already carries the foreign spelling as an alias --
eight of these did, because `apply_aliases` folded it on. Which chapter a
mention sits in is not a matter of spelling at all.

AND FIX THE SEED AFTERWARDS. `data/aliases/<book>.yaml` still holds the group
that caused the merge. `apply_aliases` now refuses a group spanning adventures,
so re-applying will not redo the damage -- but only once the swallowed entities
exist again, which is what this puts back.
"""
import re
import sys

from backend.canon.assembler import slugify
from backend.graph.schema import EntityType
from backend.core.database import neo4j_session, read_only_session

KEYED = re.compile(r"^[a-z]{1,2}\d+[a-z]?-")

FOREIGN = """
MATCH (m:Mention {plane:'canon'})-[:REFERS_TO]->(e:Entity {plane:'canon'})
MATCH (m)-[:IN_SECTION]->(sec:Section)
MATCH (c:Chapter)-[:HAS_SECTION]->(sec)
WITH e, c.slug AS found, collect(DISTINCT m.display_name) AS surfaces,
     collect(m.id) AS mentions,
     CASE WHEN size(split(e.id,':')) > 2 THEN split(e.id,':')[1] ELSE '' END AS scope
WHERE scope <> '' AND found <> scope
RETURN e.id AS source, e.name AS name,
       [l IN labels(e) WHERE l <> 'Entity'][0] AS label,
       scope, found, surfaces, mentions
ORDER BY e.id, found
"""

def wanted(source_id: str, *, unkeyed: bool) -> bool:
    """Whether this violation is one this script will act on.

    The keyed test reads the ENTITY's id, where `c10-` marks a room the book
    numbered. `--unkeyed` drops the test entirely rather than widening it,
    because what makes the rest safe is the DM's ruling, not a better regex.
    """
    return unkeyed or bool(KEYED.match(source_id.rsplit(":", 1)[-1]))


def plan_groups(groups: list[dict]) -> tuple[list[dict], list[str]]:
    """`(plan, skipped)` -- pure, so a run can be printed without a session."""
    plan, skipped = [], []
    for g in groups:
        surfaces = [x for x in g["surfaces"] if x]
        if not surfaces:
            skipped.append(f"{g['name']} -> {g['found']}: no surface to name it by")
            continue
        # The longest spelling, which is the most specific thing the section
        # called it. `Private Room` and `Private Rooms` are one room said twice.
        name = max(surfaces, key=len)
        book = g["source"].split(":", 1)[0]
        plan.append({**g, "new_name": name,
                     "new_id": f"{book}:{g['found']}:{slugify(name)}"})
    return plan, skipped


def write(tx, p):
    tx.run(
        f"""
        MATCH (src:Entity {{id:$source}})
        MERGE (e:Entity {{id:$new}})
        ON CREATE SET e.name = $name, e.plane = src.plane, e.status = src.status,
                      e.chapter_slug = $chapter
        SET e:{p['label']}
        """,
        {"source": p["source"], "new": p["new_id"], "name": p["new_name"],
         "chapter": p["found"]},
    )
    tx.run(
        """
        MATCH (e:Entity {id:$new})
        MERGE (a:Alias {name:$name})
        ON CREATE SET a.normalized = $normalized, a.plane = 'canon'
        MERGE (a)-[:ALIAS_OF]->(e)
        """,
        {"new": p["new_id"], "name": p["new_name"],
         "normalized": p["new_name"].casefold()},
    )
    # THE TARGET ID MAY BE TAKEN, and a rename is only safe while it is free --
    # the same guard `merge_duplicates` states. It happens whenever the entity
    # being given back already exists and already holds a mention in the very
    # section this one is moving to: `split_entity` had already made
    # `Braith Broadfoot`, so repointing the last `Mayor Broadfoot` collided on
    # `...braith-broadfoot@...#4` and the uniqueness constraint aborted the run.
    #
    # A collision is not an error, it is a DUPLICATE OF ONE PAIR. `mention_id`
    # is `<entity>@<section>` by construction, so two mentions wanting one id
    # are two spellings of the same entity in the same section -- which is a
    # single mention with two offsets. So the offsets are carried over and the
    # spare goes, which is what `merge_duplicates` calls folding.
    taken = {
        r["mid"]: r["wanted"]
        for r in tx.run(
            """
            MATCH (m:Mention) WHERE m.id IN $mentions
            WITH m, $new + '@' + split(m.id, '@')[1] AS wanted
            MATCH (:Mention {id: wanted})
            RETURN m.id AS mid, wanted AS wanted
            """,
            {"new": p["new_id"], "mentions": p["mentions"]},
        )
    }
    free = [m for m in p["mentions"] if m not in taken]

    moved = tx.run(
        """
        MATCH (m:Mention)-[r:REFERS_TO]->(:Entity {id:$source})
        WHERE m.id IN $mentions
        MATCH (e:Entity {id:$new})
        DELETE r
        MERGE (m)-[:REFERS_TO]->(e)
        SET m.id = $new + '@' + split(m.id, '@')[1]
        RETURN count(m) AS n
        """,
        {"source": p["source"], "new": p["new_id"], "mentions": free},
    ).single()["n"] if free else 0

    folded = 0
    for mid, wanted in taken.items():
        folded += tx.run(
            """
            MATCH (m:Mention {id:$mid}), (t:Mention {id:$wanted})
            SET t.offsets = coalesce(t.offsets, []) +
                    [x IN coalesce(m.offsets, []) WHERE NOT x IN coalesce(t.offsets, [])]
            SET t.occurrences = size(t.offsets)
            DETACH DELETE m
            RETURN count(t) AS n
            """,
            {"mid": mid, "wanted": wanted},
        ).single()["n"]
    return {"moved": moved, "folded": folded}

def label_overrides(argv: list[str]) -> dict[str, str]:
    """`{new_id: LABEL}` from repeated `--label id=LABEL`.

    CHECKED AGAINST `EntityType`, because a typo would otherwise become a label
    no query looks for -- the node would exist, hold its mentions, and be
    invisible to every read that asks for a kind.
    """
    found: dict[str, str] = {}
    for i, arg in enumerate(argv):
        if arg != "--label":
            continue
        if i + 1 >= len(argv) or "=" not in argv[i + 1]:
            raise SystemExit("--label wants <new-id>=<LABEL>")
        entity_id, _, label = argv[i + 1].partition("=")
        try:
            EntityType(label)
        except ValueError:
            raise SystemExit(
                f"{label!r} is not a type this graph uses: "
                + ", ".join(sorted(t.value for t in EntityType))
            ) from None
        found[entity_id] = label
    return found


def main() -> int:
    unkeyed = "--unkeyed" in sys.argv
    apply_it = "--apply" in sys.argv
    overrides = label_overrides(sys.argv)
    with read_only_session() as session:
        groups = [dict(r) for r in session.run(FOREIGN)
                  if wanted(r["source"], unkeyed=unkeyed)]
    plan, skipped = plan_groups(groups)
    for p in plan:
        p["label"] = overrides.get(p["new_id"], p["label"])
    unused = sorted(set(overrides) - {p["new_id"] for p in plan})
    for entity_id in unused:
        print(f"  WARNING --label {entity_id} matches nothing in this plan")
    for line in skipped:
        print(f"  SKIP {line}")
    what = "violations" if unkeyed else "rooms"
    print(f"  {len(plan)} {what} to give back\n")
    for p in plan:
        print(f"    {p['name']}  ({p['scope']})")
        print(f"      -> {p['new_name']!r} as {p['new_id']}  [{p['label']}]  "
              f"{len(p['mentions'])} mention(s)")
    if not apply_it:
        print("\n  dry run: nothing written. Re-run with --apply.")
        return 0
    moved = folded = failed = 0
    with neo4j_session() as session:
        for p in plan:
            # ONE FAILURE IS NOT ALL OF THEM. The first version aborted the
            # whole run on the first collision, leaving one row applied and
            # eighteen not -- a half-done state nothing reported.
            try:
                counts = session.execute_write(lambda tx, p=p: write(tx, p))
            except Exception as exc:  # noqa: BLE001 -- reported, not swallowed
                failed += 1
                print(f"    FAILED {p['name']} -> {p['new_id']}: {exc}")
                continue
            moved += counts["moved"]
            folded += counts["folded"]
    print(f"\n  gave back {len(plan) - failed} {what}, {moved} mentions repointed"
          + (f", {folded} folded into a mention that already existed" if folded else "")
          + (f", {failed} FAILED" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
