"""Question in, grounded canon out.

The pure half -- finding names in a question, and the scoring the harness does
with what comes back -- needs no database and is tested here directly. The
graph half is marked `neo4j` and writes its own small chapter, following the
same `pytest:` id and `Zz` name conventions as `test_write_canon_neo4j`: the
mention scan matches on NAME across the whole canon plane, so an unprefixed test
entity would be found by the real book sitting in the same local database.
"""

import pytest

from backend.canon import lookup
from backend.canon.aliases import WriteAlias
from backend.canon.lookup import CANON_PLANE
from backend.canon.models import Section
from backend.canon.retrieval import (
    PATH_GRAPH,
    PATH_TEXT,
    CanonRetriever,
    Passage,
    anchorable_forms,
    combine_passages,
    dedupe_edges,
    find_names,
    is_common_noun,
)
from backend.canon.spine import ChapterSpine, WriteSection
from backend.canon.writer import (
    STRUCTURAL_EVIDENCE,
    WriteEdge,
    WriteNode,
    ensure_schema,
    write_chapter,
)
from backend.graph.schema import RelationshipType
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


def _p(section_id: str, path: str = PATH_GRAPH) -> Passage:
    """A passage with nothing on it but its identity and its provenance, which
    is all the combining rule is allowed to look at."""
    return Passage(section_id, "ch", 0, "S", 0, "text", 0, (), path=path)


def _graph(*ids: str) -> list[Passage]:
    return [_p(i) for i in ids]


def _text(*ids: str) -> list[Passage]:
    return [_p(i, PATH_TEXT) for i in ids]


class TestRefusingCommonNouns:
    """The extractor minted `cos:coffin`, `cos:wagon`, `cos:vampire` and forty-
    odd more generic props as global entities, each with an alias spelled the
    way the book writes it. They anchored real questions: `coffin` sent "who is
    lying in the coffin in the burgomaster's mansion" to Castle Ravenloft's
    tombs."""

    def test_a_single_lowercase_word_is_a_thing_word(self):
        assert is_common_noun("coffin")
        assert is_common_noun("vampire")

    def test_a_capital_makes_it_a_name(self):
        assert not is_common_noun("Strahd")
        assert not is_common_noun("Rahadin")

    def test_a_multi_word_lowercase_form_is_not_refused(self):
        """53 of the plane's 103 all-lowercase forms are multi-word, and nearly
        every one is a spell or magic item that D&D writes lower case by
        convention. Refusing them would break anchoring on half the treasure."""
        assert not is_common_noun("dispel magic")
        assert not is_common_noun("potion of healing")
        assert not is_common_noun("staff of power")

    def test_whitespace_is_not_a_thing_word(self):
        assert not is_common_noun("")
        assert not is_common_noun("   ")

    def test_an_entity_with_a_lowercase_alias_loses_every_spelling(self):
        """THE BUG THE FIRST ATTEMPT SHIPPED. Dropping only the lower-case form
        moved the defect instead of fixing it: with `wagon` gone nothing else
        matched, `find_names` reached its case-folded second pass, and `Wagon`
        matched the same word. The anchor came back under a different spelling,
        so the refusal has to disqualify the ENTITY."""
        rows = [
            {"name": "wagon", "entity_id": "cos:wagon"},
            {"name": "Wagon", "entity_id": "cos:wagon"},
        ]
        assert anchorable_forms(rows) == []

    def test_an_entity_of_names_keeps_all_of_them(self):
        rows = [
            {"name": "Strahd", "entity_id": "cos:strahd"},
            {"name": "Strahd von Zarovich", "entity_id": "cos:strahd"},
        ]
        assert anchorable_forms(rows) == ["Strahd", "Strahd von Zarovich"]

    def test_one_entitys_refusal_does_not_touch_another(self):
        rows = [
            {"name": "coffin", "entity_id": "cos:coffin"},
            {"name": "Coffin", "entity_id": "cos:coffin"},
            {"name": "Rahadin", "entity_id": "cos:rahadin"},
        ]
        assert anchorable_forms(rows) == ["Rahadin"]

    def test_a_form_shared_by_two_entities_survives_through_the_clean_one(self):
        """`Barovia` names a region and a village. If either were disqualified,
        dropping the shared spelling outright would silently unname the other."""
        rows = [
            {"name": "Barovia", "entity_id": "cos:barovia"},
            {"name": "Barovia", "entity_id": "cos:village-of-barovia"},
            {"name": "barovia", "entity_id": "cos:barovia"},
        ]
        assert anchorable_forms(rows) == ["Barovia"]

    def test_nothing_in_gives_nothing_out(self):
        assert anchorable_forms([]) == []


