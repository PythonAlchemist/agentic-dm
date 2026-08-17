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
