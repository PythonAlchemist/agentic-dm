"""Score extracted candidates against a hand-authored golden subset.

Recall is reported as a number. Precision is deliberately not: the golden set is
not exhaustive -- chapter 3 contains far more nameable things than the 18 nodes
the key lists -- so a candidate with no match is usually a legitimate entity the
key omits rather than a fabrication. Scoring it would punish an extractor for
being thorough and reward one for being timid.

Unmatched candidates are therefore listed for human spot-check, never scored.

Matching is TYPE-AWARE (see `golden_entity_type`). A name alone is not evidence:
a reviewer's ~10-line regex, scraping every capitalized run out of chapter 3 and
emitting every name pair across every relationship type, out-scored the tuned
three-pass pipeline on node recall (0.78 vs 0.72 unambiguous). `*_unambiguous`
cannot stop that -- it constrains what one candidate matches, never how many
candidates exist. Requiring the candidate's `entity_type` to equal the type the
golden id declares raises the price of that attack, because nearly every
collision in the key is a type collision: `Vallaki` the LOCATION versus `Escort
Ireena to Vallaki` the QUEST.

BUT IT DOES NOT CLOSE THE HOLE, and this module must not be read as claiming it
does. Measured after the change: the same shotgun, emitting each scraped name
once per EntityType (18 copies, one extra loop) and stamping a matching `layer`
to satisfy `anchor_quests`, scores node 0.84/0.84 and edge 0.72/0.48 -- 0.74/0.74
and 0.60/0.60 after `anchor_quests` -- against the tuned pipeline's node
0.79/0.74 and edge 0.32/0.28. It still wins on all four numbers with no LLM.
Type-awareness multiplied its cost by roughly the type count and nothing more.

Recall is monotone in candidate count at every looseness, so NO recall-only
metric can rank two extractors: emitting more candidates can never lose a credit
already earned. Ranking needs something recall cannot supply -- a precision term,
a candidate budget, or the hand-checked fabrication sample the spec's bar already
calls for and which has never been performed. Read these numbers as "did the
extractor find the key's entities", never as "is this extractor better".
"""

import re

from backend.canon.models import CandidateEdge, CandidateNode, GradeReport
from backend.graph.schema import EntityType

_PUNCT = re.compile(r"[^a-z0-9 ]")
_ARTICLE = re.compile(r"^(the|a|an) ")
_SPACE = re.compile(r"\s+")

_ENTITY_TYPE_VALUES = {t.value for t in EntityType}


def normalize_name(name: str) -> str:
    """Fold a name for comparison.

    Deliberately loose. Strict matching would fail on "Ismark" versus "Ismark the
    Lesser" and turn recall into a measure of naming luck rather than extraction
    quality. Canonical naming is decided in stage 2b, not here.
    """
    folded = _PUNCT.sub("", name.lower())
    folded = _SPACE.sub(" ", folded).strip()
    return _ARTICLE.sub("", folded)


def names_match(candidate: str, golden: str) -> bool:
    """True when a candidate name refers to the same entity as a golden name.

    Exact folded equality is too strict: the extractor writes what the passage
    writes, and chapter 3 says "Strahd" far more often than "Strahd von
    Zarovich". Grading the former as a miss measures naming convention rather
    than whether the entity was found.

    So one name also matches the other when its tokens are a subset -- "strahd"
    within "strahd von zarovich", "church" within "church of barovia". Subset,
    not substring: "Village of Krezk" and "Village of Barovia" share a token but
    neither contains the other, so they correctly do not match.

    Deliberately NOT fuzzy. A typo like "Morgatha" for "Morgantha" is a real
    defect -- a transcription error or an extraction error -- and absorbing it
    here would hide the class of problem this harness exists to surface.

    Names only. Whether the two are the same KIND of thing is a separate,
    non-negotiable condition -- see `golden_entity_type`.
    """
    a, b = normalize_name(candidate), normalize_name(golden)
    if a == b:
        return True
    if not a or not b:
        return False

    a_tokens, b_tokens = set(a.split()), set(b.split())
    return a_tokens < b_tokens or b_tokens < a_tokens


