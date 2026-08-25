"""The lab endpoints: knobs in, cost and provenance out."""

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.agents import canon_context
from backend.api.routes import lab
from backend.canon.retrieval import PATH_GRAPH, Anchor, Passage, Retrieval


def a_retrieval() -> Retrieval:
    return Retrieval(
        question="q",
        # A graph-path retrieval with no anchors is impossible -- the path IS
        # "a name resolved" -- and the fixture said so for a while, which meant
        # nothing seeded the subgraph from it.
        anchors=(
            Anchor(
                entity_id="cos:blood-of-the-vine-tavern",
                name="Blood of the Vine Tavern",
                labels=("LOCATION",),
                rung="SITE",
                surface="tavern",
            ),
        ),
        passages=(
            Passage(
                section_id="cos:the-village-of-barovia#5",
                chapter="the-village-of-barovia",
                chapter_index=4,
                section="E2. Blood of the Vine Tavern",
                section_index=5,
                text="A blazing fire gives scant warmth.",
                occurrences=2,
                entity_ids=("cos:blood-of-the-vine-tavern",),
            ),
        ),
        proposed=({"entity": "Arik", "relationship": "SEEKS",
                   "other": "Ireena", "direction": "out"},),
        path=PATH_GRAPH,
    )


class FakeCompletions:
    def __init__(self, content):
        self.content = content
        self.calls = []

    async def create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))],
            usage=SimpleNamespace(prompt_tokens=1000, completion_tokens=100),
        )


GENERATED = json.dumps(
    {"title": "T", "body": "B", "from_canon": [{"claim": "c", "cite": "[1]"}],
     "invented": ["i"]}
)


@pytest.fixture
def client(monkeypatch):
    """A lab whose graph and model are both fakes."""
    lab._SESSIONS.clear()

    monkeypatch.setattr(
        "backend.agents.dm_agent.HybridRAGPipeline", lambda: SimpleNamespace()
    )
    fake_retriever = lambda **kw: SimpleNamespace(  # noqa: E731
        book=kw.get("book", "cos"),
        campaign=kw.get("campaign"),
        retrieve=lambda q, **k: a_retrieval(),
    )
    monkeypatch.setattr("backend.agents.dm_agent.CanonRetriever", fake_retriever)
    monkeypatch.setattr("backend.api.routes.lab.CanonRetriever", fake_retriever)

    completions = FakeCompletions("an answer")
    real_init = lab.DMAgent.__init__

    def patched(self, *a, **kw):
        real_init(self, *a, **kw)
        self.openai = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    monkeypatch.setattr(lab.DMAgent, "__init__", patched)

    from backend.api.main import app

    test_client = TestClient(app)
    test_client.completions = completions
    return test_client


class TestConfig:
    def test_it_lists_models_with_their_rates_and_their_age(self, client):
        body = client.get("/api/lab/config").json()
        assert body["models"]
        assert {"id", "label", "input_per_1m", "last_verified"} <= set(body["models"][0])

    def test_it_offers_the_generation_kinds(self, client):
        assert set(client.get("/api/lab/config").json()["kinds"]) == {
            "quest", "npc", "monster", "scene"
        }


class TestChat:
    def test_an_answer_comes_back_with_its_cost_and_its_retrieval(self, client):
        body = client.post(
            "/api/lab/chat", json={"message": "Who drinks here?", "model": "gpt-4o-mini"}
        ).json()
        assert body["message"] == "an answer"
        assert body["usage"] == {"input": 1000, "output": 100, "total": 1100}
        assert body["cost"]["model"] == "gpt-4o-mini"
        assert body["retrieval"]["path"] == "graph"

    def test_the_chosen_model_is_the_one_called(self, client):
        client.post("/api/lab/chat", json={"message": "hi", "model": "gpt-4o"})
        assert client.completions.calls[-1]["model"] == "gpt-4o"

    def test_withholding_proposed_edges_keeps_them_out_of_the_prompt(self, client):
        client.post(
            "/api/lab/chat",
            json={"message": "hi", "depth": {"include_proposed": False}},
        )
        sent = "\n".join(
            m["content"] for m in client.completions.calls[-1]["messages"]
            if m["role"] == "system"
        )
        assert "Arik -SEEKS-> Ireena" not in sent

    def test_but_the_report_still_says_they_existed(self, client):
        """Withheld is not the same as absent. A reader must see that one
        proposed edge was held back, not that there were none."""
        body = client.post(
            "/api/lab/chat",
            json={"message": "hi", "depth": {"include_proposed": False}},
        ).json()
        assert body["retrieval"]["proposed_edges"] == 1
        assert body["retrieval"]["proposed_withheld"] is True

    def test_an_absurd_passage_count_is_refused_rather_than_charged_for(self, client):
        """An unbounded value from a browser is a way to spend real money by
        typing a big number."""
        response = client.post(
            "/api/lab/chat", json={"message": "hi", "depth": {"passages": 5000}}
        )
        assert response.status_code == 422

    def test_the_thread_survives_a_model_switch(self, client):
        """The one comparison this lab exists for: same conversation, different
        model.

        Asserted on the SUBGRAPH rather than on the transcript. The transcript
        is now bounded to the current question -- it is no longer the memory --
        so what has to survive a rebuilt agent is what the conversation is
        about, as entities. This used to look for the literal word "first" in
        the messages, which stopped being the mechanism rather than stopping
        being important."""
        client.post("/api/lab/chat", json={"message": "first", "model": "gpt-4o-mini"})
        before = dict(lab._SESSIONS["lab"].subgraph.nodes)
        client.post("/api/lab/chat", json={"message": "second", "model": "gpt-4o"})
        after = lab._SESSIONS["lab"].subgraph

        assert before, "the fixture retrieval must anchor something to test this"
        assert set(before) <= set(after.nodes)

    def test_the_chosen_book_reaches_the_retriever(self, client):
        """The whole point of the selector: a session reads the book it names."""
        client.post("/api/lab/chat", json={"message": "hi", "book": "kftgv"})
        assert lab._SESSIONS["lab"].canon.book == "kftgv"

    def test_switching_book_drops_the_thread(self, client):
        """The OPPOSITE of the model switch above, and deliberately so.

        A subgraph holds entities by id, so carrying it across a book change
        would put Barovia in front of a heist -- the cross-book bleed that
        scoping the retriever exists to stop, re-entering through the
        conversation's own memory."""
        client.post("/api/lab/chat", json={"message": "first", "book": "cos"})
        assert lab._SESSIONS["lab"].subgraph.nodes, "fixture must anchor something"

        client.post("/api/lab/chat", json={"message": "second", "book": "kftgv"})
        assert lab._SESSIONS["lab"].subgraph.turn == 1

    def test_reset_drops_the_thread(self, client):
        """Reset has to clear the subgraph too, or a "new" conversation starts
        holding the last one's entities."""
        client.post("/api/lab/chat", json={"message": "first"})
        client.post("/api/lab/reset", params={"session_id": "lab"})
        client.post("/api/lab/chat", json={"message": "second"})
        assert lab._SESSIONS["lab"].subgraph.turn == 1


