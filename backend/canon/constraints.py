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

from collections import Counter
from dataclasses import dataclass, field

from backend.canon.models import CandidateEdge, CandidateNode
from backend.graph.schema import (
    MUTUALLY_EXCLUSIVE,
    RELATIONSHIP_DOMAIN_RANGE,
    EntityType,
    RelationshipType,
)

#: `Violation.reason` for a mutual-exclusion conflict, distinct from the
#: domain/range family ("domain" | "range" | "both"). One value rather than a
#: parallel violation type: everything downstream that already knows how to
#: print, count and carry a Violation keeps working.
EXCLUSIVE_REASON = "exclusive"


@dataclass(frozen=True)
class Violation:
    """One edge the ontology forbids -- by its endpoint types, or by its company.

    `reason` says which check spoke: "domain" | "range" | "both" for the
    endpoint-type table, and `EXCLUSIVE_REASON` for an edge that contradicts
    another edge between the same ordered endpoints. The two are reported by
    different functions and must not be summed: the first is a property of one
    edge, the second of a pair, and one shared shape here is only so that
    everything downstream can print and carry both.

    `source_type` / `target_type` are `""` when that endpoint had no typed node,
    and `"A|B"` when a name carried more than one type. An unknown endpoint can
    appear here only on the OTHER side's violation: it never causes one itself.
    Both are `""` on an exclusion violation, which does not consult types.
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

    @property
    def reversals_would_pass(self) -> int:
        """How many violations would satisfy the table with endpoints swapped.

        A field on the report rather than a number `format_report` alone
        computes, because it is the stated evidence for whether a repair pass is
        worth building later -- so it has to travel in the artifact, not only
        across a terminal that scrolls away.
        """
        return sum(1 for violation in self.violations if violation.reversal_would_pass)


def fold_name(name: str) -> str:
    """Case-insensitive on the stripped string, as `anchor_quests` folds names.

    Deliberately NOT `grade.normalize_name`: extraction must not depend on the
    module that scores it, and the grade fold is loose on purpose (it matches
    "Ismark" to "Ismark the Lesser"), which would let one entity's type answer
    for another's.

    Public because `classify.py` resolves endpoint types the same way. Two
    modules folding names differently would type the same endpoint differently,
    so they share one function rather than agreeing by coincidence.
    """
    return name.strip().casefold()


def types_by_name(nodes: list[CandidateNode]) -> dict[str, frozenset[EntityType]]:
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
        types.setdefault(fold_name(node.name), set()).add(entity_type)
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
    by_name = types_by_name(nodes)
    violations: list[Violation] = []
    checked = 0
    unchecked = 0

    for index, edge in enumerate(edges):
        try:
            constraint = RELATIONSHIP_DOMAIN_RANGE.get(RelationshipType(edge.rel_type.strip()))
        except ValueError:
            constraint = None
        source_types = by_name.get(fold_name(edge.source_name), frozenset())
        target_types = by_name.get(fold_name(edge.target_name), frozenset())

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


#: rel type -> every type it contradicts, expanded once from MUTUALLY_EXCLUSIVE.
#: Built here rather than declared in the schema so there is one authored table
#: and one derived index, never two authored tables that can disagree.
_EXCLUDES: dict[RelationshipType, frozenset[RelationshipType]] = {}
for _pair in MUTUALLY_EXCLUSIVE:
    for _rel in _pair:
        _EXCLUDES[_rel] = frozenset(_pair - {_rel}) | _EXCLUDES.get(_rel, frozenset())
del _pair, _rel


def exclusive_conflicts(
    triples: list[tuple[str, str, RelationshipType]],
) -> list[tuple[int, int]]:
    """Index pairs `(i, j)`, i < j, whose types contradict between one ORDERED pair.

    The endpoint keys are opaque strings, because the two callers key on
    different things and both are right. `check_exclusive` keys on folded NAMES,
    which is all that exists before ids are minted; `writer.plan_write` keys on
    the minted IDS, because a name is not unique in canon -- a disputed
    `entity_type` leaves `Tatyana` as two nodes, and a name-keyed conflict check
    would charge an edge with contradicting an edge about a different node. One
    algorithm serving both is the point: a second copy would drift, exactly as a
    second slugifier or a second copy of LAYER_MAP would.

    ORDERED, and that is the substance of the check rather than a detail.
    `Church CONTAINS Undercroft` with `Undercroft LOCATED_IN Church` is the
    ordinary inverse pair the derived structural layer emits in bulk, and
    reading the endpoints unordered would report the cleanest layer in the graph
    as self-contradictory.

    Same type twice between one ordered pair is a DUPLICATE, which the writer
    already counts, and never a conflict -- `_EXCLUDES` never contains a type's
    own value, so this falls out rather than being special-cased.
    """
    by_endpoints: dict[tuple[str, str], list[tuple[int, RelationshipType]]] = {}
    for index, (source, target, rel) in enumerate(triples):
        by_endpoints.setdefault((source, target), []).append((index, rel))

    conflicts: list[tuple[int, int]] = []
    for entries in by_endpoints.values():
        for position, (index, rel) in enumerate(entries):
            excluded = _EXCLUDES.get(rel)
            if not excluded:
                continue
            for other_index, other_rel in entries[position + 1 :]:
                if other_rel in excluded:
                    conflicts.append((index, other_index))
    return sorted(conflicts)


def check_exclusive(edges: list[CandidateEdge]) -> list[Violation]:
    """Report every edge taking part in a mutual-exclusion conflict.

    TWO violations per conflict, one per edge, each carrying its own
    `edge_index` and `rel_type`. Which of the pair is right is NOT decided here
    and must not be decided anywhere automatic: there is no oracle -- recall
    cannot rank extractors and the wiki has no page for 8 of the 13 core NPCs --
    and a silent guess is how a wrong edge becomes indistinguishable from a
    checked one. So both are reported, both are kept, and a human at gate G3
    reads them.

    An unknown relationship type cannot conflict, for the same reason
    `report_edges` treats an unknown type as unchecked: "we could not parse
    this" is not evidence that it is wrong.

    Endpoint TYPES are not consulted, so `source_type`/`target_type` are empty
    and `reversal_would_pass` is False. A reversal is meaningless here: swapping
    the endpoints of one half of a contradiction does not resolve it, it just
    makes a different claim.
    """
    triples: list[tuple[str, str, RelationshipType]] = []
    parsed: list[int] = []
    for index, edge in enumerate(edges):
        try:
            rel = RelationshipType(edge.rel_type.strip())
        except ValueError:
            continue
        triples.append((_fold(edge.source_name), _fold(edge.target_name), rel))
        parsed.append(index)

    flagged: set[int] = set()
    for left, right in exclusive_conflicts(triples):
        flagged.update({parsed[left], parsed[right]})

    return [
        Violation(
            edge_index=index,
            rel_type=edges[index].rel_type,
            source_name=edges[index].source_name,
            target_name=edges[index].target_name,
            source_type="",
            target_type="",
            reason=EXCLUSIVE_REASON,
            reversal_would_pass=False,
        )
        for index in sorted(flagged)
    ]


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
    # Counter, not a fixed dict: `EXCLUSIVE_REASON` is a reason this function has
    # never seen, and a KeyError here would take down the extraction CLI rather
    # than print a count.
    reasons = Counter(violation.reason for violation in report.violations)
    return (
        f"  constraint violations: {len(report.violations)} of {report.checked} typed edges "
        f"(domain {reasons['domain']}, range {reasons['range']}, both {reasons['both']})\n"
        f"    of which reversal would pass: {report.reversals_would_pass}\n"
        f"  unchecked (endpoint type unknown): {report.unchecked}"
    )
