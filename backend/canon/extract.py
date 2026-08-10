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
from backend.graph.schema import (
    CANON_ENTITY_TYPES,
    LAYER_MAP,
    RELATIONSHIP_GLOSS,
    Layer,
    RelationshipType,
)

logger = logging.getLogger(__name__)

EXTRACTION_MODEL = "gpt-4o-mini"

# Fixed to remove "sampled at the API's default temperature 1.0" as a source of
# run-to-run recall swing. It does NOT make the graded path stable: measured at
# temperature 0 with this seed, unique-edge Jaccard between two runs is 0.49
# while reported recall is identical. Pinning removed the recall swing, not the
# underlying instability -- recall is simply blind to a ~50% churn in which edges
# a run produces. Do not read a repeated number as a reproduced edge set; stage
# 2b should consume multi-sample consensus rather than one run. A future bulk
# mode may want to vary temperature deliberately; the graded path must not.
EXTRACTION_SEED = 20260806

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

# Quests are never named as nouns in the prose -- the book says "Ismark asks for
# their aid in escorting Ireena to Vallaki", never "Escort Ireena to Vallaki". The
# model must coin the name, which is the highest fabrication risk in this pipeline,
# so this guidance is narrative-only and paired with `anchor_quests` below, which
# mechanically discards any coined quest nothing else in the chapter points at.
_NARRATIVE_EXTRA = """
Emit a QUEST node when a section describes a task the party is asked to undertake
or an objective the adventure sets. Name it as a short imperative verb phrase
("Escort Ireena to Vallaki", "Free Doru from the undercroft"). Link every QUEST
you emit with GAVE_QUEST from whoever asks it, and/or OBJECTIVE_AT to where it
is pursued.

Worked contrast -- these two are easy to invert:
"Ireena carries the soul of Tatyana" is IDENTITY_OF (one being, two lives).
"Doru is Donavich's son" is RELATED_TO (two beings, one family).
"""


def layer_vocabulary(layer: Layer) -> list[str]:
    """The relationship types belonging to a layer, from LAYER_MAP.

    Derived rather than listed, so adding a relationship type cannot leave the
    extractor silently unaware of it.
    """
    return sorted(r.value for r, mapped in LAYER_MAP.items() if mapped is layer)


def _prompt(unit: ExtractionUnit, layer: Layer) -> str:
    vocab = layer_vocabulary(layer)
    glosses = "\n".join(
        f"- {RELATIONSHIP_GLOSS[RelationshipType(v)]}" for v in vocab
    )
    entity_types = sorted(t.value for t in CANON_ENTITY_TYPES)
    extra = _NARRATIVE_EXTRA if layer is Layer.NARRATIVE else ""
    return f"""\
Extract {layer.value}-layer canon from this passage of a D&D sourcebook.

{_LAYER_GUIDANCE[layer]}

Use ONLY these relationship types:
{glosses}

Use ONLY these entity types: {", ".join(entity_types)}
{extra}
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
        temperature: float = 0.0,
    ):
        self.client = client or AsyncOpenAI(api_key=settings.openai_api_key)
        self.model = model or EXTRACTION_MODEL
        self.temperature = temperature
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
                    temperature=self.temperature,
                    seed=EXTRACTION_SEED,
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


def merge_edges(
    llm_edges: list[CandidateEdge], derived_edges: list[CandidateEdge]
) -> list[CandidateEdge]:
    """One edge per `(source_name, target_name, rel_type)`, derived one preferred.

    `structural_edges` deduplicates its own output, but the two lists were merely
    concatenated, so an LLM spatial edge identical to a derived one shipped twice
    -- inflating the edge count and handing stage 2b two provenances for one fact.

    The derived edge wins: it carries STRUCTURAL_EVIDENCE and an exact section
    index, and by construction it cannot have been hallucinated.
    """
    by_key: dict[tuple[str, str, str], CandidateEdge] = {}
    for e in llm_edges:
        by_key.setdefault((e.source_name, e.target_name, e.rel_type), e)
    for e in derived_edges:
        by_key[(e.source_name, e.target_name, e.rel_type)] = e
    return list(by_key.values())


ANCHORING_TYPES = frozenset({"GAVE_QUEST", "OBJECTIVE_AT", "SEEKS", "COMPLETED", "RESOLVES_TO"})


def anchor_quests(
    nodes: list[CandidateNode], edges: list[CandidateEdge]
) -> tuple[list[CandidateNode], list[CandidateEdge], int, int]:
    """Drop QUEST nodes no INDEPENDENT extracted entity points at, and their edges.

    A coined quest name is the one candidate the source text never states literally,
    so it is the one most likely to be invented. A quest that no NPC gives, no place
    hosts, and nobody seeks is not a quest the book describes.

    The anchor must be an independent witness: the non-quest endpoint of the
    anchoring edge has to be a candidate node some OTHER layer pass also produced.
    Requiring merely "some extracted node" bounds nothing, because the narrative
    prompt instructs the model to emit GAVE_QUEST/OBJECTIVE_AT for every quest it
    coins -- the same call invents the quest, the giver, and the edge between them,
    and the filter then accepts its own output as corroboration. Demonstrated: a
    coined `Assassinate the Burgomaster of Vallaki` with a GAVE_QUEST edge from
    Ismark survived, and the dropped-quest count was 0 in all four measured runs.
    An NPC the social pass also found is real corroboration; an NPC named only
    inside the same narrative response is the same sentence read twice.

    Returns the surviving nodes, the surviving edges, the number of QUEST nodes
    dropped, and the number of edges dropped with them.
    """

    def fold(name: str) -> str:
        return name.strip().casefold()

    # Keyed on (name, type), never name alone: a QUEST that happens to share a name
    # with a LOCATION must not take the LOCATION's edges down with it. Demonstrated:
    # a coined QUEST "Village of Barovia" destroyed both of the village's real
    # spatial edges, one of them a derived structural edge from the module
    # documented as unable to hallucinate.
    quest_layers: dict[str, set[str]] = {}
    other_layers: dict[str, set[str]] = {}
    for n in nodes:
        bucket = quest_layers if n.entity_type == "QUEST" else other_layers
        bucket.setdefault(fold(n.name), set()).add(n.layer)

    anchored: set[str] = set()

    def consider(quest_name: str, witness_name: str) -> None:
        if quest_name not in quest_layers:
            return
        # An independent witness is one found by a pass that did not also produce
        # the quest node itself.
        if other_layers.get(witness_name, set()) - quest_layers[quest_name]:
            anchored.add(quest_name)

    for e in edges:
        if e.rel_type not in ANCHORING_TYPES:
            continue
        source, target = fold(e.source_name), fold(e.target_name)
        consider(source, target)
        consider(target, source)

    dropped_names = set(quest_layers) - anchored
    surviving_nodes = [
        n for n in nodes if not (n.entity_type == "QUEST" and fold(n.name) in dropped_names)
    ]
    # A name that some surviving non-quest node still carries is a live entity, so
    # edges naming it are about that entity, not about the dropped quest.
    surviving_names = {fold(n.name) for n in surviving_nodes}
    surviving_edges = [
        e
        for e in edges
        if not any(
            fold(name) in dropped_names and fold(name) not in surviving_names
            for name in (e.source_name, e.target_name)
        )
    ]
    dropped_count = sum(
        1 for n in nodes if n.entity_type == "QUEST" and fold(n.name) in dropped_names
    )
    return surviving_nodes, surviving_edges, dropped_count, len(edges) - len(surviving_edges)
