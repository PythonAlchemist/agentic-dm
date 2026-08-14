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

import logging
from collections.abc import Container, Mapping
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

from neo4j.exceptions import Neo4jError

from backend.canon.assembler import slugify
from backend.canon.constraints import check_edges, exclusive_conflicts
from backend.canon.gazetteer import Gazetteer
from backend.canon.models import CandidateEdge, CandidateNode
from backend.canon.sections import KEYED_HEADING
from backend.canon.structure import STRUCTURAL_EVIDENCE
from backend.graph.schema import (
    ALIAS_LABEL,
    ALIAS_OF,
    ARTIFACT_LABEL,
    CANON_ENTITY_TYPES,
    CO_OCCURS_WITH,
    DESCRIBES,
    GRAPH_SCHEMA,
    HAS_CHAPTER,
    HAS_SECTION,
    IN_SECTION,
    LAYER_MAP,
    REFERS_TO,
    RELATIONSHIP_DOMAIN_RANGE,
    USES_ALIAS,
    EntityType,
    LocationSubtype,
    RelationshipType,
)

if TYPE_CHECKING:  # `spine` imports `mint_id` and `BOOK` from here, so the
    # runtime dependency runs one way only -- spine -> writer, aliases -> spine.
    from backend.canon.aliases import WriteAlias
    from backend.canon.cooccurrence import CoOccurrence
    from backend.canon.spine import ChapterSpine, EntityNames, WriteMention

#: Nodes and edges written here are the book's own canon, shared by every
#: campaign. The resolver filters on this property; an unstamped node is
#: invisible to it.
CANON_PLANE = "canon"

#: Derived from the document's own structure: deterministic, incapable of
#: hallucinating, and the one layer a hand read found clean. A DM or a generator
#: may read these as settled.
ACCEPTED = "accepted"

#: Everything the LLM proposed. Present in the graph and queryable, but never
#: settled canon: a hand read of all 30 LLM edges in chapter 3 found about a
#: third wrong, including `Ismark OPPOSES Ireena` (he is her brother).
PROPOSED = "proposed"

#: A proposed edge that contradicts an ACCEPTED one between the same ordered
#: endpoints. The accepted layer is deterministic, so it stands and this one is
#: demoted -- the ONLY case in which anything here picks a winner. Two PROPOSED
#: edges that contradict each other are both kept as `proposed`, because nothing
#: automatic can say which is right and a silent guess is how a wrong edge
#: becomes indistinguishable from a checked one.
CONFLICTED = "conflicted"

#: Every id is prefixed with the book. Entities merge across the chapters of one
#: book -- see `mint_id` -- but never across books.
BOOK = "cos"

#: The labels a canon node may carry beside `:Entity`, derived from the ontology
#: rather than restated. A label CANNOT be parameterized in Cypher, so it is
#: interpolated into the query text; this frozenset is the only thing standing
#: between a corrupt artifact's `entity_type` and injected Cypher.
CANON_LABELS: frozenset[str] = frozenset(t.value for t in CANON_ENTITY_TYPES)

#: The rungs of the LOCATION hierarchy, as label text. Same reasoning as
#: `CANON_LABELS`: a label is interpolated rather than parameterized, and this
#: frozenset is what stands between a hand-edited YAML and injected Cypher.
LOCATION_SUBTYPE_LABELS: frozenset[str] = frozenset(s.value for s in LocationSubtype)

#: The label a place must already carry for a rung to mean anything. A rung is
#: a position in the LOCATION hierarchy, so an ITEM keyed as `E5d. Trapdoor`
#: gets none -- an item is not on that ladder.
LOCATION_LABEL = EntityType.LOCATION.value

#: The label an entity must already carry for `:Artifact` to mean anything, the
#: way `LOCATION_LABEL` gates a rung. `:Artifact` narrows `:ITEM`, so a place or
#: a person that happens to share an authored name is not on that shelf.
ITEM_LABEL = EntityType.ITEM.value

logger = logging.getLogger(__name__)

#: Neo4j's "you already created this" family. Expected on every run after the
#: first, and the only schema errors `ensure_schema` passes over in silence.
_SCHEMA_EXISTS_CODES = frozenset(
    {
        "Neo.ClientError.Schema.ConstraintAlreadyExists",
        "Neo.ClientError.Schema.IndexAlreadyExists",
        "Neo.ClientError.Schema.EquivalentSchemaRuleAlreadyExists",
    }
)


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


def mint_id(chapter_slug: str, name: str, key: str = "") -> str:
    """`cos:<name-slug>`, or `cos:<chapter-slug>:<key>-<name-slug>` when keyed.

    UNKEYED ENTITIES ARE GLOBAL TO THE BOOK. Madam Eva is one woman whether the
    introduction or chapter 3 names her, and a chapter-scoped id gave her one
    node per chapter -- nine duplicated names across three chapters, and a major
    NPC heading for twenty nodes by chapter 25, each holding a slice of her
    edges. Merging on the exact name accepts that two different people sharing
    one name would collapse; in a single sourcebook that trade is worth one
    Strahd.

    A KEYED PLACE RESOLVES TO `(book, chapter, key)`, NEVER TO ITS NAME. Chapter
    4 holds `Closet` x2 and `Empty Cell` x3 as genuinely distinct rooms, and
    both `North Dungeon CONTAINS Empty Cell` and `South Dungeon CONTAINS Empty
    Cell` are real within that one chapter -- so a name-only id would merge
    three rooms into one and silently delete two of those edges. `K61a. Empty
    Cell` and `K62a. Empty Cell` mint `cos:castle-ravenloft:k61a-empty-cell` and
    `cos:castle-ravenloft:k62a-empty-cell`. An unkeyed place has no key to
    resolve to and falls back to its name like everything else, which is the
    riskiest case here and the one to watch.

    The name is kept alongside the key rather than replaced by it: `k61a` alone
    is opaque in a report, a query, or a stack trace, and the key already
    carries the uniqueness.

    THE TYPE IS NOT IN THE ID. It used to be, and that is precisely what made
    `Barovia` two nodes when one sample called it a LOCATION and another a
    SETTING, and `Doru` two nodes over NPC versus MONSTER -- seven names split
    by a disagreement about a label rather than about the world. The type is
    now a Neo4j label, several are allowed at once, and a disputed type
    dissolves into one node wearing both rather than into two nodes wearing one
    each. Nothing has to pick a winner.

    Reuses `assembler.slugify` rather than growing a second slugifier that
    drifts from it.
    """
    tail = "-".join(part for part in (key.strip().lower(), slugify(name)) if part)
    if key.strip():
        return f"{BOOK}:{chapter_slug}:{tail}"
    return f"{BOOK}:{tail}"


