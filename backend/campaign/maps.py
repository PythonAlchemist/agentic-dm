"""Maps, and the things a DM has put on them.

A MAP IS AN IMAGE ATTACHED TO A PLACE, not a folder of files. The map of
Barovia is a property of Barovia, so the graph is already the atlas index and
there is no map-management screen to build: pin Castle Ravenloft on the Barovia
map, and because Ravenloft has a map of its own the pin can be descended into.

COORDINATES ARE FRACTIONS OF THE IMAGE, NEVER PIXELS. A DM re-uploads a better
scan; the `:Map` keeps its id, its `IMAGE` edge is repointed at a new `:Asset`,
and every pin survives. Pixel coordinates would silently shear all of them, and
silently is the word that matters -- nobody would notice until the tavern was
in the lake.

A PIN IS AN EDGE, for the reason a mention is: its identity IS the pair
`(entity, map)`, so MERGE moves it rather than doubling it. It carries no facts
that would justify a node of its own.

AND IT IS A CAMPAIGN CLAIM even when both ends are the book's. "The innkeeper
stands here" is something a DM decided, not something the book says, so pinning
canon entities on the book's own map -- the everyday case -- writes a campaign
edge and leaves canon untouched.

PINS ARE BORN HIDDEN. The asymmetry is the whole argument: an accidental reveal
at the table cannot be taken back, and an accidental concealment costs one
click. A hidden pin does not exist on the player's view -- not blurred, not
silhouetted, because a blurred pin is a spoiler of EXISTENCE.
"""

from __future__ import annotations

def map_id(slug: str, name: str) -> str:
    """`hb:<campaign>:map-<slug>`, self-identifying like every campaign node."""
    from backend.canon.assembler import slugify

    return f"hb:{slug}:map-{slugify(name)}"


CREATE = """
MATCH (place:Entity {id:$place})
WHERE 'LOCATION' IN labels(place)
MATCH (a:Asset {id:$asset})
MERGE (m:Map {id:$id})
ON CREATE SET m.name = $name, m.campaign = $slug, m.created_at = $created_at
MERGE (m)-[:IMAGE]->(a)
MERGE (m)-[r:MAP_OF]->(place)
SET r.campaign = $slug
RETURN m.id AS id, m.name AS name
"""

MAPS_OF = """
MATCH (m:Map {campaign:$slug})-[:MAP_OF]->(place:Entity)
OPTIONAL MATCH (m)-[:IMAGE]->(a:Asset)
RETURN m.id AS id, m.name AS name, place.id AS place_id, place.name AS place,
       a.id AS asset_id, a.origin AS origin
ORDER BY m.name
"""

PIN = """
MATCH (e:Entity {id:$entity}), (m:Map {id:$map, campaign:$slug})
MERGE (e)-[p:PINNED_ON]->(m)
SET p.x = $x, p.y = $y, p.campaign = $slug, p.note = $note,
    p.revealed = coalesce(p.revealed, false)
RETURN p.x AS x, p.y AS y, p.revealed AS revealed
"""

UNPIN = """
MATCH (:Entity {id:$entity})-[p:PINNED_ON]->(:Map {id:$map, campaign:$slug})
DELETE p RETURN count(p) AS n
"""

#: Every pin a DM sees. `revealed` and the alias travel so the DM view can show
#: both what the players are looking at and what it really is.
PINS_DM = """
MATCH (e:Entity)-[p:PINNED_ON]->(:Map {id:$map, campaign:$slug})
RETURN e.id AS entity_id, e.name AS name, e.plane AS plane,
       [l IN labels(e) WHERE l <> 'Entity'] AS labels,
       p.x AS x, p.y AS y, p.note AS note,
       coalesce(p.revealed, false) AS revealed,
       coalesce(p.as_name, '') AS as_name
ORDER BY e.name
"""

