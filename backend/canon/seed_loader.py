"""Load hand-authored canon YAML into Neo4j.

Seeds live in this package rather than under data/ because data/ is gitignored and
a seed is source: it is committed, reviewed, and doubles as the golden set that
stage 2's extractor is graded against.
"""

from collections import Counter
from pathlib import Path

import yaml

from backend.canon.assembler import slugify
from backend.graph.schema import (
    DERIVED_LOCATION_SUBTYPES,
    LAYER_MAP,
    EntityType,
    LocationSubtype,
    RelationshipType,
)

SEED_DIR = Path(__file__).parent / "seeds"

#: The hand-authored half of the LOCATION hierarchy. A seed rather than data,
#: for the reason every seed is: it is committed, reviewed and diffable, and
#: `data/` is gitignored because the corpus under it is copyrighted.
LOCATION_SUBTYPE_SEED = SEED_DIR / "location-subtypes.yaml"

# Grading metadata, not graph data. A marked entry is a fact the seed asserts but the
# seed's own chapter does not state, so a run over that chapter must not be scored
# against it. Stripped before writing -- see `_GRADING_KEYS`.
#
# The axis is chapter numbers rather than a stated/implied/external scheme, because
# per-chapter golden subsets are what `extractable_subset` exists to produce.
EXTRACTABLE_FROM = "extractable_from"
EXTRACTABLE_SOURCES = {"ch1", "ch2"}

# The chapter this seed's unmarked entries are expected to come from.
DEFAULT_SOURCE = "ch3"

_GRADING_KEYS = {EXTRACTABLE_FROM}
RESERVED_EDGE_KEYS = {"source", "target", "type"} | _GRADING_KEYS


def validate_seed(data: dict) -> list[str]:
    """Return human-readable problems with a seed document. Empty means valid."""
    problems: list[str] = []
    known_types = {r.value for r in RelationshipType}
    known_entity_types = {t.value for t in EntityType}
    ids = {n.get("id") for n in data.get("nodes", [])}

    id_counts = Counter(n.get("id") for n in data.get("nodes", []))
    for dup_id, count in id_counts.items():
        if dup_id is not None and count > 1:
            problems.append(f"duplicate node id {dup_id!r} declared {count} times")

    for node in data.get("nodes", []):
        for field in ("id", "name", "entity_type"):
            if not node.get(field):
                problems.append(f"node missing {field}: {node}")
        entity_type = node.get("entity_type")
        if entity_type is not None and entity_type not in known_entity_types:
            problems.append(f"unknown entity_type {entity_type!r} in {node}")

    for e in data.get("edges", []):
        if e.get("type") not in known_types:
            problems.append(f"unknown relationship type {e.get('type')!r} in {e}")
        for end in ("source", "target"):
            if e.get(end) not in ids:
                problems.append(f"edge {end} not declared as a node: {e.get(end)!r}")

    for entry in [*data.get("nodes", []), *data.get("edges", [])]:
        marker = entry.get(EXTRACTABLE_FROM)
        if marker is not None and marker not in EXTRACTABLE_SOURCES:
            problems.append(
                f"unknown {EXTRACTABLE_FROM} {marker!r} "
                f"(expected one of {sorted(EXTRACTABLE_SOURCES)}) in {entry}"
            )

    return problems


def validate_location_subtypes(data: dict) -> list[str]:
    """Return human-readable problems with a location-subtype seed.

    Four refusals, and each one exists because the failure it catches is silent
    in the graph rather than loud at load time:

    * an unknown rung (`WILDS` for `WILD`) would confer no label, and the place
      would be indistinguishable from one deliberately left unclassified;
    * a missing or unslugifiable name can never be matched against anything;
    * a hand-authored SITE or AREA is a human overriding the key convention,
      which is the one layer here that has never been wrong -- and this file
      wins ties, so it would win that one too;
    * two entries claiming one slug is a contradiction that a dict would
      resolve by silently keeping whichever the author wrote last.
    """
    problems: list[str] = []
    known = {s.value for s in LocationSubtype}
    claimed: dict[str, str] = {}

    for entry in data.get("locations", []):
        name = entry.get("name")
        subtype = entry.get("subtype")
        if not name:
            problems.append(f"location missing name: {entry}")
        if not subtype:
            problems.append(f"location missing subtype: {entry}")
        elif subtype not in known:
            problems.append(f"unknown subtype {subtype!r} in {entry}")
        elif LocationSubtype(subtype) in DERIVED_LOCATION_SUBTYPES:
            problems.append(
                f"subtype {subtype!r} is derived from the book's key convention "
                f"and must not be hand-authored: {entry}"
            )

        for spelling in [name, *entry.get("aliases", [])]:
            if not spelling:
                continue
            slug = slugify(spelling)
            if not slug:
                problems.append(f"name {spelling!r} slugifies to nothing: {entry}")
                continue
            if slug in claimed and claimed[slug] != subtype:
                problems.append(
                    f"{slug!r} is claimed by two entries, as {claimed[slug]!r} and {subtype!r}"
                )
            claimed[slug] = subtype

    return problems


