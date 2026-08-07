"""Score extracted candidates against a hand-authored golden subset.

Recall is reported as a number. Precision is deliberately not: the golden set is
not exhaustive -- chapter 3 contains far more nameable things than the 18 nodes
the key lists -- so a candidate with no match is usually a legitimate entity the
key omits rather than a fabrication. Scoring it would punish an extractor for
being thorough and reward one for being timid.

Unmatched candidates are therefore listed for human spot-check, never scored.
"""

import re

from backend.canon.models import CandidateEdge, CandidateNode, GradeReport

_PUNCT = re.compile(r"[^a-z0-9 ]")
_ARTICLE = re.compile(r"^(the|a|an) ")
_SPACE = re.compile(r"\s+")


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
    """
    a, b = normalize_name(candidate), normalize_name(golden)
    if a == b:
        return True
    if not a or not b:
        return False

    a_tokens, b_tokens = set(a.split()), set(b.split())
    return a_tokens < b_tokens or b_tokens < a_tokens


def _golden_node_names(entry: dict) -> set[str]:
    """Every name a candidate may legitimately use for this golden node."""
    names = {entry.get("name", "")}
    names.update(entry.get("aliases", []) or [])
    return {normalize_name(n) for n in names if n}


def _find_collisions(golden_nodes: list[dict]) -> list[str]:
    """Golden node entries whose normalized names overlap.

    Loose matching is deliberate (see `normalize_name`), but a collision between
    two distinct golden entries would inflate recall silently -- a candidate
    naming either entity would count as a match for both. This does not change
    matching behaviour; it only surfaces the ambiguity for a human to look at.
    """
    # normalized name -> {entry id -> the raw name/alias strings that fold to it}
    claimants: dict[str, dict[str, set[str]]] = {}
    for entry in golden_nodes:
        entry_id = entry.get("id", entry.get("name", ""))
        raw_names = [entry.get("name", ""), *(entry.get("aliases", []) or [])]
        for raw in raw_names:
            if not raw:
                continue
            normalized = normalize_name(raw)
            claimants.setdefault(normalized, {}).setdefault(entry_id, set()).add(raw)

    collisions: list[str] = []
    for normalized, by_entry in sorted(claimants.items()):
        if len(by_entry) > 1:
            labels = sorted({raw for raws in by_entry.values() for raw in raws})
            collisions.append(f"{normalized} <- {', '.join(labels)}")
    return collisions


def _matching_golden_ids(name: str, golden_nodes: list[dict]) -> set[str]:
    """Every golden node id that `name` loosely matches.

    Used both to score a candidate node and to judge whether an edge endpoint
    string is inherently ambiguous against the golden set, independent of
    whether that exact string was ever extracted as a `CandidateNode`.
    """
    hits: set[str] = set()
    for entry in golden_nodes:
        entry_id = entry.get("id", entry.get("name", ""))
        if any(names_match(name, acc) for acc in _golden_node_names(entry)):
            hits.add(entry_id)
    return hits


def grade(
    nodes: list[CandidateNode],
    edges: list[CandidateEdge],
    golden: dict,
) -> GradeReport:
    """Score candidates against a golden subset.

    Two recall numbers are reported for both nodes and edges. The loose one
    (`node_recall`, `edge_recall`) credits a golden entry from ANY candidate
    that loosely matches it, even one that also matches a different entry --
    which inflates recall silently, since `names_match` is a token-subset
    match ("Ireena" matches both the NPC and a quest named after her). The
    unambiguous one only credits a golden entry when some candidate matches
    it and nothing else; this is an honest lower bound.
    """
    golden_nodes = golden.get("nodes", [])
    golden_edges = golden.get("edges", [])

    # id -> the set of acceptable normalized names, so edges can resolve endpoints
    by_id = {n["id"]: _golden_node_names(n) for n in golden_nodes}

    candidate_names = {normalize_name(c.name) for c in nodes}

    missing_nodes: list[str] = []
    # normalized candidate name -> golden ids it matched, so ambiguity (one
    # candidate matching more than one golden entry) can be surfaced below.
    candidate_hits: dict[str, set[str]] = {}
    for entry in golden_nodes:
        entry_id = entry.get("id", entry.get("name", ""))
        acceptable = _golden_node_names(entry)
        hit = False
        for cand in candidate_names:
            if any(names_match(cand, acc) for acc in acceptable):
                candidate_hits.setdefault(cand, set()).add(entry_id)
                hit = True
        if not hit:
            missing_nodes.append(entry.get("name", entry["id"]))

    matched_names = set(candidate_hits)
    unmatched_nodes = [c.name for c in nodes if normalize_name(c.name) not in matched_names]

    node_collisions = [
        f"{cand} matches {', '.join(sorted(ids))}"
        for cand, ids in sorted(candidate_hits.items())
        if len(ids) > 1
    ]

    # A golden entry counts toward the unambiguous number only if some
    # candidate matched it and ONLY it (candidate_hits[cand] has size 1).
    unambiguously_credited_ids = {
        entry_id for cand, ids in candidate_hits.items() if len(ids) == 1 for entry_id in ids
    }
    missing_nodes_unambiguous = sum(
        1
        for entry in golden_nodes
        if entry.get("id", entry.get("name", "")) not in unambiguously_credited_ids
    )

    missing_edges: list[str] = []
    matched_edge_indices: set[int] = set()
    # candidate edge index -> golden edge labels it satisfied, so a candidate
    # edge that satisfies more than one golden edge (endpoint ambiguity, edge
    # side) can be surfaced.
    edge_hits: dict[int, set[str]] = {}
    # (golden edge label, candidate edge index) for every credit, so the
    # unambiguous number can check both edge-side and endpoint-side ambiguity.
    credit_pairs: list[tuple[str, int]] = []
    for entry in golden_edges:
        label = f"{entry['source']} -{entry['type']}-> {entry['target']}"
        sources = by_id.get(entry["source"], set())
        targets = by_id.get(entry["target"], set())
        hit = False
        for i, e in enumerate(edges):
            if e.rel_type != entry["type"]:
                continue
            if any(names_match(e.source_name, s) for s in sources) and any(
                names_match(e.target_name, t) for t in targets
            ):
                matched_edge_indices.add(i)
                edge_hits.setdefault(i, set()).add(label)
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
        return (
            len(_matching_golden_ids(e.source_name, golden_nodes)) > 1
            or len(_matching_golden_ids(e.target_name, golden_nodes)) > 1
        )

    multi_matched_edge_collisions = [
        f"{edges[i].source_name} -{edges[i].rel_type}-> {edges[i].target_name} "
        f"matches {', '.join(sorted(labels))}"
        for i, labels in sorted(edge_hits.items())
        if len(labels) > 1
    ]
    ambiguous_endpoint_labels = sorted(
        {label for label, i in credit_pairs if _endpoint_ambiguous(edges[i])}
    )
    edge_collisions = multi_matched_edge_collisions + [
        f"{label} credited via ambiguous endpoint match" for label in ambiguous_endpoint_labels
    ]

    # A golden edge counts toward edge_recall_unambiguous only if BOTH hold:
    # the crediting candidate edge satisfies exactly one golden edge (not,
    # say, two golden edges of the same type sharing an ambiguous endpoint --
    # see multi_matched_edge_collisions above), AND neither of its endpoint
    # names is itself ambiguous against the full golden node set (the
    # "donavich -SEEKS-> save-doru" case, where the endpoint alone is
    # globally ambiguous even though this one edge match is not). Requiring
    # both makes this a lower bound of a lower bound: a real edge can fail
    # this check purely because its endpoint NAME is reused elsewhere in the
    # golden set, with no fault in the edge extraction itself. Read a low
    # edge_recall_unambiguous as "the ruler is conservative here", not
    # directly as an extraction-quality signal.
    unambiguously_credited_labels = {
        label
        for label, i in credit_pairs
        if len(edge_hits.get(i, set())) == 1 and not _endpoint_ambiguous(edges[i])
    }

    return GradeReport(
        node_recall=_recall(len(golden_nodes) - len(missing_nodes), len(golden_nodes)),
        edge_recall=_recall(len(golden_edges) - len(missing_edges), len(golden_edges)),
        node_recall_unambiguous=_recall(
            len(golden_nodes) - missing_nodes_unambiguous, len(golden_nodes)
        ),
        edge_recall_unambiguous=_recall(
            len(unambiguously_credited_labels), len(golden_edges)
        ),
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
