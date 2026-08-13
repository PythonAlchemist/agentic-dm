"""Two-plane read resolution: per-table campaign state merged over shared canon.

The Cypher in this module only matches and filters. Every decision about what a
caller actually sees -- which properties win, which canon edges a table's choices
shadow -- happens in the pure functions below, so those decisions can be tested
exhaustively without a database.
"""

from typing import Literal

from backend.core.database import neo4j_session
from backend.graph.schema import RESOLVABLE_TYPES


def merge_properties(canon: dict, campaign: dict | None) -> dict:
    """Overlay a campaign node's sparse patch on its canon node.

    Campaign nodes store only what they override, so absent keys must fall
    through to canon rather than blanking it. Neither input is mutated.
    """
    if not campaign:
        return dict(canon)
    return {**canon, **campaign}


def _canonical_source(edge: dict) -> str:
    """The id a campaign edge shadows against.

    A copy-on-write campaign node has its own id, so an edge from it can only
    replace the canon edge it descends from if both are keyed on the canon node.
    Edges with no canon ancestor key on themselves.
    """
    return edge.get("source_canon_id") or edge["source_id"]


def shadow_edges(canon_edges: list[dict], campaign_edges: list[dict]) -> list[dict]:
    """Combine canon and campaign edges, honouring resolvable types.

    Additive types (the default) union. Resolvable types -- currently only
    RESOLVES_TO -- are replaced: if the campaign plane has any edge of that type
    out of a given source, every canon edge of that type from that source is
    dropped. That is the Tarokka collapse, where a table's card draw turns ten
    candidate sites into the one that is true for them.

    Shadowing is scoped to (source's canonical id, rel_type), so resolving the
    Sunsword's location leaves the Holy Symbol's candidates untouched, and a
    copy-on-write campaign node shadows the canon fan-out it descends from even
    though it carries its own id rather than the canon one.
    """
    resolvable = {r.value for r in RESOLVABLE_TYPES}
    shadowed = {
        (_canonical_source(e), e["rel_type"])
        for e in campaign_edges
        if e["rel_type"] in resolvable
    }
    kept = [
        e for e in canon_edges if (_canonical_source(e), e["rel_type"]) not in shadowed
    ]
    return kept + list(campaign_edges)


Perspective = Literal["truth", "table"]

# The canon plane's type is a LABEL, not a property: a node the extraction
# samples disputed carries two (`Barovia` is `:LOCATION:SETTING`) and no scalar
# could hold that. Matched with `IN labels(...)` rather than as `(canon:NPC)`
# because a label cannot be parameterized and this query is a constant. The
# CAMPAIGN branches below still read the property -- campaign nodes are written
# by `graph.operations`, which stamps one type and is not what this change is.
_ENTITY_CANON_BRANCH = """
MATCH (canon:Entity {plane:'canon'})
WHERE ($entity_type IS NULL OR $entity_type IN labels(canon))
  AND ($source_book IS NULL OR canon.source_book = $source_book)
OPTIONAL MATCH (camp:Entity {plane:'campaign'})-[:INSTANCE_OF]->(canon)
  WHERE (camp)-[:BELONGS_TO]->(:Entity {id:$campaign_id})
RETURN properties(canon) AS canon_props, properties(camp) AS camp_props
"""

_ENTITY_CAMPAIGN_ONLY_BRANCH = """
MATCH (camp:Entity {plane:'campaign'})-[:BELONGS_TO]->(:Entity {id:$campaign_id})
WHERE NOT (camp)-[:INSTANCE_OF]->(:Entity)
  AND ($entity_type IS NULL OR camp.entity_type = $entity_type)
RETURN properties(camp) AS camp_props
"""

_ENTITY_TABLE_VIEW = """
MATCH (camp:Entity {plane:'campaign'})-[:BELONGS_TO]->(:Entity {id:$campaign_id})
WHERE ($entity_type IS NULL OR camp.entity_type = $entity_type)
  AND camp.revealed_in_session IS NOT NULL
  AND camp.revealed_in_session <= $as_of_session
RETURN properties(camp) AS camp_props
"""

