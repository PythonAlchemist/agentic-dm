"""Campaign retrieval: the ride-along, the labels, and the wall around canon.

CONTAMINATION TEST 2 lives here, and it is the one that protects every number
this project reports. The 96-question retrieval suite and the 10-question
answer suite both construct retrievers without a campaign; if a chained
homebrew section could reach one, the suites would stop measuring the book and
the number would not change enough for anyone to notice.
"""

import pytest

from backend.agents import canon_context
from backend.campaign import homebrew, store
from backend.campaign.chain import seed_plan
from backend.campaign.model import CAMPAIGN_PLANE, Campaign
from backend.canon.retrieval import CanonRetriever
from backend.core.database import neo4j_session

SLUG = "pytest-overlay"
BOOK = "pytest-overlay-book"
CHAPTER = "pytest-overlay-chapter"
SECTIONS = [f"{BOOK}:ch#{i}" for i in range(4)]
#: The anchor carries a distinctive word so a canon question can find it.
ANCHOR = SECTIONS[1]
ANCHOR_TEXT = "The barge crosses the freezing Vrakanth strait for eight days."
#: The scene shares NO vocabulary with the question. That is the point: its
#: relevance is positional, and nothing lexical could ever retrieve it.
SCENE_TEXT = "Corsairs swarm the deck at dawn, cutlasses drawn."


def _clean(session):
    session.run("MATCH (c:Campaign {slug:$s}) DETACH DELETE c", {"s": SLUG})
    session.run("MATCH (b:Book {slug:$b}) DETACH DELETE b", {"b": BOOK})
    session.run("MATCH (c:Chapter {slug:$c}) DETACH DELETE c", {"c": CHAPTER})
    for prefix in (f"{BOOK}:", f"hb:{SLUG}:"):
        session.run("MATCH (n) WHERE n.id STARTS WITH $p DETACH DELETE n", {"p": prefix})
    session.run("MATCH (m:Mention {campaign:$s}) DETACH DELETE m", {"s": SLUG})
    session.run(
        "MATCH (a:Alias {plane:$p}) WHERE NOT (a)-[:ALIAS_OF]->() DETACH DELETE a",
        {"p": CAMPAIGN_PLANE},
    )


@pytest.fixture
def overlaid(tmp_path):
    """A tiny book, a campaign over it, and one scene chained after ANCHOR."""
    with neo4j_session() as session:
        _clean(session)
        session.run("CREATE (:Book {slug:$b, plane:'canon', display_name:'Overlay Book'})",
                    {"b": BOOK})
        session.run("CREATE (:Chapter {slug:$c, plane:'canon', index:0, title:'Ch'})",
                    {"c": CHAPTER})
        session.run(
            "MATCH (b:Book {slug:$b}), (c:Chapter {slug:$c}) MERGE (b)-[:HAS_CHAPTER]->(c)",
            {"b": BOOK, "c": CHAPTER},
        )
        for index, section_id in enumerate(SECTIONS):
            session.run(
                """
                CREATE (s:Section {id:$id, index:$i, plane:'canon', heading:$h, text:$t})
                WITH s MATCH (c:Chapter {slug:$c}) MERGE (c)-[:HAS_SECTION]->(s)
                """,
                {
                    "id": section_id,
                    "i": index,
                    "h": f"Section {index}",
                    "t": ANCHOR_TEXT if section_id == ANCHOR else "Unrelated prose here.",
                    "c": CHAPTER,
                },
            )
        session.execute_write(
            lambda tx: store.create(tx, Campaign(slug=SLUG, name="Overlay", books=(BOOK,)))
        )
        session.execute_write(
            lambda tx: store.apply_rewire(
                tx, SLUG, seed_plan(SECTIONS), frozenset(SECTIONS),
                log_path=tmp_path / "log.jsonl",
            )
        )
        session.execute_write(
            lambda tx: homebrew.write(
                tx,
                slug=SLUG,
                kind="scene",
                title="Corsair Boarding",
                body=SCENE_TEXT,
                generated_body=SCENE_TEXT,
                from_canon=[{"claim": "the crossing takes days", "cite": "[1]"}],
                invented=["the corsairs"],
                from_context=[],
                sources=[{"source": ANCHOR, "citation": "[1]"}],
                anchor=ANCHOR,
                log_path=tmp_path / "log.jsonl",
            )
        )
        yield session
        _clean(session)


QUESTION = "what happens during the Vrakanth crossing"


def _passages(campaign):
    return CanonRetriever(book=BOOK, limit=6, campaign=campaign).retrieve(QUESTION).passages


