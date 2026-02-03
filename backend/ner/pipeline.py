"""Main NER pipeline orchestrating all extractors."""

import asyncio
import time
from typing import Optional

from backend.ner.config import NERConfig, default_config
from backend.ner.extractors.gazetteer_extractor import GazetteerExtractor
from backend.ner.extractors.llm_extractor import LLMExtractor
from backend.ner.extractors.spacy_extractor import SpacyExtractor
from backend.ner.gazetteers.loader import GazetteerLoader
from backend.ner.models import ExtractionResult, ExtractedEntity
from backend.ner.resolution.linker import GraphLinker
from backend.ner.resolution.resolver import EntityResolver


class NERPipeline:
    """Main NER pipeline orchestrating all extraction stages."""

    def __init__(self, config: Optional[NERConfig] = None):
        """Initialize the NER pipeline.

        Args:
            config: Pipeline configuration. Uses defaults if None.
        """
        self.config = config or default_config

        # Initialize extractors
        self.spacy_extractor = SpacyExtractor() if self.config.use_spacy else None
        self.gazetteer_extractor = (
            GazetteerExtractor() if self.config.use_gazetteer else None
        )
        self.llm_extractor = LLMExtractor() if self.config.use_llm_extraction else None

        # Initialize resolution components
        self.resolver = EntityResolver()
        self.linker = GraphLinker() if self.config.link_to_graph else None

        # Load gazetteers
        if self.gazetteer_extractor:
            loader = GazetteerLoader(
                canonical_dir=self.config.canonical_gazetteer_dir,
                campaign_dir=self.config.campaign_gazetteer_dir,
            )
            self.gazetteer_extractor.load_gazetteers(loader.load_all())

    async def extract(
        self,
        text: str,
        session_id: Optional[str] = None,
        use_llm: Optional[bool] = None,
    ) -> ExtractionResult:
        """Extract entities and relationships from text.

        Args:
            text: The text to process.
            session_id: Optional session identifier.
            use_llm: Override config for LLM usage.

        Returns:
            ExtractionResult with entities and relationships.
        """
        start_time = time.time()
        all_entities: list[ExtractedEntity] = []
        all_relationships = []

        # Stage 1 & 2: Parallel extraction from SpaCy and Gazetteer
        extraction_tasks = []

        if self.spacy_extractor:
            extraction_tasks.append(self._run_spacy(text))
        if self.gazetteer_extractor:
            extraction_tasks.append(self._run_gazetteer(text))

        if extraction_tasks:
            results = await asyncio.gather(*extraction_tasks)
            for result in results:
                all_entities.extend(result)

        # Also do fuzzy matching on SpaCy noun chunks
        if self.spacy_extractor and self.gazetteer_extractor:
            noun_chunks = self.spacy_extractor.extract_noun_chunks(text)
            fuzzy_entities = self.gazetteer_extractor.extract_with_fuzzy(
                text, noun_chunks
            )
            all_entities.extend(fuzzy_entities)

        # Stage 3: Resolve and deduplicate
        resolved_entities = self.resolver.resolve(all_entities)

        # Stage 4: LLM extraction (optional)
        should_use_llm = use_llm if use_llm is not None else self.config.use_llm_extraction
        if self.llm_extractor and should_use_llm:
            known_names = [e.normalized_name for e in resolved_entities]
            llm_entities, llm_relationships = await self.llm_extractor.extract(
                text,
                known_entities=known_names,
            )

            # Add new entities from LLM (avoid duplicates)
            for llm_entity in llm_entities:
                if not self._entity_exists(llm_entity, resolved_entities):
                    resolved_entities.append(llm_entity)

            all_relationships.extend(llm_relationships)

        # Stage 5: Link to graph
        if self.linker:
            self.linker.refresh_cache()
            resolved_entities = self.linker.link_entities(
                resolved_entities,
                create_if_missing=self.config.create_missing_entities,
            )

        # Filter by confidence threshold
        final_entities = [
            e
            for e in resolved_entities
            if e.confidence >= self.config.confidence_threshold
        ]

        processing_time = (time.time() - start_time) * 1000

        return ExtractionResult(
            entities=final_entities,
            relationships=all_relationships,
            source_text=text,
            session_id=session_id,
            processing_time_ms=processing_time,
        )

    async def _run_spacy(self, text: str) -> list[ExtractedEntity]:
        """Run SpaCy extraction (sync wrapper for async context)."""
        # SpaCy is sync, but we wrap it for gather()
        return self.spacy_extractor.extract(text)

    async def _run_gazetteer(self, text: str) -> list[ExtractedEntity]:
        """Run gazetteer extraction (sync wrapper for async context)."""
        return self.gazetteer_extractor.extract(text)

    def _entity_exists(
        self,
        candidate: ExtractedEntity,
        existing: list[ExtractedEntity],
    ) -> bool:
        """Check if entity already exists in list.

        Args:
            candidate: Candidate entity.
            existing: List of existing entities.

        Returns:
            True if similar entity exists.
        """
        from rapidfuzz import fuzz

        for e in existing:
            if e.entity_type != candidate.entity_type:
                continue

            similarity = fuzz.ratio(
                e.normalized_name.lower(),
                candidate.normalized_name.lower(),
            )
            if similarity > 85:
                return True

        return False

    async def extract_batch(
        self,
        texts: list[str],
        session_id: Optional[str] = None,
    ) -> list[ExtractionResult]:
        """Process multiple texts in batches.

        Args:
            texts: List of texts to process.
            session_id: Optional session identifier.

        Returns:
            List of ExtractionResults.
        """
        results = []

        for i in range(0, len(texts), self.config.batch_size):
            batch = texts[i : i + self.config.batch_size]
            batch_results = await asyncio.gather(
                *[self.extract(text, session_id) for text in batch]
            )
            results.extend(batch_results)

        return results

    def extract_sync(
        self,
        text: str,
        session_id: Optional[str] = None,
        use_llm: bool = False,
    ) -> ExtractionResult:
        """Synchronous extraction (without LLM by default).

        Args:
            text: The text to process.
            session_id: Optional session identifier.
            use_llm: Whether to use LLM extraction.

        Returns:
            ExtractionResult.
        """
        return asyncio.run(self.extract(text, session_id, use_llm=use_llm))