class TestCombiningTheTwoPaths:
    """One budget, split between a resolved name and a Lucene score.

    The rule replaced an all-or-nothing fallback: text used to run only when
    NOTHING anchored, so a question anchoring on the WRONG thing had no way
    back. Seven of the nine anchored misses hit on the text path.
    """

    def test_the_graph_keeps_every_slot_the_reservation_does_not_take(self):
        got = combine_passages(_graph("g1", "g2", "g3", "g4", "g5"), _text("t1"), 5)
        assert [p.section_id for p in got] == ["g1", "g2", "g3", "g4", "t1"]

    def test_a_short_graph_result_is_padded_out_of_text(self):
        """The effect that displaces nothing: the graph found two candidates and
        the other three slots would otherwise have gone unused."""
        got = combine_passages(_graph("g1", "g2"), _text("t1", "t2", "t3", "t4"), 5)
        assert [p.section_id for p in got] == ["g1", "g2", "t1", "t2", "t3"]

    def test_padding_cannot_evict_a_graph_passage(self):
        """Stated as a property over every split, because the claim that padding
        is free is what justifies doing it at all."""
        graph = _graph("g1", "g2", "g3", "g4", "g5", "g6")
        for reserve in range(6):
            got = combine_passages(graph, _text("t1", "t2"), 5, reserve=reserve)
            kept = [p.section_id for p in got if p.path == PATH_GRAPH]
            assert kept == [p.section_id for p in graph][: len(kept)]

    def test_reserve_zero_is_padding_alone(self):
        got = combine_passages(_graph("g1", "g2", "g3", "g4", "g5"), _text("t1"), 5,
                               reserve=0)
        assert [p.section_id for p in got] == ["g1", "g2", "g3", "g4", "g5"]

    def test_text_never_exceeds_its_reservation_while_the_graph_has_more(self):
        got = combine_passages(_graph("g1", "g2", "g3", "g4", "g5"),
                               _text("t1", "t2", "t3"), 5)
        assert sum(1 for p in got if p.path == PATH_TEXT) == 1

    def test_the_graph_reclaims_slack_text_did_not_use(self):
        """A reservation is a ceiling on text, not a floor. With nothing to
        search, the graph gets the whole budget back rather than returning four."""
        got = combine_passages(_graph("g1", "g2", "g3", "g4", "g5", "g6"), [], 5)
        assert [p.section_id for p in got] == ["g1", "g2", "g3", "g4", "g5"]

    def test_a_section_both_paths_found_appears_once(self):
        got = combine_passages(_graph("g1", "shared"), _text("shared", "t2"), 5)
        assert [p.section_id for p in got] == ["g1", "shared", "t2"]

    def test_the_shared_section_keeps_the_graphs_copy(self):
        """Whichever came first wins, and inside the kept prefix that is the
        graph's -- the copy carrying the occurrence count and the entity ids."""
        got = combine_passages(_graph("shared"), _text("shared"), 5)
        assert [p.path for p in got] == [PATH_GRAPH]

    def test_a_budget_of_one_still_goes_to_the_resolved_name(self):
        """`limit - reserve` was 0 here, so the one slot went to a Lucene guess
        and both real candidates were reported dropped. A guess may fill what a
        name left empty; it may not evict the name."""
        got = combine_passages(_graph("g1", "g2"), _text("t1"), 1)
        assert [p.section_id for p in got] == ["g1"]

    def test_a_budget_of_one_with_no_graph_result_still_reaches_text(self):
        assert [p.section_id for p in combine_passages([], _text("t1"), 1)] == ["t1"]

    def test_the_budget_is_never_exceeded(self):
        got = combine_passages(_graph("g1", "g2", "g3"), _text("t1", "t2", "t3"), 4)
        assert len(got) == 4

    def test_nothing_from_either_path_is_nothing(self):
        assert combine_passages([], [], 5) == []

    def test_scores_are_never_blended(self):
        """The rule may only reorder and cut. If it ever computed a combined
        score, a passage would come back changed -- these are the same objects."""
        graph, text = _graph("g1", "g2"), _text("t1")
        got = combine_passages(graph, text, 5)
        assert all(p is graph[0] or p is graph[1] or p is text[0] for p in got)


