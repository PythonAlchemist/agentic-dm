"""Generating material with canon and invention kept apart."""

import json
from types import SimpleNamespace

import pytest

from backend.agents import canon_context, generator
from backend.canon.retrieval import PATH_GRAPH, Passage, Retrieval


def a_retrieval(**kw) -> Retrieval:
    return Retrieval(
        question="q",
        passages=(
            Passage(
                section_id="cos:the-village-of-barovia#5",
                chapter="the-village-of-barovia",
                chapter_index=4,
                section="E2. Blood of the Vine Tavern",
                section_index=5,
                text="The tavern has grown shoddy over the years.",
                occurrences=1,
                entity_ids=("cos:blood-of-the-vine-tavern",),
            ),
        ),
        accepted=kw.get("accepted", ()),
        proposed=kw.get("proposed", ()),
        path=PATH_GRAPH,
    )


class FakeCompletions:
    def __init__(self, content):
        self.content = content
        self.kwargs = None

    async def create(self, **kw):
        self.kwargs = kw
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))],
            usage=SimpleNamespace(prompt_tokens=800, completion_tokens=200),
        )


def client_returning(content):
    return SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions(content)))


GOOD = json.dumps(
    {
        "title": "The Barkeep's Debt",
        "body": "Arik owes money to Bildrath.",
        "from_canon": [{"claim": "The tavern has grown shoddy", "cite": "[1]"}],
        "invented": ["the debt", "the amount owed"],
    }
)


class TestTheMessages:
    def test_the_canon_block_is_the_system_message(self):
        messages = build = generator.build_messages(
            "npc", "a tavern regular", a_retrieval(), canon_context.Depth()
        )
        assert messages[0]["role"] == "system"
        assert "The tavern has grown shoddy over the years." in messages[0]["content"]

    def test_the_subject_reaches_the_model(self):
        messages = generator.build_messages(
            "quest", "a debt owed to Bildrath", a_retrieval(), canon_context.Depth()
        )
        assert "a debt owed to Bildrath" in messages[1]["content"]

    def test_each_kind_asks_for_its_own_shape(self):
        npc = generator.build_messages("npc", "x", a_retrieval(), canon_context.Depth())
        monster = generator.build_messages(
            "monster", "x", a_retrieval(), canon_context.Depth()
        )
        assert npc[1]["content"] != monster[1]["content"]

    def test_an_unknown_kind_is_refused_before_a_model_is_called(self):
        """An unrecognised kind would otherwise become an unconstrained prompt."""
        with pytest.raises(ValueError, match="unknown kind"):
            generator.build_messages("haiku", "x", a_retrieval(), canon_context.Depth())

    def test_withholding_proposed_edges_keeps_them_out_of_the_prompt(self):
        retrieval = a_retrieval(
            proposed=[{"entity": "Arik", "relationship": "SEEKS",
                       "other": "Ireena", "direction": "out"}]
        )
        depth = canon_context.Depth(include_proposed=False)
        messages = generator.build_messages("npc", "x", retrieval, depth)
        assert "Arik -SEEKS-> Ireena" not in messages[0]["content"]


class TestParsing:
    def test_a_well_formed_response_parses(self):
        data, error = generator.parse(GOOD)
        assert error == ""
        assert data["title"] == "The Barkeep's Debt"

    def test_a_fenced_code_block_is_tolerated(self):
        """Models wrap JSON in fences often enough that failing on it would
        report a prompt problem as a model problem."""
        data, error = generator.parse(f"```json\n{GOOD}\n```")
        assert error == ""
        assert data["title"] == "The Barkeep's Debt"

    def test_a_response_omitting_invented_is_rejected(self):
        """An absent `invented` list reads as 'all of this is from the book' --
        the precise claim this module exists to keep honest."""
        data, error = generator.parse(
            json.dumps({"title": "t", "body": "b", "from_canon": []})
        )
        assert data == {}
        assert "invented" in error

    def test_a_response_omitting_from_canon_is_rejected(self):
        data, error = generator.parse(
            json.dumps({"title": "t", "body": "b", "invented": []})
        )
        assert data == {}
        assert "from_canon" in error

    def test_prose_instead_of_json_is_reported_not_swallowed(self):
        data, error = generator.parse("Here is a nice NPC for you!")
        assert data == {}
        assert "not JSON" in error


