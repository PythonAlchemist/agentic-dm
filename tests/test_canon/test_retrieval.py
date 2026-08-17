"""Question in, grounded canon out.

The pure half -- finding names in a question, and the scoring the harness does
with what comes back -- needs no database and is tested here directly. The
graph half is marked `neo4j` and writes its own small chapter, following the
same `pytest:` id and `Zz` name conventions as `test_write_canon_neo4j`: the
mention scan matches on NAME across the whole canon plane, so an unprefixed test
entity would be found by the real book sitting in the same local database.
"""

import pytest

from backend.canon.aliases import WriteAlias
from backend.canon.models import Section
from backend.canon.retrieval import CanonRetriever, dedupe_edges, find_names
from backend.canon.spine import ChapterSpine, WriteSection
from backend.canon.writer import WriteNode, ensure_schema, write_chapter
from backend.core.database import neo4j_session
from backend.scripts.eval_retrieval import reciprocal_rank, score, summarize


class TestFindingNamesInAQuestion:
    """The only step retrieval adds to the lookup, so the only one that can be
    wrong in a new way."""

    def test_a_name_the_question_uses_is_found(self):
        assert find_names("Who is Ismark?", ["Ismark", "Ireena"]) == ["Ismark"]

    def test_the_longest_form_wins_and_the_shorter_one_does_not_also_match(self):
        """A question naming someone in full contains their short name too.

        Both would anchor twice on one entity and let a single name outweigh
        everything else the question mentioned.
        """
        found = find_names("Tell me about Ireena Kolyana.", ["Ireena", "Ireena Kolyana"])
        assert found == ["Ireena Kolyana"]

    def test_two_different_names_both_anchor(self):
        found = find_names("Does Ismark trust Ireena?", ["Ismark", "Ireena"])
        assert sorted(found) == ["Ireena", "Ismark"]

    def test_a_name_repeated_anchors_once(self):
        assert find_names("Strahd, and again Strahd.", ["Strahd"]) == ["Strahd"]

    def test_a_partial_word_is_not_a_match(self):
        """Whole-word, the scan's own rule -- `Doru` must not match `Dorugan`."""
        assert find_names("Who is Dorugan?", ["Doru"]) == []

    def test_a_lowercase_single_word_does_not_match_under_the_scans_rule(self):
        """The rule that makes `Light` a LORE entity rather than every torch."""
        assert find_names("what about the light?", ["Light"]) == []

    def test_fold_case_is_what_rescues_a_typed_question(self):
        """Nobody types `the Trapdoor in the Church` with the capitals right."""
        found = find_names(
            "how do I open the trapdoor in the church?",
            ["Trapdoor", "Church"],
            fold_case=True,
        )
        assert sorted(found) == ["Church", "Trapdoor"]

    def test_a_multi_word_name_matches_whatever_its_casing(self):
        found = find_names("where is the blood of the vine tavern?",
                           ["Blood of the Vine Tavern"])
        assert found == ["Blood of the Vine Tavern"]

    def test_an_empty_form_cannot_match_everywhere(self):
        """A name folding to nothing compiles to a pattern matching at every
        position, which is the one way this could anchor once per character."""
        assert find_names("Who is Ismark?", ["", "   "]) == []


