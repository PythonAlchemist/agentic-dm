"""Extract candidate entities and relationships, one layer at a time.

Three focused passes per unit beat one general pass: a prompt that knows only
about containment produces cleaner spatial output than one asked to find
everything at once, and when a layer extracts badly it is diagnosable on its own.

Candidates are keyed by NAME. Minting deterministic ids and collapsing an entity
across chapters is stage 2b's job; doing it here would entangle the tuning loop
with dedup logic it would have to be correct about first.
"""

import asyncio
import json
import logging

from openai import AsyncOpenAI

from backend.canon.models import CandidateEdge, CandidateNode, ExtractionUnit
from backend.core.config import settings
from backend.graph.schema import CANON_ENTITY_TYPES, LAYER_MAP, EntityType, Layer

logger = logging.getLogger(__name__)

EXTRACTION_MODEL = "gpt-4o-mini"

_LAYER_GUIDANCE = {
    Layer.SPATIAL: (
        "Physical arrangement only: what contains what, what connects to what, "
        "and where a character or object is located."
    ),
    Layer.SOCIAL: (
        "Relationships between people and factions: who knows, serves, guards, "
        "owns, allies with, or is hostile to whom."
    ),
    Layer.NARRATIVE: (
        "Plot machinery: what an agent WANTS (SEEKS, with the reason in "
        "`evidence`), what it works against (OPPOSES), hidden identities "
        "(IDENTITY_OF), quest structure, and standing threats."
    ),
}


def layer_vocabulary(layer: Layer) -> list[str]:
    """The relationship types belonging to a layer, from LAYER_MAP.

    Derived rather than listed, so adding a relationship type cannot leave the
    extractor silently unaware of it.
    """
    return sorted(r.value for r, mapped in LAYER_MAP.items() if mapped is layer)


def _prompt(unit: ExtractionUnit, layer: Layer) -> str:
    vocab = layer_vocabulary(layer)
    entity_types = sorted(t.value for t in EntityType)
    return f"""\
Extract {layer.value}-layer canon from this passage of a D&D sourcebook.

{_LAYER_GUIDANCE[layer]}

Use ONLY these relationship types: {", ".join(vocab)}
Use ONLY these entity types: {", ".join(entity_types)}

Rules:
- Extract only what the passage states. Do not infer from outside knowledge.
- Name entities as the passage names them. Do not invent ids.
- An entity worth extracting is one another passage could refer to. Skip scenery.
- If the passage states nothing for this layer, return empty lists. That is a
  valid and common answer.

Return JSON:
{{"nodes": [{{"name": ..., "entity_type": ..., "description": ...}}],
  "edges": [{{"source_name": ..., "target_name": ..., "rel_type": ..., "evidence": ...}}]}}

Chapter: {unit.chapter_title}
Section: {unit.heading}

---
{unit.markdown}
"""


class CandidateExtractor:
    """Runs the per-layer passes. Never raises: a bad unit yields nothing."""

    def __init__(
        self,
        client: AsyncOpenAI | None = None,
        model: str | None = None,
        concurrency: int = 6,
    ):
        self.client = client or AsyncOpenAI(api_key=settings.openai_api_key)
        self.model = model or EXTRACTION_MODEL
        self._semaphore = asyncio.Semaphore(concurrency)
        # Nodes dropped by the entity_type filter in `_parse` -- see section 1
        # of the task-9 brief. Surfaced by the CLI, never dropped silently.
        self.rejected_entity_types = 0

    async def extract_unit(
        self,
        unit: ExtractionUnit,
        layer: Layer,
    ) -> tuple[list[CandidateNode], list[CandidateEdge], bool]:
        """Returns `(nodes, edges, failed)`.

        `failed` is True when the API call raised or the response could not
        be parsed. An empty `(nodes, edges)` is ambiguous on its own -- it is
        the same shape whether the passage legitimately said nothing for this
        layer, or the call hard-failed (a 401, a rate limit). The caller must
        be able to tell those apart, so this never raises but always reports.
        """
        try:
            async with self._semaphore:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": _prompt(unit, layer)}],
                    response_format={"type": "json_object"},
                )
            payload = json.loads(response.choices[0].message.content or "{}")
        except Exception as exc:  # one unit must not abort a chapter
            logger.warning(
                "extraction failed for %s / %s: %s", unit.chapter_slug, layer.value, exc
            )
            return [], [], True

        nodes, edges = self._parse(payload, unit, layer)
        return nodes, edges, False

    async def extract_units(
        self,
        units: list[ExtractionUnit],
        layers: list[Layer] | None = None,
    ) -> tuple[list[CandidateNode], list[CandidateEdge], int]:
        """Returns `(nodes, edges, failed_count)`.

        `failed_count` is how many of the `len(units) * len(wanted)` calls
        failed -- see `extract_unit`. A caller that ignores this cannot tell
        a quiet chapter from a chapter that failed to extract at all.
        """
        wanted = layers or list(Layer)
        results = await asyncio.gather(
            *(self.extract_unit(u, layer) for u in units for layer in wanted),
            return_exceptions=True,
        )

        nodes: list[CandidateNode] = []
        edges: list[CandidateEdge] = []
        failed = 0
        for result in results:
            if isinstance(result, BaseException):
                logger.warning("extraction task failed: %s", result)
                failed += 1
                continue
            unit_nodes, unit_edges, unit_failed = result
            nodes.extend(unit_nodes)
            edges.extend(unit_edges)
            if unit_failed:
                failed += 1
        return nodes, edges, failed

    def _parse(
        self,
        payload: dict,
        unit: ExtractionUnit,
        layer: Layer,
    ) -> tuple[list[CandidateNode], list[CandidateEdge]]:
        allowed_rel_types = set(layer_vocabulary(layer))
        allowed_entity_types = {t.value for t in CANON_ENTITY_TYPES}
        heading = unit.heading

        raw_nodes = [n for n in payload.get("nodes", []) if str(n.get("name", "")).strip()]
        nodes = [
            CandidateNode(
                name=str(n.get("name", "")).strip(),
                entity_type=str(n.get("entity_type", "")).strip(),
                description=str(n.get("description", "") or ""),
                layer=layer.value,
                chapter_slug=unit.chapter_slug,
                section_heading=heading,
                section_index=unit.section_index,
            )
            for n in raw_nodes
            # A model that ignores its offered types must not smuggle in a
            # campaign-runtime or mechanical one -- mirrors the edge filter below.
            if str(n.get("entity_type", "")).strip() in allowed_entity_types
        ]
        self.rejected_entity_types += len(raw_nodes) - len(nodes)

        edges = [
            CandidateEdge(
                source_name=str(e.get("source_name", "")).strip(),
                target_name=str(e.get("target_name", "")).strip(),
                rel_type=str(e.get("rel_type", "")).strip(),
                evidence=str(e.get("evidence", "") or ""),
                layer=layer.value,
                chapter_slug=unit.chapter_slug,
                section_heading=heading,
                section_index=unit.section_index,
            )
            for e in payload.get("edges", [])
            # A model that ignores its vocabulary must not smuggle another layer in.
            if str(e.get("rel_type", "")).strip() in allowed_rel_types
            and str(e.get("source_name", "")).strip()
            and str(e.get("target_name", "")).strip()
        ]

        return nodes, edges
