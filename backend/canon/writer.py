"""Write one chapter's canon candidates into Neo4j, atomically.

Split in two on purpose.

`plan_write` is a pure function -- candidates in, the exact nodes and edges to
write out, plus a count of every drop. It never opens a connection, so every
filter rule is assertable without a database, and a planning bug cannot leave
half a chapter behind.

`write_chapter` runs the plan in ONE transaction. The loop that consumes this
graph discovers work by asking which chapters have at least one node, so a
half-committed chapter looks *done* forever and carries a silently truncated
chapter into every campaign that inherits the canon plane. Commit or roll back;
there is no third outcome, and no node-by-node loop that commits as it goes.

The canon plane only. A campaign's own play is layered on top of these nodes and
is somebody's game -- nothing here may delete it, which is why `--replace`
refuses rather than reaching for DETACH DELETE.
"""

from dataclasses import dataclass, field

from backend.canon.assembler import slugify
from backend.canon.constraints import check_edges
from backend.canon.gazetteer import Gazetteer
from backend.canon.models import CandidateEdge, CandidateNode
from backend.canon.sections import KEYED_HEADING
from backend.graph.schema import GRAPH_SCHEMA, LAYER_MAP, RelationshipType

#: Nodes and edges written here are the book's own canon, shared by every
#: campaign. The resolver filters on this property; an unstamped node is
#: invisible to it.
CANON_PLANE = "canon"

#: Every id is prefixed with the book. Nothing merges across chapters -- see
#: `mint_id` -- and nothing merges across books either.
BOOK = "cos"


class ChapterAlreadyWritten(Exception):
    """The chapter already has canon nodes and `--replace` was not asked for.

    Gate G6 in the loop's HUMAN-GATES.md: overwriting canon a human may already
    have reviewed is a decision, not a default.
    """

    def __init__(self, chapter_slug: str, nodes: int) -> None:
        super().__init__(
            f"{chapter_slug} already has {nodes} canon node(s); "
            "pass --replace to delete them and write fresh"
        )
        self.chapter_slug = chapter_slug
        self.nodes = nodes


class CampaignDataAttached(Exception):
    """A `--replace` would have had to delete something outside the canon plane.

    A canon node cannot be deleted while a relationship still points at it, and
    the only way to force it is DETACH DELETE -- which would take a table's own
    play with it. Refusing is the only behaviour that keeps "never delete
    anything outside plane='canon'" true.
    """

    def __init__(self, chapter_slug: str, relationships: int) -> None:
        super().__init__(
            f"refusing to replace {chapter_slug}: {relationships} relationship(s) outside this "
            "chapter's canon plane are attached to its nodes. Deleting them would destroy "
            "campaign data; resolve by hand."
        )
        self.chapter_slug = chapter_slug
        self.relationships = relationships


def mint_id(chapter_slug: str, entity_type: str, name: str) -> str:
    """`cos:<chapter-slug>:<entity-type-lowercase>:<name-slug>`.

    Chapter-scoped because NOTHING merges across chapters in this pipeline.
    Chapter 4 alone holds `Chapel`, `Closet` x2 and `Empty Cell` x3 as genuinely
    distinct rooms, and both `North Dungeon CONTAINS Empty Cell` and `South
    Dungeon CONTAINS Empty Cell` are real within that one chapter.
    Cross-chapter resolution is a separate pass with its own measurement.

    `entity_type` is part of the id because a coined QUEST sharing a LOCATION's
    name is a measured occurrence in this corpus -- `anchor_quests` keys on
    `(name, type)` for the same reason.

    Reuses `assembler.slugify` rather than growing a second slugifier that
    drifts from it.
    """
    return f"{BOOK}:{chapter_slug}:{entity_type.strip().lower()}:{slugify(name)}"


