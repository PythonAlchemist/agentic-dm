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
from backend.campaign.model import is_campaign_id
from backend.canon.retrieval import PATH_FOCUS, CanonRetriever
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

#: The scene the fixture chains after ANCHOR, as a focus target.
SCENE_SECTION = f"hb:{SLUG}:corsair-boarding#0"


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


class TestANamedCampaignEntityBringsItsOwnProse:
    """Resolving a name and returning nothing about it is the worse half of a miss.

    THE GAP THIS CLOSED, which the ride-along hid. `MENTIONS` filters
    `Entity {plane:'canon'}` AND requires a `:Chapter` to hang the section
    from, while a campaign section hangs off a `:Campaign`. So a campaign
    entity resolved by name and then returned no passage: ask "tell me about
    Captain Saltmarrow", watch the name resolve, get nothing back about him.
    It went unnoticed because a scene chained beside a retrieved canon section
    still arrived -- by POSITION, never by name.
    """

    def test_the_scene_comes_back_when_named(self, overlaid):
        result = CanonRetriever(book=BOOK, limit=6, campaign=SLUG).retrieve(
            "tell me about Corsair Boarding"
        )
        campaign = [p for p in result.passages if p.origin == "campaign"]
        assert campaign, "the entity resolved but brought no prose"
        assert SCENE_TEXT[:20] in campaign[0].text

    def test_it_is_not_a_ride_along(self, overlaid):
        """Distinguished from the positional path: this passage rode with
        nothing, because the question named it outright."""
        result = CanonRetriever(book=BOOK, limit=6, campaign=SLUG).retrieve(
            "tell me about Corsair Boarding"
        )
        named = [p for p in result.passages if p.origin == "campaign" and not p.rode_with]
        assert named

    def test_it_comes_back_first(self, overlaid):
        """Ordering between the lists is a separate question from ordering
        inside them, and nothing here is blended. A DM who asks about a thing
        they made should not read eight keyword hits from the book before their
        own write-up of it -- which is where it was landing."""
        result = CanonRetriever(book=BOOK, limit=6, campaign=SLUG).retrieve(
            "tell me about Corsair Boarding"
        )
        assert result.passages[0].origin == "campaign"

    def test_a_canon_question_still_opens_with_the_book(self, overlaid):
        """Only when a CAMPAIGN entity was named. A scene of yours mentioning
        Strahd is not a better answer about Strahd than the chapter he is in,
        so the rule is narrow on purpose."""
        result = CanonRetriever(book=BOOK, limit=6, campaign=SLUG).retrieve(
            QUESTION
        )
        assert result.passages[0].origin == "canon"

    def test_a_campaign_less_session_still_sees_nothing(self, overlaid):
        """The wall holds: naming it without a campaign selected returns
        neither the anchor nor the prose."""
        result = CanonRetriever(book=BOOK, limit=6).retrieve(
            "tell me about Corsair Boarding"
        )
        assert not any(p.origin == "campaign" for p in result.passages)


class TestAStubDoesNotReadAsAbsent:
    """A thing the DM made is not a passage, and must not look like a gap.

    THE DEFECT. A cluster element gets a node, a name and a role, but the prose
    stored beside it is the SCENE's -- "Corsairs swarm the deck at dawn" never
    says Captain Saltmarrow. So the passage arrived, carried no mention of him,
    and a fresh session answered "the canon does not cover any specific details
    about Captain Saltmarrow" about a character the DM had invented an hour
    earlier. The node knew his kind, his role, what was invented and which
    scene minted him. None of it reached the model.
    """

    def test_the_record_travels_with_the_retrieval(self, overlaid):
        result = CanonRetriever(book=BOOK, limit=6, campaign=SLUG).retrieve(
            "tell me about Corsair Boarding"
        )
        assert result.campaign_entities
        assert result.campaign_entities[0]["name"] == "Corsair Boarding"

    def test_the_model_is_told_it_is_the_dms_own(self, overlaid):
        result = CanonRetriever(book=BOOK, limit=6, campaign=SLUG).retrieve(
            "tell me about Corsair Boarding"
        )
        block = canon_context.render(result)
        assert "YOUR CAMPAIGN" in block
        assert "never as canon" in block

    def test_a_stub_says_so_rather_than_saying_nothing(self):
        """"You made this and have not fleshed it out" and "the book does not
        mention this" are different answers, and only one of them is true."""
        from backend.agents.canon_context import _your_material

        block = _your_material(
            ({"name": "Captain Soldreth", "kind": "npc", "role": "the corsair captain",
              "described_in": []},)
        )
        assert "Nothing has been written about it yet" in block
        assert "the corsair captain" in block

    def test_something_with_prose_names_where_it_appears(self):
        from backend.agents.canon_context import _your_material

        block = _your_material(
            ({"name": "The Red Barge", "kind": "location", "role": "",
              "described_in": ["The Corsair Boarding"]},)
        )
        assert "Appears in: The Corsair Boarding" in block

    def test_a_campaign_less_session_gets_no_record(self, overlaid):
        """The wall again: a canon-only session must not learn the DM made
        anything at all."""
        result = CanonRetriever(book=BOOK, limit=6).retrieve(
            "tell me about Corsair Boarding"
        )
        assert result.campaign_entities == ()