@pytest.mark.asyncio
class TestGenerating:
    async def test_the_split_survives_into_the_result(self):
        result = await generator.generate(
            client_returning(GOOD),
            kind="npc",
            subject="a tavern regular",
            retrieval=a_retrieval(),
            depth=canon_context.Depth(),
            model="gpt-4o-mini",
        )
        assert result.from_canon[0]["cite"] == "[1]"
        assert "the debt" in result.invented
        assert result.error == ""

    async def test_usage_and_cost_come_back_with_it(self):
        result = await generator.generate(
            client_returning(GOOD),
            kind="npc",
            subject="x",
            retrieval=a_retrieval(),
            depth=canon_context.Depth(),
            model="gpt-4o-mini",
        )
        assert result.usage == {"input": 800, "output": 200, "total": 1000}
        assert result.cost["model"] == "gpt-4o-mini"

    async def test_a_malformed_response_keeps_the_raw_text_to_debug_from(self):
        result = await generator.generate(
            client_returning("not json at all"),
            kind="quest",
            subject="x",
            retrieval=a_retrieval(),
            depth=canon_context.Depth(),
            model="gpt-4o-mini",
        )
        assert result.error
        assert result.raw == "not json at all"

    async def test_a_good_response_does_not_carry_raw_text(self):
        """Raw is evidence about a failure; shipping it on success would double
        every payload for nothing."""
        result = await generator.generate(
            client_returning(GOOD),
            kind="npc",
            subject="x",
            retrieval=a_retrieval(),
            depth=canon_context.Depth(),
            model="gpt-4o-mini",
        )
        assert result.raw == ""

    async def test_the_citations_point_at_the_passages_supplied(self):
        result = await generator.generate(
            client_returning(GOOD),
            kind="npc",
            subject="x",
            retrieval=a_retrieval(),
            depth=canon_context.Depth(),
            model="gpt-4o-mini",
        )
        assert result.sources[0]["source"] == "cos:the-village-of-barovia#5"
        assert result.sources[0]["citation"] == "[1]"


class TestTheBookIsNamedFromTheRetrieval:
    """Both model-facing blocks name the book the passages actually came from.

    THE DEFECT THIS PINS. `_INSTRUCTIONS` opened "a Dungeon Master running
    Curse of Strahd" and `_PREAMBLE` said "passages retrieved from Curse of
    Strahd", both unconditionally. A second book was loaded and made selectable
    and neither string changed, so every Golden Vault turn was prefaced to the
    model as Barovia -- the stale-constant defect the chapter count already
    taught this project, except said to the MODEL, where no reader sees it.
    """

    def _messages(self, title: str) -> str:
        # A PASSAGE IS REQUIRED. `render` short-circuits to the no-canon message
        # when there are none, so a passage-less retrieval never reaches the
        # preamble at all -- and a first draft of this test passed happily while
        # the preamble was still hardcoded, because it was never rendered.
        retrieval = Retrieval(
            question="a guard",
            book_title=title,
            path=PATH_GRAPH,
            passages=(
                Passage(
                    section_id="x:ch#0",
                    chapter="ch",
                    chapter_index=0,
                    section="A Section",
                    section_index=0,
                    text="A guard stands here.",
                    occurrences=1,
                    entity_ids=(),
                ),
            ),
        )
        depth = canon_context.Depth()
        return "\n".join(
            m["content"] for m in generator.build_messages("npc", "a guard", retrieval, depth)
        )

    def test_the_heist_anthology_is_named(self):
        text = self._messages("Keys from the Golden Vault")
        assert "Keys from the Golden Vault" in text
        assert "Curse of Strahd" not in text

    def test_curse_of_strahd_is_still_named_when_it_is_the_book(self):
        """The fix must not have simply deleted the name."""
        assert "Curse of Strahd" in self._messages("Curse of Strahd")

    def test_an_unknown_book_says_something_rather_than_nothing(self):
        """A retrieval with no title must not render an empty phrase."""
        text = self._messages("")
        assert "running ." not in text and "retrieved from  " not in text