def _entry_id(entry: dict) -> str:
    """The golden entry's id, falling back to its name when it declares none."""
    return entry.get("id", entry.get("name", ""))


def golden_entity_type(entry: dict) -> str:
    """The entity type a golden node's id declares, upper-cased.

    Golden ids are `cos:<type>:<slug>`, so the key already states the kind of
    every entry; nothing new has to be authored for type-aware matching.

    Raises rather than degrading. A malformed id has no type, and any "unknown
    type matches anything" fallback would restore precisely the hole this
    module closes: an untyped candidate would once again be credited for a name
    it merely shares. A key that cannot say what kind of thing an entry is is a
    defect in the key, and must be fixed there.
    """
    entry_id = _entry_id(entry)
    segments = entry_id.split(":")
    if len(segments) != 3:
        raise ValueError(
            f"golden id {entry_id!r} is not <book>:<type>:<slug> -- "
            "matching is type-aware and an id with no type segment cannot be graded"
        )
    declared = segments[1].strip().upper()
    if declared not in _ENTITY_TYPE_VALUES:
        raise ValueError(
            f"golden id {entry_id!r} declares entity type {segments[1]!r}, "
            "which is not a member of EntityType"
        )
    return declared


def _candidate_type(entity_type: str) -> str:
    return (entity_type or "").strip().upper()


def _golden_node_names(entry: dict) -> set[str]:
    """Every name a candidate may legitimately use for this golden node."""
    names = {entry.get("name", "")}
    names.update(entry.get("aliases", []) or [])
    return {normalize_name(n) for n in names if n}


def _find_collisions(golden_nodes: list[dict]) -> list[str]:
    """Golden node entries of the SAME TYPE whose normalized names overlap.

    Loose matching is deliberate (see `normalize_name`), but a collision between
    two distinct golden entries would inflate recall silently -- a candidate
    naming either entity would count as a match for both. This does not change
    matching behaviour; it only surfaces the ambiguity for a human to look at.

    Two entries of different types sharing a name are no longer ambiguous to the
    matcher, so reporting them here would be noise rather than a finding.
    """
    # (normalized name, type) -> {entry id -> the raw name/alias strings that fold to it}
    claimants: dict[tuple[str, str], dict[str, set[str]]] = {}
    for entry in golden_nodes:
        entry_id = _entry_id(entry)
        entity_type = golden_entity_type(entry)
        raw_names = [entry.get("name", ""), *(entry.get("aliases", []) or [])]
        for raw in raw_names:
            if not raw:
                continue
            key = (normalize_name(raw), entity_type)
            claimants.setdefault(key, {}).setdefault(entry_id, set()).add(raw)

    collisions: list[str] = []
    for (normalized, entity_type), by_entry in sorted(claimants.items()):
        if len(by_entry) > 1:
            labels = sorted({raw for raws in by_entry.values() for raw in raws})
            collisions.append(f"{normalized} ({entity_type}) <- {', '.join(labels)}")
    return collisions


def _matching_golden_ids(name: str, types: set[str], golden_nodes: list[dict]) -> set[str]:
    """Every golden node id that `name`, carrying one of `types`, matches.

    Used to judge whether an edge endpoint is inherently ambiguous against the
    golden set, independent of whether that exact string was ever extracted as a
    `CandidateNode`. An endpoint with no type (`types` empty) matches nothing.
    """
    hits: set[str] = set()
    for entry in golden_nodes:
        if golden_entity_type(entry) not in types:
            continue
        if any(names_match(name, acc) for acc in _golden_node_names(entry)):
            hits.add(_entry_id(entry))
    return hits


def golden_as_candidates(golden: dict) -> tuple[list[CandidateNode], list[CandidateEdge]]:
    """The golden subset restated as a perfect-by-construction candidate set.

    Every node is named exactly as the key names it and typed exactly as its id
    declares; every edge names its endpoints the same way. No extractor can do
    better than this, which is what makes it the ceiling.
    """
    by_id = {_entry_id(entry): entry for entry in golden.get("nodes", [])}
    nodes = [
        CandidateNode(name=entry.get("name", ""), entity_type=golden_entity_type(entry))
        for entry in golden.get("nodes", [])
    ]
    edges = [
        CandidateEdge(
            source_name=by_id[entry["source"]].get("name", ""),
            target_name=by_id[entry["target"]].get("name", ""),
            rel_type=entry["type"],
        )
        for entry in golden.get("edges", [])
        if entry["source"] in by_id and entry["target"] in by_id
    ]
    return nodes, edges