def load_location_subtypes(path: str | Path = LOCATION_SUBTYPE_SEED) -> dict[str, LocationSubtype]:
    """The authored rungs, keyed on the slug of every spelling that reaches one.

    Slug rather than folded text, for the reason `KeyedIndex` matches on slugs:
    `Bildrath's Mercantile` and `Bildrath’s Mercantile` differ by one invisible
    character, and anything `slugify` already treats as one name is one name.

    Returns a plain mapping and touches no database -- `plan_write` is a pure
    function, so the file is read by its caller and handed in, exactly as the
    gazetteer is.
    """
    data = yaml.safe_load(Path(path).read_text()) or {}
    problems = validate_location_subtypes(data)
    if problems:
        raise ValueError("invalid location-subtype seed:\n  " + "\n  ".join(problems))

    subtypes: dict[str, LocationSubtype] = {}
    for entry in data.get("locations", []):
        subtype = LocationSubtype(entry["subtype"])
        for spelling in [entry["name"], *entry.get("aliases", [])]:
            subtypes[slugify(spelling)] = subtype
    return subtypes


def load_artifacts(path: str | Path = LOCATION_SUBTYPE_SEED) -> frozenset[str]:
    """The slugs of the items that wear `:Artifact`.

    The same seed as the location rungs, read the same way and handed to
    `plan_write` the same way: one hand-authored file and one mechanism, because
    two mechanisms for two kinds of authored label is two things that drift.

    Slugs, matched the way `mint_id` mints ids and the way the rungs match, so
    the seed needs one spelling of a name rather than every apostrophe variant
    of it. EXACT, never a substring: chapter 3's `Holy Symbol` is a wooden sun
    nailed to a church wall, and a substring match would make it the Holy Symbol
    of Ravenkind.

    ONE refusal, unlike `validate_location_subtypes`' four, because only one
    failure here is silent. A name that slugifies to nothing can never match
    anything, and an item it was meant to label reads in the graph exactly like
    an item nobody authored. A repeated name is not a problem the way a repeated
    location is: there is one item label, so two entries cannot disagree about
    which one an item wears, and a set absorbs the duplicate.

    Returns a frozenset and touches no database, for the reason
    `load_location_subtypes` returns a plain mapping: `plan_write` is pure, so
    the file is read by its caller and handed in.
    """
    data = yaml.safe_load(Path(path).read_text()) or {}

    slugs: set[str] = set()
    problems: list[str] = []
    for name in data.get("artifacts") or []:
        slug = slugify(name) if name else ""
        if not slug:
            problems.append(f"artifact name {name!r} slugifies to nothing")
            continue
        slugs.add(slug)

    if problems:
        raise ValueError("invalid artifact seed:\n  " + "\n  ".join(problems))
    return frozenset(slugs)


def validate_aliases(data: dict) -> list[str]:
    """Return human-readable problems with the alias block.

    Three refusals, each catching a failure that is silent in the graph:

    * a missing or unslugifiable name can never be matched against an entity,
      so the aliases under it would never reach one;
    * an alias that slugifies to nothing can never be an `:Alias` node, and the
      spelling it was meant to record would read exactly like one nobody
      authored;
    * two entries reaching one slug with DIFFERENT sets of spellings is a
      contradiction a dict would resolve by keeping whichever came last. Two
      entries agreeing is not a problem -- the same name written twice is the
      same claim.
    """
    problems: list[str] = []
    claimed: dict[str, frozenset[str]] = {}

    for entry in data.get("aliases", []):
        name = entry.get("name")
        spellings = entry.get("aliases") or []
        if not name:
            problems.append(f"alias entry missing name: {entry}")
            continue
        if not spellings:
            problems.append(f"alias entry for {name!r} records no spellings: {entry}")
        for spelling in spellings:
            if not spelling or not slugify(spelling):
                problems.append(f"alias {spelling!r} slugifies to nothing: {entry}")

        forms = frozenset([name, *spellings])
        for key in [name, *spellings]:
            slug = slugify(key) if key else ""
            if not slug:
                problems.append(f"name {key!r} slugifies to nothing: {entry}")
                continue
            if slug in claimed and claimed[slug] != forms:
                problems.append(
                    f"{slug!r} is claimed by two alias entries, as "
                    f"{sorted(claimed[slug])} and {sorted(forms)}"
                )
            claimed[slug] = forms

    return problems


def load_aliases(path: str | Path = LOCATION_SUBTYPE_SEED) -> dict[str, tuple[str, ...]]:
    """The authored surface forms, keyed on the slug of every spelling.

    The same seed as the location rungs and the artifact list, read the same way
    and handed to a pure planner the same way: one hand-authored file and one
    mechanism, because three mechanisms for three kinds of authored claim is
    three things that drift.

    Keyed on the slug of the entry's `name` AND of every alias under it, the way
    `load_location_subtypes` is. That is what lets one entry cover a straight and
    a curly apostrophe, and what lets `The Village of Barovia` be found whether
    the extractor's provenance tiebreak minted the node under that spelling or
    under `Village of Barovia`.

    The VALUE is every spelling in the entry, canonical included, because the
    entity's own name may be any of them. `plan_aliases` unions the node's real
    name in and deduplicates, so an entry cannot cost an entity its own name.

    Returns a plain mapping and touches no database.
    """
    data = yaml.safe_load(Path(path).read_text()) or {}
    problems = validate_aliases(data)
    if problems:
        raise ValueError("invalid alias seed:\n  " + "\n  ".join(problems))

    authored: dict[str, tuple[str, ...]] = {}
    for entry in data.get("aliases", []):
        forms = tuple(dict.fromkeys([entry["name"], *(entry.get("aliases") or [])]))
        for key in forms:
            authored[slugify(key)] = forms
    return authored


