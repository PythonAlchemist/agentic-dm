"""What the model is actually asked to answer from.

Pure rendering, so the grounding can be asserted directly rather than inferred
from an answer a model happened to produce.
"""


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
        path=kw.get("path", PATH_GRAPH),
        origin=kw.get("origin", "canon"),
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

    def test_a_keyword_passage_among_resolved_ones_is_marked_on_its_own_line(self):
        """`TEXT_SLOTS` puts a Lucene guess inside a result that resolved a
        name. The block-level warning does not fire for that result, so without
        a per-passage mark the model reads the guess as though a name had
        resolved to it."""
        block = canon_context.render(
            graph_retrieval(
                passage("cos:x#5", "Resolved", "a"),
                passage("cos:x#9", "Guessed", "b", path=PATH_TEXT, score=1.2),
            )
        )
        assert "Guessed  (keyword match" in block
        assert "Resolved  (keyword match" not in block

    def test_a_wholly_keyword_result_does_not_repeat_the_mark_per_passage(self):
        """The block already says it once, in stronger words."""
        result = Retrieval(
            question="q",
            passages=(passage("cos:x#0", "Foreword", "t", path=PATH_TEXT, score=1.2),),
            path=PATH_TEXT,
        )
        block = canon_context.render(result)
        assert "KEYWORD MATCH ONLY" in block
        assert "(keyword match — may be about something else)" not in block


class TestWhenThereIsNothing:
    def test_an_empty_retrieval_says_the_canon_does_not_cover_it(self):
        block = canon_context.render(Retrieval(question="q"))
        assert "nothing retrieved" in block

    def test_it_says_a_retrieval_miss_is_not_the_book_being_silent(self):
        """The distinction a DM's trust rests on: a model told only "not found"
        will helpfully answer from its memory of the published module.

        This asserted the literal words "3 of its 25 chapters" until the whole
        book was loaded and the sentence became false -- the model was told the
        corpus was a tenth present while it was complete. Pinning the CLAIM
        rather than the count is what keeps this from happening twice."""
        block = canon_context.render(Retrieval(question="q"))
        assert "Do not answer from memory" in block
        assert "is not the same as the book not containing it" in block

    def test_it_states_no_count_of_what_is_loaded(self):
        """A number describing the database does not belong in a constant."""
        block = canon_context.render(Retrieval(question="q"))
        assert "25 chapters" not in block


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
            question="q",
            passages=(passage("cos:x#0", "F", "t", path=PATH_TEXT),),
            path=PATH_TEXT,
        )
        assert canon_context.sources(result)[0]["path"] == PATH_TEXT

    def test_each_citation_takes_its_own_path_not_the_questions(self):
        """A mixed result cited every passage with the question's coarse label,
        which showed a Lucene guess in the UI as a resolved name."""
        result = graph_retrieval(
            passage("cos:x#5", "Resolved", "a"),
            passage("cos:x#9", "Guessed", "b", path=PATH_TEXT),
        )
        assert [r["path"] for r in canon_context.sources(result)] == [
            PATH_GRAPH,
            PATH_TEXT,
        ]

    def test_no_passages_means_no_citations(self):
        assert canon_context.sources(Retrieval(question="q")) == []