@dataclass(frozen=True)
class WriteNode:
    """One canon entity, with its id already minted."""

    id: str
    name: str
    entity_type: str
    chapter_slug: str
    section_heading: str = ""
    section_index: int = -1
    votes: int = 0
    description: str = ""

    @property
    def properties(self) -> dict:
        """What lands on the node. `id` is the MERGE key, so it is not here."""
        props: dict = {
            "name": self.name,
            "entity_type": self.entity_type,
            "plane": CANON_PLANE,
            "chapter_slug": self.chapter_slug,
            "section_heading": self.section_heading,
            "section_index": self.section_index,
            "votes": self.votes,
        }
        # Absent rather than empty: `description` is optional on a candidate,
        # and writing "" would make a node that never had one indistinguishable
        # from one whose description the extractor lost.
        if self.description:
            props["description"] = self.description
        return props


@dataclass(frozen=True)
class WriteEdge:
    """One canon relationship, endpoints already resolved to ids."""

    source_id: str
    target_id: str
    rel_type: RelationshipType
    chapter_slug: str
    evidence: str = ""
    section_heading: str = ""
    section_index: int = -1
    votes: int = 0

    @property
    def properties(self) -> dict:
        """What lands on the relationship.

        `layer` is DERIVED from LAYER_MAP, never re-listed here: a second copy
        of that table would drift from the one the intersection queries use.
        A type mapped explicitly to None is not a surface, and carries no
        `layer` at all rather than a null one.

        `evidence` travels because `evidence == "derived from document
        structure"` is the only thing downstream has to tell the deterministic
        layer from LLM output, and stage 2b is told to trust the two
        differently.
        """
        props: dict = {
            "plane": CANON_PLANE,
            "chapter_slug": self.chapter_slug,
            "evidence": self.evidence,
            "section_heading": self.section_heading,
            "section_index": self.section_index,
            "votes": self.votes,
        }
        layer = LAYER_MAP[self.rel_type]
        if layer is not None:
            props["layer"] = layer.value
        return props


@dataclass
class FilterReport:
    """Why every candidate that did not reach the graph did not reach it.

    Every drop is counted and every count is printed. Silent filtering has twice
    hidden a defect in this project for weeks, so a filter that cannot say what
    it removed is not finished.
    """

    candidate_nodes: int = 0
    candidate_edges: int = 0
    # Node drops
    gazetteer_dropped: int = 0
    unnameable: int = 0
    duplicate_nodes: int = 0
    # Edge drops, in the order they are applied
    self_loops: int = 0
    constraint_violations: int = 0
    dangling_edges: int = 0
    ambiguous_edges: int = 0
    duplicate_edges: int = 0
    written_nodes: int = 0
    written_edges: int = 0
    # Samples, so a reader can see WHAT was dropped and not only how much.
    dropped_gazetteer: list[str] = field(default_factory=list)
    dropped_self_loops: list[str] = field(default_factory=list)
    dropped_violations: list[str] = field(default_factory=list)
    dropped_dangling: list[str] = field(default_factory=list)
    dropped_ambiguous: list[str] = field(default_factory=list)
    ambiguous_names: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        """The counts alone, for the run artifact."""
        return {
            "candidate_nodes": self.candidate_nodes,
            "candidate_edges": self.candidate_edges,
            "gazetteer_dropped": self.gazetteer_dropped,
            "unnameable": self.unnameable,
            "duplicate_nodes": self.duplicate_nodes,
            "self_loops": self.self_loops,
            "constraint_violations": self.constraint_violations,
            "dangling_edges": self.dangling_edges,
            "ambiguous_edges": self.ambiguous_edges,
            "duplicate_edges": self.duplicate_edges,
            "written_nodes": self.written_nodes,
            "written_edges": self.written_edges,
        }


def _fold(name: str) -> str:
    """Case-insensitive on the stripped string, as `constraints._fold` folds.

    Strict: no fuzzy distance, no token subsets, no substring containment. Loose
    matching is how a regex shotgun came to outscore a real extractor.
    """
    return name.strip().casefold()