@dataclass(frozen=True)
class WriteNode:
    """One canon entity, with its id already minted."""

    id: str
    name: str
    #: Every type any candidate for this id gave it, sorted and deduplicated.
    #: A TUPLE rather than a scalar because two extraction samples routinely
    #: disagree -- `Barovia` is a LOCATION to one and a SETTING to another --
    #: and there is nothing to choose between them. Both become labels.
    entity_types: tuple[str, ...]
    #: The chapter whose write this is. Bookkeeping for the write, NOT a property
    #: of the entity: a globally unique node has no one chapter, and where it
    #: APPEARS is now a set of `:Mention` nodes rather than anything here.
    chapter_slug: str
    votes: int = 0
    #: `ACCEPTED` when the book itself keys this place, or when some accepted
    #: edge attaches to it; `PROPOSED` otherwise. Defaults to PROPOSED because
    #: acceptance has to be EARNED from evidence -- a node built by hand, or by
    #: a caller that has not thought about it, must not arrive pre-trusted.
    status: str = PROPOSED
    #: Where this place sits in the spatial hierarchy -- a `LocationSubtype`
    #: value, or `""` for a place with no derivable rung and no authored one.
    #: A SCALAR, unlike `entity_types`: the rungs are a single ladder, so two at
    #: once is a contradiction rather than two readings the way `:NPC:MONSTER`
    #: is. Empty by default and never defaulted to a value: an unclassified
    #: place must be visibly unclassified.
    location_subtype: str = ""
    #: Whether the authored seed names this item one of the campaign's
    #: artifacts. A BOOL rather than a second `location_subtype`-shaped scalar:
    #: there is exactly one item label, so there is no sibling for it to be
    #: chosen against and nothing to record but membership. False by default,
    #: and never defaulted true: an item nobody authored is a plain item.
    is_artifact: bool = False

    @property
    def labels(self) -> tuple[str, ...]:
        """The Neo4j labels beside `:Entity`, one per type, sorted.

        Filtered through `CANON_LABELS` because a label is interpolated into
        Cypher rather than parameterized. A type the ontology does not admit as
        canon -- a campaign-plane `PC`, or garbage out of a corrupt artifact --
        confers no label at all, leaving a plain `:Entity` that every "everything"
        query still finds and no type query wrongly claims.
        """
        return tuple(sorted(t for t in self.entity_types if t in CANON_LABELS))

    @property
    def subtype_label(self) -> str:
        """The hierarchy rung's label, or `""` when there is none to write.

        Kept apart from `labels` rather than folded into it, because the two are
        written differently: a type label is only ever ADDED (a second chapter
        typing `Barovia` a SETTING adds to the chapter that typed it a LOCATION),
        while a rung REPLACES the rung a node was wearing -- a place is not both
        a room and a building. `_write_node` needs to tell them apart.

        Filtered through `LOCATION_SUBTYPE_LABELS` for the same reason `labels`
        is filtered: this text is interpolated into Cypher. It is also gated on
        the node actually being a LOCATION, so `E5d. Trapdoor` -- which the
        extractor typed ITEM -- gets no rung on a ladder it is not standing on.
        """
        if LOCATION_LABEL not in self.labels:
            return ""
        return self.location_subtype if self.location_subtype in LOCATION_SUBTYPE_LABELS else ""

    @property
    def artifact_label(self) -> str:
        """`:Artifact`, or `""` for the items that are just items.

        Gated on the node actually being an ITEM, the way `subtype_label` is
        gated on LOCATION. The node passed in already carries its unioned types,
        so a disputed `:ITEM:LORE` qualifies on the half of the disagreement
        that is an item.

        A THIRD property rather than a third case in either of the other two,
        because it is written a third way. A type label is only ever ADDED; a
        rung REPLACES the rung a node was wearing; this is added and never
        replaced, because it is not on the rung ladder and has no sibling to
        supersede it.

        No allowlist filter, unlike `labels` and `subtype_label`. Those two
        interpolate text that ultimately came from an artifact or a hand-edited
        YAML, so each is filtered through a frozenset of the ontology's own
        names. Here the label text is this module's constant and the seed
        contributes only the NAME that selects a node -- nothing a YAML can say
        reaches Cypher.
        """
        return ARTIFACT_LABEL if self.is_artifact and ITEM_LABEL in self.labels else ""

    @property
    def properties(self) -> dict:
        """What lands on the node. `id` is the MERGE key, so it is not here.

        NO `entity_type`. The labels are the type, and a scalar property beside
        them would be the same fact in two places -- with the disputed case
        forcing it to be a lie, since `Barovia` is `:LOCATION:SETTING` and no
        single string says that. A consumer that needs a scalar derives it from
        `labels(n)` at read time.

        NO `chapter_slug`, `section_heading` or `section_index` either: an
        entity the whole book shares appears in many chapters and many sections,
        and each appearance is a `:Mention` carrying its own.

        NO `description`, AND ITS ABSENCE IS THE POINT. It was one sentence,
        single-valued and last-write-wins: Strahd is described across twenty-five
        chapters and the node kept whichever extraction ran most recently, the
        same defect class as the shared-edge `chapter_slug` overwrite. Every
        `:Mention` now carries an evidence span quoting the section it was found
        in, so "what does the book say about X" is an aggregation over those --
        harder to read than a property, and able to answer *when*. If a
        description comes back it comes back as an aggregate of the mentions,
        computed rather than overwritten.
        """
        return {
            "name": self.name,
            "plane": CANON_PLANE,
            "votes": self.votes,
            "status": self.status,
        }


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
    #: `"constraint"` when at least one endpoint was picked out of a disputed
    #: name by `RELATIONSHIP_DOMAIN_RANGE` -- see `_resolve_endpoint`. Empty
    #: when both endpoints were unambiguous.
    endpoint_resolved: str = ""
    #: The relationship types this edge contradicts between these very
    #: endpoints, comma-joined. Empty for the overwhelming majority.
    conflict: str = ""
    #: Set only when this PROPOSED edge lost to an ACCEPTED one it contradicts.
    #: Never set on an accepted edge, and never on either half of a
    #: proposed-versus-proposed conflict -- see `CONFLICTED`.
    conflicted: bool = False

    @property
    def status(self) -> str:
        """`accepted` | `proposed` | `conflicted`.

        DERIVED from `evidence`, not stored beside it, for the same reason
        `layer` is derived from LAYER_MAP: a second field saying the same thing
        can drift from the first, and `evidence == STRUCTURAL_EVIDENCE` is
        already the only signal downstream has for telling the deterministic
        layer from LLM output. Anything that can construct a WriteEdge therefore
        gets the right status without being told about statuses at all.
        """
        if self.conflicted:
            return CONFLICTED
        return ACCEPTED if self.evidence.strip() == STRUCTURAL_EVIDENCE else PROPOSED

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

        `endpoint_resolved` travels for a colder reason: an edge whose endpoint
        was CHOSEN to satisfy the domain/range table will always satisfy that
        table afterwards, so the verifier's constraint check is vacuous on it.
        That is acceptable -- the alternative is dropping a real edge -- but it
        must be visible on the edge rather than quietly weakening the check.
        A filter that only offers legal options has a violation rate of zero by
        construction, and nothing downstream may mistake that for evidence.

        `status` travels for the reason this whole layer exists: without it a
        DM or a generator reading the graph gets `Ismark OPPOSES Ireena` with
        exactly the same authority as `Church CONTAINS Undercroft`, and no query
        can tell them apart.
        """
        props: dict = {
            "plane": CANON_PLANE,
            "chapter_slug": self.chapter_slug,
            "evidence": self.evidence,
            "section_heading": self.section_heading,
            "section_index": self.section_index,
            "votes": self.votes,
            "status": self.status,
        }
        layer = LAYER_MAP[self.rel_type]
        if layer is not None:
            props["layer"] = layer.value
        # Absent rather than "": an edge that needed no resolution must not look
        # like one that was resolved into some other category.
        if self.endpoint_resolved:
            props["endpoint_resolved"] = self.endpoint_resolved
        # Likewise absent unless real: this is the property a reviewer at gate
        # G3 filters on, and an empty string on every ordinary edge would bury
        # the handful that actually contradict something.
        if self.conflict:
            props["conflict"] = self.conflict
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
    # NOT a drop and NOT a candidate: nodes this stage MINTED rather than
    # received. Only the chapter's own place, today. Counted because the
    # verifier's accounting identity is `written + every named drop ==
    # candidates`, and a node that arrived from outside the candidate set breaks
    # it by exactly one -- correctly. The identity gains a term rather than a
    # fudge factor: `written + drops == candidates + derived`.
    derived_nodes: int = 0
    # Node drops
    gazetteer_dropped: int = 0
    unnameable: int = 0
    undecidable_keyed: int = 0
    duplicate_nodes: int = 0
    # Edge drops, in the order they are applied
    self_loops: int = 0
    constraint_violations: int = 0
    dangling_edges: int = 0
    ambiguous_edges: int = 0
    duplicate_edges: int = 0
    # NOT a drop: edges kept because the domain/range table picked one endpoint
    # out of a disputed name. Counted apart from every drop above AND from the
    # plain writes, because the constraint check is vacuous on exactly these.
    endpoint_resolved: int = 0
    # NOT a drop either: both halves of every mutual-exclusion conflict are
    # WRITTEN. `exclusive_conflicts` counts PAIRS; `conflicted_edges` counts the
    # proposed edges demoted because an accepted edge contradicted them. The two
    # are different denominators and must never be summed.
    exclusive_conflicts: int = 0
    conflicted_edges: int = 0
    # The accepted/proposed split, which is what this whole stage exists to
    # record. Counted here so it lands in the run artifact rather than only in a
    # terminal that scrolls away. `proposed_*` INCLUDES the conflicted edges: a
    # conflicted edge is a proposed one that lost, not a third trust level, and
    # accepted + proposed must add up to written or the split hides something.
    accepted_nodes: int = 0
    proposed_nodes: int = 0
    accepted_edges: int = 0
    proposed_edges: int = 0
    written_nodes: int = 0
    written_edges: int = 0
    # Samples, so a reader can see WHAT was dropped and not only how much.
    dropped_gazetteer: list[str] = field(default_factory=list)
    dropped_undecidable_keyed: list[str] = field(default_factory=list)
    dropped_self_loops: list[str] = field(default_factory=list)
    dropped_violations: list[str] = field(default_factory=list)
    dropped_dangling: list[str] = field(default_factory=list)
    dropped_ambiguous: list[str] = field(default_factory=list)
    resolved_endpoints: list[str] = field(default_factory=list)
    ambiguous_names: list[str] = field(default_factory=list)
    #: One line per conflicting PAIR, both halves named. Complete, not capped:
    #: this is the list a human reads at gate G3, and it is the only record of a
    #: contradiction the graph now holds on purpose.
    conflicts: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        """The counts alone, for the run artifact."""
        return {
            "candidate_nodes": self.candidate_nodes,
            "candidate_edges": self.candidate_edges,
            "derived_nodes": self.derived_nodes,
            "gazetteer_dropped": self.gazetteer_dropped,
            "unnameable": self.unnameable,
            "undecidable_keyed": self.undecidable_keyed,
            "duplicate_nodes": self.duplicate_nodes,
            "self_loops": self.self_loops,
            "constraint_violations": self.constraint_violations,
            "dangling_edges": self.dangling_edges,
            "ambiguous_edges": self.ambiguous_edges,
            "duplicate_edges": self.duplicate_edges,
            "endpoint_resolved": self.endpoint_resolved,
            "exclusive_conflicts": self.exclusive_conflicts,
            "conflicted_edges": self.conflicted_edges,
            "accepted_nodes": self.accepted_nodes,
            "proposed_nodes": self.proposed_nodes,
            "accepted_edges": self.accepted_edges,
            "proposed_edges": self.proposed_edges,
            "written_nodes": self.written_nodes,
            "written_edges": self.written_edges,
        }


def _fold(name: str) -> str:
    """Case-insensitive on the stripped string, as `constraints._fold` folds.

    Strict: no fuzzy distance, no token subsets, no substring containment. Loose
    matching is how a regex shotgun came to outscore a real extractor.
    """
    return name.strip().casefold()


def _entity_type(raw: str) -> EntityType | None:
    """The ontology's type for a candidate's `entity_type`, or None if unknown."""
    try:
        return EntityType(raw.strip())
    except ValueError:
        return None


@dataclass(frozen=True)
class KeyedIndex:
    """Every keyed area this chapter's sections name, by section and by name.

    Read off the section headings the candidates carry, using the same
    `KEYED_HEADING` the splitter and the structural deriver share -- `E5g.
    Undercroft` keys the place `Undercroft` as `E5g`. A prose heading like
    "Approaching the Village" is not keyed and confers nothing; treating it as
    a place would invent one the book never keys.

    Places are matched on their SLUG, not their folded text, so that two names
    which would mint the same id are the same place here too. `Bildrath's
    Mercantile` and `Bildrath’s Mercantile` differ by one invisible character --
    the DDB corpus preserves the book's U+2019 while the extractor sometimes
    emits an ASCII quote -- and matching on text alone let the ASCII spelling
    miss its own keyed heading and mint a SECOND Bildrath's Mercantile. Anything
    `slugify` already treats as one name is one name.
    """

    #: section_index -> (key, place slug, place as the heading writes it)
    by_section: dict[int, tuple[str, str, str]]
    #: place slug -> the distinct keys naming it, in first-seen order
    keys_by_place: dict[str, list[str]]
    #: The keys carrying a sub-area suffix -- `e5g` but not `e5`. Recorded from
    #: the SAME `KEYED_HEADING` match that built the key, rather than re-parsed
    #: from the joined text: a second pattern that has to agree with the first
    #: is the defect `structure.py` keeps one copy of this regex to avoid.
    subarea_keys: frozenset[str] = frozenset()

    @property
    def place_slugs(self) -> set[str]:
        """Slugs of every keyed place -- the gazetteer's exempt set."""
        return set(self.keys_by_place)

    def subtype_for_key(self, key: str) -> LocationSubtype:
        """The hierarchy rung a key implies. `E5g` is a room, `E5` a building.

        The whole of the derived half of the hierarchy, and it is one lookup:
        the book's own key convention already separates a sub-area from the
        area containing it, so nothing here has to read a name or ask a model.
        """
        return LocationSubtype.AREA if key in self.subarea_keys else LocationSubtype.SITE

    def keys_own_name(self, name: str, section_index: int) -> bool:
        """Whether this section's own heading keys this very name."""
        entry = self.by_section.get(section_index)
        return entry is not None and entry[1] == slugify(name)

    def spells_it_as_the_book_does(self, name: str, section_index: int) -> bool:
        """Whether this candidate spells the place exactly as its heading does.

        The tiebreak within a tiebreak: two candidates can both be keyed by
        their own section and disagree on typography, and canon should carry
        the book's spelling rather than whichever the extractor emitted first.
        """
        entry = self.by_section.get(section_index)
        return entry is not None and entry[2] == name.strip()

    def key_for(self, name: str, section_index: int) -> tuple[str, bool]:
        """`(key, undecidable)` for a candidate. `("", False)` means not keyed.

        The section a candidate came from decides first: `Empty Cell` extracted
        out of `K61a. Empty Cell` is K61a's cell, whatever else the chapter
        keys by that name. Failing that, a name the chapter keys exactly once
        is that room wherever it is mentioned -- which is what lets a mention
        of `Undercroft` from inside `E5a. Hall` join the room keyed at `E5g`
        rather than minting a second one.

        A name keyed by two different sections, mentioned from neither, is
        undecidable: `Empty Cell` in prose could be K61a's or K62a's, and
        picking would invent a room. The caller drops it and counts it.
        """
        keys = self.keys_by_place.get(slugify(name))
        if not keys:
            return "", False
        if self.keys_own_name(name, section_index):
            return self.by_section[section_index][0], False
        if len(keys) == 1:
            return keys[0], False
        return "", True