def extractable_subset(data: dict, source: str = DEFAULT_SOURCE) -> dict:
    """The nodes and edges an extraction run over `source` should be graded against.

    Entries carrying an `extractable_from` marker name a different chapter, so a run
    over this seed's own chapter cannot be expected to produce them.
    Grading against the whole seed penalises an extractor for correctly reading only
    what its input actually says, and rewards one that invents the rest.

    Unmarked entries belong to DEFAULT_SOURCE. Asking for a marked source returns only
    entries carrying that marker -- NOT that chapter plus everything before it.

    Whether a later chapter's expected set should be cumulative depends on how stage 2
    feeds its extractor: strict-per-source is right if each run sees one chapter's text,
    and under-grades every later run if runs see cumulative text. Deliberately left
    strict until that consumer exists, rather than guessing the semantics here.

    ONE exception to the strictness, and it is not a guess: a node referenced by a kept
    edge is kept too, whatever its own marker says. A subset that emits an edge but not
    its endpoint emits an edge nothing can ever match -- `grade` resolves an endpoint id
    to the names of a node in the same subset, so a missing endpoint yields an empty name
    set and the edge fails at every looseness. Measured: `ireena-kolyana IDENTITY_OF
    tatyana` sat in the chapter-3 edge subset while Tatyana (marked ch1) sat outside the
    node subset, a permanent 4-point floor on edge recall that was read as an extraction
    failure for four review rounds.

    Keeping the edge and pulling its endpoint in, rather than dropping the edge, because
    an edge IS the joint assertion that both its ends exist: asking an extractor for
    `Ireena IDENTITY_OF Tatyana` is asking it to name Tatyana. Dropping the edge instead
    would silently shrink the key on chapter 3's most plot-central fact -- and would
    empty the ch1 subset of the entire Tarokka fan-out, which is the only thing that
    subset grades.
    """
    if source == DEFAULT_SOURCE:
        keep = lambda entry: entry.get(EXTRACTABLE_FROM) is None  # noqa: E731
    else:
        keep = lambda entry: entry.get(EXTRACTABLE_FROM) == source  # noqa: E731

    edges = [e for e in data.get("edges", []) if keep(e)]
    needed = {n.get("id") for n in data.get("nodes", []) if keep(n)}
    needed.update(e.get(end) for e in edges for end in ("source", "target"))

    # Filtered from the seed rather than appended, so pulled-in endpoints keep the
    # order the seed author wrote them in.
    return {
        "nodes": [n for n in data.get("nodes", []) if n.get("id") in needed],
        "edges": edges,
    }


def load_seed(path: str | Path, session) -> dict:
    """Load a seed into Neo4j, stamping canon provenance and edge layers.

    MERGE on id makes this idempotent, so a seed can be reloaded after editing
    without duplicating nodes.
    """
    data = yaml.safe_load(Path(path).read_text())
    problems = validate_seed(data)
    if problems:
        raise ValueError("invalid seed:\n  " + "\n  ".join(problems))

    for node in data["nodes"]:
        props = {
            k: v
            for k, v in node.items()
            if k != "id" and k != "entity_type" and k not in _GRADING_KEYS
        }
        props.setdefault("plane", "canon")
        props.setdefault("source_book", "cos")
        # The type is a LABEL, as it is on every node `canon.writer` writes --
        # `MATCH (n:NPC)`, not `MATCH (n:Entity {entity_type:'NPC'})`. Coerced
        # through the enum first because a label cannot be parameterized in
        # Cypher and is interpolated into the statement; `validate_seed` has
        # already refused anything the enum does not know, and this is the
        # second lock on the same door.
        raw_type = node.get("entity_type")
        label = f":{EntityType(raw_type).value}" if raw_type else ""
        session.run(
            f"MERGE (e:Entity {{id:$id}}) {f'SET e{label} ' if label else ''}SET e += $props",
            {"id": node["id"], "props": props},
        )

    for e in data["edges"]:
        rel = RelationshipType(e["type"])
        props = {k: v for k, v in e.items() if k not in RESERVED_EDGE_KEYS}
        layer = LAYER_MAP[rel]
        if layer is not None:
            props["layer"] = layer.value
        session.run(
            f"""
            MATCH (a:Entity {{id:$source}}), (b:Entity {{id:$target}})
            MERGE (a)-[r:{rel.value}]->(b)
            SET r += $props
            """,
            {"source": e["source"], "target": e["target"], "props": props},
        )

    return {"nodes": len(data["nodes"]), "edges": len(data["edges"])}