def keyed_place_names(nodes: list[CandidateNode]) -> set[str]:
    """The folded names of every keyed area this chapter's sections name.

    Read off the section headings the candidates carry, using the same
    `KEYED_HEADING` the splitter and the structural deriver share -- `E5g.
    Undercroft` names the place `Undercroft`. A prose heading like "Approaching
    the Village" is not keyed and confers nothing; treating it as a place would
    invent one the book never keys.
    """
    keyed: set[str] = set()
    for node in nodes:
        match = KEYED_HEADING.match(node.section_heading.strip())
        if match:
            keyed.add(_fold(match.group("name")))
    return keyed


def plan_write(
    nodes: list[CandidateNode],
    edges: list[CandidateEdge],
    gazetteer: Gazetteer,
    chapter_slug: str,
) -> tuple[list[WriteNode], list[WriteEdge], FilterReport]:
    """Decide exactly what to write, and count every candidate that is dropped.

    `chapter_slug` is the CALLER's, not the artifact's: the loop keys the graph
    on the corpus filename while the extractor derived its slug from the chapter
    title, and the graph must be keyed on the one the loop discovers.

    Filters, in this order:

    1. self-loops -- free, and one survived even the two-stage classifier
    2. constraint violations -- ~30% of LLM edges are type-impossible. Endpoint
       types come from the FULL candidate node set, before the gazetteer has
       removed any: a node dropped later still typed its endpoint correctly.
    3. gazetteer -- bare generic nouns, 89% of chapter 4's rejected. A keyed
       place survives REGARDLESS: the wiki indexes 38 locations against the
       book's 414 keyed areas, so a keyed room's absence is expected and is not
       evidence against the room.
    4. edges left dangling or ambiguous by a dropped or duplicated node

    Raises ValueError on an unknown relationship type: a rel type cannot be
    parameterized in Cypher, so it is interpolated into the query text, and
    `check_edges` treats an unknown type as unchecked rather than violating.
    """
    report = FilterReport(candidate_nodes=len(nodes), candidate_edges=len(edges))

    # 1 -- self-loops
    surviving_edges: list[CandidateEdge] = []
    for edge in edges:
        if _fold(edge.source_name) == _fold(edge.target_name):
            report.self_loops += 1
            report.dropped_self_loops.append(f"{edge.source_name} -{edge.rel_type}->")
            continue
        surviving_edges.append(edge)

    # 2 -- type-impossible edges, judged against every candidate node's type
    violating = {v.edge_index for v in check_edges(nodes, surviving_edges)}
    for index in sorted(violating):
        bad = surviving_edges[index]
        report.dropped_violations.append(
            f"{bad.source_name} -{bad.rel_type}-> {bad.target_name}"
        )
    report.constraint_violations = len(violating)
    surviving_edges = [e for i, e in enumerate(surviving_edges) if i not in violating]

    # 3 -- gazetteer junk, with keyed places exempt
    keyed = keyed_place_names(nodes)
    kept_nodes: list[CandidateNode] = []
    for node in nodes:
        if gazetteer.is_known(node.name) or _fold(node.name) in keyed:
            kept_nodes.append(node)
            continue
        report.gazetteer_dropped += 1
        report.dropped_gazetteer.append(f"{node.entity_type} {node.name}")

    # Ids, and the name index the edges resolve through. First candidate for an
    # id wins: later ones are the same entity named again in another section,
    # and the earliest occurrence is the provenance closest to its introduction.
    by_id: dict[str, WriteNode] = {}
    ids_by_name: dict[str, set[str]] = {}
    for node in kept_nodes:
        if not slugify(node.name):
            # A name that slugifies to nothing cannot be given an id at all.
            report.unnameable += 1
            continue
        node_id = mint_id(chapter_slug, node.entity_type, node.name)
        if node_id in by_id:
            report.duplicate_nodes += 1
            continue
        by_id[node_id] = WriteNode(
            id=node_id,
            name=node.name,
            entity_type=node.entity_type,
            chapter_slug=chapter_slug,
            section_heading=node.section_heading,
            section_index=node.section_index,
            votes=node.votes,
            description=node.description,
        )
        ids_by_name.setdefault(_fold(node.name), set()).add(node_id)

    report.ambiguous_names = sorted(name for name, ids in ids_by_name.items() if len(ids) > 1)

    # 4 -- edges whose endpoints did not survive, or which name an entity that
    # two surviving nodes both answer to.
    write_edges: list[WriteEdge] = []
    seen: set[tuple[str, str, str]] = set()
    for edge in surviving_edges:
        # Coerced before anything is built from it: this is the only thing
        # standing between a corrupt artifact and interpolated Cypher.
        rel = RelationshipType(edge.rel_type.strip())
        source_ids = ids_by_name.get(_fold(edge.source_name))
        target_ids = ids_by_name.get(_fold(edge.target_name))
        label = f"{edge.source_name} -{edge.rel_type}-> {edge.target_name}"
        if not source_ids or not target_ids:
            report.dangling_edges += 1
            report.dropped_dangling.append(label)
            continue
        if len(source_ids) > 1 or len(target_ids) > 1:
            # Choosing one would manufacture an assertion the extractor never
            # made -- the same reason a reversal is detected and never
            # performed. Counted, so the disputed types are visible as the
            # evidence for whether a type-reconciliation pass is worth building.
            report.ambiguous_edges += 1
            report.dropped_ambiguous.append(label)
            continue
        source_id = next(iter(source_ids))
        target_id = next(iter(target_ids))
        key = (source_id, rel.value, target_id)
        if key in seen:
            report.duplicate_edges += 1
            continue
        seen.add(key)
        write_edges.append(
            WriteEdge(
                source_id=source_id,
                target_id=target_id,
                rel_type=rel,
                chapter_slug=chapter_slug,
                evidence=edge.evidence,
                section_heading=edge.section_heading,
                section_index=edge.section_index,
                votes=edge.votes,
            )
        )

    write_nodes = list(by_id.values())
    report.written_nodes = len(write_nodes)
    report.written_edges = len(write_edges)
    return write_nodes, write_edges, report


