"""Per-layer candidate extraction.

Each pass sees only its own layer's vocabulary. A spatial pass that knows only
about containment produces markedly cleaner output than one prompt asked to find
everything, and it makes a bad layer diagnosable in isolation.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.canon.extract import CandidateExtractor, anchor_quests, layer_vocabulary
from backend.canon.models import CandidateEdge, CandidateNode, ExtractionUnit
from backend.graph.schema import RELATIONSHIP_GLOSS, Layer, RelationshipType


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


class TestRelationshipGloss:
    def test_every_layer_type_has_a_gloss(self):
        """A relationship type added to a layer must fail this until it is
        glossed -- iterates the layers and layer_vocabulary rather than a
        hardcoded count, so this stays true as LAYER_MAP grows."""
        for layer in Layer:
            for value in layer_vocabulary(layer):
                assert RelationshipType(value) in RELATIONSHIP_GLOSS, (
                    f"{value} ({layer.value}) has no entry in RELATIONSHIP_GLOSS"
                )


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
    async def test_nodes_with_an_unknown_entity_type_are_dropped(self):
        """Mirrors test_edges_of_the_wrong_layer_are_dropped: a model that
        ignores the offered entity types (measured on chapter 3: 3 nodes
        typed ROOM, which is not a member of CANON_ENTITY_TYPES) must not
        smuggle a campaign-runtime or mechanical type into canon."""
        client = make_client(
            {"nodes": [{"name": "Cellar", "entity_type": "ROOM"}], "edges": []}
        )
        extractor = CandidateExtractor(client=client)
        nodes, _, failed = await extractor.extract_unit(unit(), Layer.SPATIAL)

        assert nodes == []
        assert failed is False, (
            "a clean response with an off-vocabulary entity_type is not a failure"
        )
        assert extractor.rejected_entity_types == 1

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


def cand_node(name: str, entity_type: str = "NPC") -> CandidateNode:
    return CandidateNode(name=name, entity_type=entity_type)


def cand_edge(source: str, target: str, rel_type: str) -> CandidateEdge:
    return CandidateEdge(source_name=source, target_name=target, rel_type=rel_type)


class TestAnchorQuests:
    """See task-9 brief section 4b: a coined quest name is the one candidate
    the source text never states literally, so a QUEST node only survives
    when some other extracted entity points at it via an ANCHORING_TYPES edge."""

    def test_quest_with_gave_quest_edge_from_extracted_npc_survives(self):
        nodes = [cand_node("Ismark", "NPC"), cand_node("Escort Ireena to Vallaki", "QUEST")]
        edges = [cand_edge("Ismark", "Escort Ireena to Vallaki", "GAVE_QUEST")]

        surviving_nodes, surviving_edges, dropped = anchor_quests(nodes, edges)

        assert surviving_nodes == nodes
        assert surviving_edges == edges
        assert dropped == 0

    def test_orphan_quest_is_dropped_along_with_its_edges(self):
        """The quest has an edge, but its other endpoint ("Undercroft") was
        never itself extracted as a candidate node, so it does not anchor."""
        ismark = cand_node("Ismark", "NPC")
        nodes = [ismark, cand_node("Free Doru from the undercroft", "QUEST")]
        edges = [cand_edge("Free Doru from the undercroft", "Undercroft", "OBJECTIVE_AT")]

        surviving_nodes, surviving_edges, dropped = anchor_quests(nodes, edges)

        assert surviving_nodes == [ismark]
        assert surviving_edges == []
        assert dropped == 1

    def test_quest_anchored_only_by_another_quest_is_dropped(self):
        nodes = [
            cand_node("Escort Ireena to Vallaki", "QUEST"),
            cand_node("Free Doru from the undercroft", "QUEST"),
        ]
        edges = [
            cand_edge(
                "Escort Ireena to Vallaki", "Free Doru from the undercroft", "SEEKS"
            )
        ]

        surviving_nodes, surviving_edges, dropped = anchor_quests(nodes, edges)

        assert surviving_nodes == []
        assert surviving_edges == []
        assert dropped == 2

    def test_non_quest_node_is_never_touched(self):
        nodes = [cand_node("Bildrath", "NPC")]
        edges = [cand_edge("Bildrath", "Bildrath's Mercantile", "OWNS")]

        surviving_nodes, surviving_edges, dropped = anchor_quests(nodes, edges)

        assert surviving_nodes == nodes
        assert surviving_edges == edges
        assert dropped == 0
