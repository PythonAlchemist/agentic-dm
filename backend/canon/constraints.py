"""Flag extracted edges that are impossible by TYPE, not merely false in fact.

The pipeline has no automatic precision signal: recall is monotone in candidate
count, so it cannot rank extractors -- a regex shotgun outscores the tuned
pipeline. The only precision measurement so far is a human reading 30 chapter-4
edges, which found 16 false. Nine of those sixteen are wrong by construction
rather than by fact: `Chapel -LOCATED_IN-> Donavich` puts a location inside a
priest, and `Guards' Post -GUARDS-> Skeleton` has a room standing watch. Every
candidate already carries an `entity_type`, so those nine cost nothing to catch
-- no LLM call, no external source, no sampling.

TWO RULES SHAPE EVERYTHING HERE.

An UNKNOWN endpoint type is UNCHECKED, never violating. `structure.py` emits
edges without emitting nodes, so an endpoint with no type is normal and common,
and those derived edges are the one part of the output a fabrication check found
clean. Conflating "we could not type this" with "this is wrong" would make the
check fire hardest on the most reliable layer, which is worse than no check at
all. The two counts are therefore reported separately and never summed.

A reversal is DETECTED, never PERFORMED. `reversal_would_pass` records that
swapping the endpoints would satisfy the table -- `Chapel LOCATED_IN Donavich`
fails while `Donavich LOCATED_IN Chapel` passes. Repairing it would manufacture
an edge the model never proposed, and nothing here can yet tell a genuine
inversion from a coincidence. The count is the evidence for whether a repair
pass is worth building later, not a repair pass.
"""

from dataclasses import dataclass, field

from backend.canon.models import CandidateEdge, CandidateNode
from backend.graph.schema import RELATIONSHIP_DOMAIN_RANGE, EntityType, RelationshipType


@dataclass(frozen=True)
class Violation:
    """One edge whose endpoint types the ontology forbids.

    `source_type` / `target_type` are `""` when that endpoint had no typed node,
    and `"A|B"` when a name carried more than one type. An unknown endpoint can
    appear here only on the OTHER side's violation: it never causes one itself.
    """

    edge_index: int
    rel_type: str
    source_name: str
    target_name: str
    source_type: str
    target_type: str
    reason: str  # "domain" | "range" | "both"
    reversal_would_pass: bool


@dataclass(frozen=True)
class ConstraintReport:
    """Violations plus the denominators that make them readable.

    `checked` and `unchecked` partition the edge list: an edge is checked when
    the table could say ANYTHING about it (a known rel_type and at least one
    typed endpoint), and unchecked when it could say nothing. Reporting a
    violation count without `unchecked` beside it would let a run in which
    almost nothing was typed look clean.
    """

    violations: list[Violation] = field(default_factory=list)
    checked: int = 0
    unchecked: int = 0


def _fold(name: str) -> str:
    """Case-insensitive on the stripped string, as `anchor_quests` folds names.

    Deliberately NOT `grade.normalize_name`: extraction must not depend on the
    module that scores it, and the grade fold is loose on purpose (it matches
    "Ismark" to "Ismark the Lesser"), which would let one entity's type answer
    for another's.
    """
    return name.strip().casefold()


def _types_by_name(nodes: list[CandidateNode]) -> dict[str, frozenset[EntityType]]:
    """Folded name -> every entity type some candidate node gave it.

    A SET, not one type: a coined QUEST sharing a LOCATION's name is a measured
    occurrence in this corpus (`anchor_quests` keys on `(name, type)` for the
    same reason). Picking one of the two arbitrarily would charge the edge with
    a type nothing asserted. An `entity_type` the ontology does not define
    leaves the endpoint unknown -- that is a typing failure, not evidence.
    """
    types: dict[str, set[EntityType]] = {}
    for node in nodes:
        try:
            entity_type = EntityType(node.entity_type.strip())
        except ValueError:
            continue
        types.setdefault(_fold(node.name), set()).add(entity_type)
    return {name: frozenset(found) for name, found in types.items()}


