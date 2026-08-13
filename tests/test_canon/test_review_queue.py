"""What a human actually sees at gate G3.

`render` is pure so this needs no database: the queue is the only precision gate
the pipeline has, and a report that silently drops an edge would let a wrong one
into canon unread. The Neo4j half -- that the query finds proposed edges and
skips accepted ones -- is pinned in `test_write_canon_neo4j.py`.
"""

from backend.scripts.review_queue import build_parser, render

SLUG = "the-village-of-barovia"


def row(source: str, target: str, rel_type: str = "OWNS", **kwargs) -> dict:
    return {
        "rel_type": rel_type,
        "source": source,
        "target": target,
        "status": "proposed",
        "evidence": f"{source} does something to {target}.",
        "conflict": None,
        "votes": 3,
        "section_heading": "E1. Blood of the Vine Tavern",
        "endpoint_resolved": None,
        **kwargs,
    }


class TestRender:
    def test_every_proposed_edge_appears_with_its_evidence(self):
        text = render(SLUG, [row("Alenka", "Blood of the Vine Tavern")])

        assert "Alenka -> Blood of the Vine Tavern" in text
        assert "Alenka does something to Blood of the Vine Tavern." in text

    def test_edges_are_grouped_by_relationship_type(self):
        """A reviewer judges OWNS claims as a set: three tavern patrons promoted
        to owners is obvious in a group and invisible one edge at a time."""
        text = render(
            SLUG,
            [
                row("Alenka", "Blood of the Vine Tavern"),
                row("Mirabel", "Blood of the Vine Tavern"),
                row("Ismark", "Ireena", rel_type="OPPOSES"),
            ],
        )

        assert "OWNS  (2)" in text
        assert "OPPOSES  (1)" in text

    def test_a_conflict_is_flagged_and_hoisted_to_the_top(self):
        text = render(
            SLUG,
            [
                row("Ireena", "Tatyana", rel_type="IDENTITY_OF", conflict="RELATED_TO"),
                row("Alenka", "Blood of the Vine Tavern"),
            ],
        )

        assert "CONTRADICTIONS -- read these first" in text
        assert "CONFLICTS WITH RELATED_TO" in text
        assert text.index("CONTRADICTIONS") < text.index("OWNS  (1)")

    def test_a_conflicted_edge_says_what_beat_it(self):
        text = render(
            SLUG,
            [
                row(
                    "Church",
                    "Undercroft",
                    rel_type="LOCATED_IN",
                    status="conflicted",
                    conflict="CONTAINS",
                )
            ],
        )

        assert "LOST TO AN ACCEPTED EDGE" in text

    def test_a_vacuous_constraint_check_is_called_out(self):
        """The endpoint was CHOSEN to satisfy the domain/range table, so a
        reviewer must not read a clean check as support for the edge."""
        text = render(
            SLUG, [row("Ireena", "Tatyana", rel_type="IDENTITY_OF", endpoint_resolved="constraint")]
        )

        assert "endpoint chosen by constraint" in text

    def test_a_missing_evidence_span_is_stated_not_omitted(self):
        """An edge with no span is a claim with no stated support, and that is
        review-relevant rather than a formatting problem."""
        text = render(SLUG, [row("Ireena", "Castle Ravenloft", rel_type="THREATENS", evidence="")])

        assert "(no evidence span recorded)" in text

    def test_an_empty_queue_says_so(self):
        """An empty queue and a query that found the wrong chapter look
        identical when the report is silent."""
        text = render(SLUG, [])

        assert "nothing proposed for this chapter" in text
        assert SLUG in text

    def test_the_header_counts_the_queue_and_the_contradictions(self):
        text = render(
            SLUG,
            [
                row("Ireena", "Tatyana", rel_type="IDENTITY_OF", conflict="RELATED_TO"),
                row("Ireena", "Tatyana", rel_type="RELATED_TO", conflict="IDENTITY_OF"),
                row("Alenka", "Blood of the Vine Tavern"),
            ],
        )

        assert "3 proposed edge(s) awaiting review, 2 in a mutual-exclusion conflict." in text

    def test_a_long_evidence_span_is_wrapped_and_never_truncated(self):
        """The span IS the thing under review; a cut one has a reviewer
        approving a claim on half of its support."""
        span = (
            "Strahd intends to make Ireena his bride, turn her into a vampire, and lock her "
            "away in the castle crypts for all time, which is the whole of his interest in "
            "the village of Barovia and everyone living in it."
        )
        text = render(SLUG, [row("Strahd", "Ireena", rel_type="HOSTILE_TO", evidence=span)])

        assert all(len(line) <= 100 for line in text.splitlines())
        assert "".join(text.split()) .count("".join(span.split())) == 1


class TestParser:
    def test_the_chapter_slug_is_required(self):
        parser = build_parser()
        assert parser.parse_args([SLUG]).chapter == SLUG