class TestTheThirdSource:
    """A conversation is neither the book nor the model's invention.

    Once chat can call the generator, three things can put a detail on the
    page: the book, the model, and what the DM said at the table. Two buckets
    for three origins forces a lie either way -- `from_canon` claims the book
    says something it does not, `invented` claims the model made up a fact the
    table established.
    """

    def _retrieval(self):
        return Retrieval(
            question="a sea battle",
            book_title="Keys from the Golden Vault",
            path=PATH_GRAPH,
            passages=(
                Passage(
                    section_id="kftgv:prisoner-13#7",
                    chapter="prisoner-13",
                    chapter_index=3,
                    section="Trek to the Prison",
                    section_index=7,
                    text="The voyage north takes eight days.",
                    occurrences=1,
                    entity_ids=(),
                ),
            ),
        )

    def _messages(self, context=None):
        return generator.build_messages(
            "scene", "a sea battle", self._retrieval(), canon_context.Depth(), context
        )

    def test_context_is_its_own_block_not_folded_into_canon(self):
        """A DM's remark and the book's sentence must not arrive looking alike."""
        system = self._messages(
            generator.GenerationContext(entities=("Meera Raheer",), note="they took the boat")
        )[0]["content"]
        assert "CONVERSATION" in system
        canon_block, _, context_block = system.partition("CONVERSATION")
        assert "they took the boat" in context_block
        assert "they took the boat" not in canon_block

    def test_the_third_list_is_asked_for_when_context_is_given(self):
        user = self._messages(generator.GenerationContext(note="they took the boat"))[1]["content"]
        assert "from_context" in user

    def test_and_is_not_asked_for_when_there_is_none(self):
        """A required list that is always empty teaches the model to ignore it."""
        assert "from_context" not in self._messages()[1]["content"]

    def test_empty_context_renders_nothing_at_all(self):
        assert generator.GenerationContext().render() == ""
        assert "CONVERSATION" not in self._messages()[0]["content"]

    def test_parse_rejects_a_response_missing_the_third_list(self):
        _, error = generator.parse(
            json.dumps({"title": "t", "body": "b", "from_canon": [], "invented": []}),
            expect_context=True,
        )
        assert "from_context" in error

    def test_parse_still_accepts_it_when_no_context_was_given(self):
        data, error = generator.parse(
            json.dumps({"title": "t", "body": "b", "from_canon": [], "invented": []})
        )
        assert error == "" and data["title"] == "t"

    def test_the_two_original_lists_are_still_required(self):
        """The contract this module was built on does not weaken."""
        for missing in ("from_canon", "invented"):
            payload = {"title": "t", "body": "b", "from_canon": [], "invented": []}
            del payload[missing]
            assert missing in generator.parse(json.dumps(payload))[1]


class TestTheSceneKind:
    def test_scene_is_generatable(self):
        assert "scene" in generator.KINDS

    def test_it_asks_about_where_it_interrupts(self):
        """What makes a scene a scene is its position, not its contents."""
        user = generator.build_messages(
            "scene", "a sea battle",
            Retrieval(question="x", book_title="B", path=PATH_GRAPH, passages=(
                Passage(section_id="b:c#0", chapter="c", chapter_index=0, section="S",
                        section_index=0, text="t", occurrences=1, entity_ids=()),
            )),
            canon_context.Depth(),
        )[1]["content"]
        assert "interrupts" in user

    def test_an_unknown_kind_is_still_refused(self):
        with pytest.raises(ValueError):
            generator.build_messages(
                "sea-shanty", "x", Retrieval(question="x"), canon_context.Depth()
            )


class TestTheManifestContract:
    """A generation may declare what it contains, and is held to it.

    THE AUTHOR DECLARES RATHER THAN A READER REDISCOVERING. The call that
    writes "Captain Saltmarrow commands the Red Barge" already holds that edge.
    Asking a second model to find it again in the prose is a lossy round-trip:
    book extraction exists because the author is unavailable, and here the
    author is the same call.
    """

    def _retrieval(self):
        return Retrieval(
            question="a sea battle",
            book_title="Keys from the Golden Vault",
            path=PATH_GRAPH,
            passages=(
                Passage(
                    section_id="kftgv:prisoner-13#7", chapter="prisoner-13",
                    chapter_index=3, section="Trek to the Prison", section_index=7,
                    text="The voyage north takes eight days.", occurrences=1,
                    entity_ids=(),
                ),
            ),
        )

    def test_a_cluster_is_asked_for_only_when_requested(self):
        plain = generator.build_messages(
            "scene", "x", self._retrieval(), canon_context.Depth()
        )[1]["content"]
        clustered = generator.build_messages(
            "scene", "x", self._retrieval(), canon_context.Depth(), cluster=True
        )[1]["content"]
        assert "elements" not in plain
        assert "elements" in clustered and "edges" in clustered

    def test_the_offered_vocabulary_is_in_the_prompt(self):
        """A model told to pick from a vocabulary must be shown it."""
        clustered = generator.build_messages(
            "scene", "x", self._retrieval(), canon_context.Depth(), cluster=True
        )[1]["content"]
        assert "LOCATED_IN" in clustered and "GUARDS" in clustered

    def test_a_cluster_response_missing_elements_is_rejected(self):
        _, error = generator.parse(
            json.dumps({"from_canon": [], "invented": []}), expect_cluster=True
        )
        assert "elements" in error

    def test_empty_lists_are_legal(self):
        """A generation that contains nothing worth minting is not a failure,
        and is what every pre-cluster generation looks like."""
        data, error = generator.parse(
            json.dumps({"from_canon": [], "invented": [], "elements": [], "edges": []}),
            expect_cluster=True,
        )
        assert error == "" and data["elements"] == []


