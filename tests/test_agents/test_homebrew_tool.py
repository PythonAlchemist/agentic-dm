"""The contract between the chat agent and the generator.

The rule this file exists to hold: a model may ASK for material and may never
WRITE it into an answer. Everything else here is about not letting a model
invent an id.
"""


import pytest

from backend.agents import homebrew_tool
from backend.campaign import homebrew, store
from backend.campaign.model import Campaign
from backend.core.database import neo4j_session

SLUG = "pytest-read-tool"


@pytest.fixture
def table(tmp_path):
    """One campaign holding one written-up scene."""
    with neo4j_session() as session:
        _wipe(session)
        session.execute_write(
            lambda tx: store.create(tx, Campaign(slug=SLUG, name="Read Tool", books=()))
        )
        session.execute_write(
            lambda tx: homebrew.write(
                tx, slug=SLUG, kind="scene", title="Pytest Night Watch",
                body="A quiet watch on deck.", generated_body="A quiet watch on deck.",
                from_canon=[], invented=[], from_context=[], sources=[], anchor=None,
                log_path=tmp_path / "log.jsonl",
            )
        )
        yield session
        _wipe(session)


def _wipe(session):
    session.run("MATCH (c:Campaign {slug:$s}) DETACH DELETE c", {"s": SLUG})
    session.run("MATCH (n) WHERE n.id STARTS WITH $p DETACH DELETE n",
                {"p": f"hb:{SLUG}:"})
    session.run("MATCH (a:Alias) WHERE NOT (a)-[:ALIAS_OF]->() DETACH DELETE a")

HELD = frozenset({"kftgv:prisoner-13:varrin-axebreaker", "kftgv:golden-vault"})
SEEN = frozenset({"kftgv:prisoner-13#7", "kftgv:prisoner-13#8"})


def _validate(**arguments):
    return homebrew_tool.validate(arguments, held_ids=HELD, seen_sections=SEEN)


class TestTheAsk:
    def test_a_well_formed_ask_is_accepted(self):
        request, error = _validate(
            kind="scene",
            subject="a sea battle on the voyage",
            context_entity_ids=["kftgv:golden-vault"],
            insert_after_section_id="kftgv:prisoner-13#7",
            note="the party chartered a boat",
        )
        assert error == ""
        assert request.kind == "scene"
        assert request.context_entity_ids == ("kftgv:golden-vault",)
        assert request.insert_after == "kftgv:prisoner-13#7"

    def test_an_unknown_kind_is_refused(self):
        _, error = _validate(kind="sea-shanty", subject="x")
        assert "unknown kind" in error

    def test_a_missing_subject_is_refused(self):
        _, error = _validate(kind="npc", subject="   ")
        assert "subject" in error


class TestIdsAreCheckedAgainstTheConversation:
    """A constrained menu, not free text."""

    def test_an_invented_entity_id_is_dropped_and_reported(self):
        """Silently dropping it would let the model make the same mistake
        again next round with no idea why nothing happened."""
        request, _ = _validate(
            kind="npc", subject="a guard", context_entity_ids=["cos:strahd-von-zarovich"]
        )
        assert request.context_entity_ids == ()
        assert "cos:strahd-von-zarovich" in request.rejected

    def test_an_unseen_anchor_is_dropped_and_reported(self):
        """A model must not place a scene in a chapter nobody has opened."""
        request, _ = _validate(
            kind="scene", subject="a battle", insert_after_section_id="cos:the-village#3"
        )
        assert request.insert_after == ""
        assert "cos:the-village#3" in request.rejected

    def test_too_much_context_is_truncated_and_counted(self):
        held = frozenset(f"kftgv:e{i}" for i in range(10))
        request, _ = _validate_with(
            held, kind="npc", subject="x",
            context_entity_ids=[f"kftgv:e{i}" for i in range(10)],
        )
        assert len(request.context_entity_ids) == homebrew_tool.MAX_CONTEXT
        assert len(request.rejected) == 10 - homebrew_tool.MAX_CONTEXT

    def test_a_non_list_context_is_refused(self):
        _, error = _validate(kind="npc", subject="x", context_entity_ids="everything")
        assert "list" in error


def _validate_with(held, **arguments):
    return homebrew_tool.validate(arguments, held_ids=held, seen_sections=SEEN)


