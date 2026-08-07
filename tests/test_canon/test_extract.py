"""Per-layer candidate extraction.

Each pass sees only its own layer's vocabulary. A spatial pass that knows only
about containment produces markedly cleaner output than one prompt asked to find
everything, and it makes a bad layer diagnosable in isolation.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.canon.extract import CandidateExtractor, layer_vocabulary
from backend.canon.models import ExtractionUnit
from backend.graph.schema import Layer


def unit(markdown: str = "## E1\n\nBildrath sells overpriced rope.") -> ExtractionUnit:
    return ExtractionUnit(
        chapter_slug="chapter-3-the-village-of-barovia",
        chapter_title="Chapter 3: The Village of Barovia",
        headings=["E1"],
        markdown=markdown,
        token_count=12,
    )


def make_client(payload: dict) -> MagicMock:
    message = MagicMock()
    message.content = json.dumps(payload)
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=response)
    return client


class TestLayerVocabulary:
    def test_derives_from_layer_map_not_a_literal(self):
        """Adding a relationship type must not silently leave the extractor blind."""
        spatial = layer_vocabulary(Layer.SPATIAL)

        assert set(spatial) == {"CONNECTED_TO", "CONTAINS", "LOCATED_IN", "TRAVELED_TO"}

    def test_narrative_includes_the_new_types(self):
        narrative = layer_vocabulary(Layer.NARRATIVE)

        for expected in ("SEEKS", "OPPOSES", "IDENTITY_OF", "RESOLVES_TO"):
            assert expected in narrative

    def test_layers_do_not_overlap(self):
        vocabs = [set(layer_vocabulary(layer)) for layer in Layer]

        assert not vocabs[0] & vocabs[1]
        assert not vocabs[1] & vocabs[2]
        assert not vocabs[0] & vocabs[2]


class TestExtractUnit:
    @pytest.mark.asyncio
    async def test_parses_nodes_and_edges(self):
        client = make_client(
            {
                "nodes": [{"name": "Bildrath", "entity_type": "NPC",
                           "description": "The shopkeeper."}],
                "edges": [{"source_name": "Bildrath", "target_name": "E1",
                           "rel_type": "OWNS", "evidence": "sells rope"}],
            }
        )
        nodes, edges = await CandidateExtractor(client=client).extract_unit(
            unit(), Layer.SOCIAL
        )

        assert nodes[0].name == "Bildrath"
        assert edges[0].rel_type == "OWNS"

    @pytest.mark.asyncio
    async def test_stamps_provenance_on_every_candidate(self):
        client = make_client(
            {
                "nodes": [{"name": "Bildrath", "entity_type": "NPC"}],
                "edges": [{"source_name": "Bildrath", "target_name": "E1",
                           "rel_type": "OWNS"}],
            }
        )
        nodes, edges = await CandidateExtractor(client=client).extract_unit(
            unit(), Layer.SOCIAL
        )

        assert nodes[0].chapter_slug == "chapter-3-the-village-of-barovia"
        assert nodes[0].section_heading == "E1"
        assert nodes[0].layer == "social"
        assert edges[0].layer == "social"

    @pytest.mark.asyncio
    async def test_prompt_carries_only_its_own_layer_vocabulary(self):
        client = make_client({"nodes": [], "edges": []})
        await CandidateExtractor(client=client).extract_unit(unit(), Layer.SPATIAL)

        prompt = json.dumps(client.chat.completions.create.call_args.kwargs["messages"])
        assert "CONTAINS" in prompt
        assert "SEEKS" not in prompt, "a spatial pass must not see narrative types"

    @pytest.mark.asyncio
    async def test_edges_of_the_wrong_layer_are_dropped(self):
        """A model that ignores its vocabulary must not smuggle in another layer."""
        client = make_client(
            {"nodes": [], "edges": [{"source_name": "A", "target_name": "B",
                                     "rel_type": "SEEKS"}]}
        )
        _, edges = await CandidateExtractor(client=client).extract_unit(
            unit(), Layer.SPATIAL
        )

        assert edges == []

    @pytest.mark.asyncio
    async def test_malformed_json_yields_nothing_and_does_not_raise(self):
        message = MagicMock()
        message.content = "not json at all"
        choice = MagicMock()
        choice.message = message
        response = MagicMock()
        response.choices = [choice]
        client = MagicMock()
        client.chat.completions.create = AsyncMock(return_value=response)

        nodes, edges = await CandidateExtractor(client=client).extract_unit(
            unit(), Layer.SOCIAL
        )

        assert nodes == []
        assert edges == []

    @pytest.mark.asyncio
    async def test_api_failure_yields_nothing_and_does_not_raise(self):
        """One bad unit must not abort a chapter."""
        client = MagicMock()
        client.chat.completions.create = AsyncMock(side_effect=RuntimeError("boom"))

        nodes, edges = await CandidateExtractor(client=client).extract_unit(
            unit(), Layer.SOCIAL
        )

        assert nodes == []
        assert edges == []


class TestExtractUnits:
    @pytest.mark.asyncio
    async def test_runs_every_layer_over_every_unit(self):
        client = make_client({"nodes": [], "edges": []})
        await CandidateExtractor(client=client).extract_units([unit(), unit()])

        assert client.chat.completions.create.await_count == 6  # 2 units x 3 layers


class TestPerSectionProvenance:
    @pytest.mark.asyncio
    async def test_candidates_carry_the_units_own_heading(self):
        """A unit spans one section, so its heading is unambiguous."""
        client = make_client(
            {"nodes": [{"name": "Donavich", "entity_type": "NPC"}], "edges": []}
        )
        one_section = ExtractionUnit(
            chapter_slug="chapter-3-the-village-of-barovia",
            chapter_title="Chapter 3: The Village of Barovia",
            headings=["E5. Church"],
            markdown="## E5. Church\n\nDonavich prays here.",
            token_count=9,
        )
        nodes, _ = await CandidateExtractor(client=client).extract_unit(
            one_section, Layer.SOCIAL
        )

        assert nodes[0].section_heading == "E5. Church"