def keyed_index(nodes: list[CandidateNode]) -> KeyedIndex:
    """Build the chapter's keyed-area index from its candidates' provenance."""
    by_section: dict[int, tuple[str, str, str]] = {}
    keys_by_place: dict[str, list[str]] = {}
    subarea_keys: set[str] = set()
    for node in nodes:
        match = KEYED_HEADING.match(node.section_heading.strip())
        if not match:
            continue
        suffix = match.group("suffix") or ""
        key = f"{match.group('stem')}{suffix}".strip().lower()
        if suffix:
            subarea_keys.add(key)
        place = match.group("name").strip()
        by_section.setdefault(node.section_index, (key, slugify(place), place))
        keys = keys_by_place.setdefault(slugify(place), [])
        if key not in keys:
            keys.append(key)
    return KeyedIndex(
        by_section=by_section,
        keys_by_place=keys_by_place,
        subarea_keys=frozenset(subarea_keys),
    )


def keyed_place_slugs(nodes: list[CandidateNode]) -> set[str]:
    """The slugs of every keyed area this chapter's sections name."""
    return keyed_index(nodes).place_slugs

def _endpoint_ids(
    name: str,
    section_index: int,
    keyed: KeyedIndex,
    ids_by_name: dict[str, set[str]],
    ids_by_section: dict[int, set[str]],
) -> set[str]:
    """The nodes an edge's endpoint name could mean, narrowed by its section.

    An edge derived from `K61a. Empty Cell` naming `Empty Cell` means THAT
    cell, not the one at K62a -- the section it came from is direct evidence,
    and without it `North Dungeon CONTAINS Empty Cell` and `South Dungeon
    CONTAINS Empty Cell` would both collapse into "ambiguous" and be dropped,
    though the brief names both as real within one chapter.

    Everything else falls through to the folded-name index unchanged.
    """
    if keyed.keys_own_name(name, section_index):
        scoped = ids_by_section.get(section_index)
        if scoped:
            return scoped
    return ids_by_name.get(_fold(name), set())


def _as_write_node(node: CandidateNode, node_id: str, chapter_slug: str) -> WriteNode:
    """A candidate with its id minted and the caller's chapter slug stamped.

    The candidate's `description` and its section provenance are deliberately
    NOT carried across -- see `WriteNode.properties`. They stay in the run
    artifact, which is the record of what the extractor said; the graph records
    where the entity actually appears instead.
    """
    return WriteNode(
        id=node_id,
        name=node.name,
        entity_types=(node.entity_type,),
        chapter_slug=chapter_slug,
        votes=node.votes,
    )


def _resolve_endpoint(
    ids: set[str],
    by_id: dict[str, WriteNode],
    allowed: frozenset[EntityType] | None,
) -> tuple[str | None, bool]:
    """Which node an edge's endpoint name means. `(id, was_resolved)`.

    One id, no question -- that is every ordinary edge, and it is not
    "resolved". A DISPUTED TYPE NO LONGER REACHES HERE: `Tatyana` typed NPC by
    one sample and LORE by four is one node wearing both labels, so the name
    answers to a single id. What still can is a name the chapter keys twice
    (`Empty Cell` at K61a and K62a), or one the chapter both keys and mentions
    unkeyed.

    When EXACTLY ONE candidate has a type the relationship's domain (or range)
    admits, that is the only reading of the edge the ontology permits, so it is
    the reading taken. `IDENTITY_OF`'s range is `{NPC, MONSTER}`, so `Ireena
    IDENTITY_OF Tatyana` can only mean the animate one.

    Zero or two or more satisfy, or the relationship has no domain/range entry
    at all: nothing decides it, and picking anyway would manufacture an
    assertion the extractor never made. The caller drops the edge.

    A candidate satisfies when ANY of its types is admitted -- a node is
    genuinely both, and refusing the edge because one of its two labels is
    inadmissible would drop a fact the other label supports. A type outside the
    ontology never counts: `check_edges` treats an unknown type as unCHECKED,
    which is right when asking "is this edge legal"; it cannot make an unknown
    type the unique answer to "which of these two nodes is meant".
    """
    if len(ids) == 1:
        return next(iter(ids)), False
    if allowed is None:
        return None, False
    satisfying = [
        i for i in ids if any(_entity_type(t) in allowed for t in by_id[i].entity_types)
    ]
    if len(satisfying) == 1:
        return satisfying[0], True
    return None, False



def _subtype_of(
    node: WriteNode,
    keyed: KeyedIndex,
    key_by_id: dict[str, str],
    chapter_place_ids: set[str],
    subtypes: Mapping[str, LocationSubtype],
) -> str:
    """Where a place sits in the hierarchy. `""` when nothing decides it.

    Three sources, in priority order, and NO fourth:

    1. the hand-authored seed, which is the only thing that can say REGION,
       SETTLEMENT or WILD, because no key distinguishes a village from a wood;
    2. the key convention -- a suffixed key is a room, an unsuffixed one is the
       building containing it. Deterministic, free, and never wrong;
    3. the chapter's own place, which is the thing the chapter is about and
       therefore the SITE its keyed areas hang beneath.

    The seed goes FIRST on purpose. `The Village of Barovia` is a chapter's own
    place and derives SITE, and a human has written SETTLEMENT beside it; a key
    convention does not overrule a human, and a village labelled a building
    would be wrong in a way no query could see.

    Anything that reaches the end stays `""`. There is no default rung: a place
    with no key and no entry is genuinely unclassified, and filing it somewhere
    plausible would make a guess indistinguishable from a derivation.

    Everything is gated on the node BEING a location. A rung is a position in
    the LOCATION hierarchy, so `E5d. Trapdoor` -- keyed, but typed ITEM by the
    extractor -- gets none. The node passed in must already carry its unioned
    types, so a disputed `:LOCATION:SETTING` still qualifies on the half of the
    disagreement that is on the ladder.
    """
    if LOCATION_LABEL not in node.labels:
        return ""
    authored = subtypes.get(slugify(node.name))
    if authored is not None:
        return authored.value
    key = key_by_id.get(node.id)
    if key:
        return keyed.subtype_for_key(key).value
    if node.id in chapter_place_ids:
        return LocationSubtype.SITE.value
    return ""


