"""Entity resolution and deduplication."""

from rapidfuzz import fuzz

from backend.graph.schema import EntityType
from backend.ner.models import ExtractedEntity, ExtractionSource


class EntityResolver:
    """Resolve and deduplicate extracted entities."""

    def __init__(self, similarity_threshold: float = 0.85):
        """Initialize the resolver.

        Args:
            similarity_threshold: Minimum similarity for merging (0.0-1.0).
        """
        self.similarity_threshold = similarity_threshold

    def resolve(self, entities: list[ExtractedEntity]) -> list[ExtractedEntity]:
        """Deduplicate and merge similar entities.

        Args:
            entities: List of entities to resolve.

        Returns:
            Deduplicated list of entities.
        """
        if not entities:
            return []

        # Group by entity type for more efficient comparison
        by_type: dict[EntityType, list[ExtractedEntity]] = {}
        for entity in entities:
            by_type.setdefault(entity.entity_type, []).append(entity)

        resolved = []
        for entity_type, group in by_type.items():
            resolved.extend(self._resolve_group(group))

        return resolved

    def _resolve_group(self, entities: list[ExtractedEntity]) -> list[ExtractedEntity]:
        """Resolve entities within a single type group.

        Args:
            entities: Entities of the same type.

        Returns:
            Resolved entities.
        """
        if len(entities) <= 1:
            return entities

        # Sort by confidence (highest first)
        sorted_entities = sorted(
            entities,
            key=lambda e: e.confidence,
            reverse=True,
        )

        merged = []
        used_indices = set()

        for i, entity in enumerate(sorted_entities):
            if i in used_indices:
                continue

            # Find similar entities to merge
            cluster = [entity]

            for j, other in enumerate(sorted_entities[i + 1 :], start=i + 1):
                if j in used_indices:
                    continue

                similarity = self._compute_similarity(entity, other)
                if similarity >= self.similarity_threshold:
                    cluster.append(other)
                    used_indices.add(j)

            # Merge the cluster
            merged_entity = self._merge_cluster(cluster)
            merged.append(merged_entity)
            used_indices.add(i)

        return merged

    def _compute_similarity(
        self,
        entity1: ExtractedEntity,
        entity2: ExtractedEntity,
    ) -> float:
        """Compute similarity between two entities.

        Args:
            entity1: First entity.
            entity2: Second entity.

        Returns:
            Similarity score (0.0-1.0).
        """
        # Use fuzzy string matching on normalized names
        score = fuzz.ratio(
            entity1.normalized_name.lower(),
            entity2.normalized_name.lower(),
        )
        return score / 100.0

    def _merge_cluster(self, cluster: list[ExtractedEntity]) -> ExtractedEntity:
        """Merge a cluster of similar entities into one.

        Args:
            cluster: List of similar entities.

        Returns:
            Merged entity.
        """
        if len(cluster) == 1:
            return cluster[0]

        # Find the best entity to use as base
        # Prefer gazetteer matches, then highest confidence
        base = None
        for entity in cluster:
            if entity.source == ExtractionSource.GAZETTEER:
                base = entity
                break

        if base is None:
            # Use highest confidence
            base = cluster[0]

        # Compute confidence boost for multi-source agreement
        sources = {e.source for e in cluster}
        confidence_boost = min(0.2, 0.1 * (len(sources) - 1))
        new_confidence = min(1.0, base.confidence + confidence_boost)

        # Determine source type
        if len(sources) > 1:
            new_source = ExtractionSource.HYBRID
        else:
            new_source = base.source

        # Collect all spans
        spans = [e.span for e in cluster if e.span is not None]
        merged_span = spans[0] if spans else None

        return ExtractedEntity(
            text=base.text,
            normalized_name=base.normalized_name,
            entity_type=base.entity_type,
            span=merged_span,
            confidence=new_confidence,
            source=new_source,
            graph_id=base.graph_id,
            gazetteer_id=base.gazetteer_id,
            metadata={
                "merged_count": len(cluster),
                "original_sources": list(sources),
                **base.metadata,
            },
        )

    def resolve_coreferences(
        self,
        entities: list[ExtractedEntity],
        text: str,
    ) -> list[ExtractedEntity]:
        """Resolve coreferences (e.g., 'he', 'the wizard' -> character name).

        This is a simplified version. Full coreference resolution would
        require more sophisticated NLP.

        Args:
            entities: Extracted entities.
            text: Original text.

        Returns:
            Entities with resolved coreferences.
        """
        # For now, this is a placeholder.
        # A full implementation would:
        # 1. Identify pronouns and definite descriptions
        # 2. Link them to the most likely antecedent
        # 3. Update entity spans/mentions
        return entities
