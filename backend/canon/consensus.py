"""Keep the LLM candidates that recur across independent extraction samples.

Extraction is sampled, not deterministic. Measured on chapter 3 at temperature
0 with a pinned seed, two runs share only 0.40-0.49 of their unique edges while
reporting identical recall -- recall is blind to the churn. Separately, a hand
check of 30 LLM edges found roughly half false as stated: real evidence spans
with an unsupported or inverted relationship hung on them.

Both are attacked by the same mechanism: draw N samples with different seeds and
keep what more than one of them found. An edge four samples agree on is far
likelier true than one a single sample invented.

Only LLM candidates are voted on. Structural edges (`backend.canon.structure`)
are derived deterministically from a node set, so running them N times would
produce N identical copies -- voting on that measures nothing. The caller
derives them ONCE, from the consensus node set, after this module has run.

DUPLICATE SEMANTICS DIFFER BY FLAG, and a consumer of the candidate artifact
has to know which it is holding. `--samples 1` bypasses this module entirely,
so the artifact carries within-section duplicates exactly as the three layer
passes emitted them -- one entity named by all three passes appears three
times, with `votes: 0`. `--samples N` (N > 1) routes through `consense`, which
collapses each `node_key`/`edge_key` to ONE record carrying its vote count. So
a 5-sample chapter-3 run yields 166 distinct nodes where a single run yields
246 rows over the same entities. Anything downstream that counts candidates,
or that assumes it must deduplicate, must read `run.samples` in the artifact
rather than infer the shape from the rows.
"""

from collections.abc import Callable, Iterable
from dataclasses import replace

from backend.canon.models import CandidateEdge, CandidateNode

# `(normalized name, entity_type, section_index)`. Section-scoped so the same
# name in two different rooms cannot vote for itself, and type-scoped because a
# coined QUEST sharing a LOCATION's name is a measured occurrence in this corpus.
NodeKey = tuple[str, str, int]
# `(normalized source, normalized target, rel_type, section_index)`. Direction
# and type are part of the identity: an inverted or retyped edge is a different
# claim, and it is exactly the failure the fabrication check found.
EdgeKey = tuple[str, str, str, int]

Sample = tuple[list[CandidateNode], list[CandidateEdge]]


def normalize(name: str) -> str:
    """Fold a name for vote identity: lowercase and strip, nothing cleverer.

    Deliberately NOT `grade.normalize_name`. Extraction must not import from the
    module that scores it -- see `anchor_quests`, which keeps its own fold for
    the same reason. The grade fold is also loose on purpose (it matches
    "Ismark" to "Ismark the Lesser"), and merging distinct names here would
    decide entity identity before anyone had voted on it. That is stage 2b's
    job.
    """
    return name.strip().lower()


def node_key(node: CandidateNode) -> NodeKey:
    return (normalize(node.name), node.entity_type, node.section_index)


def edge_key(edge: CandidateEdge) -> EdgeKey:
    return (
        normalize(edge.source_name),
        normalize(edge.target_name),
        edge.rel_type,
        edge.section_index,
    )


def _tally[T, K](per_sample: Iterable[list[T]], key: Callable[[T], K]) -> dict[K, tuple[T, int]]:
    """First-seen record and vote count for every distinct candidate.

    A candidate appearing twice *within* one sample is one vote, not two: the
    three layer passes of a single sample routinely name one entity more than
    once, and counting those would make a single sample able to clear k=3 on its
    own -- a frequency count wearing consensus as a disguise.

    Insertion order is first appearance, so the output order is deterministic.
    """
    tally: dict[K, tuple[T, int]] = {}
    for items in per_sample:
        counted: set[K] = set()
        for item in items:
            k = key(item)
            if k in counted:
                continue
            counted.add(k)
            first, votes = tally.get(k, (item, 0))
            tally[k] = (first, votes + 1)
    return tally


def _survivors[T, K](
    per_sample: Iterable[list[T]], key: Callable[[T], K], threshold: int
) -> list[T]:
    return [
        replace(first, votes=votes)  # never mutates the input samples
        for first, votes in _tally(per_sample, key).values()
        if votes >= threshold
    ]


def consense(
    samples: list[Sample],
    node_k: int,
    edge_k: int,
) -> tuple[list[CandidateNode], list[CandidateEdge]]:
    """The candidates at least `k` distinct samples produced, carrying their votes.

    `samples` is one `(nodes, edges)` pair per extraction run. A run with any
    failed call must be excluded by the caller before it gets here: a truncated
    sample makes every candidate in it look rarer than it is.

    Survivors keep the record from the sample that first produced them, plus the
    vote count, which stage 2b weights by.
    """
    if node_k < 1 or edge_k < 1:
        raise ValueError(f"k must be at least 1, got node_k={node_k}, edge_k={edge_k}")
    return (
        _survivors((nodes for nodes, _ in samples), node_key, node_k),
        _survivors((edges for _, edges in samples), edge_key, edge_k),
    )


def vote_histograms(samples: list[Sample]) -> tuple[dict[int, int], dict[int, int]]:
    """`{votes: how many candidates got that many}`, for nodes and for edges.

    Over the whole population, at no threshold: it is the evidence for choosing
    k, so it has to show what a given k would discard as well as what it keeps.
    """

    def histogram[T, K](per_sample: Iterable[list[T]], key: Callable[[T], K]) -> dict[int, int]:
        counts: dict[int, int] = {}
        for _, votes in _tally(per_sample, key).values():
            counts[votes] = counts.get(votes, 0) + 1
        return counts

    return (
        histogram((nodes for nodes, _ in samples), node_key),
        histogram((edges for _, edges in samples), edge_key),
    )


def format_votes(histogram: dict[int, int]) -> str:
    """`5:41  4:12  3:9  2:15  1:63` -- most-agreed first."""
    return "  ".join(f"{votes}:{count}" for votes, count in sorted(histogram.items(), reverse=True))