def _mark_conflicts(edges: list[WriteEdge], report: FilterReport) -> list[WriteEdge]:
    """Record every mutual-exclusion conflict on both edges. Drop neither.

    Run over MINTED IDS rather than names: a name is not unique in canon -- a
    disputed `entity_type` leaves `Tatyana` as an NPC node and a LORE node -- and
    a name-keyed check would report an edge as contradicting an edge about a
    different node.

    Exactly one asymmetry, and it is the only place anything here picks a
    winner: an ACCEPTED edge beats a PROPOSED one, because the accepted layer is
    derived from the document's structure and cannot hallucinate. The loser is
    marked `conflicted` and still written -- demoted, never deleted, so a
    reviewer can see what was proposed and why it lost.

    Two PROPOSED edges are BOTH kept as proposed. There is no oracle here:
    recall cannot rank extractors, and a wiki oracle failed because 8 of the 13
    core NPCs have no page. Choosing between them would put a guess into the
    graph wearing the same clothes as a checked fact.

    Two ACCEPTED edges in conflict would be a defect in the deriver rather than
    a judgment call, so neither is demoted and the pair is reported like any
    other -- silently preferring one would hide the defect.
    """
    conflicts = exclusive_conflicts([(e.source_id, e.target_id, e.rel_type) for e in edges])
    if not conflicts:
        return edges

    demoted: set[int] = set()
    contradicts: dict[int, list[str]] = {}
    for left, right in conflicts:
        report.conflicts.append(
            f"{edges[left].source_id} -{edges[left].rel_type.value}|"
            f"{edges[right].rel_type.value}-> {edges[left].target_id}"
            f"  ({edges[left].status} vs {edges[right].status})"
        )
        contradicts.setdefault(left, []).append(edges[right].rel_type.value)
        contradicts.setdefault(right, []).append(edges[left].rel_type.value)
        left_accepted = edges[left].status == ACCEPTED
        right_accepted = edges[right].status == ACCEPTED
        if left_accepted and not right_accepted:
            demoted.add(right)
        elif right_accepted and not left_accepted:
            demoted.add(left)
    report.exclusive_conflicts = len(conflicts)
    report.conflicted_edges = len(demoted)

    return [
        replace(
            edge,
            conflict=",".join(sorted(set(contradicts[index]))),
            conflicted=index in demoted,
        )
        if index in contradicts
        else edge
        for index, edge in enumerate(edges)
    ]


def _mark_node_status(
    nodes: list[WriteNode], edges: list[WriteEdge], keyed_ids: set[str]
) -> list[WriteNode]:
    """A node is ACCEPTED when the book keys it, or an accepted edge attaches.

    Both halves are needed. A keyed place is the book's own assertion that the
    place exists -- `E5g. Undercroft` is a heading, not a model's opinion -- and
    it must stand even for a room with no edges at all. An unkeyed node earns
    acceptance from the derived structural layer touching it, in either
    direction: an edge derived from the document's nesting is evidence about
    both of its endpoints, not only its source.

    A `conflicted` edge confers nothing: it is a proposed edge that already
    lost.
    """
    accepted_ids = set(keyed_ids)
    for edge in edges:
        if edge.status == ACCEPTED:
            accepted_ids.update({edge.source_id, edge.target_id})
    return [
        replace(node, status=ACCEPTED if node.id in accepted_ids else PROPOSED)
        for node in nodes
    ]


def restrict_to_accepted(
    nodes: list[WriteNode], edges: list[WriteEdge]
) -> tuple[list[WriteNode], list[WriteEdge]]:
    """The `--accepted-only` view: derived edges, and the nodes they need.

    A node with nothing attached is dropped even when it is accepted in its own
    right, because the alternative is writing an isolated node the loop's own
    predicate would then count as canon.

    Pure, and separate from `plan_write`, so the question this task exists to
    answer -- what is LEFT when the unvetted layer is stripped -- can be asked of
    a plan without touching a database, and so that the default path is
    unchanged by the flag's existence.
    """
    kept_edges = [edge for edge in edges if edge.status == ACCEPTED]
    needed = {edge.source_id for edge in kept_edges} | {edge.target_id for edge in kept_edges}
    return [node for node in nodes if node.id in needed], kept_edges


