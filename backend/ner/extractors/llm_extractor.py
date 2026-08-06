"""LLM-based entity and relationship extraction."""

import json
import logging
from typing import Optional

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

from backend.core.config import settings
from backend.graph.schema import EntityType, RelationshipType
from backend.ner.config import default_config
from backend.ner.models import (
    ExtractedEntity,
    ExtractedRelationship,
    ExtractionSource,
)


EXTRACTION_SYSTEM_PROMPT = """You are a D&D entity extractor. Extract named entities and relationships from D&D session transcripts.

Entity types to extract:
- PC: Player characters (the party members being played by people at the table)
- NPC: Non-player characters (characters controlled by the DM)
- LOCATION: Places (cities, dungeons, rooms, regions)
- ITEM: Objects, weapons, artifacts, treasure
- MONSTER: Creatures and enemies encountered in combat
- FACTION: Organizations and groups
- SPELL: Named spells that are cast
- QUEST: Quest names or objectives mentioned
- CLASS: Character classes (Fighter, Bard, Druid, Ranger, etc.)
- RACE: Character races/species (Gnome, Elf, Half-Elf, Human, Goliath, etc.)

IMPORTANT rules:
- Races and classes are their OWN entities (type RACE or CLASS), NOT characters. "Half-Elf" is a RACE entity, "Ranger" is a CLASS entity. Then link them to characters via HAS_RACE / HAS_CLASS relationships.
- Deduplicate: use ONE canonical name per entity. If someone is called both "Vex" and "Vex'ahlia", pick the full name "Vex'ahlia" as canonical_name. Do NOT create separate entities for nicknames/shortened names.
- If a known entity is mentioned by a nickname or alias, use the known entity's exact name — do not create a new entity.
- Player names (the real people) should use PLAYS_AS relationships to link to their PC entities.

Relationship types to extract:
- HAS_CLASS: Character -> CLASS entity (e.g. Scanlan -> Bard)
- HAS_RACE: Character -> RACE entity (e.g. Keyleth -> Half-Elf)
- LOCATED_IN: Entity is in a location
- KNOWS: Character knows another character
- ALLIED_WITH: Characters/factions are allies
- HOSTILE_TO: Characters/factions are enemies
- OWNS: Character owns an item
- WIELDS: Character wields or is equipped with a weapon/item
- KILLED: Entity killed another entity
- MEMBER_OF: Character is member of faction
- SERVES: Character serves another character or faction
- RELATED_TO: Characters are family/blood relations (specify in evidence)
- TRAVELED_TO: Character traveled to or visited a location
- PLAYS_AS: Real player -> their PC (e.g. "Laura" PLAYS_AS "Vex'ahlia")
- PARTICIPATED_IN: Entity participated in an event

Return valid JSON only. Be conservative - only extract entities you're confident about."""

EXTRACTION_USER_PROMPT = """Extract D&D entities and relationships from this transcript segment.

Known campaign entities (use these exact names if referenced, do NOT create duplicates):
{known_entities}

Transcript:
---
{text}
---

Return JSON with this exact format:
{{
  "entities": [
    {{"text": "exact text found", "type": "ENTITY_TYPE", "canonical_name": "full standardized name"}}
  ],
  "relationships": [
    {{"source": "canonical entity name", "target": "canonical entity name", "type": "RELATIONSHIP_TYPE", "evidence": "brief quote from text"}}
  ]
}}

Remember:
- Races/classes are separate entities (type RACE/CLASS), linked to characters via HAS_RACE/HAS_CLASS
- Use full canonical names, merge nicknames (Vex -> Vex'ahlia, Pike -> Pike Trickfoot)
- Match known entities exactly, don't create duplicates
- Only include entities and relationships you find in the text"""


class LLMExtractor:
    """Extract entities and relationships using LLM."""

    def __init__(self):
        """Initialize the LLM extractor."""
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)
        self.model = settings.openai_model
        self.confidence = default_config.llm_confidence

    async def extract(
        self,
        text: str,
        known_entities: Optional[list[str]] = None,
    ) -> tuple[list[ExtractedEntity], list[ExtractedRelationship]]:
        """Extract entities and relationships from text.

        Args:
            text: The transcript text to process.
            known_entities: List of known entity names from the campaign.

        Returns:
            Tuple of (entities, relationships).
        """
        if not text.strip():
            return [], []

        # Format known entities
        known_str = "\n".join(f"- {name}" for name in (known_entities or []))
        if not known_str:
            known_str = "(No known entities yet)"

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": EXTRACTION_USER_PROMPT.format(
                            known_entities=known_str,
                            text=text[:default_config.llm_chunk_size],
                        ),
                    },
                ],
                response_format={"type": "json_object"},
                temperature=0.1,  # Low temperature for consistent extraction
                max_tokens=2000,
            )

            result = json.loads(response.choices[0].message.content)
            entities = self._parse_entities(result.get("entities", []))
            relationships = self._parse_relationships(result.get("relationships", []))

            return entities, relationships

        except Exception as e:
            # Log error but don't fail the pipeline
            print(f"LLM extraction error: {e}")
            return [], []

    def _parse_entities(self, raw_entities: list[dict]) -> list[ExtractedEntity]:
        """Parse raw entity dicts into ExtractedEntity objects.

        Args:
            raw_entities: List of entity dicts from LLM.

        Returns:
            List of ExtractedEntity objects.
        """
        entities = []

        for raw in raw_entities:
            try:
                # Get entity type
                type_str = raw.get("type", "").upper()
                try:
                    entity_type = EntityType(type_str)
                except ValueError:
                    continue  # Skip unknown types

                text = raw.get("text", "")
                canonical = raw.get("canonical_name", text)

                if not text:
                    continue

                entities.append(
                    ExtractedEntity(
                        text=text,
                        normalized_name=canonical,
                        entity_type=entity_type,
                        confidence=self.confidence,
                        source=ExtractionSource.LLM,
                        metadata={"llm_extracted": True},
                    )
                )
            except Exception:
                continue  # Skip malformed entries

        return entities

    def _parse_relationships(
        self, raw_relationships: list[dict]
    ) -> list[ExtractedRelationship]:
        """Parse raw relationship dicts into ExtractedRelationship objects.

        Args:
            raw_relationships: List of relationship dicts from LLM.

        Returns:
            List of ExtractedRelationship objects.
        """
        relationships = []

        for raw in raw_relationships:
            try:
                # Get relationship type
                type_str = raw.get("type", "").upper()
                try:
                    rel_type = RelationshipType(type_str)
                except ValueError:
                    logger.warning("Skipping unknown relationship type: %s (%s -> %s)", type_str, raw.get("source"), raw.get("target"))
                    continue

                source = raw.get("source", "")
                target = raw.get("target", "")
                evidence = raw.get("evidence", "")

                if not source or not target:
                    continue

                relationships.append(
                    ExtractedRelationship(
                        source_entity_name=source,
                        target_entity_name=target,
                        relationship_type=rel_type,
                        confidence=self.confidence,
                        evidence=evidence,
                    )
                )
            except Exception:
                continue  # Skip malformed entries

        return relationships

    async def extract_relationships_only(
        self,
        text: str,
        entities: list[ExtractedEntity],
    ) -> list[ExtractedRelationship]:
        """Extract only relationships between known entities.

        Use this when entities are already extracted and you just need relationships.

        Args:
            text: The transcript text.
            entities: Already extracted entities.

        Returns:
            List of relationships.
        """
        entity_names = [e.normalized_name for e in entities]
        _, relationships = await self.extract(text, entity_names)
        return relationships
