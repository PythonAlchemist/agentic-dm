"""The one place that decides what a player may see.

DEFAULT DENY, POSITIVE GRANTS. A player sees nothing until a DM says so. The
alternative -- everything except what is marked secret -- fails the first time
somebody writes a scene and forgets, and the failure is unrecoverable: an
accidental reveal at the table cannot be taken back, while an accidental
concealment costs one click. The asymmetry decides the default, exactly as it
does for a pin on a map.

ONE CHOKE POINT. Every read a player can reach comes through this module, and
the module offers no way to ask for somebody else's view. A route does not
compute visibility; it calls `entity_for` or `section_for` with the reader the
gate identified, and gets back what that person may have.

THE FILTER IS IN THE PATTERN, NEVER APPLIED AFTERWARDS. The player queries are
anchored on the `REVEALED` edge, so an unrevealed thing is not fetched and
discarded -- it is never selected. A filter applied after a read is one
refactor, one early return, one `if debug` away from being skipped, and the
skip looks like nothing at all until a player reads a twist off their screen.

AND THE SAME RULE POINTED AT THE MODEL. `visible_ids` exists so generation can
be SEEDED with the revealed closure rather than filtered after the fact. A
model that was given the secret and asked not to mention it has already been
given the secret: it will shape the prose around it, decline in a way that
confirms it, or leak it under mild rephrasing. There is no post-filter that
undoes having been told.

TWO GRANTS, ONE MECHANISM. Revealing an ENTITY says "you know this exists".
Revealing a SECTION says "you have read or heard this". They are separate on
purpose: a party can know Strahd exists for ten sessions before they may read
what the book says about him, and collapsing the two would make every reveal
hand over every passage at once.

AND ONE THING NOBODY HAS TO GRANT: A RULEBOOK. A player owns the Player's
Handbook. Making a DM reveal `Fireball` to their own party is a rule whose only
effect is busywork, and a product that hid the rules from the people playing by
them would be wrong about what a secret is.

THE MARK IS ON THE BOOK, NOT ON THE ENTITY. `:Book {reference: true}` says
"this is a rulebook rather than an adventure", and everything carrying its
prefix is public by that fact. One property on one node makes a whole book's
spells, classes and conditions readable, and loading a new rulebook needs no
per-entity migration -- the same leverage the book prefix already gives the
mention scan.

SET TRUE ONLY, NEVER FALSE, the discipline `NAMED_BY_BOOK` records: an
adventure needs no property to say it is one, and a second place recording the
same fact is a second place for it to be wrong.

NOTHING IN THIS GRAPH IS PUBLIC TODAY. Both books loaded are adventures, so the
clause below matches nothing and every read still falls to the grant. That is
the correct state, not a stub: the mechanism is what a rulebook needs to exist
in here, and until one is loaded there is no common material to show.
"""

from __future__ import annotations

from backend.campaign import roles

DM = roles.DM
PLAYER = roles.PLAYER

#: Public because it comes from a rulebook.
#:
#: DERIVED IN THE QUERY, NOT PASSED IN. An earlier draft took the prefixes as a
#: parameter, which is an argument a caller could get wrong -- and getting it
#: wrong in the widening direction (`['']`, since every id starts with the empty
#: string) would make the whole graph public. Nothing about this is the
#: caller's to say, so nothing about it crosses the boundary.
PUBLIC = """
  EXISTS {
    MATCH (b:Book) WHERE b.reference = true AND %s STARTS WITH b.slug + ':'
  }
"""


def public_clause(alias: str) -> str:
    """The rulebook test for one bound variable."""
    return PUBLIC % f"{alias}.id"


GRANT = """
MATCH (c:Campaign {slug:$slug}), (t) WHERE t:Entity OR t:Section
WITH c, t WHERE t.id = $target
MERGE (c)-[g:REVEALED]->(t)
SET g.campaign = $slug, g.at_session = $at_session, g.as_name = $as_name
RETURN t.id AS id, coalesce(g.as_name, '') AS as_name
"""

