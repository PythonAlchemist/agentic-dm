"""What a conversation remembers, kept where a restart cannot reach it.

THE SUBGRAPH IS THE MEMORY. `dm_agent._trim` bounds the transcript to the
current question and leans on the subgraph to carry who the conversation is
about -- a deliberate design, and the best idea in the agent layer. It lived in
a dict on one uvicorn worker, so every deploy, restart and LRU eviction was
amnesia mid-campaign, and `/elements` is documented as "THE FRESH-SESSION ENTRY
POINT" because of it.

A `:SessionMemory` NODE, NOT A PLANE. This is neither the book nor the DM's
material: it is what one browser was talking about. Giving it a `plane` would
put tooling state into a distinction that exists to separate two kinds of
CLAIM, and every plane-scoped read would then have to remember to exclude it.
It carries `campaign` so `delete_campaign` takes it along -- a table's memory
of a table that no longer exists is exactly the debris the invariants hunt.

WRITTEN WHOLE, NEVER MERGED FIELD BY FIELD. The snapshot is one JSON string;
half a restored subgraph is worse than none, because it reads as a conversation
that forgot only some of what it knew.
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

SAVE = """
MERGE (m:SessionMemory {id:$id})
SET m.campaign = $campaign, m.book = $book, m.snapshot = $snapshot,
    m.updated_at = $updated_at
RETURN m.id AS id
"""

LOAD = """
MATCH (m:SessionMemory {id:$id})
RETURN m.snapshot AS snapshot, m.book AS book, m.campaign AS campaign
"""

FORGET = """
MATCH (m:SessionMemory {id:$id}) DETACH DELETE m RETURN count(m) AS n
"""


def save(tx, *, session_id: str, book: str, campaign: str | None,
         snapshot: dict, updated_at: str) -> None:
    """Write this session's memory. One node, one string, one write."""
    tx.run(SAVE, {
        "id": session_id, "campaign": campaign, "book": book,
        "snapshot": json.dumps(snapshot), "updated_at": updated_at,
    })


def load(tx, *, session_id: str, book: str, campaign: str | None) -> dict | None:
    """This session's memory, or `None`.

    REFUSES A MEMORY OF ANOTHER WORLD. `_agent_for` already treats a changed
    book or campaign as a new thread, because the subgraph holds entities by id
    and carrying one table's cast into another is the cross-plane bleed the
    scoping exists to stop. The same rule has to hold across a restart, or the
    restore becomes the hole the live path refuses to be.
    """
    row = tx.run(LOAD, {"id": session_id}).single()
    if row is None or not row["snapshot"]:
        return None
    if row["book"] != book or row["campaign"] != campaign:
        return None
    try:
        return json.loads(row["snapshot"])
    except (TypeError, ValueError):
        # A snapshot that will not parse is a bug worth seeing, and not worth
        # failing a DM's question over. They lose the thread, which is what
        # they would have lost anyway.
        logger.exception("could not read session memory for %s", session_id)
        return None


def forget(tx, *, session_id: str) -> int:
    """Drop it. `/lab/reset` means the conversation, not just this process's."""
    return tx.run(FORGET, {"id": session_id}).single()["n"]
