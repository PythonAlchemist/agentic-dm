"""Remove canon entities no section of the book names.

    uv run python -m backend.scripts.drop_unsupported --book kftgv          # plan
    uv run python -m backend.scripts.drop_unsupported --book kftgv --apply

THIS DELETES CANON, which nothing in this repository does casually, AND IT IS
NOT THE ANSWER TO THE SEVENTH INVARIANT. Read the next paragraph before running
it.

THE RULING THAT GOVERNS THIS SCRIPT. It was written to empty out the 154
entities that hold no mention, and the DM read the list and refused: most of
them are valuable. `Monodrones GUARDS Abacus Car` says something true about a
real train car; the node simply cannot cite prose for the word `Monodrones`,
because the book writes modrons in lowercase. Deleting it would destroy a fact
to tidy up a scan.

So "no section names it" is NOT a reason to run this. The standard repair is
`mark_unnamed`, which records the gap ON the node so a read can show it, and
the invariant is satisfied by that -- keeping such an entity is a decision the
graph states out loud. This script is for entities separately judged to be junk
on their own merits, one list at a time, by a person who has read them.

NOTHING RUNS IT AUTOMATICALLY, `--apply` is spelled out, and it has never been
run against the live graph.

WHAT THEY ARE. A mention is how an entity cites the prose that says it, so an
entity holding none can be traced to no word of the book -- while reading, in
`expand` and everything else that returns it, exactly like one that can. The
seventh invariant, `a canon entity is named by the book`, is this shape; this
script is its fix line.

THEY ARRIVED TWO WAYS AND ARE ONE DEFECT. Measured across both books, 154 of
2,213 canon entities:

  * THE EXTRACTOR NAMED A COMMON NOUN. `Spellbook`, `Cabinet`, `Note`,
    `Potion`, `Amethyst`, `Mimic` -- title-cased by the extractor, written by
    the book only in lowercase running prose. `mention_pattern` is
    case-sensitive for a single word on purpose (a capitalised word in prose is
    a proper noun, a lowercase one is not), so the scan correctly refuses to
    mint a mention and the node can never earn one.

  * THE EXTRACTOR DESCRIBED OR INVENTED A NAME. `Closet 1`, `Side Room 2`,
    eight spell scrolls named by pattern, `Painting by famous artist`,
    `Treasure in Sythian's Study`, `Potion of Far Realm Surprise`. These appear
    nowhere in their own chapter under any spelling.

144 of the 154 are `kftgv` and none of the `cos` ten are chapter-scoped, so
this is a property of how one book was extracted rather than of the design.

ONLY THE BOOK'S OWN PROSE ANSWERS, which is why the mentions here name a
plane. `rescan` scans a campaign section against the canon entities of the
books the table draws on, so the DM's own scene mints a CAMPAIGN-plane mention
on a CANON entity -- seven of them in the live graph. Without the plane this
would read "no section at all" while claiming to mean "no section of the book",
and a scene the DM wrote would quietly protect an entity from a list it belongs
on. It errs safe either way; it was still saying something it did not mean.

NO EDGE IS DROPPED SILENTLY, and the reason that matters is the ruling above: 70 of them carry canon edges -- `GUARDS`,
`CONTAINS`, `GAVE_QUEST` -- and every one is printed with the entity that held
it, because a claim removed without being named is one the DM cannot decide to
put back. What is lost, stated plainly: some of those edges point at a real
thing on the other end and say something true about it. They are lost here and
come back only through the review queue, which is the same trade
`drop_derived_placements` made.

IT WILL NOT DROP A NAME THE BOOK MIGHT STILL BE SAYING. `Gunther Arasek` holds
no mention and is entirely real: the book writes "Gunther and Yelena Arasek",
so his own name never appears as one run of text and the scan cannot match it.
So does `Anna Krezkova`, whose node dropped the feminine ending, and Davian
Martikov's daughter `Stefania`, whose surname the book never writes beside her.
Four of the ten `cos` rows are people, and dropping them would delete correct
canon to tidy up a scan.

They are told apart by the SAME SIGNAL THE SCANNER USES. `mention_pattern`
takes a capitalised single word in running prose as a proper noun and a
lowercase one as not; so a candidate whose name carries a distinctive
CAPITALISED word that its chapter actually prints is held back for review, and
one whose words the book only ever sets in lowercase -- `spellbook`, `cabinet`,
`potion` -- is the defect this drops. Held-back rows are not a smaller problem
than the dropped ones, only a different repair: they want an alias the scan can
match, which is what `propose_aliases` is for.

IT REFUSES ANYTHING A CAMPAIGN TOUCHES. There are none today -- measured at
zero campaign edges and zero campaign-plane neighbours -- and the check is here
anyway, because the one thing worse than a node the book never said is a
session's prep deleted to remove it.
"""

