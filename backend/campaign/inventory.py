"""Who is carrying what, and who was carrying it before.

AN EDGE, NOT A LIST ON A CHARACTER. "The party's inventory" is the obvious
shape and the wrong one: an item moves -- the Sunsword is Ismark's, then the
party's, then dropped in the crypt -- and a list on a holder makes every move
two writes that can half-fail, leaving an item in two inventories or none. As
an edge it is one relationship whose ends ARE the answer.

TIME IS TWO PROPERTIES, NOT TWO GRAPHS. `since_session` and `until_session`
turn the current holding into a query -- `until_session IS NULL` -- and keep
every previous one where a DM can read it. "Who had the Sunsword in session
three" is then a question the graph can answer, which is precisely why sessions
had to exist as nodes before this could be built.

CLOSING IS PART OF HANDING OVER, IN ONE TRANSACTION. An item with two open
holders is not a state a DM can see and fix; the graph would just answer
"who has it" twice. So `give` closes whatever was open before it opens the
new one, and the eleventh invariant catches any that a hand-written Cypher
leaves behind.

THE PARTY IS AN ENTITY. `hb:<slug>:the-party`, a `:FACTION` in the campaign
plane, minted the first time something is given to it. That is what makes
"the party has it" the same shape as "Ismark has it" rather than a special
case every read has to know about -- and it means the party can be pinned on
a map, portrayed, and mentioned like anything else.

CANON IS NOT TOUCHED. The Sunsword is the book's; who is carrying it is this
table's. The edge carries the campaign, points AT the canon node, and changes
nothing on it -- the same ruling `assets.portray` makes about a portrait.
"""

from __future__ import annotations

PARTY = "the-party"


def party_id(slug: str) -> str:
    return f"hb:{slug}:{PARTY}"


#: A campaign entity is a campaign entity by its `plane` and `campaign`
#: properties, not by an edge to the `:Campaign` -- that is how every other
#: element in `homebrew.py` is written, and a second convention here would be
#: a second thing `delete_campaign` has to know about.
ENSURE_PARTY = """
MATCH (c:Campaign {slug:$slug})
MERGE (p:Entity {id:$id})
ON CREATE SET p:FACTION, p.name = 'The party', p.plane = 'campaign',
              p.campaign = $slug, p.status = 'authored',
              p.kind = 'faction'
RETURN p.id AS id, p.name AS name
"""

#: Close whatever is open, then open the new one. Two statements, one
#: transaction, because between them the item has no holder and a reader
#: arriving there would be told nobody has it.
#:
#: `coalesce($at, '')` IS LOad-BEARING. In Cypher, setting a property to NULL
#: REMOVES it, so closing an undated holding with a NULL stamp left
#: `until_session IS NULL` true and closed nothing at all -- the item stayed
#: open under both holders, and the graph answered "who has it" twice. An empty
#: string is the honest record: this holding ended, and nobody knows when.
CLOSE = """
MATCH (:Entity)-[h:HOLDS {campaign:$slug}]->(:Entity {id:$item})
WHERE h.until_session IS NULL
SET h.until_session = coalesce($at, '')
RETURN count(h) AS n
"""

OPEN = """
MATCH (holder:Entity {id:$holder}), (item:Entity {id:$item})
CREATE (holder)-[h:HOLDS {campaign:$slug, since_session:$at,
                          note:$note}]->(item)
RETURN holder.name AS holder, item.name AS item, h.since_session AS since
"""

#: What a holder is carrying now. `until_session IS NULL` IS the word "now",
#: and putting it in the pattern rather than in a caller's filter is what makes
#: a stale holding impossible to read as a current one.
HELD_BY = """
MATCH (holder:Entity {id:$holder})-[h:HOLDS {campaign:$slug}]->(item:Entity)
WHERE h.until_session IS NULL
RETURN item.id AS item_id, item.name AS name, item.plane AS plane,
       [l IN labels(item) WHERE l <> 'Entity'] AS labels,
       h.since_session AS since_session, coalesce(h.note, '') AS note
ORDER BY item.name
"""

