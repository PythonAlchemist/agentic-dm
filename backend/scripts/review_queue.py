#!/usr/bin/env python3
"""Print one chapter's UNVETTED canon for a human to read at gate G3.

This is the only precision gate the pipeline has. Recall is monotone in
candidate count, so it cannot rank extractors -- a regex shotgun outscores the
tuned pipeline -- and a wiki oracle failed because 8 of the 13 core NPCs have no
page. A hand read of all 30 LLM edges in chapter 3 found about a third wrong
while all 37 derived edges were sound, which is why the accepted layer is not
printed here at all: a reviewer's attention is the scarce resource, and spending
it on edges that are already deterministic wastes it.

    uv run python -m backend.scripts.review_queue the-village-of-barovia

A TERMINAL report, not a JSON dump. It is grouped by relationship type because a
reviewer judges `OWNS` claims as a set -- three tavern patrons promoted to
owners is obvious in a group and invisible one edge at a time -- and conflicts
are hoisted to the top because a contradiction is a stronger signal than any
single edge's plausibility.
"""

import argparse
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.canon.writer import ACCEPTED, CANON_PLANE, CONFLICTED
from backend.core.database import neo4j_session

#: Evidence spans run to a full sentence of book prose. Wrapped rather than
#: truncated: the span IS the thing being reviewed, and a cut one would have a
#: reviewer approving a claim on half of its support.
WRAP = 96


def fetch_rows(session, chapter_slug: str) -> list[dict]:
    """Every non-accepted canon edge of one chapter, with its evidence.

    Scoped by `plane` as well as `chapter_slug`: a campaign's own play may carry
    a chapter slug for provenance, and it is not canon under review.
    """
    return [
        dict(record)
        for record in session.run(
            """
            MATCH (a:Entity)-[r]->(b:Entity)
            WHERE r.chapter_slug = $slug AND r.plane = $plane AND r.status <> $accepted
            RETURN type(r) AS rel_type,
                   a.name AS source, b.name AS target,
                   r.status AS status, r.evidence AS evidence,
                   r.conflict AS conflict, r.votes AS votes,
                   r.section_heading AS section_heading,
                   r.endpoint_resolved AS endpoint_resolved
            ORDER BY rel_type, source, target
            """,
            {"slug": chapter_slug, "plane": CANON_PLANE, "accepted": ACCEPTED},
        )
    ]


def _edge_block(row: dict) -> list[str]:
    """One edge: the claim, then the prose it rests on."""
    flags = []
    if row.get("conflict"):
        flags.append(f"CONFLICTS WITH {row['conflict']}")
    if row.get("status") == CONFLICTED:
        flags.append("LOST TO AN ACCEPTED EDGE")
    if row.get("endpoint_resolved"):
        # The domain/range check is vacuous on these -- the endpoint was CHOSEN
        # to satisfy it -- so a reviewer must not read a clean check as support.
        flags.append("endpoint chosen by constraint")

    head = f"  {row['source']} -> {row['target']}"
    if row.get("votes"):
        head += f"   [{row['votes']} votes]"
    lines = [head]
    if flags:
        lines.append(f"    !! {'; '.join(flags)}")
    evidence = (row.get("evidence") or "").strip()
    if evidence:
        lines.extend(
            textwrap.wrap(
                evidence, width=WRAP, initial_indent="    ", subsequent_indent="    "
            )
        )
    else:
        # Absence is itself review-relevant: an edge with no span is a claim
        # with no stated support.
        lines.append("    (no evidence span recorded)")
    if row.get("section_heading"):
        lines.append(f"    from: {row['section_heading']}")
    return lines


def render(chapter_slug: str, rows: list[dict]) -> str:
    """The whole queue as one block of text.

    Pure, so what a reviewer sees is assertable without a database.
    """
    conflicted = [row for row in rows if row.get("conflict")]
    lines = [
        f"REVIEW QUEUE -- {chapter_slug}",
        f"{len(rows)} proposed edge(s) awaiting review, "
        f"{len(conflicted)} in a mutual-exclusion conflict.",
        "Accepted (derived) edges are not listed: they are deterministic.",
        "",
    ]

    if not rows:
        # Printed rather than silent: an empty queue and a query that found the
        # wrong chapter look identical otherwise.
        lines.append("  nothing proposed for this chapter.")
        return "\n".join(lines)

    if conflicted:
        lines.append("CONTRADICTIONS -- read these first")
        lines.append("-" * WRAP)
        lines.append(
            "  Both halves are in the graph on purpose. Nothing automatic chose between them:"
        )
        lines.append("  there is no oracle, and a silent guess would look exactly like a fact.")
        lines.append("")
        for row in conflicted:
            lines.append(f"  [{row['rel_type']}]")
            lines.extend(_edge_block(row))
            lines.append("")

    by_type: dict[str, list[dict]] = {}
    for row in rows:
        by_type.setdefault(row["rel_type"], []).append(row)

    for rel_type in sorted(by_type):
        group = by_type[rel_type]
        lines.append(f"{rel_type}  ({len(group)})")
        lines.append("-" * WRAP)
        for row in group:
            lines.extend(_edge_block(row))
            lines.append("")

    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("chapter", metavar="SLUG", help="Chapter slug, e.g. the-village-of-barovia")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    with neo4j_session() as session:
        rows = fetch_rows(session, args.chapter)
    print(render(args.chapter, rows))


if __name__ == "__main__":
    main()