REVOKE = """
MATCH (:Campaign {slug:$slug})-[g:REVEALED]->(t) WHERE t.id = $target
DELETE g RETURN count(g) AS n
"""

REVEALED = """
MATCH (:Campaign {slug:$slug})-[g:REVEALED]->(t)
RETURN t.id AS id, coalesce(t.name, t.heading) AS name,
       [l IN labels(t) WHERE l <> 'Entity'] AS labels,
       coalesce(g.as_name, '') AS as_name,
       coalesce(g.at_session, '') AS at_session
ORDER BY name
"""

#: One entity, as a player may have it.
#:
#: EVERY CLAUSE IS ANCHORED ON A GRANT. The entity itself must be revealed; a
#: quote appears only if ITS SECTION is revealed too; a connection appears only
#: if the thing at the far end is revealed. Nothing here is fetched and then
#: dropped, so there is no filter for a later edit to lose.
ENTITY_PLAYER = """
MATCH (c:Campaign {slug:$slug}), (e:Entity {id:$id})
WHERE (c)-[:REVEALED]->(e) OR """ + public_clause("e") + """
OPTIONAL MATCH (c)-[g:REVEALED]->(e)
OPTIONAL MATCH (e)<-[:REFERS_TO]-(m:Mention)-[:IN_SECTION]->(sec:Section)
WHERE (c)-[:REVEALED]->(sec) OR """ + public_clause("sec") + """
RETURN e.id AS entity_id,
       // THE NAME THE TABLE KNOWS IT BY. Revealing under an alias is how a
       // party actually meets somebody: the coachman for three sessions
       // before Strahd. The true name is not in this payload at all.
       CASE WHEN coalesce(g.as_name, '') <> '' THEN g.as_name ELSE e.name END
         AS name,
       e.kind AS kind, e.plane AS plane, e.role AS role,
       labels(e) AS labels, null AS own_section,
       e.named_by_book AS named_by_book,
       // `invented` IS THE DM'S NOTE TO THEMSELVES. It lists which parts of a
       // character the model supplied -- "his name" -- and a player reading it
       // learns which bits of their world were made up on the spot and which
       // came from the book. That is a fact about the AUTHORSHIP, useful to
       // the person writing and corrosive to the person playing.
       null AS invented,
       collect(DISTINCT {
         section_id: sec.id, heading: sec.heading, plane: sec.plane,
         text: sec.text, offsets: m.offsets
       }) AS named_in,
       [(e)-[r]->(far:Entity)
         WHERE NOT type(r) IN $plumbing
           AND ((c)-[:REVEALED]->(far) OR """ + public_clause("far") + """)
         | {dir: 'out', rel: type(r), status: r.status,
            other: far.name, other_id: far.id,
            other_labels: labels(far), other_plane: far.plane}]
       +
       [(e)<-[r]-(near:Entity)
         WHERE NOT type(r) IN $plumbing
           AND ((c)-[:REVEALED]->(near) OR """ + public_clause("near") + """)
         | {dir: 'in', rel: type(r), status: r.status,
            other: near.name, other_id: near.id,
            other_labels: labels(near), other_plane: near.plane}]
       AS connections
"""