def _render(types: frozenset[EntityType]) -> str:
    return "|".join(sorted(t.value for t in types))


def _fits(types: frozenset[EntityType], allowed: frozenset[EntityType]) -> bool:
    """Whether an endpoint may stand here. An unknown endpoint always may.

    Any one of an ambiguous name's types satisfying is enough: the alternative
    is a violation asserted against a type the edge may not even be about.
    """
    return not types or bool(types & allowed)


def report_edges(nodes: list[CandidateNode], edges: list[CandidateEdge]) -> ConstraintReport:
    """Check every edge's endpoint types against RELATIONSHIP_DOMAIN_RANGE.

    Endpoint types come from the candidate NODES, matched by folded name. Ids do
    not exist yet at this stage -- names are all there is.
    """
    by_name = _types_by_name(nodes)
    violations: list[Violation] = []
    checked = 0
    unchecked = 0

    for index, edge in enumerate(edges):
        try:
            constraint = RELATIONSHIP_DOMAIN_RANGE.get(RelationshipType(edge.rel_type.strip()))
        except ValueError:
            constraint = None
        source_types = by_name.get(_fold(edge.source_name), frozenset())
        target_types = by_name.get(_fold(edge.target_name), frozenset())

        # Nothing to say: an unconstrained type, or neither endpoint typed.
        if constraint is None or not (source_types or target_types):
            unchecked += 1
            continue

        checked += 1
        domain, range_ = constraint
        bad_domain = not _fits(source_types, domain)
        bad_range = not _fits(target_types, range_)
        if not (bad_domain or bad_range):
            continue

        violations.append(
            Violation(
                edge_index=index,
                rel_type=edge.rel_type,
                source_name=edge.source_name,
                target_name=edge.target_name,
                source_type=_render(source_types),
                target_type=_render(target_types),
                reason="both" if bad_domain and bad_range else "domain" if bad_domain else "range",
                # The same unknown-is-permitted rule, applied to the swap.
                reversal_would_pass=_fits(target_types, domain) and _fits(source_types, range_),
            )
        )

    return ConstraintReport(violations=violations, checked=checked, unchecked=unchecked)


def check_edges(nodes: list[CandidateNode], edges: list[CandidateEdge]) -> list[Violation]:
    """Just the violations, for callers that do not need the denominators."""
    return report_edges(nodes, edges).violations


def enforce(
    nodes: list[CandidateNode],
    edges: list[CandidateEdge],
    *,
    reject: bool,
) -> tuple[list[CandidateEdge], ConstraintReport]:
    """Returns `(surviving_edges, report)` -- the shape `anchor_quests` uses.

    `reject=False` returns the input list untouched, and is the default
    everywhere: the table is validated against one chapter's golden set only,
    and this project has twice had silent filtering hide a defect for weeks.
    The report is produced identically either way, so turning rejection on
    cannot change what is measured -- only what is kept.
    """
    report = report_edges(nodes, edges)
    if not reject:
        return edges, report
    violating = {v.edge_index for v in report.violations}
    return [edge for index, edge in enumerate(edges) if index not in violating], report


def format_report(report: ConstraintReport) -> str:
    """The block printed before the scores. Printed even when clean: a silent
    pass is indistinguishable from a check that never ran."""
    reasons = {reason: 0 for reason in ("domain", "range", "both")}
    for violation in report.violations:
        reasons[violation.reason] += 1
    reversals = sum(1 for v in report.violations if v.reversal_would_pass)
    return (
        f"  constraint violations: {len(report.violations)} of {report.checked} typed edges "
        f"(domain {reasons['domain']}, range {reasons['range']}, both {reasons['both']})\n"
        f"    of which reversal would pass: {reversals}\n"
        f"  unchecked (endpoint type unknown): {report.unchecked}"
    )
