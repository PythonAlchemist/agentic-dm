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


def grade(
    nodes: list[CandidateNode],
    edges: list[CandidateEdge],
    golden: dict,
) -> GradeReport:
    """Score candidates against a golden subset."""
    golden_nodes = golden.get("nodes", [])
    golden_edges = golden.get("edges", [])

    # id -> the set of acceptable normalized names, so edges can resolve endpoints
    by_id = {n["id"]: _golden_node_names(n) for n in golden_nodes}

    candidate_names = {normalize_name(c.name) for c in nodes}

    missing_nodes: list[str] = []
    matched_names: set[str] = set()
    for entry in golden_nodes:
        acceptable = _golden_node_names(entry)
        hit = acceptable & candidate_names
        if hit:
            matched_names |= hit
        else:
            missing_nodes.append(entry.get("name", entry["id"]))

    unmatched_nodes = [c.name for c in nodes if normalize_name(c.name) not in matched_names]

    candidate_edges = {
        (normalize_name(e.source_name), normalize_name(e.target_name), e.rel_type)
        for e in edges
    }

    missing_edges: list[str] = []
    matched_edges: set[tuple[str, str, str]] = set()
    for entry in golden_edges:
        sources = by_id.get(entry["source"], set())
        targets = by_id.get(entry["target"], set())
        hits = {
            (s, t, entry["type"])
            for s in sources
            for t in targets
            if (s, t, entry["type"]) in candidate_edges
        }
        if hits:
            matched_edges |= hits
        else:
            missing_edges.append(f"{entry['source']} -{entry['type']}-> {entry['target']}")

    unmatched_edges = [
        f"{e.source_name} -{e.rel_type}-> {e.target_name}"
        for e in edges
        if (normalize_name(e.source_name), normalize_name(e.target_name), e.rel_type)
        not in matched_edges
    ]

    return GradeReport(
        node_recall=_recall(len(golden_nodes) - len(missing_nodes), len(golden_nodes)),
        edge_recall=_recall(len(golden_edges) - len(missing_edges), len(golden_edges)),
        missing_nodes=missing_nodes,
        missing_edges=missing_edges,
        unmatched_nodes=unmatched_nodes,
        unmatched_edges=unmatched_edges,
        collisions=_find_collisions(golden_nodes),
    )


def _recall(hits: int, total: int) -> float:
    """An empty golden set scores 1.0: nothing was asked for, nothing was missed."""
    return 1.0 if total == 0 else hits / total
