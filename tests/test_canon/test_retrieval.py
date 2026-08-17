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
from backend.canon.retrieval import CanonRetriever, find_names
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
            {"id": "q1", "anchored": True, "hit": True, "rr": 1.0},
            {"id": "q2", "anchored": True, "hit": False, "rr": 0.0},
            {"id": "q3", "anchored": False, "hit": False, "rr": 0.0},
            {"id": "q4", "anchored": False, "hit": False, "rr": 0.0},
        ]
        s = summarize(rows)
        assert s["recall_overall"] == pytest.approx(0.25)
        assert s["recall_anchored"] == pytest.approx(0.5)
        assert s["no_anchor"] == ["q3", "q4"]
        assert s["anchored_but_missed"] == ["q2"]

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
        _section(0, "The Church", f"{named('Donavich')} prays here."),
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

    def test_a_recorded_alias_resolves_to_the_same_entity(self, written):
        result = CanonRetriever().retrieve(f"Who is {named('Father Donavich')}?")
        assert [a.entity_id for a in result.anchors] == [f"{PREFIX}donavich"]

    def test_a_question_naming_nothing_says_so_rather_than_returning_junk(self, written):
        result = CanonRetriever().retrieve("What is the capital of France?")
        assert result.anchors == ()
        assert result.passages == ()
        assert "nothing to anchor on" in result.miss_reason

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

    def test_a_passage_is_derived_prose_not_an_id(self, written):
        result = CanonRetriever().retrieve(f"Who is {named('Donavich')}?")
        assert named("Donavich") in result.passages[0].text
