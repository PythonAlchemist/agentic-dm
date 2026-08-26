"""That the canon block actually reaches the model.

Rendering is tested next door; this tests the WIRING, which is the part that
silently does nothing when it is wrong. The pipeline beside this one has been
inserting a list of source names for months and looked, from the outside,
exactly like grounding.

Both the graph and the model are fakes. What is asserted is the messages the
agent would send.
"""

from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace

import pytest

from backend.agents.dm_agent import DMAgent
from backend.canon.ontology import Ontology
from backend.canon.retrieval import PATH_GRAPH, PATH_TEXT, Passage, Retrieval


@contextmanager
def _no_session():
    """A read-only session that reaches no database."""
    yield None

#: Only the rendered block says this; the SYSTEM_PROMPT's guidance says "CANON"
#: on its own, so a bare substring check would pass on the prompt alone.
BLOCK_MARK = "CANON \u2014"


class FakeRetriever:
    def __init__(self, result=None, boom=False):
        self.result = result
        self.boom = boom
        self.asked = []

    def retrieve(self, question, **kw):
        self.asked.append(question)
        if self.boom:
            raise RuntimeError("neo4j is down")
        return self.result


class FakeCompletions:
    def __init__(self):
        self.messages = None

    async def create(self, **kw):
        self.messages = kw["messages"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="an answer"))]
        )


def a_retrieval(text="Ismark sits by himself at a corner table.") -> Retrieval:
    return Retrieval(
        question="q",
        passages=(
            Passage(
                section_id="cos:the-village-of-barovia#5",
                chapter="the-village-of-barovia",
                chapter_index=4,
                section="E2. Blood of the Vine Tavern",
                section_index=5,
                text=text,
                occurrences=2,
                entity_ids=("cos:ismark-kolyanovich",),
            ),
        ),
        path=PATH_GRAPH,
    )


@pytest.fixture
def agent(monkeypatch):
    """A DMAgent whose model and RAG pipeline are inert."""
    monkeypatch.setattr(
        "backend.agents.dm_agent.HybridRAGPipeline", lambda: SimpleNamespace()
    )
    built = DMAgent(canon=FakeRetriever(a_retrieval()))
    built.openai = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    return built


def system_text(agent) -> str:
    sent = agent.openai.chat.completions.messages
    return "\n".join(m["content"] for m in sent if m["role"] == "system")


@pytest.mark.asyncio
class TestTheBlockReachesTheModel:
    async def test_the_passage_text_is_in_the_messages_sent(self, agent):
        await agent.process_message("Who is Ismark?", use_rag=False)
        assert "Ismark sits by himself at a corner table." in system_text(agent)

    async def test_the_question_is_what_canon_was_asked(self, agent):
        await agent.process_message("Who is Ismark?", use_rag=False)
        assert agent.canon.asked == ["Who is Ismark?"]

    async def test_canon_is_read_before_the_conversation(self, agent):
        """The model should read the book's words before the question, not
        after its own previous answers."""
        await agent.process_message("Who is Ismark?", use_rag=False)
        sent = agent.openai.chat.completions.messages
        canon_at = next(i for i, m in enumerate(sent) if BLOCK_MARK in m["content"])
        user_at = next(i for i, m in enumerate(sent) if m["role"] == "user")
        assert canon_at < user_at

    async def test_the_citation_comes_back_as_a_source(self, agent):
        response = await agent.process_message("Who is Ismark?", use_rag=False)
        assert response.sources[0]["source"] == "cos:the-village-of-barovia#5"
        assert response.sources[0]["type"] == "canon"

    async def test_use_canon_false_sends_no_block_and_asks_nothing(self, agent):
        await agent.process_message("Who is Ismark?", use_rag=False, use_canon=False)
        assert BLOCK_MARK not in system_text(agent)
        assert agent.canon.asked == []

    async def test_a_slash_command_never_reaches_canon(self, agent):
        """`/roll 1d20` is not a question about the book."""
        await agent.process_message("/roll 1d20", use_rag=False)
        assert agent.canon.asked == []


