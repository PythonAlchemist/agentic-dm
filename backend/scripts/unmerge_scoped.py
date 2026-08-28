"""Give back the rooms an alias merge took across adventure lines.

    uv run python -m backend.scripts.unmerge_scoped              # plan
    uv run python -m backend.scripts.unmerge_scoped --apply


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

RUN `audit_scope` FIRST. This handles only the KEYED rooms, which are the
cases that need no judgement -- the book keys rooms per adventure, so `C10` in
one heist and `C10` in another are different rooms and a foreign mention of one
is always a bad merge. The rest of what the audit reports is a decision about
whether a name is genuinely book-wide, and this script has no opinion about it.

AND FIX THE SEED AFTERWARDS. `data/aliases/<book>.yaml` still holds the group
that caused the merge. `apply_aliases` now refuses a group spanning adventures,
so re-applying will not redo the damage -- but only once the swallowed entities
exist again, which is what this puts back.
"""
import re
import sys

from backend.canon.assembler import slugify
from backend.core.database import neo4j_session, read_only_session

APPLY = "--apply" in sys.argv
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

with read_only_session() as s:
    groups = [
        dict(r) for r in s.run(FOREIGN)
        if KEYED.match(r["source"].rsplit(":", 1)[-1])
    ]

plan = []
for g in groups:
    surfaces = [x for x in g["surfaces"] if x]
    if not surfaces:
        print(f"  SKIP {g['name']} -> {g['found']}: no surface to name it by")
        continue
    # The longest spelling, which is the most specific thing the section called
    # it. `Private Room` and `Private Rooms` are one room said twice.
    name = max(surfaces, key=len)
    book = g["source"].split(":", 1)[0]
    plan.append({**g, "new_name": name,
                 "new_id": f"{book}:{g['found']}:{slugify(name)}"})

print(f"  {len(plan)} rooms to give back\n")
for p in plan:
    print(f"    {p['name']}  ({p['scope']})")
    print(f"      -> {p['new_name']!r} as {p['new_id']}  [{p['label']}]  "
          f"{len(p['mentions'])} mention(s)")
if not APPLY:
    print("\n  dry run: nothing written. Re-run with --apply.")
    raise SystemExit(0)

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
    # REPOINT, not recreate: the mention keeps its offsets and occurrences,
    # which are facts about the section and unaffected by whose room it is.
    return tx.run(
        """
        MATCH (m:Mention)-[r:REFERS_TO]->(:Entity {id:$source})
        WHERE m.id IN $mentions
        MATCH (e:Entity {id:$new})
        DELETE r
        MERGE (m)-[:REFERS_TO]->(e)
        SET m.id = $new + '@' + split(m.id, '@')[1]
        RETURN count(m) AS n
        """,
        {"source": p["source"], "new": p["new_id"], "mentions": p["mentions"]},
    ).single()["n"]

with neo4j_session() as s:
    moved = sum(s.execute_write(lambda tx, p=p: write(tx, p)) for p in plan)
print(f"\n  gave back {len(plan)} rooms, {moved} mentions repointed")