#: What the PARTY is holding, for the people holding it.
#:
#: A PLAYER'S INVENTORY IS THE PARTY'S, NOT THE TABLE'S. The full ledger names
#: every holder, so a player reading it would learn that somebody called Strahd
#: is carrying a tome -- an NPC's pockets are the DM's material, and the
#: sentence "party inventory" already says whose this is.
PARTY_LEDGER = """
MATCH (holder:Entity {id:$party})-[h:HOLDS {campaign:$slug}]->(item:Entity)
WHERE h.until_session IS NULL
RETURN holder.id AS holder_id, holder.name AS holder,
       item.id AS item_id, item.name AS name, item.plane AS plane,
       h.since_session AS since_session, coalesce(h.note, '') AS note
ORDER BY item.name
"""

#: Everything this table is holding, whoever is holding it.
LEDGER = """
MATCH (holder:Entity)-[h:HOLDS {campaign:$slug}]->(item:Entity)
WHERE h.until_session IS NULL
RETURN holder.id AS holder_id, holder.name AS holder,
       item.id AS item_id, item.name AS name, item.plane AS plane,
       h.since_session AS since_session, coalesce(h.note, '') AS note
ORDER BY holder.name, item.name
"""

#: Every hand this item has passed through, oldest first.
PROVENANCE = """
MATCH (holder:Entity)-[h:HOLDS {campaign:$slug}]->(:Entity {id:$item})
RETURN holder.id AS holder_id, holder.name AS holder,
       h.since_session AS since_session, h.until_session AS until_session
ORDER BY h.since_session, holder.name
"""

#: The same `coalesce`, for the same reason: a NULL stamp would un-set the
#: property and leave the holding open.
DROP = """
MATCH (:Entity {id:$holder})-[h:HOLDS {campaign:$slug}]->(:Entity {id:$item})
WHERE h.until_session IS NULL
SET h.until_session = coalesce($at, '')
RETURN count(h) AS n
"""


def ensure_party(tx, *, slug: str) -> dict:
    """The party, minted on demand.

    A `MATCH` ON THE CAMPAIGN, NEVER A `MERGE`, the ruling `ownership.claim`
    and `roles.seat` both make: a typo in a slug must not conjure a table with
    a party standing in it.
    """
    row = tx.run(ENSURE_PARTY, {"slug": slug, "id": party_id(slug)}).single()
    if row is None:
        raise ValueError(f"no table {slug!r} to have a party")
    return dict(row)


def give(tx, *, slug: str, item: str, holder: str, at_session: str = "",
         note: str = "") -> dict:
    """Hand an item to somebody, closing whoever had it.

    `at_session` IS WHEN, AND IT MAY BE EMPTY. A DM recording history from
    memory does not always know which session; an empty stamp records the fact
    without inventing a date, and "who had it in session three" simply does not
    return it rather than returning it wrongly.
    """
    if holder == party_id(slug):
        ensure_party(tx, slug=slug)
    closed = tx.run(CLOSE, {"slug": slug, "item": item,
                            "at": at_session or None}).single()["n"]
    row = tx.run(OPEN, {"slug": slug, "item": item, "holder": holder,
                        "at": at_session or None, "note": note}).single()
    if row is None:
        raise ValueError(f"no holder {holder!r} or item {item!r}")
    return {**dict(row), "took_from": closed}


def drop(tx, *, slug: str, item: str, holder: str, at_session: str = "") -> int:
    """Put it down. The holding closes; it is not deleted.

    A DELETED EDGE WOULD BE A DELETED FACT. That the party carried the Sunsword
    for six sessions is true whether or not they still do, and a graph that
    forgets it cannot answer the only interesting question about an item.
    """
    return tx.run(DROP, {"slug": slug, "item": item, "holder": holder,
                         "at": at_session or None}).single()["n"]


def held_by(tx, *, slug: str, holder: str) -> list[dict]:
    return [dict(r) for r in tx.run(HELD_BY, {"slug": slug, "holder": holder})]


def ledger(tx, *, slug: str) -> list[dict]:
    """Everything this table is carrying, by holder. The DM's view."""
    return [dict(r) for r in tx.run(LEDGER, {"slug": slug})]


def party_ledger(tx, *, slug: str) -> list[dict]:
    """What the party is carrying. The players'."""
    return [dict(r) for r in tx.run(PARTY_LEDGER,
                                    {"slug": slug, "party": party_id(slug)})]


def provenance(tx, *, slug: str, item: str) -> list[dict]:
    """Every hand it has passed through. The reason time is a property."""
    return [dict(r) for r in tx.run(PROVENANCE, {"slug": slug, "item": item})]