class TestLinkingACanonEntityIntoAScene:
    """"Use the book's" has to mean something.

    THE HOLE THIS CLOSES. Choosing `link` correctly declined to mint a second
    Marta Marthannis -- and then recorded nothing at all. Zero connections
    existed from campaign material to canon entities, so a DM who had told the
    system their scene involves the book's NPC got nothing back when they asked
    about her. The decision was real and its consequence was not.
    """

    LINKED = f"{BOOK}:ch#3"
    #: A NAME NO BOOK USES. `Alias.name` is globally unique, so a fixture
    #: borrowing a real one ("Marta Marthannis", "Varrin") dies on the
    #: constraint against live data. Third time in this suite.
    CANON_NAME = "Pytestmarta Pytestmarthannis"

    @pytest.fixture
    def linked(self, overlaid):
        """A canon entity, and a campaign scene that mentions it."""
        overlaid.run(
            """
            CREATE (e:Entity {id:$id, name:$name, plane:'canon'})
            CREATE (a:Alias {name:$name, normalized:$norm, plane:'canon'})
            CREATE (a)-[:ALIAS_OF]->(e)
            """,
            {"id": self.LINKED, "name": self.CANON_NAME,
             "norm": self.CANON_NAME.lower()},
        )
        overlaid.run(
            """
            MATCH (e:Entity {id:$e}), (s:Section {id:$s})
            CREATE (m:Mention {plane:'campaign', campaign:$c, surface:$name})
            CREATE (m)-[:REFERS_TO]->(e)
            CREATE (m)-[:IN_SECTION]->(s)
            """,
            {"e": self.LINKED, "s": f"hb:{SLUG}:corsair-boarding#0", "c": SLUG,
             "name": self.CANON_NAME},
        )
        yield overlaid
        overlaid.run("MATCH (e:Entity {id:$id}) DETACH DELETE e", {"id": self.LINKED})
        overlaid.run("MATCH (a:Alias {normalized:$n}) DETACH DELETE a",
                     {"n": self.CANON_NAME.lower()})

    def test_asking_about_the_book_s_npc_surfaces_the_scene(self, linked):
        result = CanonRetriever(book=BOOK, limit=6, campaign=SLUG).retrieve(
            f"tell me about {self.CANON_NAME}"
        )
        campaign = [p for p in result.passages if p.origin == "campaign"]
        assert campaign, "the link recorded nothing a question could reach"

    def test_the_canon_entity_itself_is_untouched(self, linked):
        """A mention points AT the node. It never changes it."""
        row = dict(
            linked.run(
                "MATCH (e:Entity {id:$id}) RETURN e.plane AS plane, properties(e) AS p",
                {"id": self.LINKED},
            ).single()
        )
        assert row["plane"] == "canon"
        assert "campaign" not in row["p"]

    def test_a_campaign_less_session_sees_none_of_it(self, linked):
        """THE CONTAMINATION QUESTION, and it holds by construction rather than
        by a filter: `MENTIONS` requires the section to hang off a `:Chapter`,
        and a campaign section hangs off a `:Campaign`."""
        result = CanonRetriever(book=BOOK, limit=6).retrieve(
            f"tell me about {self.CANON_NAME}"
        )
        assert not any(p.origin == "campaign" for p in result.passages)
        assert not any("hb:" in p.section_id for p in result.passages)

    def test_the_canon_read_is_byte_identical_either_way(self, linked):
        """The stronger form: a linked canon entity answers canon questions
        exactly as it did before anyone linked it."""
        question = f"tell me about {self.CANON_NAME}"
        without = [
            p.section_id
            for p in CanonRetriever(book=BOOK, limit=6).retrieve(question).passages
        ]
        with_campaign = [
            p.section_id
            for p in CanonRetriever(book=BOOK, limit=6, campaign=SLUG)
            .retrieve(question)
            .passages
            if not p.section_id.startswith("hb:")
        ]
        assert with_campaign == without


