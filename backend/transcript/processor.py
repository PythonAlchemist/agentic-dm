"""Transcript processor for NER extraction and graph population."""

import asyncio
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from backend.graph.operations import CampaignGraphOps
from backend.graph.schema import EntityType, RelationshipType
from backend.ner import NERPipeline, NERConfig, ExtractedEntity
from backend.transcript.models import (
    ParsedTranscript,
    ProcessingResult,
    SpeakerRole,
)
from backend.transcript.parser import TranscriptParser


class TranscriptProcessor:
    """Process transcripts: parse, extract entities, populate graph."""

    def __init__(
        self,
        ner_config: Optional[NERConfig] = None,
        create_entities: bool = True,
        create_relationships: bool = True,
    ):
        """Initialize the processor.

        Args:
            ner_config: NER pipeline configuration.
            create_entities: Whether to create entities in graph.
            create_relationships: Whether to create relationships.
        """
        # Configure NER
        config = ner_config or NERConfig(
            use_llm_extraction=True,
            link_to_graph=True,
            create_missing_entities=create_entities,
        )

        self.ner_pipeline = NERPipeline(config)
        self.parser = TranscriptParser()
        self.graph_ops = CampaignGraphOps()
        self.create_entities = create_entities
        self.create_relationships = create_relationships

    async def process(
        self,
        content: str,
        session_number: Optional[int] = None,
        campaign_id: Optional[str] = None,
        speakers: Optional[list[dict]] = None,
        format_hint: Optional[str] = None,
    ) -> ProcessingResult:
        """Process a transcript string.

        Args:
            content: Transcript content.
            session_number: Optional session number.
            campaign_id: Optional campaign identifier.
            speakers: Optional speaker definitions.
            format_hint: Optional format hint.

        Returns:
            ProcessingResult with extraction stats.
        """
        start_time = time.time()

        # Parse transcript
        parsed = self.parser.parse(content, format_hint, speakers)

        # Process parsed transcript
        result = await self._process_parsed(
            parsed, session_number, campaign_id
        )

        result.processing_time_ms = (time.time() - start_time) * 1000
        return result

    async def process_file(
        self,
        filepath: str | Path,
        session_number: Optional[int] = None,
        campaign_id: Optional[str] = None,
        speakers: Optional[list[dict]] = None,
    ) -> ProcessingResult:
        """Process a transcript file.

        Args:
            filepath: Path to transcript file.
            session_number: Optional session number.
            campaign_id: Optional campaign identifier.
            speakers: Optional speaker definitions.

        Returns:
            ProcessingResult with extraction stats.
        """
        start_time = time.time()

        # Parse file
        parsed = self.parser.parse_file(filepath, speakers)

        # Process parsed transcript
        result = await self._process_parsed(
            parsed, session_number, campaign_id
        )

        result.processing_time_ms = (time.time() - start_time) * 1000
        return result

    async def _process_parsed(
        self,
        parsed: ParsedTranscript,
        session_number: Optional[int],
        campaign_id: Optional[str],
    ) -> ProcessingResult:
        """Process a parsed transcript.

        Args:
            parsed: Parsed transcript.
            session_number: Session number.
            campaign_id: Campaign ID.

        Returns:
            ProcessingResult.
        """
        # Create session entity
        session_id = self._create_session_entity(
            session_number, campaign_id, parsed
        )

        result = ProcessingResult(
            session_id=session_id,
            session_number=session_number,
            campaign_id=campaign_id,
        )

        # Process each segment
        all_entities: list[ExtractedEntity] = []
        seen_entity_keys: set[tuple[str, str]] = set()

        for segment in parsed.segments:
            try:
                # Run NER on segment
                extraction = await self.ner_pipeline.extract(
                    segment.text,
                    session_id=session_id,
                )

                # Store results in segment
                segment.entities = extraction.entities
                segment.relationships = extraction.relationships

                # Collect unique entities
                for entity in extraction.entities:
                    key = (entity.normalized_name.lower(), entity.entity_type.value)
                    if key not in seen_entity_keys:
                        seen_entity_keys.add(key)
                        all_entities.append(entity)
                        result.add_entity(entity)

                # Collect relationships
                result.all_relationships.extend(extraction.relationships)

                result.segments_processed += 1

            except Exception as e:
                result.errors.append(f"Segment {segment.index}: {str(e)}")

        result.entities_extracted = len(all_entities)
        result.relationships_extracted = len(result.all_relationships)

        # Create entities in graph
        if self.create_entities:
            created = self._create_graph_entities(all_entities, session_id)
            result.entities_created = created

        # Create relationships in graph
        if self.create_relationships:
            created = self._create_graph_relationships(
                result.all_relationships,
                all_entities,
                session_id,
            )
            result.relationships_created = created

        # Create speaker entities (PCs/NPCs)
        self._create_speaker_entities(parsed.speakers, session_id)

        return result

    def _create_session_entity(
        self,
        session_number: Optional[int],
        campaign_id: Optional[str],
        parsed: ParsedTranscript,
    ) -> str:
        """Create a session entity in the graph.

        Args:
            session_number: Session number.
            campaign_id: Campaign ID.
            parsed: Parsed transcript.

        Returns:
            Session entity ID.
        """
        session_id = f"session_{uuid.uuid4().hex[:8]}"

        name = f"Session {session_number}" if session_number else f"Session {session_id}"

        self.graph_ops.create_entity(
            name=name,
            entity_type=EntityType.SESSION,
            entity_id=session_id,
            properties={
                "session_number": session_number,
                "campaign_id": campaign_id,
                "segment_count": len(parsed.segments),
                "speaker_count": len(parsed.speakers),
                "source_format": parsed.source_format,
                "processed_at": datetime.utcnow().isoformat(),
            },
        )

        return session_id

    def _create_graph_entities(
        self,
        entities: list[ExtractedEntity],
        session_id: str,
    ) -> int:
        """Create entities in the graph.

        Args:
            entities: Extracted entities.
            session_id: Session ID for linking.

        Returns:
            Number of entities created.
        """
        created = 0

        for entity in entities:
            # Skip if already has a graph ID (already exists)
            if entity.graph_id:
                continue

            try:
                # Create entity
                node = self.graph_ops.create_entity(
                    name=entity.normalized_name,
                    entity_type=entity.entity_type,
                    properties={
                        "source": "transcript_extraction",
                        "confidence": entity.confidence,
                        "gazetteer_id": entity.gazetteer_id,
                        "first_session": session_id,
                    },
                )

                if node:
                    entity.graph_id = node["id"]
                    created += 1

                    # Link to session
                    self.graph_ops.create_relationship(
                        source_id=node["id"],
                        target_id=session_id,
                        relationship_type=RelationshipType.OCCURRED_IN,
                    )

            except Exception:
                pass  # Entity might already exist

        return created

    def _create_graph_relationships(
        self,
        relationships: list,
        entities: list[ExtractedEntity],
        session_id: str,
    ) -> int:
        """Create relationships in the graph.

        Args:
            relationships: Extracted relationships.
            entities: All extracted entities (for ID lookup).
            session_id: Session ID.

        Returns:
            Number of relationships created.
        """
        created = 0

        # Build entity lookup
        entity_lookup: dict[str, str] = {}  # name -> graph_id
        for entity in entities:
            if entity.graph_id:
                entity_lookup[entity.normalized_name.lower()] = entity.graph_id

        for rel in relationships:
            source_name = rel.source_entity_name.lower()
            target_name = rel.target_entity_name.lower()

            source_id = entity_lookup.get(source_name)
            target_id = entity_lookup.get(target_name)

            if source_id and target_id:
                try:
                    self.graph_ops.create_relationship(
                        source_id=source_id,
                        target_id=target_id,
                        relationship_type=rel.relationship_type,
                        properties={
                            "confidence": rel.confidence,
                            "evidence": rel.evidence[:200] if rel.evidence else "",
                            "session_id": session_id,
                        },
                    )
                    created += 1
                except Exception:
                    pass

        return created

    def _create_speaker_entities(
        self,
        speakers: list,
        session_id: str,
    ) -> None:
        """Create speaker entities (Players and PCs).

        Creates Player entities, their PC entities, and establishes relationships:
        - Player PLAYS_AS PC
        - Player ATTENDED Session
        - PC PARTICIPATED_IN Session

        Args:
            speakers: List of speakers from transcript.
            session_id: Session ID.
        """
        player_ids = []

        for speaker in speakers:
            if speaker.role == SpeakerRole.PLAYER:
                try:
                    # Find or create Player entity
                    player = self._find_or_create_player(speaker.name)
                    if player:
                        player_ids.append(player["id"])

                        # Create PC if character name is provided
                        if speaker.character_name:
                            pc = self._find_or_create_pc(
                                character_name=speaker.character_name,
                                player_id=player["id"],
                                player_name=speaker.name,
                                session_id=session_id,
                                aliases=speaker.aliases,
                            )

                            if pc:
                                # Ensure PLAYS_AS relationship exists
                                self.graph_ops.link_player_character(
                                    player["id"], pc["id"]
                                )

                                # Link PC to session
                                self.graph_ops.create_relationship(
                                    source_id=pc["id"],
                                    target_id=session_id,
                                    relationship_type=RelationshipType.PARTICIPATED_IN,
                                )
                except Exception:
                    pass

        # Record session attendance for all players
        if player_ids:
            try:
                self.graph_ops.record_session_attendance(
                    session_id=session_id,
                    player_ids=player_ids,
                )
            except Exception:
                pass

    def _find_or_create_player(self, name: str) -> Optional[dict]:
        """Find an existing player by name or create a new one.

        Args:
            name: Player name.

        Returns:
            Player entity dict or None.
        """
        # Search for existing player
        existing = self.graph_ops.search(
            name,
            entity_types=[EntityType.PLAYER.value],
            limit=1,
        )

        if existing and existing[0].get("name", "").lower() == name.lower():
            return existing[0]

        # Create new player
        return self.graph_ops.create_player(name=name)

    def _find_or_create_pc(
        self,
        character_name: str,
        player_id: str,
        player_name: str,
        session_id: str,
        aliases: Optional[list] = None,
    ) -> Optional[dict]:
        """Find an existing PC by name or create a new one.

        Args:
            character_name: Character name.
            player_id: Player ID to link to.
            player_name: Player name for denormalization.
            session_id: Session ID for tracking.
            aliases: Optional character aliases.

        Returns:
            PC entity dict or None.
        """
        # Search for existing PC
        existing = self.graph_ops.search(
            character_name,
            entity_types=[EntityType.PC.value],
            limit=1,
        )

        if existing and existing[0].get("name", "").lower() == character_name.lower():
            return existing[0]

        # Create new PC
        node = self.graph_ops.create_entity(
            name=character_name,
            entity_type=EntityType.PC,
            properties={
                "player_id": player_id,
                "player_name": player_name,
                "aliases": aliases or [],
                "first_session": session_id,
            },
        )

        return node

    def process_sync(
        self,
        content: str,
        session_number: Optional[int] = None,
        campaign_id: Optional[str] = None,
        speakers: Optional[list[dict]] = None,
        format_hint: Optional[str] = None,
    ) -> ProcessingResult:
        """Synchronous version of process().

        Args:
            content: Transcript content.
            session_number: Session number.
            campaign_id: Campaign ID.
            speakers: Speaker definitions.
            format_hint: Format hint.

        Returns:
            ProcessingResult.
        """
        return asyncio.run(
            self.process(content, session_number, campaign_id, speakers, format_hint)
        )

    def process_file_sync(
        self,
        filepath: str | Path,
        session_number: Optional[int] = None,
        campaign_id: Optional[str] = None,
        speakers: Optional[list[dict]] = None,
    ) -> ProcessingResult:
        """Synchronous version of process_file().

        Args:
            filepath: Path to file.
            session_number: Session number.
            campaign_id: Campaign ID.
            speakers: Speaker definitions.

        Returns:
            ProcessingResult.
        """
        return asyncio.run(
            self.process_file(filepath, session_number, campaign_id, speakers)
        )
