"""That the canon block actually reaches the model.

Rendering is tested next door; this tests the WIRING, which is the part that
silently does nothing when it is wrong. The pipeline beside this one has been
inserting a list of source names for months and looked, from the outside,
exactly like grounding.

Both the graph and the model are fakes. What is asserted is the messages the
agent would send.
"""

from types import SimpleNamespace

import pytest

from backend.agents.dm_agent import DMAgent
from backend.canon.retrieval import PATH_GRAPH, Passage, Retrieval

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