class TestDedupingEdges:
    """`EDGES` reads both directions on purpose -- half of what a DM wants about
    an NPC is written with the NPC as the target. When BOTH endpoints are
    anchors, that returns each edge twice."""

    def test_the_same_edge_seen_from_both_ends_is_one_row(self):
        rows = [
            {"entity": "Mirabel", "relationship": "OWNS", "other": "Tavern",
             "direction": "out", "status": "accepted"},
            {"entity": "Tavern", "relationship": "OWNS", "other": "Mirabel",
             "direction": "in", "status": "accepted"},
        ]
        assert len(dedupe_edges(rows)) == 1

    def test_the_surviving_row_keeps_its_own_direction(self):
        """`_edge_line` flips an inbound row when rendering, so a survivor that
        lost its direction would have its arrow written backwards -- and
        reversal is one of the extractor's measured failure modes."""
        rows = [
            {"entity": "Tavern", "relationship": "OWNS", "other": "Mirabel",
             "direction": "in", "status": "accepted"},
        ]
        assert dedupe_edges(rows)[0]["direction"] == "in"

    def test_two_genuinely_different_edges_both_survive(self):
        rows = [
            {"entity": "Mirabel", "relationship": "OWNS", "other": "Tavern",
             "direction": "out", "status": "accepted"},
            {"entity": "Sorvia", "relationship": "OWNS", "other": "Tavern",
             "direction": "out", "status": "accepted"},
        ]
        assert len(dedupe_edges(rows)) == 2

    def test_opposite_claims_between_one_pair_are_not_collapsed(self):
        """`A SEEKS B` and `B SEEKS A` are different claims about the same two
        nodes. Both are outbound, so nothing about direction makes them one."""
        rows = [
            {"entity": "Strahd", "relationship": "SEEKS", "other": "Ireena",
             "direction": "out", "status": "proposed"},
            {"entity": "Ireena", "relationship": "SEEKS", "other": "Strahd",
             "direction": "out", "status": "proposed"},
        ]
        assert len(dedupe_edges(rows)) == 2


class TestScoring:
    """What the harness concludes from a retrieval, with no graph involved."""

    def test_reciprocal_rank_is_one_over_the_first_gold_position(self):
        assert reciprocal_rank(("a", "b", "c"), ["c"]) == pytest.approx(1 / 3)
        assert reciprocal_rank(("a", "b"), ["a"]) == 1.0

    def test_a_gold_section_that_was_never_returned_scores_zero(self):
        """Scored over what was RETURNED, so a section the budget cut scores 0
        rather than scoring by where it would have sat unbounded. The budget is
        part of the system being measured."""
        assert reciprocal_rank(("a", "b"), ["z"]) == 0.0

    def test_recall_is_reported_twice_and_the_pair_is_the_point(self):
        """Overall recall and recall-over-anchored answer different questions:
        one asks whether the system helped, the other whether RANKING is the
        thing to fix."""
        rows = [
            {"id": "q1", "anchored": True, "hit": True, "rr": 1.0, "path": "graph"},
            {"id": "q2", "anchored": True, "hit": False, "rr": 0.0, "path": "graph"},
            {"id": "q3", "anchored": False, "hit": False, "rr": 0.0, "path": "-"},
            {"id": "q4", "anchored": False, "hit": False, "rr": 0.0, "path": "-"},
        ]
        s = summarize(rows)
        assert s["recall_overall"] == pytest.approx(0.25)
        assert s["recall_anchored"] == pytest.approx(0.5)
        assert s["no_anchor"] == ["q3", "q4"]
        assert s["anchored_but_missed"] == ["q2"]

    def test_a_text_hit_cannot_inflate_the_anchored_recall(self):
        """Two populations, one divided by the other, reported 111%. A text hit
        answers a question that never anchored, so it belongs to neither the
        numerator nor the denominator of anchored recall."""
        rows = [
            {"id": "q1", "anchored": True, "hit": True, "rr": 1.0, "path": "graph"},
            {"id": "q2", "anchored": False, "hit": True, "rr": 1.0, "path": "text"},
            {"id": "q3", "anchored": False, "hit": True, "rr": 1.0, "path": "text"},
        ]
        s = summarize(rows)
        assert s["recall_anchored"] == pytest.approx(1.0)
        assert s["recall_overall"] == pytest.approx(1.0)

    def test_the_two_paths_are_reported_apart(self):
        """A graph hit resolved a name the book wrote; a text hit is a Lucene
        score agreeing with a guess. Merged, the fallback would read as an
        improvement to the graph."""
        rows = [
            {"id": "q1", "anchored": True, "hit": True, "rr": 1.0, "path": "graph"},
            {"id": "q2", "anchored": True, "hit": False, "rr": 0.0, "path": "graph"},
            {"id": "q3", "anchored": False, "hit": True, "rr": 1.0, "path": "text"},
        ]
        by_path = summarize(rows)["by_path"]
        assert by_path["graph"] == {"n": 2, "hits": 1}
        assert by_path["text"] == {"n": 1, "hits": 1}

    def test_a_hit_is_membership_not_position(self):
        from backend.canon.retrieval import Passage, Retrieval

        result = Retrieval(
            question="q",
            anchors=(),
            passages=(
                Passage("cos:x#1", "x", 0, "S", 1, "t", 1, ("e",)),
                Passage("cos:x#9", "x", 0, "S", 9, "t", 1, ("e",)),
            ),
        )
        row = score({"id": "q1", "question": "q", "sections": ["cos:x#9"]}, result)
        assert row["hit"] is True
        assert row["rr"] == pytest.approx(0.5)


