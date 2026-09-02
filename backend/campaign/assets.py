"""Pictures, and where each one came from.

`origin` IS `plane` FOR PIXELS. The foundational promise -- a DM can tell what
the published book says from what a model invented -- does not stop at
sentences. A portrait the book printed, a photograph the DM uploaded, and a
face a model imagined are three different things, and the moment they render
alike the promise is broken in the most persuasive medium the product has.

SO IT IS PINNED, NOT DEFAULTED, exactly as `plane` is pinned in
`graph/operations.py` after a caller-supplied one was allowed to win. There is
one writer per origin and no route may choose: `store_upload` can only ever
stamp `uploaded`, `store_generated` can only ever stamp `generated`, and `book`
is writable only by canon ingestion -- the same rule that makes `plane:'canon'`
the seed loader's alone.

BYTES ON DISK, METADATA IN THE GRAPH, keyed by content hash. Neo4j is not a
blob store, and a hash key means the same portrait uploaded twice is one file.

AN `:Asset` IS APPARATUS. A picture asserts nothing about the world -- the EDGE
to an entity is the claim, and it carries the campaign that made it. So an
asset takes no `plane`, and a generated portrait of a canon NPC is a campaign
edge pointing at a canon node: canon is never mutated, which is the invariant
the whole two-plane design rests on.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

BOOK = "book"
UPLOADED = "uploaded"
GENERATED = "generated"
ORIGINS = frozenset({BOOK, UPLOADED, GENERATED})

#: What a DM is told, per origin. Kept here rather than in the frontend so the
#: words cannot drift from the property that decides them.
CAPTION = {
    BOOK: "the book's art",
    UPLOADED: "yours",
    GENERATED: "imagined",
}

WRITE = """
MERGE (a:Asset {id:$id})
ON CREATE SET a.kind = $kind, a.media_type = $media_type, a.sha256 = $sha256,
              a.origin = $origin, a.campaign = $campaign,
              a.generator = $generator, a.prompt = $prompt,
              a.uploaded_by = $uploaded_by, a.created_at = $created_at
RETURN a.id AS id, a.origin AS origin
"""

PORTRAY = """
MATCH (e:Entity {id:$entity}), (a:Asset {id:$asset})
MERGE (e)-[r:PORTRAYED_BY]->(a)
SET r.campaign = $campaign, r.primary = $primary
RETURN count(r) AS n
"""

PORTRAITS = """
MATCH (e:Entity {id:$entity})-[r:PORTRAYED_BY]->(a:Asset)
WHERE r.campaign = $campaign OR r.campaign IS NULL
RETURN a.id AS id, a.origin AS origin, a.media_type AS media_type,
       coalesce(r.primary, false) AS primary
ORDER BY primary DESC, a.id
"""


def asset_id(sha256: str) -> str:
    """Content-addressed, so the same picture twice is the same asset."""
    return f"asset:{sha256[:32]}"


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def path_for(root: Path, sha256: str, suffix: str) -> Path:
    """`<root>/ab/cd/<sha>.png` -- fanned out so one directory never holds
    tens of thousands of files."""
    return root / sha256[:2] / sha256[2:4] / f"{sha256}{suffix}"


def _write(tx, *, sha256: str, media_type: str, origin: str, campaign: str,
           created_at: str, generator: str = "", prompt: str = "",
           uploaded_by: str = "", kind: str = "image") -> dict:
    """The one place an asset row is written. `origin` arrives already decided
    by the caller that is allowed to decide it, and is never read from input."""
    if origin not in ORIGINS:
        raise ValueError(f"{origin!r} is not an origin: {sorted(ORIGINS)}")
    row = tx.run(WRITE, {
        "id": asset_id(sha256), "kind": kind, "media_type": media_type,
        "sha256": sha256, "origin": origin, "campaign": campaign or None,
        "generator": generator, "prompt": prompt, "uploaded_by": uploaded_by,
        "created_at": created_at,
    }).single()
    return dict(row)


def store_upload(tx, *, sha256: str, media_type: str, campaign: str,
                 uploaded_by: str, created_at: str) -> dict:
    """A picture a person chose. Cannot be recorded as anything else."""
    return _write(tx, sha256=sha256, media_type=media_type, origin=UPLOADED,
                  campaign=campaign, uploaded_by=uploaded_by,
                  created_at=created_at)


def store_generated(tx, *, sha256: str, media_type: str, campaign: str,
                    generator: str, prompt: str, created_at: str) -> dict:
    """A picture a model made.

    `generator` AND `prompt` ARE THE ASSET'S EVIDENCE, the same way a canon
    edge carries the sentence it was read from. An image with no record of what
    produced it is a claim nobody can check, and this is the medium where that
    matters most.
    """
    if not generator:
        raise ValueError("a generated asset must say what generated it")
    return _write(tx, sha256=sha256, media_type=media_type, origin=GENERATED,
                  campaign=campaign, generator=generator, prompt=prompt,
                  created_at=created_at)


def portray(tx, *, entity: str, asset: str, campaign: str,
            primary: bool = True) -> int:
    """Point an entity at a picture of it.

    THE EDGE CARRIES THE CAMPAIGN, not the asset, because two tables may
    imagine the same canon NPC differently and neither is the book's. It is
    also what lets `delete_campaign` take the portrait without touching a node
    the book owns.
    """
    return tx.run(PORTRAY, {"entity": entity, "asset": asset,
                            "campaign": campaign, "primary": primary}).single()["n"]


def portraits(tx, *, entity: str, campaign: str) -> list[dict]:
    """Every picture of this entity this table may see, primary first."""
    return [dict(r) for r in tx.run(PORTRAITS,
                                    {"entity": entity, "campaign": campaign})]