def ceiling(golden: dict) -> tuple[float, float]:
    """The best `(node, edge)` unambiguous recall this golden subset admits.

    Grades the key against itself. A result below 1.0 is a defect in the KEY, not
    in any extractor: it means two entries of the same type are indistinguishable
    under the matcher, so no candidate set can ever credit both unambiguously.
    Measured before type-aware matching: 0.78 node / 0.68 edge, against a spec bar
    of 0.9 -- unreachable by construction, and invisible without this function.
    """
    nodes, edges = golden_as_candidates(golden)
    report = _grade(nodes, edges, golden, 1.0, 1.0)
    return report.node_recall_unambiguous, report.edge_recall_unambiguous


def grade(
    nodes: list[CandidateNode],
    edges: list[CandidateEdge],
    golden: dict,
) -> GradeReport:
    """Score candidates against a golden subset.

    Two recall numbers are reported for both nodes and edges. The loose one
    (`node_recall`, `edge_recall`) credits a golden entry from ANY candidate
    that matches it, even one that also matches a different entry of the same
    type -- which inflates recall silently, since `names_match` is a
    token-subset match. The unambiguous one only credits a golden entry when
    some candidate matches it and nothing else; this is an honest lower bound.

    Both are bounded by `ceiling(golden)`, reported alongside them.
    """
    node_ceiling, edge_ceiling = ceiling(golden)
    return _grade(nodes, edges, golden, node_ceiling, edge_ceiling)