#: What the table may see. THE FILTER IS IN THE PATTERN, not in a `WHERE` a
#: caller could forget: a query anchored on `revealed = true` cannot be made to
#: return a hidden pin by getting an argument wrong.
PINS_PLAYER = """
MATCH (e:Entity)-[p:PINNED_ON]->(:Map {id:$map, campaign:$slug})
WHERE p.revealed = true
RETURN e.id AS entity_id,
       // THE NAME THE TABLE KNOWS IT BY. A DM showing Strahd as "the coachman"
       // is the ordinary case, not an edge one -- and the true name must not
       // travel to a client that is only allowed the alias.
       CASE WHEN coalesce(p.as_name, '') <> '' THEN p.as_name ELSE e.name END
         AS name,
       [l IN labels(e) WHERE l <> 'Entity'] AS labels,
       p.x AS x, p.y AS y
ORDER BY name
"""

REVEAL = """
MATCH (:Entity {id:$entity})-[p:PINNED_ON]->(:Map {id:$map, campaign:$slug})
SET p.revealed = $revealed, p.as_name = $as_name, p.at_session = $at_session
RETURN coalesce(p.revealed, false) AS revealed
"""


def create(tx, *, slug: str, name: str, place: str, asset: str,
           created_at: str) -> dict:
    """Attach a map image to the place it depicts.

    `MAP_OF` TARGETS A LOCATION ONLY, the same range discipline `DESCRIBES`
    keeps. A map of "the party's journey" is a map of a region; a quest is not
    a place and cannot hold one.
    """
    row = tx.run(CREATE, {
        "slug": slug, "id": map_id(slug, name), "name": name,
        "place": place, "asset": asset, "created_at": created_at,
    }).single()
    if row is None:
        raise ValueError(
            f"no LOCATION {place!r} or no asset {asset!r} to make a map from")
    return dict(row)


def maps_of(tx, *, slug: str) -> list[dict]:
    return [dict(r) for r in tx.run(MAPS_OF, {"slug": slug})]


def pin(tx, *, slug: str, map_ref: str, entity: str, x: float, y: float,
        note: str = "") -> dict:
    """Put something on the map, hidden.

    FRACTIONS, AND REFUSED OUTSIDE THE IMAGE. A pin at 1.4 is a bug somewhere
    upstream -- a pixel coordinate that escaped conversion is the likely one --
    and storing it would put a token off the edge of the map where nobody can
    find or delete it.
    """
    if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
        raise ValueError(
            f"a pin is a fraction of the image, not a pixel: got ({x}, {y})")
    row = tx.run(PIN, {"slug": slug, "map": map_ref, "entity": entity,
                       "x": float(x), "y": float(y), "note": note}).single()
    if row is None:
        raise ValueError(f"no map {map_ref!r} or entity {entity!r} to pin")
    return dict(row)


def unpin(tx, *, slug: str, map_ref: str, entity: str) -> int:
    return tx.run(UNPIN, {"slug": slug, "map": map_ref,
                          "entity": entity}).single()["n"]


def pins(tx, *, slug: str, map_ref: str, for_player: bool) -> list[dict]:
    """What this audience may see on this map.

    TWO QUERIES, NOT ONE WITH A FLAG. The player query cannot express a hidden
    pin: `revealed = true` is in its pattern, so no argument a caller gets
    wrong can widen it. A single query taking `include_hidden` would put the
    whole guarantee on remembering to pass `False`.
    """
    query = PINS_PLAYER if for_player else PINS_DM
    return [dict(r) for r in tx.run(query, {"slug": slug, "map": map_ref})]


def reveal(tx, *, slug: str, map_ref: str, entity: str, revealed: bool = True,
           as_name: str = "", at_session: str = "") -> bool:
    """Turn a pin face-up, optionally under another name.

    REVEALING AS SOMETHING ELSE IS NOT A TRICK, it is how a table meets an NPC:
    the players know the coachman for three sessions before they know Strahd.
    The mention system already separates a surface from an entity's name; this
    is the same idea pointed at a map.
    """
    row = tx.run(REVEAL, {
        "slug": slug, "map": map_ref, "entity": entity,
        "revealed": bool(revealed), "as_name": as_name,
        "at_session": at_session,
    }).single()
    if row is None:
        raise ValueError(f"no pin for {entity!r} on {map_ref!r}")
    return bool(row["revealed"])