# Shared by _EDGES_CANON and _EDGES_CAMPAIGN, which are identical apart from their
# MATCH/WHERE clauses -- this is what keeps them from drifting apart again now that
# both have been touched in the same pass. _EDGES_TABLE cannot share it: Critical 2
# requires it to return NULL for source_canon_id rather than the real canon id, so
# forcing it into this constant would mean parameterising the RETURN clause itself.
# That is more contortion than the three-line duplication it would save, so
# _EDGES_TABLE keeps its own RETURN below, with a comment pointing back here.
_EDGE_RETURN = """
RETURN a.id AS source_id, coalesce(a.canon_id, a.id) AS source_canon_id,
       b.id AS target_id, type(r) AS rel_type, r.layer AS layer,
       a.plane AS plane, properties(r) AS props
"""

_EDGES_CANON = (
    """
MATCH (a:Entity {plane:'canon'})-[r]->(b:Entity)
WHERE r.layer IS NOT NULL
  AND ($layers IS NULL OR r.layer IN $layers)
"""
    + _EDGE_RETURN
)

# Truth deliberately does NOT constrain the target's plane to campaign-only: a
# campaign entity legitimately points at a canon entity it hasn't overridden (e.g.
# a table-invented hireling located in a canon town nobody has touched). But an
# unconstrained target also lets a campaign-plane source's edge point at ANOTHER
# campaign's node and leak that node's id, so the target must be allowed to be
# canon OR to belong to this same campaign -- never a bare, unscoped campaign node.
_EDGES_CAMPAIGN = (
    """
MATCH (a:Entity {plane:'campaign'})-[:BELONGS_TO]->(c:Entity {id:$campaign_id})
MATCH (a)-[r]->(b:Entity)
WHERE r.layer IS NOT NULL
  AND ($layers IS NULL OR r.layer IN $layers)
  AND (b.plane = 'canon' OR (b)-[:BELONGS_TO]->(c))
"""
    + _EDGE_RETURN
)

# Table view: BOTH endpoints must be campaign-plane, belong to this campaign, AND
# be independently revealed as of the session -- the edge's own reveal state says
# nothing about whether either endpoint has ever been shown to the table. Node ids
# are human-readable spoilers (e.g. "cos:location:castle-ravenloft:k37"), so an
# unrevealed or canon endpoint leaking through an edge is as severe as an
# unrevealed entity leaking directly. `c` is bound once and both endpoints must
# belong to it, so this also fixes the cross-campaign leak without weakening the
# canon-endpoint guard. source_canon_id is NULL here (not the shared _EDGE_RETURN)
# because it is consumed only by shadow_edges, which the table path never calls,
# and a copy-on-write node's canon_id is itself a canon id that must not reach
# the table.
_EDGES_TABLE = """
MATCH (a:Entity {plane:'campaign'})-[:BELONGS_TO]->(c:Entity {id:$campaign_id})
MATCH (b:Entity {plane:'campaign'})-[:BELONGS_TO]->(c)
MATCH (a)-[r]->(b)
WHERE r.layer IS NOT NULL
  AND ($layers IS NULL OR r.layer IN $layers)
  AND r.revealed_in_session IS NOT NULL AND r.revealed_in_session <= $as_of_session
  AND a.revealed_in_session IS NOT NULL AND a.revealed_in_session <= $as_of_session
  AND b.revealed_in_session IS NOT NULL AND b.revealed_in_session <= $as_of_session
RETURN a.id AS source_id, NULL AS source_canon_id,
       b.id AS target_id, type(r) AS rel_type, r.layer AS layer,
       a.plane AS plane, properties(r) AS props
"""


