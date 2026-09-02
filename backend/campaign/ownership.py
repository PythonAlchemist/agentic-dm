"""Whose table a campaign is, and who may write to it.

THE GATE AUTHENTICATES AND NOTHING AUTHORISED. `ReaderGate` decides whether a
request is served at all, and every reader who gets through was equal: the
`campaign` slug is a field in the request body, so any token-holder could
`/edit` another table's prose, `/rescan` it, or `DELETE /store-cluster` out of
it. For a handful of people the DM vouched for that is tolerable and it is not
a design -- it is the absence of one, and the gate was doing authorisation work
it was only built to do authentication for.

AN OWNER IS A READER'S NAME, the same string `identify` returns and the gate now
puts on the request. Not a user table: there are no accounts here, and inventing
one to hold a single field would be a bigger claim about this system than it
makes.

UNOWNED IS OPEN, AND IS NOT A HOLE. Campaigns predate this and the deployment
runs open on localhost, where nobody is identified at all. A campaign with no
owner behaves exactly as it did before -- and the first write by an identified
reader CLAIMS it, so the protection arrives the moment there is somebody to
protect it for, without a migration and without a DM losing their own table to a
field they never set.
"""

from __future__ import annotations

OWNER_OF = """
MATCH (c:Campaign {slug:$slug}) RETURN coalesce(c.owner, '') AS owner
"""

CLAIM = """
MATCH (c:Campaign {slug:$slug})
WHERE c.owner IS NULL OR c.owner = ''
SET c.owner = $reader
RETURN c.owner AS owner
"""


def may_write(owner: str, reader: str) -> bool:
    """Whether this reader may change this campaign's material.

    THREE WAYS TO BE ALLOWED, and each is a real state rather than a hole:

      * the campaign has no owner -- it predates this, or was made on an open
        deployment, and refusing would lock a DM out of their own table;
      * nobody is identified -- `ACCESS_TOKENS` is unset, which is the
        documented local-development case, and there is no one to check;
      * the reader IS the owner, which is the ordinary answer.

    Everything else is refused, including the case worth naming: an identified
    reader who is not the owner of an owned campaign.
    """
    return not owner or not reader or owner == reader


def owner_of(tx, slug: str) -> str:
    """The campaign's owner, or `""` when it has none or does not exist."""
    row = tx.run(OWNER_OF, {"slug": slug}).single()
    return (row["owner"] if row else "") or ""


def claim(tx, slug: str, reader: str) -> str:
    """Record this reader as the owner if nobody holds it yet.

    FIRST WRITE WINS, and it is a MATCH rather than a MERGE: claiming must not
    conjure a campaign that does not exist, because a typo in a slug would then
    create an empty table owned by whoever made the typo.
    """
    if not reader:
        return ""
    row = tx.run(CLAIM, {"slug": slug, "reader": reader}).single()
    return (row["owner"] if row else "") or ""