def ensure_schema(session) -> None:
    """Create the constraints and indexes `GRAPH_SCHEMA` declares.

    Declared once in `backend/graph/schema.py` and applied here, rather than
    restating any of it. Schema changes cannot share a transaction with writes
    in Neo4j, so this runs before the write rather than inside it -- it creates
    nothing a rollback would need to undo.
    """
    for statement in [*GRAPH_SCHEMA["constraints"], *GRAPH_SCHEMA["indexes"]]:
        try:
            session.run(statement)
        except Exception:  # noqa: BLE001 -- already exists is the normal case
            pass


def count_canon_nodes(session, chapter_slug: str) -> int:
    """How many canon nodes this chapter already has. The loop's own predicate."""
    record = session.run(
        "MATCH (n:Entity {chapter_slug:$slug, plane:$plane}) RETURN count(n) AS c",
        {"slug": chapter_slug, "plane": CANON_PLANE},
    ).single()
    return record["c"] if record else 0


def _delete_chapter(tx, chapter_slug: str) -> tuple[int, int]:
    """Delete this chapter's canon relationships and nodes. Nothing else.

    Scoped by `plane` AND `chapter_slug` on both statements, so another
    chapter's canon and every campaign's play are untouchable from here. A node
    still carrying a relationship this scope does not cover is refused rather
    than DETACH DELETEd -- see `CampaignDataAttached`.
    """
    attached = tx.run(
        """
        MATCH (n:Entity {chapter_slug:$slug, plane:$plane})-[r]-()
        WHERE NOT (r.plane = $plane AND r.chapter_slug = $slug)
        RETURN count(r) AS c
        """,
        {"slug": chapter_slug, "plane": CANON_PLANE},
    ).single()["c"]
    if attached:
        raise CampaignDataAttached(chapter_slug, attached)

    edges = tx.run(
        """
        MATCH ()-[r]->()
        WHERE r.chapter_slug = $slug AND r.plane = $plane
        DELETE r
        RETURN count(r) AS c
        """,
        {"slug": chapter_slug, "plane": CANON_PLANE},
    ).single()["c"]
    nodes = tx.run(
        """
        MATCH (n:Entity {chapter_slug:$slug, plane:$plane})
        DELETE n
        RETURN count(n) AS c
        """,
        {"slug": chapter_slug, "plane": CANON_PLANE},
    ).single()["c"]
    return nodes, edges