class TestSuggestingWhereAGenerationFits:
    """The agent already knows; it was throwing the answer away.

    A scene about the voyage retrieves six passages from Prisoner 13, the top
    one literally `Trek to the Prison` -- and the card then offered 546
    sections across thirteen unconnected heists with no suggestion, listing a
    museum room as readily as the voyage.
    """

    def _sourced(self, *pairs, path=PATH_GRAPH):
        return Retrieval(
            question="x",
            path=path,
            passages=tuple(
                Passage(
                    section_id=f"kftgv:{chapter}#{index}",
                    chapter=chapter,
                    chapter_index=0,
                    section=heading,
                    section_index=index,
                    text="t",
                    occurrences=1,
                    entity_ids=(),
                    path=path,
                )
                for index, (chapter, heading) in enumerate(pairs)
            ),
        )

    def test_it_proposes_a_passage_from_the_heaviest_chapter(self):
        retrieval = self._sourced(
            ("prisoner-13", "Trek to the Prison"),
            ("prisoner-13", "Approaching the Prison"),
            ("prisoner-13", "Prison Features"),
        )
        anchor, chapters = canon_context.suggest_anchor(retrieval)
        assert anchor == "kftgv:prisoner-13#0"
        assert chapters[0] == "prisoner-13"

    def test_weight_beats_rank_so_front_matter_does_not_win(self):
        """THE DEFECT THIS FIXES. Taking the single top passage proposed the
        book's Introduction for a mutiny on a prison barge: one general
        passage about rival crews outranked four from the adventure itself."""
        retrieval = self._sourced(
            ("introduction-a-collection-of-heists", "Rival Crew"),
            ("prisoner-13", "Trek to the Prison"),
            ("prisoner-13", "Revel's End"),
            ("prisoner-13", "Prison Features"),
        )
        anchor, chapters = canon_context.suggest_anchor(retrieval)
        assert chapters[0] == "prisoner-13"
        assert "introduction" not in anchor

    def test_a_single_chapter_still_wins_on_rank(self):
        """Weight must not swamp quality: one chapter contributing one very
        good passage beats another contributing one mediocre one."""
        retrieval = self._sourced(
            ("the-stygian-gambit", "Casino Features"),
            ("axe-from-the-grave", "Toadhop"),
        )
        anchor, _ = canon_context.suggest_anchor(retrieval)
        assert "the-stygian-gambit" in anchor

    def test_nothing_retrieved_proposes_nothing(self):
        assert canon_context.suggest_anchor(Retrieval(question="x")) == ("", ())

    def test_it_always_proposes_something_when_it_can(self):
        """A suggestion a DM can override beats a list of 546 to search."""
        retrieval = self._sourced(("prisoner-13", "Trek"), path=PATH_TEXT)
        anchor, _ = canon_context.suggest_anchor(retrieval)
        assert anchor


class TestTheAnchorFollowsTheStrongerSignal:
    """`suggest_anchor` weighted a resolved name and a keyword guess the same,
    so four keyword hits scattered across one chapter outvoted four names the
    question actually resolved. "A cast of enemies for the sea battle"
    anchored past the voyage the fight happens on."""

    def test_a_chapter_with_a_resolved_name_beats_one_with_more_guesses(self):
        shown = graph_retrieval(
            passage("cos:guessed#1", "Guessed A", "x", chapter="loud", path=PATH_TEXT),
            passage("cos:guessed#2", "Guessed B", "x", chapter="loud", path=PATH_TEXT),
            passage("cos:guessed#3", "Guessed C", "x", chapter="loud", path=PATH_TEXT),
            passage("cos:named#1", "Named", "x", chapter="quiet", path=PATH_GRAPH),
        )
        anchor, chapters = canon_context.suggest_anchor(shown)
        assert chapters[0] == "quiet", "a fact outranks three guesses"
        assert anchor == "cos:named#1"

    def test_weight_still_decides_between_chapters_that_both_resolved(self):
        """The rule is lexicographic, not a multiplier: resolution first, then
        the weighting that was already there. A number would have been a guess
        about how much more a name is worth."""
        shown = graph_retrieval(
            passage("cos:a#1", "A one", "x", chapter="big", path=PATH_GRAPH),
            passage("cos:a#2", "A two", "x", chapter="big", path=PATH_GRAPH),
            passage("cos:b#1", "B one", "x", chapter="small", path=PATH_GRAPH),
        )
        _anchor, chapters = canon_context.suggest_anchor(shown)
        assert chapters[0] == "big"

    def test_the_dms_own_material_named_by_the_question_wins_outright(self):
        """They have already decided where that scene lives, and a thing
        generated ABOUT it belongs beside it. This is the only signal here
        that reflects a decision a person actually made."""
        shown = graph_retrieval(
            passage("hb:t:the-sea-battle#0", "The Sea Battle", "x",
                    chapter="t", path=PATH_GRAPH, origin="campaign"),
            passage("cos:canon#1", "A Canon Section", "x",
                    chapter="loud", path=PATH_GRAPH),
            passage("cos:canon#2", "Another", "x", chapter="loud", path=PATH_GRAPH),
        )
        anchor, _chapters = canon_context.suggest_anchor(shown)
        assert anchor == "hb:t:the-sea-battle#0"

    def test_a_campaign_passage_that_only_RODE_ALONG_does_not_win(self):
        """One rides along positionally beside almost any canon hit. Only a
        campaign passage the question RESOLVED means the generation is about
        it -- otherwise every draft would anchor to whatever scene happened to
        sit near the retrieval."""
        shown = graph_retrieval(
            passage("cos:canon#1", "A Canon Section", "x",
                    chapter="loud", path=PATH_GRAPH),
            passage("hb:t:rode-along#0", "Rode Along", "x",
                    chapter="t", path=PATH_TEXT, origin="campaign"),
        )
        anchor, _chapters = canon_context.suggest_anchor(shown)
        assert anchor == "cos:canon#1"
