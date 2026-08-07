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
        heading="E1",
        section_index=0,
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
        nodes, edges, failed = await CandidateExtractor(client=client).extract_unit(
            unit(), Layer.SOCIAL
        )

        assert nodes[0].name == "Bildrath"
        assert edges[0].rel_type == "OWNS"
        assert failed is False

    @pytest.mark.asyncio
    async def test_stamps_provenance_on_every_candidate(self):
        client = make_client(
            {
                "nodes": [{"name": "Bildrath", "entity_type": "NPC"}],
                "edges": [{"source_name": "Bildrath", "target_name": "E1",
                           "rel_type": "OWNS"}],
            }
        )
        nodes, edges, _ = await CandidateExtractor(client=client).extract_unit(
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
        _, edges, failed = await CandidateExtractor(client=client).extract_unit(
            unit(), Layer.SPATIAL
        )

        assert edges == []
        assert failed is False, "a clean response with an off-vocabulary edge is not a failure"

    @pytest.mark.asyncio
    async def test_malformed_json_yields_nothing_and_is_a_failure(self):
        """A response the extractor cannot parse must not be indistinguishable
        from "the passage legitimately said nothing" -- the caller needs to
        know this unit's empty result is not trustworthy."""
        message = MagicMock()
        message.content = "not json at all"
        choice = MagicMock()
        choice.message = message
        response = MagicMock()
        response.choices = [choice]
        client = MagicMock()
        client.chat.completions.create = AsyncMock(return_value=response)

        nodes, edges, failed = await CandidateExtractor(client=client).extract_unit(
            unit(), Layer.SOCIAL
        )

        assert nodes == []
        assert edges == []
        assert failed is True

    @pytest.mark.asyncio
    async def test_api_failure_yields_nothing_and_is_a_failure(self):
        """One bad unit must not abort a chapter, but it must be counted --
        27 hard 401s printing "0 nodes, 0 edges" with no signal is exactly
        the defect this return value exists to prevent."""
        client = MagicMock()
        client.chat.completions.create = AsyncMock(side_effect=RuntimeError("boom"))

        nodes, edges, failed = await CandidateExtractor(client=client).extract_unit(
            unit(), Layer.SOCIAL
        )

        assert nodes == []
        assert edges == []
        assert failed is True


class TestExtractUnits:
    @pytest.mark.asyncio
    async def test_runs_every_layer_over_every_unit(self):
        client = make_client({"nodes": [], "edges": []})
        await CandidateExtractor(client=client).extract_units([unit(), unit()])

        assert client.chat.completions.create.await_count == 6  # 2 units x 3 layers

    @pytest.mark.asyncio
    async def test_no_failures_when_every_call_succeeds(self):
        client = make_client({"nodes": [], "edges": []})
        _, _, failed = await CandidateExtractor(client=client).extract_units([unit()])

        assert failed == 0

    @pytest.mark.asyncio
    async def test_counts_failures_across_units_and_layers(self):
        """A caller must be able to tell a failed run from a quiet one -- this
        is the count the CLI prints as "N of M extraction calls failed"."""
        client = MagicMock()
        client.chat.completions.create = AsyncMock(side_effect=RuntimeError("boom"))

        nodes, edges, failed = await CandidateExtractor(client=client).extract_units(
            [unit(), unit()]
        )

        assert nodes == []
        assert edges == []
        assert failed == 6  # 2 units x 3 layers, all failing


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
            heading="E5. Church",
            section_index=4,
            markdown="## E5. Church\n\nDonavich prays here.",
            token_count=9,
        )
        nodes, _, _ = await CandidateExtractor(client=client).extract_unit(
            one_section, Layer.SOCIAL
        )

        assert nodes[0].section_heading == "E5. Church"
        assert nodes[0].section_index == 4