@pytest.mark.asyncio
class TestWhenTheGraphIsUnreachable:
    async def test_a_dead_neo4j_degrades_rather_than_crashing_mid_session(
        self, monkeypatch
    ):
        monkeypatch.setattr(
            "backend.agents.dm_agent.HybridRAGPipeline", lambda: SimpleNamespace()
        )
        agent = DMAgent(canon=FakeRetriever(boom=True))
        agent.openai = SimpleNamespace(
            chat=SimpleNamespace(completions=FakeCompletions())
        )
        response = await agent.process_message("Who is Ismark?", use_rag=False)
        assert response.message == "an answer"

    async def test_and_the_model_is_still_told_the_canon_covers_nothing(
        self, monkeypatch
    ):
        """The block must be present and EMPTY, not absent.

        Absent, the model has no canon instruction at all and answers the
        published adventure from its own memory -- which is the failure the
        whole path exists to prevent, appearing only when the database is down
        and only in production.
        """
        monkeypatch.setattr(
            "backend.agents.dm_agent.HybridRAGPipeline", lambda: SimpleNamespace()
        )
        agent = DMAgent(canon=FakeRetriever(boom=True))
        agent.openai = SimpleNamespace(
            chat=SimpleNamespace(completions=FakeCompletions())
        )
        await agent.process_message("Who is Ismark?", use_rag=False)
        assert BLOCK_MARK in system_text(agent)
        assert "nothing retrieved" in system_text(agent)


@pytest.mark.asyncio
class TestTheReportSaysWhichPathFoundWhat:
    """A result that anchored on a name also carries text passages, because
    `TEXT_SLOTS` reserves room for them. Reporting only the question-level
    `path` showed the lab "by name" over passages Lucene had found -- the same
    mislabelling already fixed in `canon_context.sources` and in the evaluation
    harness, which had credited a resolved name for answers a keyword match
    earned."""

    @staticmethod
    def _mixed() -> Retrieval:
        def passage(section_id: str, path: str) -> Passage:
            return Passage(
                section_id=section_id,
                chapter="the-village-of-barovia",
                chapter_index=4,
                section="S",
                section_index=5,
                text="prose",
                occurrences=1,
                entity_ids=(),
                path=path,
            )

        return Retrieval(
            question="q",
            passages=(
                passage("cos:x#1", PATH_GRAPH),
                passage("cos:x#2", PATH_GRAPH),
                passage("cos:x#3", PATH_TEXT),
            ),
            path=PATH_GRAPH,
        )

    async def _report(self, monkeypatch, retrieval: Retrieval) -> dict:
        monkeypatch.setattr(
            "backend.agents.dm_agent.HybridRAGPipeline", lambda: SimpleNamespace()
        )
        built = DMAgent(canon=FakeRetriever(retrieval))
        built.openai = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
        result = await built.process_message("q", use_rag=False, use_canon=True)
        return result.retrieval

    async def test_a_mixed_result_counts_each_path(self, monkeypatch):
        report = await self._report(monkeypatch, self._mixed())
        assert report["passages_by_path"] == {PATH_GRAPH: 2, PATH_TEXT: 1}

    async def test_the_question_level_path_is_still_reported(self, monkeypatch):
        """Both are wanted: how the QUESTION resolved, and what found each
        passage. They are different facts and the panel shows both."""
        report = await self._report(monkeypatch, self._mixed())
        assert report["path"] == PATH_GRAPH

    async def test_the_counts_add_up_to_the_passages_sent(self, monkeypatch):
        report = await self._report(monkeypatch, self._mixed())
        assert sum(report["passages_by_path"].values()) == report["passages"]

    async def test_a_wholly_text_result_credits_no_graph_passage(self, monkeypatch):
        text_only = replace(
            self._mixed(),
            passages=tuple(
                replace(p, path=PATH_TEXT) for p in self._mixed().passages
            ),
            path=PATH_TEXT,
        )
        report = await self._report(monkeypatch, text_only)
        assert report["passages_by_path"] == {PATH_GRAPH: 0, PATH_TEXT: 3}