def _grade(
    nodes: list[CandidateNode],
    edges: list[CandidateEdge],
    golden: dict,
    node_ceiling: float,
    edge_ceiling: float,
) -> GradeReport:
    """The scoring itself. Split from `grade` so `ceiling` can reuse it without
    recursing into its own ceiling computation."""
    golden_nodes = golden.get("nodes", [])
    golden_edges = golden.get("edges", [])

    # id -> the golden entry, so edges can resolve endpoints to a name AND a type
    by_id = {_entry_id(n): n for n in golden_nodes}

    # A candidate is a (name, type) pair: the same name carrying a different type
    # is a different claim, and only one of them can be right.
    candidate_keys = {(normalize_name(c.name), _candidate_type(c.entity_type)) for c in nodes}
    # normalized name -> every type some candidate node gave it. An edge endpoint
    # is typed by the candidate nodes that carry its name; a name never extracted
    # as a node has no type, and therefore matches nothing.
    types_by_name: dict[str, set[str]] = {}
    for c in nodes:
        types_by_name.setdefault(normalize_name(c.name), set()).add(_candidate_type(c.entity_type))

    missing_nodes: list[str] = []
    # (normalized candidate name, type) -> golden ids it matched, so ambiguity (one
    # candidate matching more than one golden entry) can be surfaced below.
    candidate_hits: dict[tuple[str, str], set[str]] = {}
    for entry in golden_nodes:
        entry_id = _entry_id(entry)
        entity_type = golden_entity_type(entry)
        acceptable = _golden_node_names(entry)
        hit = False
        for cand, cand_type in candidate_keys:
            if cand_type != entity_type:
                continue
            if any(names_match(cand, acc) for acc in acceptable):
                candidate_hits.setdefault((cand, cand_type), set()).add(entry_id)
                hit = True
        if not hit:
            missing_nodes.append(entry.get("name", entry_id))

    matched_keys = set(candidate_hits)
    unmatched_nodes = [
        c.name
        for c in nodes
        if (normalize_name(c.name), _candidate_type(c.entity_type)) not in matched_keys
    ]

    node_collisions = [
        f"{cand} ({cand_type}) matches {', '.join(sorted(ids))}"
        for (cand, cand_type), ids in sorted(candidate_hits.items())
        if len(ids) > 1
    ]

    # A golden entry counts toward the unambiguous number only if some
    # candidate matched it and ONLY it (candidate_hits[key] has size 1).
    unambiguously_credited_ids = {
        entry_id for ids in candidate_hits.values() if len(ids) == 1 for entry_id in ids
    }
    missing_nodes_unambiguous = sum(
        1 for entry in golden_nodes if _entry_id(entry) not in unambiguously_credited_ids
    )

    def _endpoint_matches(name: str, golden_id: str) -> bool:
        """True when `name`, as extracted, can stand for that golden node.

        Type-aware like the node side, and for the same reason: an edge between
        two bare name strings is exactly what the regex shotgun emitted 45,540
        of. The endpoint's type comes from the candidate nodes carrying that
        name -- an endpoint no pass ever extracted as a node is untyped, and an
        untyped endpoint is not evidence of anything.
        """
        entry = by_id.get(golden_id)
        if entry is None:
            return False
        if golden_entity_type(entry) not in types_by_name.get(normalize_name(name), set()):
            return False
        return any(names_match(name, acc) for acc in _golden_node_names(entry))

    missing_edges: list[str] = []
    matched_edge_indices: set[int] = set()
    # (golden edge label, candidate edge index) for every credit, so the
    # unambiguous number can check endpoint ambiguity.
    credit_pairs: list[tuple[str, int]] = []
    for entry in golden_edges:
        label = f"{entry['source']} -{entry['type']}-> {entry['target']}"
        hit = False
        for i, e in enumerate(edges):
            if e.rel_type != entry["type"]:
                continue
            if _endpoint_matches(e.source_name, entry["source"]) and _endpoint_matches(
                e.target_name, entry["target"]
            ):
                matched_edge_indices.add(i)
                credit_pairs.append((label, i))
                hit = True
        if not hit:
            missing_edges.append(label)

    unmatched_edges = [
        f"{e.source_name} -{e.rel_type}-> {e.target_name}"
        for i, e in enumerate(edges)
        if i not in matched_edge_indices
    ]

    def _endpoint_ambiguous(e: CandidateEdge) -> bool:
        for name in (e.source_name, e.target_name):
            types = types_by_name.get(normalize_name(name), set())
            if len(_matching_golden_ids(name, types, golden_nodes)) > 1:
                return True
        return False

    # One report, not two. A candidate edge that satisfies several golden edges
    # does so BECAUSE an endpoint of it is ambiguous, so the old
    # "multi_matched_edge_collisions" list said the same thing in a second
    # format and was dropped rather than double-reported.
    edge_collisions = [
        f"{label} credited via ambiguous endpoint match"
        for label in sorted({label for label, i in credit_pairs if _endpoint_ambiguous(edges[i])})
    ]

    # A golden edge counts toward edge_recall_unambiguous only when neither
    # endpoint name of the crediting candidate edge is itself ambiguous against
    # the full golden node set (the "donavich -SEEKS-> save-doru" case, where
    # the endpoint alone is globally ambiguous even though this one edge match
    # is not). That makes this a lower bound: a real edge can fail purely
    # because its endpoint NAME is reused within its own type elsewhere in the
    # key, with no fault in the edge extraction itself.
    unambiguously_credited_labels = {
        label for label, i in credit_pairs if not _endpoint_ambiguous(edges[i])
    }

    return GradeReport(
        node_recall=_recall(len(golden_nodes) - len(missing_nodes), len(golden_nodes)),
        edge_recall=_recall(len(golden_edges) - len(missing_edges), len(golden_edges)),
        node_recall_unambiguous=_recall(
            len(golden_nodes) - missing_nodes_unambiguous, len(golden_nodes)
        ),
        edge_recall_unambiguous=_recall(len(unambiguously_credited_labels), len(golden_edges)),
        node_ceiling=node_ceiling,
        edge_ceiling=edge_ceiling,
        missing_nodes=missing_nodes,
        missing_edges=missing_edges,
        unmatched_nodes=unmatched_nodes,
        unmatched_edges=unmatched_edges,
        collisions=_find_collisions(golden_nodes) + node_collisions,
        edge_collisions=edge_collisions,
    )


def _recall(hits: int, total: int) -> float:
    """An empty golden set scores 1.0: nothing was asked for, nothing was missed."""
    return 1.0 if total == 0 else hits / total