from __future__ import annotations

import argparse
import re
from collections import Counter

from backend.canon.writer import CANON_PLANE
from backend.core.database import neo4j_session, read_only_session

#: The invariant's shape, unlimited and answerable per book. `invariants.py`
#: states the rule and takes `LIMIT ROW_LIMIT` because it prints evidence a
#: person reads; a repair has to see all of them.
FIND = """
MATCH (e:Entity {plane:$plane})
WHERE NOT (e)<-[:REFERS_TO]-(:Mention {plane:$plane})
  AND ($prefix = '' OR e.id STARTS WITH $prefix)
OPTIONAL MATCH (e)-[r]-(o) WHERE NOT o:Alias
WITH e, collect({type: type(r), other: coalesce(o.name, o.id),
                 campaign: r.campaign, plane: o.plane}) AS rels
RETURN e.id AS id, e.name AS name,
       [l IN labels(e) WHERE l <> 'Entity'] AS kind,
       [x IN rels WHERE x.type IS NOT NULL] AS edges
ORDER BY e.id
"""

#: An alias node is keyed on its NAME and may serve more than one entity, so it
#: goes only when nothing else answers to it. Deleting it unconditionally would
#: take a spelling off an entity that is perfectly well attested.
PROSE = """
MATCH (c:Chapter)-[:HAS_SECTION]->(s:Section)
WHERE ($prefix = '' OR c.slug STARTS WITH $slug OR s.id STARTS WITH $prefix)
RETURN c.slug AS chapter, collect(s.text) AS texts
"""

DROP_ALIASES = """
MATCH (a:Alias)-[:ALIAS_OF]->(e:Entity {id:$id, plane:$plane})
WHERE NOT EXISTS {
    MATCH (a)-[:ALIAS_OF]->(other:Entity) WHERE other.id <> $id
}
DETACH DELETE a
RETURN count(*) AS dropped
"""

DROP_ENTITY = """
MATCH (e:Entity {id:$id, plane:$plane})
WHERE NOT (e)<-[:REFERS_TO]-(:Mention {plane:$plane})
DETACH DELETE e
RETURN count(*) AS dropped
"""


#: Words that carry no identity, so their presence in a chapter says nothing
#: about whether the book names the thing. Kept short deliberately: the test is
#: already conservative, and every word added to it drops a real signal.
_EMPTY_WORDS = frozenset(
    "the a an of in on at to and or for by with from area room".split()
)


def _distinctive(name: str) -> list[str]:
    """The words of a name that could identify it, longest first."""
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z'’-]+", name or "")
             if len(w) > 3 and w.lower() not in _EMPTY_WORDS]
    return sorted(set(words), key=len, reverse=True)


def _book_may_name_it(name: str, prose: str) -> str:
    """The capitalised word of `name` that `prose` prints, or `""`.

    CASE-SENSITIVE AND WHOLE-WORD, because that is the inference
    `spine.mention_pattern` makes and this has to agree with it: a capitalised
    word in running prose is a proper noun and the book is naming something; a
    lowercase one is a common noun and it is not.
    """
    for word in _distinctive(name):
        if not word[:1].isupper():
            continue
        if re.search(rf"(?<![A-Za-z]){re.escape(word)}(?![A-Za-z])", prose):
            return word
    return ""