class _Call:
    """One tool call, shaped as the OpenAI client returns it."""

    def __init__(self, name, arguments, call_id="c1"):
        self.id = call_id
        self.function = SimpleNamespace(name=name, arguments=arguments)


class ScriptedCompletions:
    """Returns each scripted response in turn, recording what it was sent."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    async def create(self, **kw):
        self.calls.append(kw)
        content, tool_calls = self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]
        return SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content=content, tool_calls=tool_calls)
            )],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=10),
        )


@pytest.mark.asyncio
class TestTheToolLoop:
    """A turn may reach into the graph before answering. What it finds goes
    into the subgraph; the transcript of finding it does not."""

    async def _agent(self, monkeypatch, completions):
        monkeypatch.setattr(
            "backend.agents.dm_agent.HybridRAGPipeline", lambda: SimpleNamespace()
        )
        built = DMAgent(canon=FakeRetriever(a_retrieval()))
        built.openai = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        return built

    async def test_a_turn_with_no_tool_calls_is_one_call(self, monkeypatch):
        """The common case must not have become more expensive."""
        completions = ScriptedCompletions(("an answer", None))
        agent = await self._agent(monkeypatch, completions)
        await agent.process_message("q", use_rag=False, use_canon=True)
        assert len(completions.calls) == 1

    async def test_a_tool_call_is_run_and_the_model_asked_again(self, monkeypatch):
        completions = ScriptedCompletions(
            (None, [_Call("resolve", '{"name": "Rictavio"}')]),
            ("an answer", None),
        )
        agent = await self._agent(monkeypatch, completions)
        result = await agent.process_message("q", use_rag=False, use_canon=True)
        assert result.message == "an answer"
        assert len(completions.calls) == 2

    async def test_usage_accumulates_across_the_rounds(self, monkeypatch):
        """Reporting only the final call would tell somebody a turn cost a
        fraction of what it did."""
        completions = ScriptedCompletions(
            (None, [_Call("resolve", '{"name": "Rictavio"}')]),
            ("an answer", None),
        )
        agent = await self._agent(monkeypatch, completions)
        result = await agent.process_message("q", use_rag=False, use_canon=True)
        assert result.usage["input"] == 200
        assert result.usage["output"] == 20

    async def test_the_tool_transcript_never_enters_the_conversation(self, monkeypatch):
        """THE WHOLE POINT. Forty edges fetched on turn three must not be
        re-sent on turn four, or forty."""
        completions = ScriptedCompletions(
            (None, [_Call("expand", '{"entity_id": "cos:rictavio"}')]),
            ("an answer", None),
        )
        agent = await self._agent(monkeypatch, completions)
        await agent.process_message("q", use_rag=False, use_canon=True)
        roles = [m["role"] for m in agent.conversation.get_context()]
        assert "tool" not in roles

    async def test_a_failing_tool_is_reported_back_rather_than_raised(self, monkeypatch):
        """A malformed argument is something the model can correct next round.
        Raising would fail the whole turn over a recoverable mistake."""
        completions = ScriptedCompletions(
            (None, [_Call("no_such_tool", "{}")]),
            ("an answer", None),
        )
        agent = await self._agent(monkeypatch, completions)
        result = await agent.process_message("q", use_rag=False, use_canon=True)
        assert result.message == "an answer"
        sent = completions.calls[-1]["messages"]
        assert any(m.get("role") == "tool" and "error" in m["content"] for m in sent)

    async def test_a_model_that_never_stops_asking_is_answered_anyway(self, monkeypatch):
        """Bounded: a model still asking after three rounds is not converging,
        and a DM mid-session gets a degraded answer rather than a hang."""
        completions = ScriptedCompletions(
            (None, [_Call("resolve", '{"name": "Rictavio"}')]),
        )
        agent = await self._agent(monkeypatch, completions)
        await agent.process_message("q", use_rag=False, use_canon=True)
        assert len(completions.calls) == 4  # three rounds, then one without tools

    async def test_the_final_call_offers_no_tools(self, monkeypatch):
        """Otherwise it would ask again and the cap would not be a cap."""
        completions = ScriptedCompletions(
            (None, [_Call("resolve", '{"name": "Rictavio"}')]),
        )
        agent = await self._agent(monkeypatch, completions)
        await agent.process_message("q", use_rag=False, use_canon=True)
        assert "tools" not in completions.calls[-1]


@pytest.mark.asyncio
class TestTheGraphVocabularyReachesTheModel:
    """Before this, nothing told the model what kinds of thing the graph holds.
    It read the schema off whatever instances a result happened to contain --
    `Strahd von Zarovich (LORE/MONSTER/NPC)` and one arrow -- from a sample it
    did not choose.

    Wiring again, not rendering: `test_canon/test_ontology.py` checks what the
    block says.
    """

    @staticmethod
    def _speaking(monkeypatch, found: Ontology) -> None:
        """Make the vocabulary deterministic and hit no database."""
        monkeypatch.setattr(
            "backend.agents.dm_agent.read_only_session", _no_session
        )
        monkeypatch.setattr(
            "backend.agents.dm_agent.ontology.read", lambda session, **kw: found
        )

    async def test_the_vocabulary_is_in_the_messages_sent(self, agent, monkeypatch):
        self._speaking(monkeypatch, Ontology(entity_types=("NPC",), guessed=("SERVES",)))
        await agent.process_message("Who is Ismark?", use_rag=False)
        assert "Entity types: NPC" in system_text(agent)
        assert "SERVES" in system_text(agent)

    async def test_it_comes_before_the_canon_block(self, agent, monkeypatch):
        """Static contract first, then the evidence. A vocabulary read after
        the passages is a vocabulary read after the model has already decided
        what the passages mean."""
        self._speaking(monkeypatch, Ontology(entity_types=("NPC",)))
        await agent.process_message("Who is Ismark?", use_rag=False)
        sent = agent.openai.chat.completions.messages
        vocabulary_at = next(
            i for i, m in enumerate(sent) if "Entity types:" in m["content"]
        )
        canon_at = next(i for i, m in enumerate(sent) if BLOCK_MARK in m["content"])
        assert vocabulary_at < canon_at

    async def test_it_is_sent_even_when_canon_is_off(self, agent, monkeypatch):
        """The tools are offered on every call, so the vocabulary describing
        them belongs on every call. A question that retrieved nothing is
        exactly when the model goes looking through them."""
        self._speaking(monkeypatch, Ontology(entity_types=("NPC",)))
        await agent.process_message("Who is Ismark?", use_rag=False, use_canon=False)
        assert "Entity types: NPC" in system_text(agent)

    async def test_an_unreadable_graph_omits_it_rather_than_failing_the_turn(
        self, agent, monkeypatch
    ):
        """Empty here, unlike the canon block, which must be present and say it
        covers nothing. Silence returns the model to reading the schema off
        instances -- degraded, but not misleading. An invented vocabulary would
        be misleading."""

        def boom(*_args, **_kw):
            raise RuntimeError("neo4j is down")

        monkeypatch.setattr("backend.agents.dm_agent.read_only_session", boom)
        response = await agent.process_message("Who is Ismark?", use_rag=False)
        assert response.message == "an answer"
        assert "Entity types:" not in system_text(agent)

    async def test_an_empty_graph_sends_no_block_at_all(self, agent, monkeypatch):
        self._speaking(monkeypatch, Ontology())
        await agent.process_message("Who is Ismark?", use_rag=False)
        assert "Entity types:" not in system_text(agent)
        # ...and the canon block is still where it was, rather than shifted by
        # an empty string inserted ahead of it.
        assert BLOCK_MARK in system_text(agent)


@pytest.mark.asyncio
class TestTheSentenceLayerIsForTheReaderOnly:
    """`CO_OCCURS_WITH` records that the book named two entities in one
    sentence, and `cooccurrence` is emphatic that inferring a relationship from
    that is a judgment this project has failed to automate four separate ways.

    So it travels to the PANEL and never into the prompt. 5,490 untyped "named
    together" pairs offered to a model as relationships would outnumber the 957
    typed ones six to one, and the model has no way to treat them differently
    from the typed ones it is also given.
    """

    TOGETHER = [{"source": "Alenka", "target": "Vistani", "sentences": 1}]

    @staticmethod
    def _speaking(agent, monkeypatch, rows) -> None:
        monkeypatch.setattr(
            type(agent), "_named_together", lambda self, view: rows
        )

    async def test_it_reaches_the_reader(self, agent, monkeypatch):
        self._speaking(agent, monkeypatch, self.TOGETHER)
        response = await agent.process_message("Who is Ismark?", use_rag=False)
        assert response.subgraph["together"] == self.TOGETHER

    async def test_it_does_NOT_reach_the_model(self, agent, monkeypatch):
        self._speaking(agent, monkeypatch, self.TOGETHER)
        await agent.process_message("Who is Ismark?", use_rag=False)
        sent = system_text(agent)
        # Neither endpoint is in the fixture's passage or the vocabulary, so
        # either name appearing means the layer leaked.
        assert "Alenka" not in sent
        assert "Vistani" not in sent

    async def test_a_graph_that_cannot_be_read_still_answers(self, agent, monkeypatch):
        def boom(*_args, **_kw):
            raise RuntimeError("neo4j is down")

        monkeypatch.setattr("backend.agents.dm_agent.read_only_session", boom)
        response = await agent.process_message("Who is Ismark?", use_rag=False)
        assert response.message == "an answer"
        assert response.subgraph["together"] == []


class TestTheRandomTableCommandsAreRetired:
    """`generate npc` must not steal the turn from the grounded path.

    THE TRAP THIS CLOSES. `_check_tool_commands` ran before retrieval, and two
    of its prefixes returned NPCs and encounters built by `random.choice` over
    hardcoded lists -- no model, no canon, no provenance split. So in one chat
    box "generate npc" got random tables and "make me an NPC for the tavern"
    got a grounded card with citations, the phrasing chose the engine, and the
    answer never said which had written it.
    """

    def _agent(self):
        from backend.agents.dm_agent import DMAgent

        return DMAgent.__new__(DMAgent)

    @pytest.mark.parametrize(
        "typed",
        [
            "generate npc",
            "create npc merchant",
            "/npc",
            "generate encounter",
            "create encounter",
            "/encounter",
        ],
    )
    def test_a_generation_phrase_no_longer_short_circuits(self, typed):
        from backend.agents.dm_agent import DMAgent

        assert DMAgent._check_tool_commands(self._agent(), typed) is None

    def test_the_dice_command_still_works(self):
        """Retiring the generators must not take the dice roller with them: it
        invents nothing and claims nothing about the book."""
        from backend.agents.dm_agent import DMAgent
        from backend.agents.tools import DMTools

        agent = self._agent()
        agent.tools = DMTools()
        found = DMAgent._check_tool_commands(agent, "/roll 1d20")
        assert found is not None and found["type"] == "dice"

    def test_the_agent_offers_no_random_table_generator(self):
        """`agent.generate_npc()` returned random tables while
        `generator.generate(kind='npc')` returned a grounded card. One name,
        two engines, is the same trap one level in."""
        from backend.agents.dm_agent import DMAgent

        assert not hasattr(DMAgent, "generate_npc")
        assert not hasattr(DMAgent, "generate_encounter")