class TestYourOwnNamesAreMatchedCaseFolded:
    """The two-pass case rule is all-or-nothing: a strict match anywhere means
    the folded pass never runs. So "lets revisit the homebrew content about the
    sea battle from prisoner 13" resolved `Prisoner 13` and never saw `the sea
    battle` -- a scene the DM had written and named. The chat had no idea it
    existed and offered to write one."""

    def test_a_lower_case_mention_of_your_own_scene_resolves(self, overlaid):
        result = CanonRetriever(book=BOOK, limit=6, campaign=SLUG).retrieve(
            "lets revisit the corsair boarding"
        )
        assert any(is_campaign_id(a.entity_id) for a in result.anchors)

    def test_it_resolves_even_when_a_canon_name_matched_strictly(self, overlaid):
        """The exact case reported: a canon name anchoring the question used to
        mean the DM's own name was never looked for at all, because the folded
        pass only ran when the strict one found NOTHING."""
        overlaid.run(
            """
            CREATE (e:Entity {id:$id, name:'Pytest Warden Kessel', plane:'canon'})
            CREATE (a:Alias {name:'Pytest Warden Kessel',
                             normalized:'pytest warden kessel', plane:'canon'})
            CREATE (a)-[:ALIAS_OF]->(e)
            """,
            {"id": f"{BOOK}:pytest-warden-kessel"},
        )
        try:
            result = CanonRetriever(book=BOOK, limit=6, campaign=SLUG).retrieve(
                "what does Pytest Warden Kessel know about the corsair boarding"
            )
            ids = [a.entity_id for a in result.anchors]
            assert any(is_campaign_id(i) for i in ids), "the DM's own name resolved"
            assert any(not is_campaign_id(i) for i in ids), "canon still resolves too"
        finally:
            # The entity goes with the book prefix on teardown; the alias is
            # canon-plane, so the fixture's orphan sweep does not reach it.
            overlaid.run(
                "MATCH (a:Alias {name:$n}) DETACH DELETE a",
                {"n": "Pytest Warden Kessel"},
            )

    def test_it_does_not_make_the_answer_loose(self, overlaid):
        """`loose` says the weaker rule rescued a question that would otherwise
        have found nothing. Folding case for a campaign name is the normal
        rule now, not a rescue, and labelling it as one would teach a reader to
        distrust an answer that is fine."""
        result = CanonRetriever(book=BOOK, limit=6, campaign=SLUG).retrieve(
            "lets revisit the corsair boarding"
        )
        assert not result.loose


class TestWhatTheDMHasOpenBiasesRetrieval:
    """A PRIOR, NOT A FILTER. The whole graph is still read; the focus only
    fills anchor slots the question itself did not, so nothing typed can be
    outvoted by whatever happens to be on screen."""

    def test_a_question_that_names_nothing_leans_on_the_focus(self, overlaid):
        """"give me a cast of enemies" resolves no name and fell straight to
        Lucene, returning hits from unrelated adventures — and it is exactly
        the question a DM asks with the scene open in front of them."""
        r = CanonRetriever(book=BOOK, limit=6, campaign=SLUG)
        blind = r.retrieve("give me a cast of enemies")
        led = r.retrieve("give me a cast of enemies", focus=SCENE_SECTION)
        assert not any(a.path == PATH_FOCUS for a in blind.anchors)
        assert any(a.path == PATH_FOCUS for a in led.anchors)

    def test_what_the_question_names_keeps_its_place(self, overlaid):
        """The rule is lexicographic. A focus anchor can only be appended
        after everything the DM actually typed has resolved."""
        led = CanonRetriever(book=BOOK, limit=6, campaign=SLUG).retrieve(
            "tell me about Corsair Boarding", focus=SCENE_SECTION
        )
        typed = [a for a in led.anchors if a.path != PATH_FOCUS]
        assert typed, "the named anchor survived"
        assert led.anchors[0].path != PATH_FOCUS, "and it is still first"

    def test_a_focus_only_passage_says_so(self, overlaid):
        """An invisible bias is indistinguishable from the tool quietly
        getting worse. A passage here because of the screen carries its own
        label, exactly as a keyword hit does."""
        led = CanonRetriever(book=BOOK, limit=6, campaign=SLUG).retrieve(
            "give me a cast of enemies", focus=SCENE_SECTION
        )
        assert any(p.path == PATH_FOCUS for p in led.passages)

    def test_the_open_prose_travels_whole_and_apart(self, overlaid):
        """Not among the ranked passages — it is not competing for a slot, it
        is here because they are looking at it."""
        led = CanonRetriever(book=BOOK, limit=6, campaign=SLUG).retrieve(
            "what happens next", focus=SCENE_SECTION
        )
        assert led.focus_prose is not None
        assert led.focus_prose["section_id"] == SCENE_SECTION

    def test_no_focus_is_the_behaviour_that_came_before(self, overlaid):
        blind = CanonRetriever(book=BOOK, limit=6, campaign=SLUG).retrieve(QUESTION)
        assert blind.focus_prose is None
        assert not any(p.path == PATH_FOCUS for p in blind.passages)