def _write_node(tx, node: WriteNode) -> None:
    """MERGE on the id, so a re-run after `--replace` cannot double a node."""
    tx.run(
        "MERGE (e:Entity {id:$id}) SET e += $props",
        {"id": node.id, "props": node.properties},
    )


def _write_edge(tx, edge: WriteEdge) -> None:
    """MERGE the relationship, and REFUSE an endpoint that is not there.

    A `MATCH ... MERGE` whose MATCH finds nothing writes nothing and reports no
    error, which is exactly how a chapter acquires an edge count lower than its
    plan without anything failing. Raising inside the transaction rolls the
    whole chapter back instead.

    The type is interpolated because Cypher cannot parameterize one. It is a
    `RelationshipType` member, coerced in `plan_write`, so the interpolated text
    can only ever be one of the enum's own values.
    """
    written = tx.run(
        f"""
        MATCH (a:Entity {{id:$source}}), (b:Entity {{id:$target}})
        MERGE (a)-[r:{edge.rel_type.value}]->(b)
        SET r += $props
        RETURN count(r) AS c
        """,
        {"source": edge.source_id, "target": edge.target_id, "props": edge.properties},
    ).single()["c"]
    if not written:
        raise ValueError(
            f"edge endpoint missing: {edge.source_id} -{edge.rel_type.value}-> {edge.target_id}"
        )


def _write_tx(tx, chapter_slug: str, nodes, edges, replace: bool) -> dict:
    """The whole chapter, in one transaction. Commit or roll back.

    The existing-chapter check lives INSIDE the transaction on purpose: read it
    outside and a concurrent write could land between the check and the write,
    which is the truncation hazard wearing a different hat. `--replace` deletes
    in here too, for the same reason -- a delete that commits before a failed
    write empties a chapter and leaves it looking done.
    """
    existing = tx.run(
        "MATCH (n:Entity {chapter_slug:$slug, plane:$plane}) RETURN count(n) AS c",
        {"slug": chapter_slug, "plane": CANON_PLANE},
    ).single()["c"]

    deleted_nodes = deleted_edges = 0
    if existing and not replace:
        raise ChapterAlreadyWritten(chapter_slug, existing)
    if replace:
        deleted_nodes, deleted_edges = _delete_chapter(tx, chapter_slug)

    for node in nodes:
        _write_node(tx, node)
    for edge in edges:
        _write_edge(tx, edge)

    return {
        "nodes": len(nodes),
        "edges": len(edges),
        "deleted_nodes": deleted_nodes,
        "deleted_edges": deleted_edges,
    }


def write_chapter(
    session,
    chapter_slug: str,
    nodes: list[WriteNode],
    edges: list[WriteEdge],
    *,
    replace: bool = False,
) -> dict:
    """Write one chapter's canon in a single transaction.

    `session.execute_write` commits when the unit of work returns and rolls back
    when it raises, so a failure anywhere -- a missing endpoint, a constraint,
    Neo4j restarting mid-write -- leaves the chapter exactly as it was.
    """
    return session.execute_write(_write_tx, chapter_slug, nodes, edges, replace)