class TestTheRideAlong:
    def test_a_scene_arrives_beside_its_anchor(self, overlaid):
        """It shares no words with the question. Only the chain knows it."""
        found = _passages(SLUG)
        rider = next((p for p in found if p.origin == "campaign"), None)
        assert rider is not None, "the chained scene did not ride along"
        assert rider.rode_with == ANCHOR

    def test_nothing_lexical_could_have_found_it(self, overlaid):
        """Proves the previous test is about position, not about words.

        Compared on CONTENT words: the two strings share "the", and a test that
        counted stopwords as overlap would be asserting about English rather
        than about this retrieval.
        """
        from backend.canon.questions import content_terms

        assert not set(content_terms(SCENE_TEXT)) & set(content_terms(QUESTION))

    def test_canon_passages_are_labelled_canon(self, overlaid):
        found = _passages(SLUG)
        assert any(p.origin == "canon" for p in found)
        assert all(p.origin == "canon" for p in found if not p.section_id.startswith("hb:"))

    def test_every_passage_carries_its_chain_status(self, overlaid):
        for passage in _passages(SLUG):
            assert passage.chain_status in {"in-chain", "skipped"}


class TestTheCitationsSayWhose:
    def test_the_type_is_read_off_the_passage(self, overlaid):
        """It was the constant "canon" on every citation, which stopped being
        true the moment a DM's own material could be cited beside the book."""
        result = CanonRetriever(book=BOOK, limit=6, campaign=SLUG).retrieve(QUESTION)
        kinds = {s["type"] for s in canon_context.sources(result)}
        assert kinds == {"canon", "campaign"}

    def test_a_rider_says_what_it_rode_with(self, overlaid):
        result = CanonRetriever(book=BOOK, limit=6, campaign=SLUG).retrieve(QUESTION)
        rider = next(s for s in canon_context.sources(result) if s["type"] == "campaign")
        assert rider["rode_with"] == ANCHOR


class TestContaminationTwo:
    """A chained scene beside a gold section must be invisible without a campaign.

    THE WALL IS TWO QUERIES AND THEY GATE EACH OTHER, which mutation testing
    showed: breaching `ALL_ALIASES` alone leaks nothing, because a name that is
    never found in the question is never looked up; breaching `BY_ALIAS` alone
    leaks nothing, because nothing asks it about a name it was never offered.
    Only breaching BOTH lets a campaign entity resolve in a campaign-less
    session, and that is what fails the test below. Recorded because a reader
    finding one of the two clauses might otherwise think it was doing the work
    on its own, and remove the other.
    """

    def test_a_campaign_less_retriever_never_sees_it(self, overlaid):
        found = _passages(None)
        assert not any(p.origin == "campaign" for p in found)
        assert not any(p.section_id.startswith("hb:") for p in found)

    def test_the_canon_result_is_byte_identical_either_way(self, overlaid):
        """The stronger assertion: not merely that homebrew is absent, but that
        selecting a campaign changes NOTHING about the canon half."""
        without = [p.section_id for p in _passages(None)]
        with_campaign = [
            p.section_id for p in _passages(SLUG) if not p.section_id.startswith("hb:")
        ]
        assert with_campaign == without

    def test_the_scenes_name_does_not_resolve_without_a_campaign(self, overlaid):
        """Alias resolution is the front door; the wall has to hold there too."""
        result = CanonRetriever(book=BOOK, limit=6).retrieve("tell me about Corsair Boarding")
        assert not any(a.entity_id.startswith("hb:") for a in result.anchors)

    def test_and_does_resolve_with_one(self, overlaid):
        """The other half: scoping must SCOPE, not merely exclude everything."""
        result = CanonRetriever(book=BOOK, limit=6, campaign=SLUG).retrieve(
            "tell me about Corsair Boarding"
        )
        assert any(a.entity_id.startswith("hb:") for a in result.anchors)


class TestTheEvalHarnessesAreCampaignLess:
    """Contamination is impossible BY CONSTRUCTION, and this pins it.

    A future refactor that gave either harness a campaign would silently
    change every number the project reports.
    """

    def test_neither_harness_constructs_a_campaign_retriever(self):
        from pathlib import Path

        for name in ("eval_retrieval.py", "eval_answers.py"):
            source = Path("backend/scripts") / name
            text = source.read_text()
            assert "campaign=" not in text, f"{name} constructs a campaign retriever"

    def test_the_default_is_no_campaign(self):
        assert CanonRetriever(book="cos").campaign is None
