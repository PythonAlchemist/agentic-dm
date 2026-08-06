"""Two-plane read resolution: per-table campaign state merged over shared canon.

The Cypher in this module only matches and filters. Every decision about what a
caller actually sees -- which properties win, which canon edges a table's choices
shadow -- happens in the pure functions below, so those decisions can be tested
exhaustively without a database.
"""

from backend.graph.schema import RESOLVABLE_TYPES


def merge_properties(canon: dict, campaign: dict | None) -> dict:
    """Overlay a campaign node's sparse patch on its canon node.

    Campaign nodes store only what they override, so absent keys must fall
    through to canon rather than blanking it. Neither input is mutated.
    """
    if not campaign:
        return dict(canon)
    return {**canon, **campaign}


def shadow_edges(canon_edges: list[dict], campaign_edges: list[dict]) -> list[dict]:
    """Combine canon and campaign edges, honouring resolvable types.

    Additive types (the default) union. Resolvable types -- currently only
    RESOLVES_TO -- are replaced: if the campaign plane has any edge of that type
    out of a given source, every canon edge of that type from that source is
    dropped. That is the Tarokka collapse, where a table's card draw turns ten
    candidate sites into the one that is true for them.

    Shadowing is scoped to (source_id, rel_type), so resolving the Sunsword's
    location leaves the Holy Symbol's candidates untouched.
    """
    resolvable = {r.value for r in RESOLVABLE_TYPES}
    shadowed = {
        (e["source_id"], e["rel_type"])
        for e in campaign_edges
        if e["rel_type"] in resolvable
    }
    kept = [
        e for e in canon_edges if (e["source_id"], e["rel_type"]) not in shadowed
    ]
    return kept + list(campaign_edges)
