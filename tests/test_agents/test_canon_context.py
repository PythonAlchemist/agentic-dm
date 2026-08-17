"""What the model is actually asked to answer from.

Pure rendering, so the grounding can be asserted directly rather than inferred
from an answer a model happened to produce.
"""

import pytest

from backend.agents import canon_context
from backend.canon.retrieval import PATH_GRAPH, PATH_TEXT, Passage, Retrieval


def passage(section_id: str, section: str, text: str, **kw) -> Passage:
    return Passage(
        section_id=section_id,
        chapter=kw.get("chapter", "the-village-of-barovia"),
        chapter_index=kw.get("chapter_index", 4),
        section=section,
        section_index=kw.get("section_index", 5),
        text=text,
        occurrences=kw.get("occurrences", 1),
        entity_ids=kw.get("entity_ids", ("cos:ismark-kolyanovich",)),
        score=kw.get("score"),
    )


def graph_retrieval(*passages, accepted=(), proposed=()) -> Retrieval:
    return Retrieval(
        question="q",
        anchors=(),
        passages=tuple(passages),
        accepted=tuple(accepted),
        proposed=tuple(proposed),
        path=PATH_GRAPH,
    )


class TestThePassagesTravel:
    """The defect this exists not to repeat: the pipeline beside it inserts a
    list of source NAMES and tells the model context was retrieved, which
    grounds nothing."""

    def test_the_prose_itself_is_in_the_block(self):
        block = canon_context.render(
            graph_retrieval(passage("cos:x#5", "E2. Blood of the Vine Tavern",
                                    "Ismark sits by himself at a corner table."))
        )
        assert "Ismark sits by himself at a corner table." in block

    def test_each_passage_is_numbered_so_it_can_be_cited(self):
        block = canon_context.render(
            graph_retrieval(
                passage("cos:x#5", "First", "alpha"),
                passage("cos:x#6", "Second", "beta"),
            )
        )
        assert "[1]" in block and "[2]" in block
        assert block.index("[1]") < block.index("[2]")

    def test_the_section_is_named_so_a_dm_can_open_the_book(self):
        block = canon_context.render(
            graph_retrieval(passage("cos:x#5", "E5g. Undercroft", "A gaunt shape."))
        )
        assert "E5g. Undercroft" in block


class TestProvenanceSurvives:
    def test_a_guessed_relationship_is_labelled_as_unreliable(self):
        """Roughly a third are wrong. Handed over unlabelled, they wear the same
        clothes as the book's own words."""
        block = canon_context.render(
            graph_retrieval(
                passage("cos:x#5", "S", "text"),
                proposed=[{"entity": "Ismark", "relationship": "SEEKS",
                           "other": "Ireena", "direction": "out"}],
            )
        )
        assert "GUESSED" in block
        assert "third are wrong" in block
        assert "Ismark -SEEKS-> Ireena" in block

    def test_a_derived_relationship_is_labelled_as_reliable(self):
        block = canon_context.render(
            graph_retrieval(
                passage("cos:x#5", "S", "text"),
                accepted=[{"entity": "Chapel", "relationship": "LOCATED_IN",
                           "other": "Church", "direction": "out"}],
            )
        )
        assert "DERIVED" in block
        assert "Chapel -LOCATED_IN-> Church" in block

    def test_the_two_kinds_are_never_mixed_into_one_list(self):
        block = canon_context.render(
            graph_retrieval(
                passage("cos:x#5", "S", "text"),
                accepted=[{"entity": "A", "relationship": "CONTAINS",
                           "other": "B", "direction": "out"}],
                proposed=[{"entity": "C", "relationship": "SEEKS",
                           "other": "D", "direction": "out"}],
            )
        )
        assert block.index("A -CONTAINS-> B") < block.index("GUESSED")
        assert block.index("GUESSED") < block.index("C -SEEKS-> D")

    def test_an_inbound_edge_is_written_in_the_graphs_own_direction(self):
        """`Strahd SEEKS Ireena` and `Ireena SEEKS Strahd` are different claims,
        and reversal is one of the extractor's measured failure modes."""
        block = canon_context.render(
            graph_retrieval(
                passage("cos:x#5", "S", "text"),
                proposed=[{"entity": "Ireena", "relationship": "SEEKS",
                           "other": "Strahd", "direction": "in"}],
            )
        )
        assert "Strahd -SEEKS-> Ireena" in block

    def test_a_keyword_match_is_flagged_as_possibly_irrelevant(self):
        result = Retrieval(
            question="q",
            passages=(passage("cos:x#0", "Foreword", "Byron in Switzerland.", score=1.2),),
            path=PATH_TEXT,
            terms=("capital", "france"),
        )
        block = canon_context.render(result)
        assert "KEYWORD MATCH ONLY" in block
        assert "capital, france" in block

    def test_a_resolved_question_carries_no_keyword_warning(self):
        block = canon_context.render(graph_retrieval(passage("cos:x#5", "S", "t")))
        assert "KEYWORD MATCH ONLY" not in block


class TestWhenThereIsNothing:
    def test_an_empty_retrieval_says_the_canon_does_not_cover_it(self):
        block = canon_context.render(Retrieval(question="q"))
        assert "nothing retrieved" in block

    def test_it_says_the_graph_is_incomplete_rather_than_the_book(self):
        """The distinction a DM's trust rests on. 3 of 25 chapters are loaded,
        so silence means 'not loaded', and a model told only 'not found' will
        helpfully answer from its memory of the published module."""
        block = canon_context.render(Retrieval(question="q"))
        assert "3 of its 25 chapters" in block
        assert "Do not answer from memory" in block


class TestTheEdgeBudget:
    def test_what_is_cut_is_counted_rather_than_dropped_silently(self):
        edges = [
            {"entity": f"E{i}", "relationship": "SEEKS", "other": "X", "direction": "out"}
            for i in range(20)
        ]
        block = canon_context.render(
            graph_retrieval(passage("cos:x#5", "S", "t"), proposed=edges), max_edges=5
        )
        assert "and 15 more, not shown" in block
        assert "E19 -SEEKS-> X" not in block


class TestSources:
    def test_one_citation_per_passage_numbered_as_the_model_saw_them(self):
        result = graph_retrieval(
            passage("cos:x#5", "First", "a"), passage("cos:x#6", "Second", "b")
        )
        rows = canon_context.sources(result)
        assert [r["citation"] for r in rows] == ["[1]", "[2]"]
        assert [r["source"] for r in rows] == ["cos:x#5", "cos:x#6"]

    def test_the_path_rides_along_so_a_keyword_hit_can_be_shown_differently(self):
        result = Retrieval(
            question="q", passages=(passage("cos:x#0", "F", "t"),), path=PATH_TEXT
        )
        assert canon_context.sources(result)[0]["path"] == PATH_TEXT

    def test_no_passages_means_no_citations(self):
        assert canon_context.sources(Retrieval(question="q")) == []