class TestWhatTheModelGetsBack:
    """THE LOAD-BEARING RULE. The tool returns an acknowledgement, never the
    material -- so a model cannot weave invention into an answer without the
    provenance envelope the generator enforces."""

    def test_the_result_carries_no_material(self):
        request, _ = _validate(kind="npc", subject="a harbour master")
        payload = request.acknowledgement
        assert "body" not in payload and "title" not in payload
        assert payload["queued"] is True

    def test_the_model_is_told_not_to_write_it(self):
        request, _ = _validate(kind="npc", subject="a harbour master")
        assert "Do not write it out yourself" in request.acknowledgement["instruction"]

    def test_rejected_ids_are_reported_back(self):
        request, _ = _validate(
            kind="npc", subject="x", context_entity_ids=["made:up"]
        )
        assert "made:up" in request.acknowledgement["ignored"]


class TestTheSchema:
    def test_the_description_tells_the_model_it_gets_a_card(self):
        description = homebrew_tool.SCHEMA["function"]["description"]
        assert "card" in description and "do not write the content" in description.lower()

    def test_scene_is_offered(self):
        enum = homebrew_tool.SCHEMA["function"]["parameters"]["properties"]["kind"]["enum"]
        assert "scene" in enum


class TestReadingWhatTheTableAlreadyMade:
    """The chat's only actionable tool was `generate_homebrew`, described as
    "use when the DM asks you to make something up". So "lets revisit the
    homebrew content about the sea battle" had exactly one place to go, went
    there, and drafted a new scene over a scene that existed."""

    def test_a_name_returns_the_prose(self, table):
        found = homebrew_tool.read(table, SLUG, "pytest night watch")["found"]
        assert found[0]["written"] is True
        assert "quiet" in found[0]["text"]

    def test_the_name_is_matched_case_folded(self, table):
        """A DM types "the sea battle", not `hb:p13-home:the-sea-battle`, and
        the roster they were shown lists names."""
        assert homebrew_tool.read(table, SLUG, "PYTEST NIGHT WATCH")["found"]

    def test_omitting_the_name_returns_everything(self, table):
        assert len(homebrew_tool.read(table, SLUG)["found"]) >= 1

    def test_a_name_that_matches_nothing_says_what_there_is(self, table):
        """An empty result would read as "you have made nothing", which is the
        failure this whole tool exists to stop."""
        answer = homebrew_tool.read(table, SLUG, "the kraken")
        assert answer["found"] is None
        assert answer["this_table_has"], "it says what the table does have"

    def test_another_campaign_sees_none_of_it(self, table):
        assert homebrew_tool.read(table, "someone-elses")["found"] == []


class TestRewritingSomethingThatExists:
    """A DM looking at their own one-sentence scene and asking to build it out
    got a SECOND scene beside the first. `generate_homebrew` makes new things
    and `read_my_material` shows them; neither could change one."""

    def test_what_is_open_is_what_gets_rewritten(self, table):
        """A model asked to rewrite "this" means the thing on screen. Making it
        name that thing would be asking it to guess at something known."""
        found = homebrew_tool.resolve_revision(
            table, campaign=SLUG, name="",
            focus=f"hb:{SLUG}:pytest-night-watch#0",
        )
        assert found["name"] == "Pytest Night Watch"
        assert found["section_id"] == f"hb:{SLUG}:pytest-night-watch#0"

    def test_the_entity_id_works_as_well_as_the_section_id(self):
        """Focus follows the entity, so it may be either. Both mean the same
        thing to a person."""
        assert "$focus STARTS WITH e.id" in homebrew_tool.RESOLVE_REVISION

    def test_a_name_can_be_given_instead(self, table):
        found = homebrew_tool.resolve_revision(
            table, campaign=SLUG, name="pytest night watch", focus="",
        )
        assert found["section_id"].endswith("#0")

    def test_a_stub_has_nothing_to_rewrite(self, table):
        """Something with only a role resolves to None -- that is what `expand`
        is for. The DM is told, rather than handed a "revision" of a blank
        page."""
        table.run(
            "MATCH (c:Campaign {slug:$s}) CREATE (e:Entity {id:$i, plane:'campaign', "
            "campaign:$s, name:'Pytest Stub', kind:'npc', role:'a name only'})",
            {"s": SLUG, "i": f"hb:{SLUG}:pytest-stub"},
        )
        assert homebrew_tool.resolve_revision(
            table, campaign=SLUG, name="Pytest Stub", focus=""
        ) is None

    def test_another_campaign_cannot_reach_it(self, table):
        assert homebrew_tool.resolve_revision(
            table, campaign="someone-elses", name="pytest night watch", focus=""
        ) is None
