"""Who sits at a table, and in which chair.

THE GATE KNOWS WHO, AND NOTHING KNEW WHAT THEY MAY DO. `auth.identify` returns
a reader's name and `ReaderGate` puts it on the request; `ownership.py` uses it
to stop one reader writing to another's campaign. That is one bit -- yours or
not yours -- and the roadmap needs two chairs at the same table: a DM who sees
everything, and a player who must not.

A SEAT IS AN EDGE, NOT A PROPERTY. One person runs one table and plays at
another, so `role` cannot live on a `:Player` node; it lives on the edge that
joins them to a campaign. That is the same reason `HOLDS` will carry its
campaign rather than the item carrying an owner.

`:Player` IS APPARATUS. It is not a claim about the world -- it is a seat -- so
it carries no `plane`, for the reason `schema.APPARATUS_LABELS` records. It is
NOT the character they play: that is an `:Entity:PC` in the campaign plane, and
a person is not their character.

DEFAULT DENY, WITH ONE EXCEPTION THAT IS NOT A HOLE. A reader with no seat gets
no role. The exception is the campaign's OWNER, who is its DM by construction --
`ownership.claim` records whoever first writes to a table, and requiring them to
then grant themselves a chair would be a rule whose only effect is locking
people out of their own game.
"""

from __future__ import annotations

DM = "dm"
PLAYER = "player"
ROLES = frozenset({DM, PLAYER})

SEAT = """
MATCH (c:Campaign {slug:$slug})
MERGE (p:Player {reader:$reader, campaign:$slug})
MERGE (p)-[r:PLAYS_IN]->(c)
SET r.role = $role, p.campaign = $slug
RETURN r.role AS role
"""

ROLE_OF = """
MATCH (c:Campaign {slug:$slug})
OPTIONAL MATCH (p:Player {reader:$reader, campaign:$slug})-[r:PLAYS_IN]->(c)
RETURN coalesce(r.role, '') AS role, coalesce(c.owner, '') AS owner
"""

SEATED = """
MATCH (p:Player {campaign:$slug})-[r:PLAYS_IN]->(:Campaign {slug:$slug})
RETURN p.reader AS reader, r.role AS role ORDER BY p.reader
"""

UNSEAT = """
MATCH (p:Player {reader:$reader, campaign:$slug})
DETACH DELETE p RETURN count(p) AS n
"""


def seat(tx, *, slug: str, reader: str, role: str) -> str:
    """Give this reader a chair at this table.

    MERGEd on `(reader, campaign)`, so seating somebody twice moves their chair
    rather than giving them two. A `MATCH` on the campaign, never a `MERGE`: a
    typo in a slug must not conjure a table with one player in it, which is the
    ruling `ownership.claim` already makes for the same reason.
    """
    if role not in ROLES:
        raise ValueError(f"{role!r} is not a chair at this table: {sorted(ROLES)}")
    if not reader:
        raise ValueError("a seat needs somebody to sit in it")
    row = tx.run(SEAT, {"slug": slug, "reader": reader, "role": role}).single()
    return (row["role"] if row else "") or ""


def role_of(tx, *, slug: str, reader: str) -> str:
    """This reader's chair, or `""`.

    THE OWNER IS THE DM WITHOUT BEING SEATED. `ownership.claim` records whoever
    first writes to a table; making them then grant themselves a role would be
    a rule whose only effect is locking a DM out of their own game.

    AN UNIDENTIFIED READER GETS NO ROLE, not the DM's. On an open deployment
    -- `ACCESS_TOKENS` unset, the documented local case -- there is nobody to
    check, and callers decide what that means; `role_of` will not decide it for
    them by inventing an identity.
    """
    if not reader:
        return ""
    row = tx.run(ROLE_OF, {"slug": slug, "reader": reader}).single()
    if row is None:
        return ""
    if row["role"]:
        return str(row["role"])
    return DM if row["owner"] and row["owner"] == reader else ""


def seated(tx, *, slug: str) -> list[dict]:
    """Everyone with a chair, for the settings screen."""
    return [dict(r) for r in tx.run(SEATED, {"slug": slug})]


def unseat(tx, *, slug: str, reader: str) -> int:
    """Take the chair away. Returns how many were removed."""
    return tx.run(UNSEAT, {"slug": slug, "reader": reader}).single()["n"]