def plan_write(
    nodes: list[CandidateNode],
    edges: list[CandidateEdge],
    gazetteer: Gazetteer,
    chapter_slug: str,
    *,
    chapter_place: str | None = None,
    subtypes: Mapping[str, LocationSubtype] | None = None,
    artifacts: Container[str] | None = None,
) -> tuple[list[WriteNode], list[WriteEdge], FilterReport]:
    """Decide exactly what to write, and count every candidate that is dropped.

    `chapter_slug` is the CALLER's, not the artifact's: the loop keys the graph
    on the corpus filename while the extractor derived its slug from the chapter
    title, and the graph must be keyed on the one the loop discovers.

    `chapter_place` IS A NODE, and this is the fix for a severed hierarchy.
    `derive_structure` hangs every top-level keyed area off the chapter's own
    place -- `The Village of Barovia CONTAINS Church` -- naming it after the
    chapter title, which is a heading rather than anything the extractor
    proposed. No candidate was ever called that, so all seven of chapter 3's
    chapter-level CONTAINS edges were dropped as dangling and the graph held
    rooms nested inside `Church` while `Church` itself hung from nothing.
    Minting the node makes those edges land. It is exempt from the gazetteer and
    ACCEPTED for the same reason a keyed area is: the book's own heading is the
    book asserting the place exists, not a model's opinion.

    `subtypes` is the hand-authored half of the LOCATION hierarchy, slug ->
    rung, read from a seed by the caller the way the gazetteer is. It WINS over
    the derived rung: the village is a chapter's own place, which derives SITE,
    and a human has said SETTLEMENT. A key does not overrule a human.

    `artifacts` is the slugs of the items that wear `:Artifact`, out of the same
    seed and handed in the same way. Wholly authored, with no derived half at
    all: no convention in the text marks an artifact the way a suffixed key
    marks a room. An item absent from it stays plain `:ITEM`, the same
    no-default rule the rungs follow.

    Filters, in this order:

    1. self-loops -- free, and one survived even the two-stage classifier
    2. constraint violations -- ~30% of LLM edges are type-impossible. Endpoint
       types come from the FULL candidate node set, before the gazetteer has
       removed any: a node dropped later still typed its endpoint correctly.
    3. gazetteer -- bare generic nouns, 89% of chapter 4's rejected. A keyed
       place survives REGARDLESS: the wiki indexes 38 locations against the
       book's 414 keyed areas, so a keyed room's absence is expected and is not
       evidence against the room.
    4. edges left dangling by a dropped node, and edges whose endpoint name is
       answered by two nodes of different types -- unless the domain/range
       table admits exactly one of them, in which case the edge is kept and
       STAMPED `endpoint_resolved="constraint"` (see `_resolve_endpoint`)

    Then a fifth step that filters NOTHING: every surviving node and edge is
    stamped `accepted` or `proposed`, and every mutual-exclusion conflict is
    recorded on both of its edges. A third of the LLM edges in the live
    chapter-3 graph are wrong while all 37 derived edges are sound, and until
    now no query could tell the two apart.

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
    keyed = keyed_index(nodes)
    kept_nodes: list[CandidateNode] = []
    for node in nodes:
        if gazetteer.is_known(node.name) or slugify(node.name) in keyed.place_slugs:
            kept_nodes.append(node)
            continue
        report.gazetteer_dropped += 1
        report.dropped_gazetteer.append(f"{node.entity_type} {node.name}")

    # Ids, and the indexes the edges resolve through.
    by_id: dict[str, WriteNode] = {}
    ids_by_name: dict[str, set[str]] = {}
    ids_by_section: dict[int, set[str]] = {}
    provenance_rank: dict[str, int] = {}
    #: id -> every type any candidate for it gave, unioned at the end into the
    #: node's labels. Two samples disagreeing is a disagreement about a label,
    #: not about the world, and both readings are kept.
    types_seen: dict[str, list[str]] = {}
    # Ids the BOOK ITSELF asserts -- through a keyed heading or the chapter's own
    # title -- which is the half of node acceptance that owes nothing to any
    # edge: a keyed room with no relationships is still the book's own.
    keyed_ids: set[str] = set()
    #: id -> the key that minted it, so the hierarchy rung can be read off the
    #: same key rather than re-derived from a name.
    key_by_id: dict[str, str] = {}
    for node in kept_nodes:
        node_key, undecidable = keyed.key_for(node.name, node.section_index)
        if undecidable:
            # A name two sections key, mentioned from neither. Choosing one
            # would invent a room; the count says how often the book's own
            # repetition defeats this.
            report.undecidable_keyed += 1
            report.dropped_undecidable_keyed.append(
                f"{node.entity_type} {node.name} "
                f"({'/'.join(keyed.keys_by_place[slugify(node.name)])})"
            )
            continue
        if not slugify(node.name) and not node_key:
            # A name that slugifies to nothing cannot be given an id at all.
            report.unnameable += 1
            continue
        node_id = mint_id(chapter_slug, node.name, node_key)
        if node_key:
            keyed_ids.add(node_id)
            key_by_id[node_id] = node_key
        # Every kept candidate is indexed under its own folded name and its own
        # section, duplicate or not: a second spelling of a name already written
        # -- straight for curly apostrophe, say -- must still lead an edge to
        # the node, and an edge derived from a section must be able to reach the
        # room that section keys.
        ids_by_name.setdefault(_fold(node.name), set()).add(node_id)
        if keyed.keys_own_name(node.name, node.section_index):
            ids_by_section.setdefault(node.section_index, set()).add(node_id)

        # Spelling tiebreak, highest rank wins and the earliest wins a tie:
        #   2  the section that keys this room, spelling it as the book does
        #   1  the section that keys this room
        #   0  anything else -- a passing mention, or an unkeyed entity
        # What this decides is now the NAME and only the name: where an entity
        # appears is a set of `:Mention` nodes rather than one section heading on
        # the node. The name still matters more than it did, because it is what
        # the mention scan looks for in every section of the book -- a node
        # carrying the extractor's `burgomaster's mansion` instead of the book's
        # `E4. Burgomaster's Mansion` finds fewer of its own appearances.
        rank = 0
        if keyed.keys_own_name(node.name, node.section_index):
            rank = 2 if keyed.spells_it_as_the_book_does(node.name, node.section_index) else 1
        # The TYPE unions across every candidate for this id, whichever one wins
        # the provenance tiebreak. The tiebreak is about which section to cite;
        # it is not evidence about what the thing is, and letting it pick a
        # single type would put back the winner-picking that folding the type
        # out of the id removed.
        types_seen.setdefault(node_id, []).append(node.entity_type)
        if node_id in by_id:
            report.duplicate_nodes += 1
            if rank > provenance_rank[node_id]:
                by_id[node_id] = _as_write_node(node, node_id, chapter_slug)
                provenance_rank[node_id] = rank
            continue
        by_id[node_id] = _as_write_node(node, node_id, chapter_slug)
        provenance_rank[node_id] = rank

    # The chapter's own place, which `derive_structure` has already used as the
    # source of every top-level CONTAINS edge and which nothing else mints.
    #
    # ONLY when the chapter keys at least one area. A title is not evidence of a
    # place -- chapter 1 keys Tarokka card results, not rooms -- and the deriver
    # applies the identical guard before it emits a single chapter-level edge.
    # Minting a node here for a chapter that keys nothing would put a place in
    # the graph that no edge references and the book never established.
    if chapter_place and keyed.place_slugs:
        place_id = mint_id(chapter_slug, chapter_place)
        keyed_ids.add(place_id)
        # No key, so no rung from `key_by_id`. A chapter is about a discrete
        # thing -- a village, a castle, an abbey -- and SITE is the rung for the
        # thing itself, with its keyed areas hanging beneath it. A hand-authored
        # entry overrides this, which is how the village becomes a SETTLEMENT.
        chapter_place_ids = {place_id}
        types_seen.setdefault(place_id, []).append(LOCATION_LABEL)
        ids_by_name.setdefault(_fold(chapter_place), set()).add(place_id)
        # Not `setdefault` on a dict that may already hold this id from a
        # candidate: the candidate carries a real section heading and this does
        # not, and overwriting it would send a reader to nowhere.
        if place_id not in by_id:
            by_id[place_id] = WriteNode(
                id=place_id,
                name=chapter_place,
                entity_types=(LOCATION_LABEL,),
                chapter_slug=chapter_slug,
            )
            provenance_rank[place_id] = 0
            report.derived_nodes += 1
    else:
        chapter_place_ids = set()

    # Types first, the authored labels second, in two passes: `_subtype_of` and
    # `artifact_label` both read `labels`, and a node still carrying one
    # sample's type would answer "not a location" for a place four other samples
    # typed LOCATION, or "not an item" for a disputed `:ITEM:LORE`.
    subtypes = subtypes or {}
    artifacts = artifacts if artifacts is not None else frozenset()
    by_id = {
        node_id: replace(written, entity_types=tuple(sorted(set(types_seen[node_id]))))
        for node_id, written in by_id.items()
    }
    by_id = {
        node_id: replace(
            written,
            location_subtype=_subtype_of(
                written, keyed, key_by_id, chapter_place_ids, subtypes
            ),
            # The seed's own matching rule: the slug of the WHOLE name, never a
            # substring. `Holy Symbol` and `Holy Symbol of Ravenkind` are two
            # different objects in this book, and the ITEM gate lives in
            # `artifact_label` so a non-item authored by name is filtered where
            # the label is decided rather than here.
            is_artifact=slugify(written.name) in artifacts,
        )
        for node_id, written in by_id.items()
    }

    report.ambiguous_names = sorted(name for name, ids in ids_by_name.items() if len(ids) > 1)

    # 4 -- edges whose endpoints did not survive, or which name an entity that
    # two surviving nodes both answer to.
    write_edges: list[WriteEdge] = []
    seen: set[tuple[str, str, str]] = set()
    for edge in surviving_edges:
        # Coerced before anything is built from it: this is the only thing
        # standing between a corrupt artifact and interpolated Cypher.
        rel = RelationshipType(edge.rel_type.strip())
        source_ids = _endpoint_ids(edge.source_name, edge.section_index, keyed, ids_by_name,
                                   ids_by_section)
        target_ids = _endpoint_ids(edge.target_name, edge.section_index, keyed, ids_by_name,
                                   ids_by_section)
        label = f"{edge.source_name} -{edge.rel_type}-> {edge.target_name}"
        if not source_ids or not target_ids:
            report.dangling_edges += 1
            report.dropped_dangling.append(label)
            continue
        # A disputed name is settled by the domain/range table when the table
        # admits exactly one of the candidates, and by nothing otherwise --
        # choosing then would manufacture an assertion the extractor never
        # made, the same reason a reversal is detected and never performed.
        domain, range_ = RELATIONSHIP_DOMAIN_RANGE.get(rel, (None, None))
        source_id, source_resolved = _resolve_endpoint(source_ids, by_id, domain)
        target_id, target_resolved = _resolve_endpoint(target_ids, by_id, range_)
        if source_id is None or target_id is None:
            report.ambiguous_edges += 1
            report.dropped_ambiguous.append(label)
            continue
        key = (source_id, rel.value, target_id)
        if key in seen:
            report.duplicate_edges += 1
            continue
        seen.add(key)
        # Counted BELOW the duplicate check, not above it: this list is what
        # downstream reads to know where the constraint check is vacuous, and
        # two identical resolved candidates would otherwise put a phantom entry
        # in it for an edge that was written once.
        resolved = "constraint" if (source_resolved or target_resolved) else ""
        if resolved:
            report.endpoint_resolved += 1
            report.resolved_endpoints.append(
                f"{label}  ->  {source_id if source_resolved else target_id}"
            )
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
                endpoint_resolved=resolved,
            )
        )

    # 5 -- contradictions, and the trust split. Neither drops anything: this is
    # the point at which the graph starts recording HOW MUCH it can be trusted
    # rather than only what it holds.
    write_edges = _mark_conflicts(write_edges, report)
    write_nodes = _mark_node_status(list(by_id.values()), write_edges, keyed_ids)

    report.accepted_edges = sum(1 for e in write_edges if e.status == ACCEPTED)
    report.proposed_edges = len(write_edges) - report.accepted_edges
    report.accepted_nodes = sum(1 for n in write_nodes if n.status == ACCEPTED)
    report.proposed_nodes = len(write_nodes) - report.accepted_nodes
    report.written_nodes = len(write_nodes)
    report.written_edges = len(write_edges)
    return write_nodes, write_edges, report


def ensure_schema(session) -> None:
    """Create the constraints and indexes `GRAPH_SCHEMA` declares.

    Declared once in `backend/graph/schema.py` and applied here, rather than
    restating any of it. Schema changes cannot share a transaction with writes
    in Neo4j, so this runs before the write rather than inside it -- it creates
    nothing a rollback would need to undo.

    Only Neo4j's own errors are tolerated, and only the already-exists family is
    silent: that is the normal case on every run after the first. Anything else
    is logged with the statement that produced it. A bare `except Exception` here
    would swallow a bad URI, an auth failure, or a malformed statement and leave
    the write to fail later with no trace of the real cause.
    """
    for statement in [*GRAPH_SCHEMA["constraints"], *GRAPH_SCHEMA["indexes"]]:
        try:
            session.run(statement)
        except Neo4jError as exc:
            if (exc.code or "") in _SCHEMA_EXISTS_CODES:
                continue
            logger.warning("schema statement failed: %s -- %s", statement, exc)


#: Every canon node this chapter's write is responsible for, in two arms.
#:
#: `MENTIONED_IN` used to answer this in one hop, and it is gone: it recorded
#: where an entity was EXTRACTED rather than where it appears, which is the
#: defect `:Mention` exists to repair. Its BOOKKEEPING job -- "which nodes does
#: this chapter own" -- has to be reconstructed from records that are true about
#: the book, and there are exactly two:
#:
#:   1. a `:Mention` this chapter made, i.e. the chapter's text names the entity;
#:   2. an ontology edge this chapter asserted, i.e. `r.chapter_slug`.
#:
#: The union is needed, and neither arm alone is enough. Chapter 3 writes
#: `Ismark Kolyanovich`, whose full name the chapter's prose never spells (it
#: says "Ismark"), so arm 1 misses him and arm 2 catches him through his edges.
#:
#: THE UNION IS STILL NOT TOTAL, and that is a real narrowing against
#: MENTIONED_IN, which covered every written node by construction. An entity
#: with neither a textual appearance nor a single edge is invisible here: across
#: the three loaded chapters that is one node (`Tome of Strahd`, written by the
#: introduction). The consequence is bounded -- `--replace` leaves such a node
#: behind rather than deleting it, and the following write MERGEs onto it -- and
#: it is stated rather than papered over, because the alternative is minting a
#: mention with no evidence, which is the fabrication this whole design refuses.
_CHAPTER_ENTITIES = f"""
CALL () {{
    MATCH (:Mention {{plane:$plane, chapter_slug:$slug}})-[:{REFERS_TO}]->(e:Entity)
    WHERE e.plane = $plane
    RETURN e
  UNION
    MATCH (e:Entity {{plane:$plane}})-[r]-(:Entity)
    WHERE r.plane = $plane AND r.chapter_slug = $slug
    RETURN e
}}
WITH DISTINCT e AS n
"""


def count_canon_nodes(session, chapter_slug: str) -> int:
    """How many canon nodes this chapter's write owns. The loop's own predicate."""
    record = session.run(
        _CHAPTER_ENTITIES + "RETURN count(n) AS c",
        {"slug": chapter_slug, "plane": CANON_PLANE},
    ).single()
    return record["c"] if record else 0


def count_mentions(session, chapter_slug: str) -> int:
    """How many `:Mention` nodes this chapter holds."""
    record = session.run(
        "MATCH (m:Mention {plane:$plane, chapter_slug:$slug}) RETURN count(m) AS c",
        {"slug": chapter_slug, "plane": CANON_PLANE},
    ).single()
    return record["c"] if record else 0


#: The chapters a canon node belongs to, by the same two records
#: `_CHAPTER_ENTITIES` unions -- a mention made in that chapter, or an ontology
#: edge that chapter asserted. Written as pattern comprehensions rather than a
#: second CALL so it can hang off an already-bound `n`.
_CHAPTERS_OF_NODE = f"""
[ (n)<-[:{REFERS_TO}]-(m:Mention) WHERE m.plane = $plane | m.chapter_slug ]
+ [ (n)-[r2]-() WHERE r2.plane = $plane | r2.chapter_slug ]
"""


def _delete_chapter(tx, chapter_slug: str) -> tuple[int, int]:
    """Delete this chapter's canon relationships, and the nodes only it owns.

    Scoped by `plane` AND `chapter_slug` on every statement, so another chapter's
    canon and every campaign's play are untouchable from here. A node still
    carrying a relationship this scope does not cover is refused rather than
    DETACH DELETEd -- see `CampaignDataAttached`.

    A NODE ANOTHER CHAPTER ALSO OWNS SURVIVES, keeping only this chapter's
    mentions. Madam Eva is one node for the whole book, and re-writing chapter 3
    must cost the introduction nothing -- deleting her would silently truncate a
    chapter nobody asked to touch. So the delete set is the nodes whose ONLY
    record is this chapter's, and the check for attached campaign data is
    narrowed to exactly those: a node that is going to survive cannot take
    anything down with it.

    THE SPINE IS DELETED WITHOUT `DETACH`, on purpose. Mentions go first because
    they are the only things pointing into a section besides its chapter; then
    the section's own two relationship kinds; then the sections. If anything else
    has attached itself to a section by then, `DELETE s` raises and the whole
    chapter rolls back -- which is the loud failure, not a silent DETACH that
    takes an unknown edge with it.

    ALIASES ARE UNPICKED THE SAME WAY. Their edges are deleted with the nodes
    they hang off, and the `:Alias` node itself is global -- it goes only when
    the last entity answering to it has gone, because the alternative is
    deleting `Barovia` the name because the village was rewritten.

    `ALIAS_OF` and `CO_OCCURS_WITH` are listed beside `REFERS_TO` and
    `DESCRIBES` in the campaign-data check as a STATEMENT OF INTENT, and a
    mutation pass showed neither changes anything today: neither carries a
    `chapter_slug`, so `NOT (r.plane = $plane AND r.chapter_slug = $slug)` is
    `NOT (null AND null)` -- null, which a WHERE excludes anyway. They are kept
    because those four types are exactly the ones this function removes, and a
    reader should be able to see that set in one place rather than deduce half
    of it from Cypher's null semantics. No test can distinguish their removal;
    that is recorded rather than papered over with a test that would not fail.

    CO-OCCURRENCES GO WITH THE MENTIONS and are not counted into `edges`. They
    hang off a `:Mention`, which is DETACH DELETEd below, so nothing has to
    scope them; and `edges` is the figure a human compares against
    `written_edges`, which a co-occurrence is not. Giving them a `chapter_slug`
    would sweep them into that count and make the comparison unreadable.
    """
    scope = {"slug": chapter_slug, "plane": CANON_PLANE}
    doomed = _CHAPTER_ENTITIES + f"""
    WITH n, [s IN ({_CHAPTERS_OF_NODE}) WHERE s <> $slug] AS others
    WHERE size(others) = 0
    """
    attached = tx.run(
        doomed
        + f"""
        MATCH (n)-[r]-()
        WHERE NOT type(r) IN ['{REFERS_TO}', '{DESCRIBES}', '{ALIAS_OF}',
                              '{CO_OCCURS_WITH}']
          AND NOT (r.plane = $plane AND r.chapter_slug = $slug)
        RETURN count(r) AS c
        """,
        scope,
    ).single()["c"]
    if attached:
        raise CampaignDataAttached(chapter_slug, attached)

    # The node set is read BEFORE any delete: deleting this chapter's mentions
    # removes half of what identifies the nodes it owns.
    ids = tx.run(doomed + "RETURN collect(n.id) AS ids", scope).single()["ids"]

    # Counted, because it is compared against what the plan wrote.
    edges = tx.run(
        """
        MATCH ()-[r]->()
        WHERE r.chapter_slug = $slug AND r.plane = $plane
        DELETE r
        RETURN count(r) AS c
        """,
        scope,
    ).single()["c"]
    # NOT counted into `edges`: a reader compares that figure against
    # `written_edges`, and mentions are nodes rather than ontology edges.
    tx.run(
        "MATCH (m:Mention {plane:$plane, chapter_slug:$slug}) DETACH DELETE m",
        scope,
    )
    tx.run(
        f"""
        MATCH (:Chapter {{slug:$slug}})-[h:{HAS_SECTION}]->(s:Section)
        OPTIONAL MATCH (s)-[d:{DESCRIBES}]->()
        DELETE h, d
        WITH DISTINCT s
        DELETE s
        """,
        scope,
    )
    # BEFORE the nodes: `DELETE n` is deliberately not `DETACH DELETE`, so a
    # surviving `ALIAS_OF` would raise -- correctly, but for the wrong reason,
    # since these edges are this write's to remove.
    #
    # The names are COLLECTED FIRST because they are the only aliases this
    # delete may afterwards remove. Sweeping `MATCH (a:Alias) WHERE NOT
    # (a)-[:ALIAS_OF]->()` over the whole database instead would be correct on
    # the day it was written and one bad edit away from a chapter's rewrite
    # emptying the book's entire name index -- which is not hypothetical: a
    # mutation run of exactly that edit did it to the live graph while this was
    # being built. A delete should not be able to reach what it never touched.
    orphan_candidates = tx.run(
        f"""
        MATCH (n:Entity {{plane:$plane}})<-[r:{ALIAS_OF}]-(a:{ALIAS_LABEL})
        WHERE n.id IN $ids
        DELETE r
        RETURN collect(DISTINCT a.name) AS names
        """,
        {"ids": ids, "plane": CANON_PLANE},
    ).single()["names"]
    nodes = tx.run(
        """
        MATCH (n:Entity {plane:$plane}) WHERE n.id IN $ids
        DELETE n
        RETURN count(n) AS c
        """,
        {"ids": ids, "plane": CANON_PLANE},
    ).single()["c"]
    # An alias nothing answers to any more. Emptiness rather than chapter is the
    # right test WITHIN that set, because an `:Alias` is global: `Barovia`
    # survives a rewrite of the village because the region still answers to it.
    tx.run(
        f"""
        MATCH (a:{ALIAS_LABEL})
        WHERE a.name IN $names AND NOT (a)-[:{ALIAS_OF}]->()
        DETACH DELETE a
        """,
        {"names": orphan_candidates},
    )
    return nodes, edges


def _write_node(tx, node: WriteNode) -> None:
    """MERGE on the id, so a second chapter naming this entity adds no node.

    The labels are interpolated because Cypher cannot parameterize one. Every
    label comes from `WriteNode.labels` or `WriteNode.subtype_label`, which
    admit only `CANON_LABELS` and `LOCATION_SUBTYPE_LABELS`, so the interpolated
    text can only ever be one of the ontology's own names.

    TYPE LABELS UNION. `SET e:A:B` adds to whatever the node already carries,
    which is what makes a chapter that types `Barovia` a SETTING add to, rather
    than replace, the chapter that typed it a LOCATION.

    A HIERARCHY RUNG REPLACES. The rungs are one ladder, so a place that was a
    settlement and is now a region must not end up both -- and `SET` alone would
    leave it wearing the pair. Editing the authored seed and re-writing is how
    that happens, on a node another chapter keeps alive through the replace.

    The REMOVE is emitted ONLY when this write actually has a rung to put there,
    and the reachable case is a chapter that MENTIONS a place versus the chapter
    that is ABOUT it. Both reach one id, because an unkeyed place is global:
    chapter 5 is about `Vallaki` and writes its rung, chapter 3 names it in
    passing and derives none. Whichever lands second must not be the one that
    decides, so a write with nothing to say about the hierarchy says nothing.

    NOT the keyed case, which cannot arise: a keyed id carries its own chapter
    and key, so two chapters can never write one keyed node. An earlier draft of
    this docstring cited `Church` keyed in chapter 3 and mentioned in chapter 4,
    and `mint_id` makes that two different nodes. The guard is right; that
    reason for it was not.

    `:Artifact` IS ONLY EVER ADDED, and that is deliberately a third behaviour
    rather than a second copy of either. It is not a rung -- nothing is its
    sibling, so there is nothing for it to supersede and nothing that supersedes
    it -- and the rung REMOVE above is scoped to `LOCATION_SUBTYPE_LABELS`,
    which contains neither this label nor the `:ITEM` it narrows. A node that a
    disputed type makes both an item and a place therefore keeps `:Artifact`
    through every rung its place-half is rewritten with. Un-authoring one is a
    `--replace`, not a REMOVE emitted from the absence of a seed entry: the
    absence would also be there for a caller that simply passed no seed.
    """
    labels = "".join(f":{label}" for label in node.labels)
    clauses = []
    if labels:
        clauses.append(f"SET e{labels}")
    if node.subtype_label:
        superseded = "".join(
            f":{rung}" for rung in sorted(LOCATION_SUBTYPE_LABELS - {node.subtype_label})
        )
        clauses.append(f"REMOVE e{superseded}")
        clauses.append(f"SET e:{node.subtype_label}")
    if node.artifact_label:
        clauses.append(f"SET e:{node.artifact_label}")
    clauses.append("SET e += $props")
    tx.run(
        f"MERGE (e:Entity {{id:$id}}) {' '.join(clauses)}",
        {"id": node.id, "props": node.properties},
    )


def _write_spine(tx, spine: "ChapterSpine") -> None:
    """The document's own skeleton: book, chapter, sections, and their places.

    Nothing here is a judgment. A chapter has the sections it has, in the order
    it has them, and `(chapter.index, section.index)` is therefore the order the
    book reveals things -- which is what makes "what could the party know by
    chapter 3" a range query rather than bookkeeping.

    The index is written BOTH on the `:Chapter` and on its `HAS_CHAPTER` edge, as
    the design specifies. That is the same fact twice and would normally be a
    defect; it is accepted here because a node property is what an ORDER BY
    reads cheaply and the edge property is what makes the spine legible in the
    Browser, and neither is derived from anything a model said, so there is
    nothing for them to drift with respect to.

    `DESCRIBES` is MATCHed on both endpoints rather than MERGEd into existence:
    the target is an `:Entity` this same transaction has already written, and a
    MERGE that quietly created a bare node instead would put a place in the graph
    that no extraction ever proposed.
    """
    tx.run(
        f"""
        MERGE (b:Book {{slug:$book_slug}})
        SET b.title = $book_title, b.plane = $plane
        MERGE (c:Chapter {{slug:$chapter_slug}})
        SET c.title = $chapter_title, c.index = $chapter_index, c.plane = $plane
        MERGE (b)-[h:{HAS_CHAPTER}]->(c)
        SET h.index = $chapter_index
        """,
        {
            "book_slug": spine.book_slug,
            "book_title": spine.book_title,
            "chapter_slug": spine.chapter_slug,
            "chapter_title": spine.chapter_title,
            "chapter_index": spine.chapter_index,
            "plane": CANON_PLANE,
        },
    )
    for section in spine.sections:
        tx.run(
            f"""
            MATCH (c:Chapter {{slug:$chapter_slug}})
            MERGE (s:Section {{id:$id}})
            SET s += $props
            MERGE (c)-[h:{HAS_SECTION}]->(s)
            SET h.index = $index
            """,
            {
                "chapter_slug": spine.chapter_slug,
                "id": section.id,
                "props": section.properties,
                "index": section.index,
            },
        )
    for section_id, location_id in spine.describes:
        written = tx.run(
            f"""
            MATCH (s:Section {{id:$section_id}}), (e:Entity {{id:$location_id}})
            MERGE (s)-[d:{DESCRIBES}]->(e)
            SET d += $props
            RETURN count(d) AS c
            """,
            {
                "section_id": section_id,
                "location_id": location_id,
                "props": {"plane": CANON_PLANE, "chapter_slug": spine.chapter_slug},
            },
        ).single()["c"]
        if not written:
            raise ValueError(f"DESCRIBES endpoint missing: {section_id} -> {location_id}")


def _write_alias(tx, alias: "WriteAlias") -> None:
    """One surface form, and the `ALIAS_OF` edge to the entity it names.

    The `:Alias` node is MERGEd on `name` alone and is therefore GLOBAL: two
    entities answering to `Barovia` share one node with two `ALIAS_OF` edges,
    which is the graph saying out loud that the name is ambiguous rather than
    quietly picking one of them. `normalized` is SET rather than merged on,
    because it is a pure function of `name` and cannot disagree with it.

    The entity is MATCHed and a miss RAISES, the same rule `_write_edge` and
    `_write_mention` follow: a `MATCH ... MERGE` that matches nothing writes
    nothing and says nothing, and an entity that silently lost its own name is
    an entity no lookup can reach.

    `ALIAS_OF` carries `plane` but NO `chapter_slug`. What a thing is called is
    not a claim one chapter owns -- the entity node is global for exactly the
    same reason -- so stamping a chapter here would make whichever chapter named
    it first the owner of every later spelling.
    """
    written = tx.run(
        f"""
        MATCH (e:Entity {{id:$entity_id}})
        MERGE (a:{ALIAS_LABEL} {{name:$name}})
        SET a += $props
        MERGE (a)-[r:{ALIAS_OF}]->(e)
        SET r.plane = $plane
        RETURN count(a) AS c
        """,
        {
            "entity_id": alias.entity_id,
            "name": alias.name,
            "props": alias.properties,
            "plane": CANON_PLANE,
        },
    ).single()["c"]
    if not written:
        raise ValueError(f"alias endpoint missing: {alias.name!r} of {alias.entity_id}")


#: Give every canon entity in the plane its own name as an `:Alias`.
#:
#: DELIBERATELY NOT SCOPED TO THIS CHAPTER, and the exception is narrow and
#: principled: an entity's name is already on the entity, so this asserts
#: nothing a chapter could disagree with, and it is what makes "resolve a name
#: through `:Alias`" a TOTAL rule rather than one with a migration hole in it.
#: Without it, an entity written before aliases existed -- or by `load_seed`,
#: which writes canon nodes and knows nothing about this -- would be invisible
#: both to a lookup and to the scan, which is the silent zero all of this
#: exists to remove.
#:
#: Runs AFTER `_delete_chapter`, so it does not re-mint a name for a node this
#: write is about to remove.
_BACKFILL_ALIASES = f"""
MATCH (e:Entity {{plane:$plane}})
WHERE e.name IS NOT NULL AND trim(e.name) <> ''
MERGE (a:{ALIAS_LABEL} {{name:e.name}})
SET a.normalized = toLower(trim(replace(e.name, '’', "'")))
MERGE (a)-[r:{ALIAS_OF}]->(e)
SET r.plane = $plane
RETURN count(a) AS c
"""


def _write_mention(tx, mention: "WriteMention") -> None:
    """One (entity, section) pair, with the words that say so.

    MERGEd on the composite id, so re-scanning a chapter updates its mentions
    rather than doubling them.

    Every endpoint is MATCHed and a miss RAISES, for the same reason
    `_write_edge` does: a `MATCH ... MERGE` that matches nothing writes nothing
    and reports no error, which is exactly how a chapter acquires fewer mentions
    than it scanned with nothing appearing to fail. That covers the `:Alias`
    endpoints too -- the scan found the entity UNDER one of these spellings, so
    an alias node missing at write time means the graph disagrees with the scan
    about what the entity is called.

    `USES_ALIAS` is written LAST and only after the mention exists, so a mention
    can never be left pointing at a spelling while missing its own entity.
    """
    written = tx.run(
        f"""
        MATCH (e:Entity {{id:$entity_id}}), (s:Section {{id:$section_id}})
        MERGE (m:Mention {{id:$id}})
        SET m += $props
        MERGE (m)-[:{REFERS_TO}]->(e)
        MERGE (m)-[:{IN_SECTION}]->(s)
        RETURN count(m) AS c
        """,
        {
            "id": mention.id,
            "entity_id": mention.entity_id,
            "section_id": mention.section_id,
            "props": mention.properties,
        },
    ).single()["c"]
    if not written:
        raise ValueError(
            f"mention endpoint missing: {mention.entity_id} in {mention.section_id}"
        )

    for use in mention.uses:
        linked = tx.run(
            f"""
            MATCH (m:Mention {{id:$id}}), (a:{ALIAS_LABEL} {{name:$name}})
            MERGE (m)-[u:{USES_ALIAS}]->(a)
            SET u.occurrences = $occurrences, u.plane = $plane
            RETURN count(u) AS c
            """,
            {
                "id": mention.id,
                "name": use.name,
                "occurrences": use.occurrences,
                "plane": CANON_PLANE,
            },
        ).single()["c"]
        if not linked:
            raise ValueError(
                f"alias {use.name!r} used by {mention.id} is not in the graph"
            )


def _write_co_occurrence(tx, co_occurrence: "CoOccurrence") -> None:
    """One mention, and one other entity its own sentence also names.

    MERGEd on the pair, so a re-scan updates rather than doubles -- and so a
    plan that somehow emitted the same row twice lands one edge. That is why
    `_write_tx` reports `len(planned)` and a test compares it against the
    graph's count: MERGE makes a duplicated plan row invisible in the graph, so
    the only place it can be caught is the difference between those two numbers.

    NO PROPERTIES. It is not in the `accepted`/`proposed` split -- that exists
    because a model guessed a typed relationship and a hand read found a third
    of the guesses wrong, and there is nothing here for a reviewer to accept. It
    carries no `chapter_slug` either: the mention it hangs off carries one, and
    `_delete_chapter` removes these by DETACH DELETEing the mentions rather than
    by scoping on a property, so a second copy of the chapter would be a fact in
    two places free to drift. See `_delete_chapter` for what that costs.

    Both endpoints are MATCHed and a miss RAISES, as everywhere else here: a
    `MATCH ... MERGE` that matches nothing writes nothing and reports no error.
    """
    written = tx.run(
        f"""
        MATCH (m:Mention {{id:$mention_id}}), (e:Entity {{id:$entity_id}})
        MERGE (m)-[r:{CO_OCCURS_WITH}]->(e)
        RETURN count(r) AS c
        """,
        {
            "mention_id": co_occurrence.mention_id,
            "entity_id": co_occurrence.entity_id,
        },
    ).single()["c"]
    if not written:
        raise ValueError(
            f"co-occurrence endpoint missing: {co_occurrence.mention_id} "
            f"-> {co_occurrence.entity_id}"
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


def _known_entities(tx) -> list["EntityNames"]:
    """Every canon entity the graph holds and every name it answers to.

    Read INSIDE the write transaction, after this chapter's nodes and aliases
    have landed, so the scan sees both the entities this chapter minted and every
    entity an earlier chapter did. An entity is global to the book: chapter 3
    naming Castle Ravenloft is a fact about chapter 3 whichever chapter minted
    the castle, and scanning only the chapter's own plan would rebuild, one level
    up, the very defect this replaces.

    The names come through `ALIAS_OF` and nowhere else -- ONE path, which is the
    whole reason an entity's canonical name is itself an `:Alias`. Reading
    `e.name` here as well and unioning would be the second path the design
    refuses: two sources for "what is this called", free to disagree about a
    renamed node. `_BACKFILL_ALIASES` has run by this point, so the union is
    total by construction rather than by hope.

    An entity that arrives here with NO alias is refused. It would contribute no
    mentions and be unreachable by name -- a silent zero, and the failure mode
    this module exists to remove.

    The converse does not hold and is a stated limitation: writing chapter 4 does
    not re-scan chapter 3's sections, so an entity chapter 4 introduces gets no
    chapter-3 mention until chapter 3 is written again. Re-writing costs nothing
    -- the extraction artifacts are on disk and no model is called -- so the fix
    is a re-migration rather than a cross-chapter write that would break the
    one-transaction-per-chapter rule.
    """
    from backend.canon.spine import EntityNames

    known: list[EntityNames] = []
    nameless: list[str] = []
    for record in tx.run(
        f"""
        MATCH (e:Entity {{plane:$plane}})
        OPTIONAL MATCH (a:{ALIAS_LABEL})-[:{ALIAS_OF}]->(e)
        RETURN e.id AS id, e.name AS name, collect(DISTINCT a.name) AS aliases
        """,
        {"plane": CANON_PLANE},
    ):
        aliases = tuple(sorted(n for n in record["aliases"] if n))
        if not aliases:
            nameless.append(record["id"])
            continue
        known.append(EntityNames(id=record["id"], name=record["name"], aliases=aliases))
    if nameless:
        raise ValueError(
            f"{len(nameless)} canon entities carry no :Alias and can never be "
            f"found by name: {', '.join(sorted(nameless)[:5])}"
        )
    return known


def _write_tx(tx, chapter_slug: str, nodes, edges, spine, aliases, replace: bool) -> dict:
    """The whole chapter, in one transaction. Commit or roll back.

    The existing-chapter check lives INSIDE the transaction on purpose: read it
    outside and a concurrent write could land between the check and the write,
    which is the truncation hazard wearing a different hat. `--replace` deletes
    in here too, for the same reason -- a delete that commits before a failed
    write empties a chapter and leaves it looking done.

    THE MENTION SCAN RUNS IN HERE, and that is the same rule rather than an
    exception to it. It needs the entity set as it will be after this write, so
    it cannot run before the nodes land; and its output is what the loop's
    predicate and the replace path both read, so a chapter whose nodes committed
    without its mentions would look half-unwritten. The scan itself is pure --
    `spine.scan_mentions`, deterministic, no model, no cost -- and every rule it
    applies is pinned without a database.

    THE ALIASES LAND BEFORE THE SCAN, for the identical reason. The scan looks
    for an entity under every name `ALIAS_OF` records, so aliases written after
    it would produce a chapter whose mentions were found under last week's set
    of names -- and would take a second write to correct, which is the two-pass
    write this module refuses.

    CO-OCCURRENCE LANDS LAST, and it is the same rule a third time. Every edge
    hangs off a `:Mention` node, so the mentions have to exist first; and it is
    planned from exactly the mentions this transaction just wrote rather than
    from a re-read of the graph, so the pairs and the nodes they point at cannot
    disagree.
    """
    # Imported here rather than at module scope: `spine` imports `mint_id` and
    # `BOOK` from this module, so a top-level import would close the cycle.
    from backend.canon.cooccurrence import (
        co_occurrence_counts,
        plan_co_occurrences,
        widest_sentence,
    )
    from backend.canon.spine import scan_mentions

    existing = tx.run(
        _CHAPTER_ENTITIES + "RETURN count(n) AS c",
        {"slug": chapter_slug, "plane": CANON_PLANE},
    ).single()["c"]

    deleted_nodes = deleted_edges = 0
    if existing and not replace:
        raise ChapterAlreadyWritten(chapter_slug, existing)
    if replace:
        deleted_nodes, deleted_edges = _delete_chapter(tx, chapter_slug)

    for node in nodes:
        _write_node(tx, node)
    for alias in aliases:
        _write_alias(tx, alias)
    tx.run(_BACKFILL_ALIASES, {"plane": CANON_PLANE})
    _write_spine(tx, spine)
    for edge in edges:
        _write_edge(tx, edge)

    entities = _known_entities(tx)
    mentions = scan_mentions(spine.sections, entities, chapter_slug)
    for mention in mentions:
        _write_mention(tx, mention)

    co_occurrences = plan_co_occurrences(spine.sections, mentions)
    for co_occurrence in co_occurrences:
        _write_co_occurrence(tx, co_occurrence)
    names_by_id = {entity.id: entity.name for entity in entities}

    return {
        "nodes": len(nodes),
        "edges": len(edges),
        "aliases": len(aliases),
        "sections": len(spine.sections),
        "describes": len(spine.describes),
        "mentions": len(mentions),
        # The PLAN's row count, not the graph's. The write MERGEs, so a plan
        # that emitted a pair twice would land one edge and look correct; this
        # figure is what a test compares the graph against to catch that.
        "co_occurrences": len(co_occurrences),
        # The number the design says to watch, computed where the pairs are so a
        # caller cannot report a width its own edges do not support.
        "co_occurrence_counts": co_occurrence_counts(co_occurrences, names_by_id),
        "widest_sentence": widest_sentence(
            spine.sections, mentions, co_occurrences, names_by_id
        ),
        "scanned_entities": len(entities),
        "alias_uses": sum(len(m.uses) for m in mentions),
        # The census the design asks for, computed where the mentions are so a
        # caller cannot report a different set from the one that was written.
        "mention_counts": _mention_census(mentions, entities),
        "deleted_nodes": deleted_nodes,
        "deleted_edges": deleted_edges,
    }


def _mention_census(mentions, entities: list["EntityNames"]) -> list[tuple[str, int]]:
    """`(name, mentions)` for this chapter, most-mentioned first.

    Printed on every write BECAUSE junk is not filtered out of the scan. A
    `Trapdoor` entity matching forty sections is invisible in a node count and
    unmissable here, which is the entire argument for leaving it in.
    """
    from backend.canon.spine import mention_counts

    return mention_counts(mentions, {e.id: e.name for e in entities})


def write_chapter(
    session,
    chapter_slug: str,
    nodes: list[WriteNode],
    edges: list[WriteEdge],
    spine: "ChapterSpine",
    aliases: "list[WriteAlias] | None" = None,
    *,
    replace: bool = False,
) -> dict:
    """Write one chapter's canon, its spine and its aliases in one transaction.

    `session.execute_write` commits when the unit of work returns and rolls back
    when it raises, so a failure anywhere -- a missing endpoint, a constraint,
    Neo4j restarting mid-write -- leaves the chapter exactly as it was.

    `spine` is REQUIRED rather than optional. It is where the mentions live, and
    the mentions are how the loop's predicate finds the chapter at all: a write
    that skipped the spine would commit nodes into a chapter that then reads as
    unwritten, which is precisely the half-committed state this whole module is
    built to make impossible.

    `aliases` is OPTIONAL, and that is not the same concession. It is the
    HAND-AUTHORED extra spellings, and a chapter for which nobody has authored
    any is the ordinary case -- eleven entries cover the whole book. Every
    entity still gets its own name as an `:Alias` regardless, from
    `_BACKFILL_ALIASES` inside the transaction, so the invariant lookup rests on
    does not depend on a caller remembering to pass anything.
    """
    return session.execute_write(
        _write_tx, chapter_slug, nodes, edges, spine, aliases or [], replace
    )