#: One section, as a player may have it.
#:
#: THE SAME COLUMNS AS THE DM'S QUERY, because the shaping downstream is the
#: same code and a narrower row would simply crash -- or worse, quietly return
#: a card missing the fields a reader relies on. What differs is which rows
#: exist: a name underlined in this prose appears only if that entity has been
#: revealed, and a connection only if BOTH ends have.
SECTION_PLAYER = """
MATCH (c:Campaign {slug:$slug}), (s:Section {id:$id})
WHERE (c)-[:REVEALED]->(s) OR """ + public_clause("s") + """
OPTIONAL MATCH (named:Entity)<-[:REFERS_TO]-(m:Mention)-[:IN_SECTION]->(s)
WHERE (c)-[:REVEALED]->(named) OR """ + public_clause("named") + """
OPTIONAL MATCH (named)-[edge]->(far:Entity)
WHERE ((c)-[:REVEALED]->(far) OR """ + public_clause("far") + """)
  AND (far)<-[:REFERS_TO]-(:Mention)-[:IN_SECTION]->(s)
  AND coalesce(edge.status,'') <> 'rejected'
  AND NOT type(edge) IN $plumbing
RETURN s.id AS section_id, s.heading AS heading, s.text AS text,
       s.plane AS plane, s.kind AS kind,
       null AS describes, null AS chapter,
       s.invented AS invented, s.from_canon AS from_canon,
       s.from_yours AS from_yours, s.from_context AS from_context,
       s.edited AS edited,
       [] AS cites,
       collect(DISTINCT {
         entity_id: named.id, name: named.name, kind: named.kind,
         plane: named.plane,
         surface: coalesce(m.display_name, m.surface, named.name)
       }) AS mentions,
       collect(DISTINCT {
         from: named.name, from_id: named.id,
         rel: type(edge), to: far.name,
         to_id: far.id, plane: far.plane, status: edge.status
       }) AS connections
"""

VISIBLE_IDS = """
MATCH (:Campaign {slug:$slug})-[:REVEALED]->(t)
RETURN collect(t.id) AS ids
"""

#: The mention triangle and its kin join the graph; they assert nothing about
#: the world. Kept identical to the DM query's list so the two views cannot
#: disagree about what counts as a connection.
PLUMBING = [
    "REFERS_TO", "IN_SECTION", "ALIAS_OF", "CO_OCCURS_WITH", "USES_ALIAS",
    "DESCRIBES", "HAS_SECTION", "HAS_CHAPTER", "NEXT", "REVEALED",
]


def audience(tx, *, slug: str, reader: str) -> str:
    """Which chair this reader is in, defaulting to the narrow one.

    AN UNIDENTIFIED READER IS THE DM, AND ONLY BECAUSE NOBODY IS IDENTIFIED.
    `ACCESS_TOKENS` unset is the documented local case: one person at the
    machine, running their own game. Every OTHER unknown -- a seat that was
    never granted, a role the graph has forgotten -- falls to the player view,
    so a bug in seating is a closed door rather than a spoiler.
    """
    if not reader:
        return DM
    return DM if roles.role_of(tx, slug=slug, reader=reader) == DM else PLAYER


def reveal(tx, *, slug: str, target: str, at_session: str = "",
           as_name: str = "") -> dict:
    """Hand something to the table, optionally under another name.

    THE LOG WRITES ITSELF. An unstamped reveal takes the session the table is
    currently in, so "what did we learn in session four" is answerable without
    a DM ever filling in a field. Asking them to stamp each one by hand is
    asking for a log that is right for two sessions and then abandoned.

    AN EXPLICIT STAMP STILL WINS, for the DM writing up a session afterwards
    or correcting one.
    """
    from backend.campaign import sessions

    row = tx.run(GRANT, {
        "slug": slug, "target": target,
        "at_session": at_session or sessions.current(tx, slug=slug),
        "as_name": as_name}).single()
    if row is None:
        raise ValueError(f"nothing called {target!r} on table {slug!r}")
    return dict(row)


def conceal(tx, *, slug: str, target: str) -> int:
    """Take it back off the table.

    IT COSTS ONE CLICK AND CANNOT UNDO A READING. Concealing removes the grant;
    it does not remove what anybody already saw. That is not a defect to fix --
    it is why the default is deny.
    """
    return tx.run(REVOKE, {"slug": slug, "target": target}).single()["n"]


def revealed(tx, *, slug: str) -> list[dict]:
    """Everything this table has been shown. The DM's audit of their own game."""
    return [dict(r) for r in tx.run(REVEALED, {"slug": slug})]