# -- the graph half ---------------------------------------------------------

pytest_neo4j = pytest.mark.neo4j

CHAPTER = "pytest-retrieval"
BOOK = "pytest-book"
PREFIX = "pytest:"
MARKER = "Zz"


def named(name: str) -> str:
    """See `test_write_canon_neo4j.NAME_MARKER`: every TOKEN carries the marker,
    so the real book's `Church` cannot match inside a test name."""
    return " ".join(MARKER + token for token in name.split())


def _clean(session) -> None:
    session.run("MATCH (n:Entity) WHERE n.id STARTS WITH $p DETACH DELETE n", {"p": PREFIX})
    session.run("MATCH (m:Mention {chapter_slug:$c}) DETACH DELETE m", {"c": CHAPTER})
    session.run("MATCH (s:Section {chapter_slug:$c}) DETACH DELETE s", {"c": CHAPTER})
    session.run("MATCH (c:Chapter {slug:$c}) DETACH DELETE c", {"c": CHAPTER})
    session.run("MATCH (b:Book {slug:$b}) DETACH DELETE b", {"b": BOOK})
    session.run("MATCH (a:Alias) WHERE NOT (a)-[:ALIAS_OF]->() DETACH DELETE a")


@pytest.fixture
def graph():
    with neo4j_session() as session:
        ensure_schema(session)
        _clean(session)
        yield session
        _clean(session)


def _section(index: int, heading: str, text: str) -> Section:
    return Section(
        chapter_slug=CHAPTER,
        chapter_title="A Test Chapter",
        heading=heading,
        index=index,
        markdown=text,
        depth=1,
        parent_index=-1,
    )


@pytest.fixture
def written(graph):
    """One small chapter: a priest named in two sections, a room in one."""
    priest = WriteNode(
        id=f"{PREFIX}donavich",
        name=named("Donavich"),
        entity_types=("NPC",),
        chapter_slug=CHAPTER,
        votes=5,
    )
    room = WriteNode(
        id=f"{PREFIX}undercroft",
        name=named("Undercroft"),
        entity_types=("LOCATION",),
        chapter_slug=CHAPTER,
        votes=5,
    )
    # The LOUDER section is deliberately the LATER one. With the loud section
    # first, every ranking assertion below passes on the book-order tiebreak
    # alone -- neutering the occurrence signal entirely left the tests green,
    # which is the shape of a test that cannot fail.
    sections = [
        # `vestments` appears in the QUIETER section on purpose: it is what the
        # ranking test uses to check that a question's non-name words can beat a
        # louder section.
        _section(0, "The Church", f"{named('Donavich')} prays here in soiled vestments."),
        _section(1, "Below", f"{named('Donavich')} listens at the {named('Undercroft')}. "
                             f"{named('Donavich')} waits."),
        _section(2, "Elsewhere", "Nothing relevant happens in this section at all."),
    ]
    write_chapter(
        graph,
        CHAPTER,
        [priest, room],
        [],
        _spine(sections),
        [WriteAlias(f"{PREFIX}donavich", named("Father Donavich"))],
    )
    return graph