def _held_by_a_campaign(row: dict) -> bool:
    """True when any edge names a campaign or reaches a campaign-plane node."""
    return any(
        e.get("campaign") is not None or e.get("plane") == "campaign"
        for e in row["edges"]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--book", default="", help="Book slug, e.g. kftgv. "
                        "Omitted means every book.")
    parser.add_argument("--plane", default=CANON_PLANE)
    parser.add_argument("--apply", action="store_true",
                        help="Without this nothing is written.")
    args = parser.parse_args()

    prefix = f"{args.book}:" if args.book else ""
    with read_only_session() as session:
        rows = [dict(r) for r in session.run(
            FIND, {"plane": args.plane, "prefix": prefix})]

    with read_only_session() as session:
        prose = {r["chapter"]: " ".join(t or "" for t in r["texts"])
                 for r in session.run(PROSE, {"prefix": prefix,
                                              "slug": args.book})}
    everything = " ".join(prose.values())

    def _prose_for(entity_id: str) -> str:
        """A chapter-scoped id is judged against its own chapter; anything else
        against the whole book, which is the same reach `scannable_here` gives
        the scan when it decides where to look for the name."""
        parts = entity_id.split(":")
        return prose.get(parts[1], everything) if len(parts) > 2 else everything

    keep = [r for r in rows if _held_by_a_campaign(r)]
    rest = [r for r in rows if not _held_by_a_campaign(r)]
    for row in rest:
        row["said"] = _book_may_name_it(row["name"], _prose_for(row["id"]))
    review = [r for r in rest if r["said"]]
    drop = [r for r in rest if not r["said"]]

    where = args.book or "every book"
    print(f"{len(rows)} canon entities in {where} that no section names")
    if keep:
        print(f"  {len(keep)} REFUSED -- a campaign hangs off them:")
        for row in keep:
            print(f"    {row['name']!r}  {row['id']}")
    if review:
        print(f"  {len(review)} HELD BACK -- their chapter prints a capitalised "
              "word of the name, so the book may be saying it another way.")
        print("     These want an alias the scan can match, not a delete:")
        for row in review:
            print(f"       {row['name']!r}  -- the book prints {row['said']!r}")
    if not drop:
        print("  nothing to drop.")
        return 0

    kinds = Counter(r["kind"][0] if r["kind"] else "-" for r in drop)
    edges = Counter(e["type"] for r in drop for e in r["edges"])
    print(f"  {len(drop)} to drop: " +
          ", ".join(f"{n} {k}" for k, n in kinds.most_common()))
    print(f"  carrying {sum(edges.values())} edges: " +
          (", ".join(f"{n} {t}" for t, n in edges.most_common()) or "none"))
    print()

    for row in drop:
        kind = row["kind"][0] if row["kind"] else "-"
        print(f"  {kind:9} {row['name']!r}")
        # EVERY EDGE BY NAME. A claim removed without being named is one the DM
        # cannot decide to put back.
        for edge in row["edges"]:
            print(f"            {edge['type']} -- {edge['other']!r}")

    if not args.apply:
        print(f"\n  Nothing was written. {len(drop)} entities and "
              f"{sum(edges.values())} edges would go. Re-run with --apply.")
        return 0

    gone = aliases = 0
    with neo4j_session() as session:
        for row in drop:
            params = {"id": row["id"], "plane": args.plane}
            aliases += session.run(DROP_ALIASES, params).single()["dropped"]
            # The mention-less clause is repeated here rather than trusted from
            # the read above: the read and the write are two transactions, and
            # an entity that earned a mention in between is no longer this.
            gone += session.run(DROP_ENTITY, params).single()["dropped"]

    print(f"\n  dropped {gone} entities and {aliases} aliases")
    if gone != len(drop):
        print(f"  {len(drop) - gone} were left: they gained a mention "
              "between the read and the write, and are no longer unsupported")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