#: What the table learned, by the night they learned it.
#:
#: THE LOG IS DERIVED, NOT WRITTEN. Every row here already exists -- the
#: sessions, and the grants stamped with the session they were made in -- so an
#: adventure log is a read, and there is no second record to drift from the
#: first. A stored log would be the copy that disagrees.
#:
#: IT IS SAFE FOR PLAYERS BY CONSTRUCTION. It reports grants, and a grant IS
#: the permission -- there is nothing here a reader could see that they were
#: not already allowed to see.
LOG = """
MATCH (c:Campaign {slug:$slug})-[g:REVEALED]->(t)
OPTIONAL MATCH (s:Session {id:g.at_session, campaign:$slug})
WITH s, collect({
  id: t.id,
  name: CASE WHEN coalesce(g.as_name, '') <> '' THEN g.as_name
             ELSE coalesce(t.name, t.heading) END,
  kind: CASE WHEN t:Section THEN 'scene' ELSE 'who' END
}) AS learned
RETURN coalesce(s.number, 0) AS number, coalesce(s.title, '') AS title,
       coalesce(s.held_on, '') AS held_on, learned
ORDER BY number DESC
"""


def log(tx, *, slug: str) -> list[dict]:
    """The adventure so far, newest night first.

    THE UNSTAMPED ENTRIES ARE THEIR OWN NIGHT, numbered zero. A table that
    revealed things before it opened a session has a real history and it does
    not belong hidden -- calling it "before the log" is honest, and dropping it
    would lose the opening of every campaign that started here.
    """
    return [dict(r) for r in tx.run(LOG, {"slug": slug})]


def visible_ids(tx, *, slug: str) -> list[str]:
    """What a model may be SEEDED with when it answers a player.

    SEEDED, NOT FILTERED. A model given the secret and asked not to mention it
    has already been given the secret; nothing downstream undoes that.
    """
    row = tx.run(VISIBLE_IDS, {"slug": slug}).single()
    return list(row["ids"]) if row else []


MAY_SEE = """
MATCH (c:Campaign {slug:$slug}), (t) WHERE t.id = $target
RETURN ((c)-[:REVEALED]->(t) OR """ + PUBLIC % "t.id" + """) AS ok
"""


def may_see(tx, *, slug: str, reader: str, target: str) -> bool:
    """The single question, asked in one place.

    ASKED OF THE GRAPH RATHER THAN OF A LOADED SET. This used to pull every
    granted id and test membership, which was fine while the only visible
    things were grants and wrong the moment a rulebook made thousands of
    entities public without any of them being granted.
    """
    if audience(tx, slug=slug, reader=reader) == DM:
        return True
    row = tx.run(MAY_SEE, {"slug": slug, "target": target}).single()
    return bool(row and row["ok"])


def entity_for(tx, *, slug: str, reader: str, entity_id: str, dm_query: str,
               dm_params: dict) -> dict | None:
    """One entity, as this reader may have it.

    THE DM'S QUERY IS PASSED IN rather than duplicated here, so the two views
    stay one behaviour with one difference. The player's is its own query --
    not the DM's with a filter -- because the difference is which rows exist,
    and that belongs in the pattern.
    """
    if audience(tx, slug=slug, reader=reader) == DM:
        row = tx.run(dm_query, dm_params).single()
        return dict(row) if row else None
    row = tx.run(ENTITY_PLAYER, {
        "slug": slug, "id": entity_id, "plumbing": PLUMBING}).single()
    return dict(row) if row else None


def section_for(tx, *, slug: str, reader: str, section_id: str,
                dm_query: str, dm_params: dict) -> dict | None:
    """One section's prose, if this reader has been given it."""
    if audience(tx, slug=slug, reader=reader) == DM:
        row = tx.run(dm_query, dm_params).single()
        return dict(row) if row else None
    row = tx.run(SECTION_PLAYER, {
        "slug": slug, "id": section_id, "plumbing": PLUMBING}).single()
    return dict(row) if row else None