class PlaneResolver:
    """The single place two-plane reads go through.

    Truth view merges campaign state over canon with no reveal filter -- what is
    actually true, for generators and NPC behaviour. Table view reads the campaign
    plane ONLY, filtered by reveal; canon is deliberately invisible, because canon
    is the book rather than anything the party knows. That asymmetry is the whole
    spoiler defence.
    """

    def __init__(self, campaign_id: str):
        self.campaign_id = campaign_id

    def entities(
        self,
        perspective: Perspective,
        entity_type: str | None = None,
        source_book: str | None = None,
        as_of_session: int | None = None,
    ) -> list[dict]:
        self._check_perspective(perspective, as_of_session)

        with neo4j_session() as session:
            if perspective == "table":
                rows = session.run(
                    _ENTITY_TABLE_VIEW,
                    {
                        "campaign_id": self.campaign_id,
                        "entity_type": entity_type,
                        "as_of_session": as_of_session,
                    },
                )
                # A copy-on-write node's canon_id is itself a canon id -- leaking
                # it through the table view is exactly the spoiler this view
                # exists to prevent (Critical 2). `plane` is kept: callers and
                # existing tests assert on it.
                return [
                    {k: v for k, v in dict(r["camp_props"]).items() if k != "canon_id"}
                    for r in rows
                ]

            params = {
                "campaign_id": self.campaign_id,
                "entity_type": entity_type,
                "source_book": source_book,
            }
            merged = [
                merge_properties(dict(r["canon_props"]),
                                 dict(r["camp_props"]) if r["camp_props"] else None)
                for r in session.run(_ENTITY_CANON_BRANCH, params)
            ]
            invented = [
                dict(r["camp_props"])
                for r in session.run(_ENTITY_CAMPAIGN_ONLY_BRANCH, params)
            ]
            return merged + invented

    def edges(
        self,
        perspective: Perspective,
        layers: list[str] | None = None,
        as_of_session: int | None = None,
    ) -> list[dict]:
        self._check_perspective(perspective, as_of_session)

        with neo4j_session() as session:
            if perspective == "table":
                rows = session.run(
                    _EDGES_TABLE,
                    {
                        "layers": layers,
                        "campaign_id": self.campaign_id,
                        "as_of_session": as_of_session,
                    },
                )
                # Reveal filtering now happens in _EDGES_TABLE itself, for both
                # the edge and both endpoints, so the whole campaign edge set no
                # longer has to come over the wire to be filtered in Python here.
                return [self._row_to_edge(r) for r in rows]

            # Truth deliberately does NOT constrain the target's plane to
            # campaign-only: a campaign entity legitimately points at a canon
            # entity it hasn't overridden (e.g. a table-invented hireling located
            # in a canon town nobody has touched). That edge is true and
            # generators need it. The asymmetry with the table branch above is the
            # whole point -- see class docstring. Canon edges are shared across
            # every table and must NOT be campaign-scoped; only the
            # campaign-plane query is (and it also scopes the target -- see
            # _EDGES_CAMPAIGN's comment).
            canon = [
                self._row_to_edge(r)
                for r in session.run(_EDGES_CANON, {"layers": layers})
            ]
            campaign = [
                self._row_to_edge(r)
                for r in session.run(
                    _EDGES_CAMPAIGN, {"layers": layers, "campaign_id": self.campaign_id}
                )
            ]
        return shadow_edges(canon, campaign)

    def intersections(
        self,
        perspective: Perspective,
        min_layers: int = 2,
        as_of_session: int | None = None,
    ) -> list[dict]:
        """Nodes carrying edges in two or more layers.

        Derived, never stored -- "which places matter to the plot" is the query
        "which nodes have both spatial and narrative edges".
        """
        by_node: dict[str, set[str]] = {}
        for e in self.edges(perspective, as_of_session=as_of_session):
            for node_id in (e["source_id"], e["target_id"]):
                by_node.setdefault(node_id, set()).add(e["layer"])
        return [
            {"id": node_id, "layers": sorted(layers)}
            for node_id, layers in sorted(by_node.items())
            if len(layers) >= min_layers
        ]

    @staticmethod
    def _row_to_edge(row) -> dict:
        return {
            "source_id": row["source_id"],
            "source_canon_id": row["source_canon_id"],
            "target_id": row["target_id"],
            "rel_type": row["rel_type"],
            "layer": row["layer"],
            "plane": row["plane"],
            "props": dict(row["props"]),
        }

    @staticmethod
    def _check_perspective(perspective: Perspective, as_of_session: int | None) -> None:
        if perspective not in ("truth", "table"):
            raise ValueError(f"unknown perspective: {perspective!r}")
        if perspective == "truth" and as_of_session is not None:
            raise ValueError("as_of_session is meaningful only for perspective='table'")
        if perspective == "table" and as_of_session is None:
            raise ValueError("perspective='table' requires as_of_session")