class TestGenerate:
    def test_it_returns_the_canon_invention_split(self, client):
        client.completions.content = GENERATED
        body = client.post(
            "/api/lab/generate", json={"kind": "npc", "subject": "a barkeep"}
        ).json()
        assert body["from_canon"] == [{"claim": "c", "cite": "[1]"}]
        assert body["invented"] == ["i"]

    def test_it_reports_cost_like_chat_does(self, client):
        client.completions.content = GENERATED
        body = client.post(
            "/api/lab/generate",
            json={"kind": "quest", "subject": "x", "model": "gpt-4o"},
        ).json()
        assert body["usage"]["total"] == 1100
        assert body["cost"]["model"] == "gpt-4o"

    def test_an_unknown_kind_is_refused(self, client):
        response = client.post(
            "/api/lab/generate", json={"kind": "haiku", "subject": "x"}
        )
        assert response.status_code == 422

    def test_generation_never_inherits_a_chat_sessions_history(self, client):
        """Two identical generate requests must not differ because of something
        said in the chat pane."""
        client.post("/api/lab/chat", json={"message": "remember the barkeep"})
        client.completions.content = GENERATED
        client.post("/api/lab/generate", json={"kind": "npc", "subject": "x"})
        sent = [m["content"] for m in client.completions.calls[-1]["messages"]]
        assert not any("remember the barkeep" in c for c in sent)


class TestTheCampaignScopesTheSession:
    """A campaign is a world, and switching one is switching worlds."""

    def test_the_chosen_campaign_reaches_the_retriever(self, client):
        client.post("/api/lab/chat", json={"message": "hi", "campaign": "p13-home"})
        assert lab._SESSIONS["lab"].canon.campaign == "p13-home"

    def test_none_is_the_default(self):
        """The same default the evaluation harnesses use: canon only."""
        assert lab.ChatRequest(message="x").campaign is None

    def test_switching_campaign_drops_the_thread(self, client):
        """The book rule, one scope in: a subgraph holds entities by id, so
        carrying one table's scenes into another table's session is the same
        bleed the plane and prefix filters exist to stop."""
        client.post("/api/lab/chat", json={"message": "first", "campaign": "table-a"})
        assert lab._SESSIONS["lab"].subgraph.nodes, "fixture must anchor something"
        client.post("/api/lab/chat", json={"message": "second", "campaign": "table-b"})
        assert lab._SESSIONS["lab"].subgraph.turn == 1

    def test_the_thread_survives_a_model_switch_within_one_campaign(self, client):
        """The comparison the lab exists for still works."""
        client.post(
            "/api/lab/chat",
            json={"message": "first", "campaign": "table-a", "model": "gpt-4o-mini"},
        )
        before = dict(lab._SESSIONS["lab"].subgraph.nodes)
        client.post(
            "/api/lab/chat",
            json={"message": "second", "campaign": "table-a", "model": "gpt-4o"},
        )
        assert set(before) <= set(lab._SESSIONS["lab"].subgraph.nodes)


class TestDraftCardsReachTheReader:
    """A card the model asked for must survive the route.

    THE DEFECT THIS PINS. The chat route builds an explicit dict rather than
    dumping the response, so a field it does not name is dropped in silence.
    Draft cards were generated, charged for, and discarded here; the model
    politely told the DM a draft was ready and the DM was shown nothing.
    """

    def test_the_route_carries_generations(self, client, monkeypatch):
        card = {"kind": "scene", "title": "A Storm", "body": "...",
                "from_canon": [], "invented": ["the storm"], "from_context": []}

        async def fake(self, *a, **kw):
            from backend.agents.dm_agent import DMResponse

            return DMResponse(message="a draft is ready", generations=[card])

        monkeypatch.setattr(lab.DMAgent, "process_message", fake)
        body = client.post("/api/lab/chat", json={"message": "make a scene"}).json()
        assert body["generations"] == [card]

    def test_it_is_present_and_empty_on_an_ordinary_turn(self):
        """Absent and empty are different answers; the field is always sent."""
        from backend.agents.dm_agent import DMResponse

        assert DMResponse(message="hello").generations == []