def _spine(sections: list[Section]) -> ChapterSpine:
    """Built by hand rather than through `plan_spine`, so a section's text is
    exactly what these tests wrote and the ranking assertions mean what they
    say."""
    return ChapterSpine(
        book_slug=BOOK,
        book_title="A Test Book",
        chapter_slug=CHAPTER,
        chapter_index=0,
        chapter_title="A Test Chapter",
        sections=[
            WriteSection(
                id=f"cos:{CHAPTER}#{s.index}",
                chapter_slug=CHAPTER,
                heading=s.heading,
                index=s.index,
                depth=1,
                parent_index=-1,
                text=s.markdown,
            )
            for s in sections
        ],
        describes=[],
    )


@pytest.mark.neo4j
class TestRetrievingFromTheGraph:
    def test_a_question_naming_an_entity_returns_its_sections(self, written):
        result = CanonRetriever().retrieve(f"Who is {named('Donavich')}?")
        assert [a.name for a in result.anchors] == [named("Donavich")]
        assert f"cos:{CHAPTER}#0" in result.section_ids
        assert f"cos:{CHAPTER}#2" not in result.section_ids

    def test_the_section_id_matches_the_one_the_write_path_minted(self, written):
        """`_section_id` rebuilds the id from parts rather than reading it, so
        the format has to be pinned against real sections in the graph."""
        rebuilt = set(CanonRetriever().retrieve(f"Who is {named('Donavich')}?").section_ids)
        real = {
            row["id"]
            for row in written.run(
                "MATCH (s:Section {chapter_slug:$c}) RETURN s.id AS id", {"c": CHAPTER}
            )
        }
        assert rebuilt and rebuilt <= real

    def test_the_loudest_section_ranks_first_even_when_the_book_puts_it_later(self, written):
        """Section 1 names the priest twice; section 0 names him once.

        The order is deliberately against the book's, so this fails if the
        occurrence signal is dropped and the ranking falls back to document
        order -- which it did, silently, until this test was written to notice.
        """
        result = CanonRetriever().retrieve(f"Tell me about {named('Donavich')}.")
        assert result.section_ids[0] == f"cos:{CHAPTER}#1"

    def test_a_questions_own_words_can_beat_a_louder_section(self, written):
        """The defect this ranking exists to fix.

        Section 1 names the priest twice and section 0 once, so occurrences
        alone put section 1 first -- and the previous test asserts exactly that.
        Ask about something section 0 actually discusses and it must win, even
        though the anchor is quieter there. On the real set this is what moved
        "who are Strahd's undead enemies" from ninth to second.
        """
        result = CanonRetriever().retrieve(
            f"What vestments does {named('Donavich')} wear?"
        )
        assert result.section_ids[0] == f"cos:{CHAPTER}#0"
        assert result.passages[0].term_hits >= 1

    def test_the_anchors_own_name_is_not_also_scored_as_a_term(self, written):
        """Counting it twice -- once as occurrences, once as a matched word --
        would re-favour the broad sections the term signal is meant to demote."""
        result = CanonRetriever().retrieve(f"Where is {named('Donavich')}?")
        assert result.passages
        assert all(p.term_hits == 0 for p in result.passages)

    def test_a_word_the_question_never_used_scores_nothing(self, written):
        result = CanonRetriever().retrieve(f"Tell me about {named('Donavich')}.")
        assert all(p.term_hits == 0 for p in result.passages)

    def test_a_recorded_alias_resolves_to_the_same_entity(self, written):
        result = CanonRetriever().retrieve(f"Who is {named('Father Donavich')}?")
        assert [a.entity_id for a in result.anchors] == [f"{PREFIX}donavich"]

    def test_a_question_naming_nothing_is_answered_by_text_and_labelled_as_such(
        self, written
    ):
        """The fallback's contract, and its cost stated honestly.

        The text path CANNOT say it does not know: any question sharing one word
        with any section returns that section. "What is the capital of France?"
        comes back with the foreword, which discusses Byron in Switzerland. What
        the caller is owed is not silence but LABELLING -- `path` says a Lucene
        score answered this, `terms` says what was searched, and every passage
        carries its score. A caller that treats a text answer as a name match is
        then making its own mistake, not inheriting one.
        """
        result = CanonRetriever().retrieve("What is the capital of France?")
        assert result.anchors == ()
        assert result.path == "text"
        assert result.terms == ("capital", "france")
        assert all(p.score is not None for p in result.passages)

    def test_the_text_path_still_carries_what_the_graph_knows(self, written):
        """The defect a real question exposed.

        Asked "who owns the tavern" -- which names nothing, `tavern` being a
        common noun nobody should alias -- the text path found section E2,
        exactly the right section, and returned prose alone. Three `OWNS` edges
        a human had accepted about that very room never reached the model, which
        answered that the canon did not cover it.

        Which sections to read is still a guess and still labelled `text`. What
        the graph knows about the entities in them is not a guess.
        """
        result = CanonRetriever().retrieve("who listens below")
        assert result.path == "text"
        assert result.accepted or result.proposed, (
            "a section retrieved by text must still bring its entities' edges"
        )

    def test_the_text_path_honours_the_passage_width(self, written):
        """It used to call `derive_passage` directly and always send one
        sentence, silently ignoring the setting."""
        wide = CanonRetriever(passage_width="section").retrieve("who listens below")
        narrow = CanonRetriever(passage_width="sentence").retrieve("who listens below")
        assert len(wide.passages[0].text) > len(narrow.passages[0].text)

    def test_a_graph_passage_carries_no_score(self, written):
        """`None`, not `0.0`. A name match has no score, and a zero would read
        as 'scored, badly'."""
        result = CanonRetriever().retrieve(f"Who is {named('Donavich')}?")
        assert result.path == "graph"
        assert all(p.score is None for p in result.passages)

    def test_a_question_whose_words_are_all_scaffolding_searches_for_nothing(
        self, written
    ):
        """`content_terms` can empty a question completely, and an empty Lucene
        query is a syntax error rather than an empty result."""
        result = CanonRetriever().retrieve("What is it?")
        assert result.passages == ()
        assert "says nothing to search for" in result.miss_reason

    def test_the_budget_reports_what_it_cut(self, written):
        """A silent truncation reads as 'covered everything' when it did not."""
        result = CanonRetriever(limit=1).retrieve(f"Tell me about {named('Donavich')}.")
        assert len(result.passages) == 1
        assert result.dropped == 1

    def test_a_case_folded_question_anchors_and_says_it_was_loose(self, written):
        result = CanonRetriever().retrieve(f"who is {named('Donavich').lower()}?")
        assert result.anchors
        assert result.loose is True

    def test_a_question_spelled_properly_never_needs_the_fallback(self, written):
        result = CanonRetriever().retrieve(f"Who is {named('Donavich')}?")
        assert result.loose is False

    def test_by_default_a_passage_carries_its_whole_section(self, written):
        """Section 1 names the priest, then the undercroft, then him again.

        A sentence-width passage anchored on his first mention stops before the
        undercroft. On the real book the same shape put the answer to "who owns
        the Blood of the Vine Tavern" 3,331 characters outside the window.
        """
        result = CanonRetriever().retrieve(f"Tell me about {named('Donavich')}.")
        first = result.passages[0]
        # `waits` is in the section's SECOND sentence, past any window anchored
        # on the first mention -- which is what makes this discriminating.
        assert "waits" in first.text
        assert first.truncated is False

    def test_sentence_width_narrows_to_one_sentence(self, written):
        result = CanonRetriever(passage_width="sentence").retrieve(
            f"Tell me about {named('Donavich')}."
        )
        assert "waits" not in result.passages[0].text

    def test_a_heading_anchored_mention_no_longer_returns_only_the_heading(
        self, graph
    ):
        """20 of 153 live mentions did exactly that -- every keyed room and
        building, because a keyed section names its own place in its title."""
        from backend.canon.passage import derive_passage

        text = "### E2. The Tavern\n\nA fire burns low in the hearth."
        assert derive_passage(text, 8) == "A fire burns low in the hearth."

    def test_a_passage_is_derived_prose_not_an_id(self, written):
        result = CanonRetriever().retrieve(f"Who is {named('Donavich')}?")
        assert named("Donavich") in result.passages[0].text