def _row(qid: str, *, anchored: bool, hit: bool, rr: float, path: str,
         hit_path: str = "", needs: str = "") -> dict:
    """One scored question, as `score` would emit it.

    `hit_path` defaults to empty -- no path answered -- so a row declared as a
    miss cannot silently credit anything, and a row declared as a hit has to say
    which path earned it.
    """
    return {"id": qid, "anchored": anchored, "hit": hit, "rr": rr,
            "path": path, "hit_path": hit_path, "needs": needs}


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
            _row("q1", anchored=True, hit=True, rr=1.0, path="graph", hit_path="graph"),
            _row("q2", anchored=True, hit=False, rr=0.0, path="graph"),
            _row("q3", anchored=False, hit=False, rr=0.0, path="-"),
            _row("q4", anchored=False, hit=False, rr=0.0, path="-"),
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
            _row("q1", anchored=True, hit=True, rr=1.0, path="graph", hit_path="graph"),
            _row("q2", anchored=False, hit=True, rr=1.0, path="text", hit_path="text"),
            _row("q3", anchored=False, hit=True, rr=1.0, path="text", hit_path="text"),
        ]
        s = summarize(rows)
        assert s["recall_anchored"] == pytest.approx(1.0)
        assert s["recall_overall"] == pytest.approx(1.0)

    def test_the_two_paths_are_reported_apart(self):
        """A graph hit resolved a name the book wrote; a text hit is a Lucene
        score agreeing with a guess. Merged, the fallback would read as an
        improvement to the graph."""
        rows = [
            _row("q1", anchored=True, hit=True, rr=1.0, path="graph", hit_path="graph"),
            _row("q2", anchored=True, hit=False, rr=0.0, path="graph"),
            _row("q3", anchored=False, hit=True, rr=1.0, path="text", hit_path="text"),
        ]
        by_path = summarize(rows)["by_path"]
        assert by_path["graph"] == {"n": 2, "hits": 1}
        assert by_path["text"] == {"n": 1, "hits": 1}

    def test_a_text_passage_inside_a_graph_result_credits_text(self):
        """The reservation broke the old reporting. A question that anchored on
        a name can now be answered by a passage Lucene found, and grouping the
        hit by how the QUESTION resolved credited the graph for it -- the run
        that motivated this said "by name 26/31" when four of those were text."""
        rows = [
            _row("q1", anchored=True, hit=True, rr=1.0, path="graph", hit_path="text"),
            _row("q2", anchored=True, hit=True, rr=1.0, path="graph", hit_path="graph"),
        ]
        s = summarize(rows)
        assert s["by_path"]["graph"] == {"n": 2, "hits": 2}
        assert s["by_answer"] == {"graph": 1, "text": 1}

    def test_the_credit_follows_the_passage_that_holds_the_gold(self):
        from backend.canon.retrieval import Retrieval

        result = Retrieval(
            question="q",
            anchors=(),
            passages=(_p("cos:x#1"), _p("cos:x#9", PATH_TEXT)),
        )
        row = score({"id": "q1", "question": "q", "sections": ["cos:x#9"]}, result)
        assert row["hit_path"] == PATH_TEXT

    def test_a_miss_credits_no_path_at_all(self):
        from backend.canon.retrieval import Retrieval

        result = Retrieval(question="q", passages=(_p("cos:x#1"),))
        row = score({"id": "q1", "question": "q", "sections": ["cos:x#9"]}, result)
        assert row["hit_path"] == ""

    def test_an_unlabelled_question_is_in_no_needs_bucket(self):
        """Set one predates `needs` and is deliberately not backfilled: a label
        assigned to a question whose result you have already seen produces a
        prediction that cannot be wrong."""
        rows = [_row("q1", anchored=True, hit=True, rr=1.0, path="graph",
                     hit_path="graph")]
        assert summarize(rows)["by_needs"] == {}

    def test_a_prediction_is_counted_against_what_happened(self):
        """`needs: graph` claims a resolved name will answer. A `graph` question
        that Lucene answered is the disagreement worth seeing, and it has to
        survive into the summary rather than being folded into one recall."""
        rows = [
            _row("q1", anchored=True, hit=True, rr=1.0, path="graph",
                 hit_path="graph", needs="graph"),
            _row("q2", anchored=True, hit=True, rr=1.0, path="graph",
                 hit_path="text", needs="graph"),
            _row("q3", anchored=False, hit=False, rr=0.0, path="text",
                 needs="graph"),
        ]
        stat = summarize(rows)["by_needs"]["graph"]
        assert stat == {"n": 3, "hits": 2, "answered_by_graph": 1,
                        "answered_by_text": 1, "anchored": 2}

    def test_a_text_question_that_anchored_is_visible(self):
        """The other direction: `needs: text` claims the question names nothing
        the graph holds. Six did anyway -- on `wagon`, `Gatehouse` and
        `vampire` -- and that is a defect in the graph, not in the label."""
        rows = [
            _row("q1", anchored=True, hit=True, rr=1.0, path="graph",
                 hit_path="graph", needs="text"),
        ]
        assert summarize(rows)["by_needs"]["text"]["anchored"] == 1

    def test_the_buckets_do_not_bleed_into_each_other(self):
        rows = [
            _row("q1", anchored=True, hit=True, rr=1.0, path="graph",
                 hit_path="graph", needs="graph"),
            _row("q2", anchored=False, hit=True, rr=1.0, path="text",
                 hit_path="text", needs="text"),
        ]
        by_needs = summarize(rows)["by_needs"]
        assert by_needs["graph"]["n"] == 1
        assert by_needs["text"]["n"] == 1
        assert "either" not in by_needs

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
BOOK = "pytest"  # must match the id prefix its entities carry
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
        # `Zzelsewhere` is a word NO entity is named by, so this section can
        # never be a graph candidate -- and it is marker-prefixed so the real
        # book sitting in the same database cannot outrank it on the text path.
        # That makes it the one section that proves the text reservation is
        # reaching sections the graph alone could not.
        # `capital` is here for the text path's contract test: that path CANNOT
        # say it does not know, so an unrelated question must still come back
        # with something. It used to come back with a real Curse of Strahd
        # section, which meant the test passed only while retrieval searched
        # every book -- the leak this fixture now has to live without.
        _section(2, "Elsewhere",
                 "Nothing Zzelsewhere happens here at all, in this capital or any other."),
    ]
    # The fixture wrote no edges at all, and the test asserting that a
    # text-retrieved section still brings its entities' relationships was
    # passing on edges belonging to the real book. One accepted edge between
    # the fixture's own two entities makes that test true of the fixture.
    edges = [
        WriteEdge(
            source_id=f"{PREFIX}donavich",
            target_id=f"{PREFIX}undercroft",
            rel_type=RelationshipType.LOCATED_IN,
            chapter_slug=CHAPTER,
            # `accepted` is DERIVED from this, never passed -- see
            # `WriteEdge.status`. Structural evidence is what the book's
            # own hierarchy produces, and is the only thing that earns it.
            evidence=STRUCTURAL_EVIDENCE,
        )
    ]
    write_chapter(
        graph,
        CHAPTER,
        [priest, room],
        edges,
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
                # The fixture's OWN book, not Barovia's. These sections
                # hang off a `:Book {slug: BOOK}` and their ids must agree
                # with it, the way real data does -- retrieval scopes to a
                # book and a section claiming a book it does not belong to
                # is invisible to it.
                id=f"{BOOK}:{CHAPTER}#{s.index}",
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
        result = CanonRetriever(book="pytest").retrieve(f"Who is {named('Donavich')}?")
        assert [a.name for a in result.anchors] == [named("Donavich")]
        assert f"{BOOK}:{CHAPTER}#0" in result.section_ids
        assert f"{BOOK}:{CHAPTER}#2" not in result.section_ids

    def test_an_anchored_question_still_reaches_a_section_the_graph_cannot(self, written):
        """The whole change, end to end.

        Section 2 mentions no entity, so no anchor can ever reach it. Before
        this, a question that resolved a name never ran the text search at all,
        and the section was unreachable for anyone who happened to name the
        priest in the same breath.

        Satisfied here by PADDING rather than by the reservation -- the graph
        offers two candidates against a budget of five -- and it stays green at
        `TEXT_SLOTS = 0`. That is deliberate: this pins the union existing at
        all, and `TestCombiningTheTwoPaths` pins the split. A test asserting
        both would fail for two unrelated reasons.
        """
        result = CanonRetriever(book="pytest").retrieve(
            f"What does {named('Donavich')} think of Zzelsewhere?"
        )
        assert result.anchors, "the question must anchor for this to mean anything"
        assert f"{BOOK}:{CHAPTER}#2" in result.section_ids

    def test_the_passage_from_the_text_path_says_so(self, written):
        """Provenance is per passage now, because one result mixes both."""
        result = CanonRetriever(book="pytest").retrieve(
            f"What does {named('Donavich')} think of Zzelsewhere?"
        )
        found = next(p for p in result.passages if p.section_id == f"{BOOK}:{CHAPTER}#2")
        assert found.path == PATH_TEXT
        assert found.score is not None

    def test_the_graph_passages_in_a_mixed_result_are_still_labelled_graph(self, written):
        result = CanonRetriever(book="pytest").retrieve(
            f"What does {named('Donavich')} think of Zzelsewhere?"
        )
        found = next(p for p in result.passages if p.section_id == f"{BOOK}:{CHAPTER}#1")
        assert found.path == PATH_GRAPH
        assert found.score is None

    def test_the_section_id_matches_the_one_the_write_path_minted(self, written):
        """`_section_id` rebuilds the id from parts rather than reading it, so
        the format has to be pinned against real sections in the graph."""
        rebuilt = set(CanonRetriever(book="pytest").retrieve(f"Who is {named('Donavich')}?").section_ids)
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
        result = CanonRetriever(book="pytest").retrieve(f"Tell me about {named('Donavich')}.")
        assert result.section_ids[0] == f"{BOOK}:{CHAPTER}#1"

    def test_a_questions_own_words_can_beat_a_louder_section(self, written):
        """The defect this ranking exists to fix.

        Section 1 names the priest twice and section 0 once, so occurrences
        alone put section 1 first -- and the previous test asserts exactly that.
        Ask about something section 0 actually discusses and it must win, even
        though the anchor is quieter there. On the real set this is what moved
        "who are Strahd's undead enemies" from ninth to second.
        """
        result = CanonRetriever(book="pytest").retrieve(
            f"What vestments does {named('Donavich')} wear?"
        )
        assert result.section_ids[0] == f"{BOOK}:{CHAPTER}#0"
        assert result.passages[0].term_hits >= 1

    def test_the_anchors_own_name_is_not_also_scored_as_a_term(self, written):
        """Counting it twice -- once as occurrences, once as a matched word --
        would re-favour the broad sections the term signal is meant to demote."""
        result = CanonRetriever(book="pytest").retrieve(f"Where is {named('Donavich')}?")
        assert result.passages
        assert all(p.term_hits == 0 for p in result.passages)

    def test_a_word_the_question_never_used_scores_nothing(self, written):
        result = CanonRetriever(book="pytest").retrieve(f"Tell me about {named('Donavich')}.")
        assert all(p.term_hits == 0 for p in result.passages)

    def test_a_recorded_alias_resolves_to_the_same_entity(self, written):
        result = CanonRetriever(book="pytest").retrieve(f"Who is {named('Father Donavich')}?")
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
        result = CanonRetriever(book="pytest").retrieve("What is the capital of France?")
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
        result = CanonRetriever(book="pytest").retrieve("who listens below")
        assert result.path == "text"
        assert result.accepted or result.proposed, (
            "a section retrieved by text must still bring its entities' edges"
        )

    def test_the_text_path_honours_the_passage_width(self, written):
        """It used to call `derive_passage` directly and always send one
        sentence, silently ignoring the setting."""
        wide = CanonRetriever(passage_width="section", book="pytest").retrieve("who listens below")
        narrow = CanonRetriever(passage_width="sentence", book="pytest").retrieve("who listens below")
        assert len(wide.passages[0].text) > len(narrow.passages[0].text)

    def test_a_graph_passage_carries_no_score(self, written):
        """`None`, not `0.0`. A name match has no score, and a zero would read
        as 'scored, badly'."""
        result = CanonRetriever(book="pytest").retrieve(f"Who is {named('Donavich')}?")
        assert result.path == "graph"
        assert all(p.score is None for p in result.passages)

    def test_a_question_whose_words_are_all_scaffolding_searches_for_nothing(
        self, written
    ):
        """`content_terms` can empty a question completely, and an empty Lucene
        query is a syntax error rather than an empty result."""
        result = CanonRetriever(book="pytest").retrieve("What is it?")
        assert result.passages == ()
        assert "says nothing to search for" in result.miss_reason

    def test_the_budget_reports_what_it_cut(self, written):
        """A silent truncation reads as 'covered everything' when it did not."""
        result = CanonRetriever(limit=1, book="pytest").retrieve(f"Tell me about {named('Donavich')}.")
        assert len(result.passages) == 1
        assert result.dropped == 1

    def test_a_case_folded_question_anchors_and_says_it_was_loose(self, written):
        result = CanonRetriever(book="pytest").retrieve(f"who is {named('Donavich').lower()}?")
        assert result.anchors
        assert result.loose is True

    def test_a_question_spelled_properly_never_needs_the_fallback(self, written):
        result = CanonRetriever(book="pytest").retrieve(f"Who is {named('Donavich')}?")
        assert result.loose is False

    def test_by_default_a_passage_carries_its_whole_section(self, written):
        """Section 1 names the priest, then the undercroft, then him again.

        A sentence-width passage anchored on his first mention stops before the
        undercroft. On the real book the same shape put the answer to "who owns
        the Blood of the Vine Tavern" 3,331 characters outside the window.
        """
        result = CanonRetriever(book="pytest").retrieve(f"Tell me about {named('Donavich')}.")
        first = result.passages[0]
        # `waits` is in the section's SECOND sentence, past any window anchored
        # on the first mention -- which is what makes this discriminating.
        assert "waits" in first.text
        assert first.truncated is False

    def test_sentence_width_narrows_to_one_sentence(self, written):
        result = CanonRetriever(passage_width="sentence", book="pytest").retrieve(
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
        result = CanonRetriever(book="pytest").retrieve(f"Who is {named('Donavich')}?")
        assert named("Donavich") in result.passages[0].text


@pytest.mark.neo4j
class TestCarryingTheConversation:
    """A question that resolves nothing can still be about something.

    "Who owns the tavern" then "give me a list of everyone in the pub": the
    second anchors nothing -- `pub` is no alias -- so it searched Lucene for
    `give, list, everyone, pub` and read `Tyger, Tyger`, `Foreshadowing`,
    `K81. Tunnel` and `Crypt 10`. The model had been TOLD the subject was the
    Blood of the Vine Tavern and duly answered that the canon does not cover
    who is in it, while holding eight sections about something else. The book's
    E2 section lists exactly who is in that room.
    """

    #: The tavern is a KEYED place, so its id is chapter-scoped. A guess at
    #: the global form resolves to nothing and the carry silently does not
    #: fire -- which is what the first version of this test asserted against.
    TAVERN = "cos:the-village-of-barovia:e2-blood-of-the-vine-tavern"

    def test_a_question_resolving_nothing_uses_what_came_before(self, written):
        result = CanonRetriever(book="cos").retrieve(
            "give me a list of everyone in the pub", carry=[self.TAVERN]
        )
        assert result.carried is True
        assert self.TAVERN in {a.entity_id for a in result.anchors}

    def test_it_reaches_the_section_the_answer_is_in(self, written):
        result = CanonRetriever(book="cos").retrieve(
            "give me a list of everyone in the pub", carry=[self.TAVERN]
        )
        assert "cos:the-village-of-barovia#5" in result.section_ids

    def test_a_question_that_names_something_is_never_overridden(self, written):
        """What was said three turns ago must not outrank what was just asked."""
        result = CanonRetriever(book="cos").retrieve(
            "Who is Madam Eva?", carry=[self.TAVERN]
        )
        assert result.carried is False
        assert self.TAVERN not in {a.entity_id for a in result.anchors}

    def test_without_a_conversation_it_still_falls_through_to_text(self, written):
        result = CanonRetriever(book="cos").retrieve("give me a list of everyone in the pub")
        assert result.carried is False
        assert result.path == PATH_TEXT

    def test_carrying_ids_that_no_longer_exist_falls_through_to_text(self, written):
        """An evicted or deleted entity must not dead-end the turn."""
        result = CanonRetriever(book="cos").retrieve(
            "give me a list of everyone in the pub", carry=["cos:nothing-here"]
        )
        assert result.carried is False
        assert result.path == PATH_TEXT

    def test_the_anchor_surface_is_the_entitys_own_name(self, written):
        """No wording in THIS question produced it, so the panel shows the name
        rather than implying the reader typed something that matched."""
        result = CanonRetriever(book="cos").retrieve("describe it", carry=[self.TAVERN])
        anchor = next(a for a in result.anchors if a.entity_id == self.TAVERN)
        assert anchor.surface == anchor.name


class TestCampaignEdgesCannotReachCanonReads:
    """A campaign edge between two CANON entities must be invisible to canon.

    THE POLLUTION VECTOR THIS EXISTS FOR. The writer stamps a plane on the
    relationship as well as on both entities, and for a long time every edge
    read filtered only the entities: `(n {plane:$plane})-[r]->(o {plane:$plane})`
    with `r` unconstrained. Harmless while every edge was canon, and wrong the
    moment a DM asserts a fact about two canon things -- "at my table, Donavich
    owns the undercroft". Both ends are canon, so a node-only filter hands that
    edge to the model under the heading promising the book said it.

    Asserted as BYTE-IDENTICAL results rather than as an absence, because the
    interesting failure is not "the campaign edge appears" but "canon reads
    changed at all".
    """

    PRIEST = f"{PREFIX}donavich"
    ROOM = f"{PREFIX}undercroft"

    def _canon(self, session, query, ids):
        return [
            dict(r)
            for r in session.run(query, {"plane": CANON_PLANE, "ids": ids})
        ]

    def _plant(self, session):
        session.run(
            """
            MATCH (a:Entity {id:$a}), (b:Entity {id:$b})
            CREATE (a)-[:OWNS {plane:'campaign', status:'authored',
                               campaign:'pytest-table'}]->(b)
            """,
            {"a": self.PRIEST, "b": self.ROOM},
        )

    def test_edges_are_unchanged(self, written):
        ids = [self.PRIEST, self.ROOM]
        before = self._canon(written, lookup.EDGES, ids)
        self._plant(written)
        assert self._canon(written, lookup.EDGES, ids) == before

    def test_placements_are_unchanged(self, written):
        ids = [self.PRIEST, self.ROOM]
        before = self._canon(written, lookup.PLACEMENTS, ids)
        self._plant(written)
        assert self._canon(written, lookup.PLACEMENTS, ids) == before

    def test_the_planted_edge_really_is_there(self, written):
        """Guards the guard: if the CREATE silently failed, the three tests
        above would pass by testing nothing at all."""
        self._plant(written)
        found = written.run(
            "MATCH (:Entity {id:$a})-[r:OWNS]->(:Entity {id:$b}) RETURN r.plane AS plane",
            {"a": self.PRIEST, "b": self.ROOM},
        ).single()
        assert found is not None and dict(found)["plane"] == "campaign"

    def test_a_cross_plane_edge_is_readable_from_NEITHER_plane(self, written):
        """PINS A KNOWN GAP, and is here so the gap cannot be forgotten.

        `EDGES` filters the plane of both entities AND of the relationship. An
        edge asserted by a campaign between two CANON entities therefore
        matches on neither plane: canon rejects it on `r.plane`, campaign
        rejects it on the entities. Pollution is prevented and the edge is also
        unreachable.

        That is the RIGHT trade for canon -- an unreadable campaign edge is a
        missing feature, a leaking one is a lie -- but it means "at my table,
        Donavich owns the undercroft" cannot currently be read back, and any
        design that promises that case needs its own query with the entity
        filter relaxed. Change this test when that query exists; do not relax
        `EDGES` itself."""
        self._plant(written)
        for plane in (CANON_PLANE, "campaign"):
            rows = [
                dict(r)
                for r in written.run(
                    lookup.EDGES, {"plane": plane, "ids": [self.PRIEST, self.ROOM]}
                )
            ]
            assert not any(r["relationship"] == "OWNS" for r in rows), plane