class TestTheVocabularyIsDerived:
    def test_it_comes_from_the_layer_map(self):
        from backend.graph.schema import LAYER_MAP

        expected = {r.value for r, layer in LAYER_MAP.items() if layer is not None}
        assert set(generator.homebrew_vocabulary()) == expected

    def test_session_bookkeeping_is_excluded_without_a_denylist(self):
        """`ATTENDED` and `PLAYS_AS` are runtime state, not authored world.
        They fall out because `LAYER_MAP` maps them to no layer -- nothing here
        lists them, so nothing here can forget to."""
        offered = set(generator.homebrew_vocabulary())
        assert not offered & {"ATTENDED", "PLAYS_AS", "HAS_CLASS", "HAS_RACE"}
        assert "LOCATED_IN" in offered and "GUARDS" in offered


class TestBadManifestEntriesAreCountedNotSwallowed:
    """Dropped, tallied by reason, never coerced to the nearest valid thing."""

    def test_an_unoffered_element_kind_is_dropped_and_counted(self):
        _, _, dropped = generator.sift_manifest(
            {"elements": [{"kind": "ship", "name": "The Barge"}], "edges": []}
        )
        assert sum(dropped.values()) == 1 and any("ship" in r for r in dropped)

    def test_an_out_of_vocabulary_relationship_is_dropped(self):
        _, edges, dropped = generator.sift_manifest(
            {"elements": [], "edges": [{"source": "a", "target": "b", "rel_type": "PLAYS_AS"}]}
        )
        assert edges == () and any("PLAYS_AS" in r for r in dropped)

    def test_a_self_edge_is_dropped(self):
        _, edges, dropped = generator.sift_manifest(
            {"elements": [], "edges": [{"source": "a", "target": "A", "rel_type": "KNOWS"}]}
        )
        assert edges == () and "edge points at itself" in dropped

    def test_a_relationship_is_accepted_case_insensitively(self):
        """A model writing `located_in` meant the type; that is spelling, not a
        different claim."""
        _, edges, _ = generator.sift_manifest(
            {"elements": [], "edges": [{"source": "a", "target": "b", "rel_type": "located_in"}]}
        )
        assert edges[0]["rel_type"] == "LOCATED_IN"

    def test_nothing_is_coerced_to_a_near_miss(self):
        """`LOCATED` is not `LOCATED_IN`. Guessing what a model meant is how a
        wrong edge becomes indistinguishable from a checked one."""
        _, edges, dropped = generator.sift_manifest(
            {"elements": [], "edges": [{"source": "a", "target": "b", "rel_type": "LOCATED"}]}
        )
        assert edges == () and dropped


class TestClustersDoNotChangeWhatExisted:
    """The compat pin: every generation that worked yesterday is byte-identical."""

    def test_the_messages_are_unchanged_without_a_cluster(self):
        retrieval = Retrieval(
            question="a guard", book_title="Curse of Strahd", path=PATH_GRAPH,
            passages=(
                Passage(section_id="cos:c#0", chapter="c", chapter_index=0,
                        section="S", section_index=0, text="t", occurrences=1,
                        entity_ids=()),
            ),
        )
        depth = canon_context.Depth()
        before = generator.build_messages("npc", "a guard", retrieval, depth)
        after = generator.build_messages("npc", "a guard", retrieval, depth, None, False)
        assert before == after
        assert "{cluster_rule}" not in before[1]["content"]

    def test_a_plain_parse_ignores_the_manifest_entirely(self):
        data, error = generator.parse(
            json.dumps({"from_canon": [], "invented": []})
        )
        assert error == "" and "elements" not in data


class TestAskingForTheSameThingAgain:
    """A draft that is nearly right had two options: rewrite the prose by hand,
    or start over and lose the citations. "Same again, but make her older" is
    the verb that was missing."""

    def _messages(self, **kw):
        return generator.build_messages(
            "npc", "a fence", Retrieval(question="x"), canon_context.Depth(), **kw
        )[1]["content"]

    def test_the_draft_and_the_change_both_reach_the_model(self):
        text = self._messages(previous="She is young and eager.", note="make her older")
        assert "She is young and eager." in text
        assert "WHAT TO CHANGE: make her older" in text

    def test_it_is_its_own_block(self):
        """Not canon, not context, not an instruction. Folding a discarded
        draft into any of those three would make the model treat it as
        evidence about the world."""
        text = self._messages(previous="A draft.", note="change it")
        # LAST, after every rule it must not be mistaken for -- the provenance
        # split above still governs, and the revision is a constraint on the
        # answer rather than a new source for it.
        assert text.index("THE DRAFT YOU ARE REPLACING") > text.index("from_canon")

    def test_both_or_neither(self):
        """A note with no draft is a longer subject; a draft with no note asks
        for the same thing twice."""
        assert "WHAT TO CHANGE" not in self._messages(previous="A draft.")
        assert "WHAT TO CHANGE" not in self._messages(note="make her older")
        assert "WHAT TO CHANGE" not in self._messages()

    def test_whitespace_is_not_a_note(self):
        assert "WHAT TO CHANGE" not in self._messages(previous="A draft.", note="   ")
