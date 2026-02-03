"""Link extracted entities to the knowledge graph."""

from typing import Optional

from rapidfuzz import fuzz

from backend.graph.operations import CampaignGraphOps
from backend.graph.schema import EntityType
from backend.ner.models import ExtractedEntity


class GraphLinker:
    """Link extracted entities to existing graph nodes."""

    def __init__(
        self,
        similarity_threshold: float = 0.85,
        graph_ops: Optional[CampaignGraphOps] = None,
    ):
        """Initialize the graph linker.

        Args:
            similarity_threshold: Minimum similarity for linking (0.0-1.0).
            graph_ops: Graph operations instance. Creates new if None.
        """
        self.similarity_threshold = similarity_threshold
        self.graph_ops = graph_ops or CampaignGraphOps()
        self.entity_cache: dict[str, list[dict]] = {}  # type -> entities
        self._cache_loaded = False

    def refresh_cache(self) -> None:
        """Refresh the entity cache from the graph."""
        self.entity_cache = {}

        for entity_type in EntityType:
            try:
                entities = self.graph_ops.list_entities(
                    entity_type=entity_type.value,
                    limit=1000,
                )
                self.entity_cache[entity_type.value] = entities
            except Exception:
                self.entity_cache[entity_type.value] = []

        self._cache_loaded = True

    def link_entity(
        self,
        entity: ExtractedEntity,
        create_if_missing: bool = False,
    ) -> ExtractedEntity:
        """Link an extracted entity to a graph node.

        Args:
            entity: The entity to link.
            create_if_missing: Create a new node if no match found.

        Returns:
            Entity with graph_id set if linked.
        """
        if not self._cache_loaded:
            self.refresh_cache()

        # Get candidates of the same type
        candidates = self.entity_cache.get(entity.entity_type.value, [])

        best_match = None
        best_score = 0.0

        for candidate in candidates:
            score = self._compute_match_score(entity, candidate)

            if score > best_score and score >= self.similarity_threshold:
                best_score = score
                best_match = candidate

        if best_match:
            # Link to existing node
            entity.graph_id = best_match["id"]
            entity.normalized_name = best_match["name"]  # Use canonical name
            # Boost confidence for linked entities
            entity.confidence = min(1.0, entity.confidence + 0.1)
            entity.metadata["graph_match_score"] = best_score
        elif create_if_missing:
            # Create new graph node
            new_node = self.graph_ops.create_entity(
                name=entity.normalized_name,
                entity_type=entity.entity_type,
                properties={
                    "source": "ner_extraction",
                    "confidence": entity.confidence,
                    "gazetteer_id": entity.gazetteer_id,
                },
            )
            if new_node:
                entity.graph_id = new_node["id"]
                # Add to cache
                self.entity_cache.setdefault(entity.entity_type.value, []).append(
                    new_node
                )

        return entity

    def link_entities(
        self,
        entities: list[ExtractedEntity],
        create_if_missing: bool = False,
    ) -> list[ExtractedEntity]:
        """Link multiple entities to the graph.

        Args:
            entities: Entities to link.
            create_if_missing: Create new nodes for unmatched entities.

        Returns:
            Entities with graph_ids set where linked.
        """
        if not self._cache_loaded:
            self.refresh_cache()

        return [self.link_entity(e, create_if_missing) for e in entities]

    def _compute_match_score(
        self,
        entity: ExtractedEntity,
        candidate: dict,
    ) -> float:
        """Compute match score between entity and graph node.

        Args:
            entity: Extracted entity.
            candidate: Graph node dict.

        Returns:
            Match score (0.0-1.0).
        """
        name_lower = entity.normalized_name.lower()
        candidate_name_lower = candidate["name"].lower()

        # Check exact name match
        if name_lower == candidate_name_lower:
            return 1.0

        # Check fuzzy name match
        name_score = fuzz.ratio(name_lower, candidate_name_lower) / 100.0

        # Check alias matches
        aliases = candidate.get("aliases", [])
        if isinstance(aliases, str):
            aliases = [aliases]

        alias_score = 0.0
        for alias in aliases:
            alias_lower = alias.lower()
            if name_lower == alias_lower:
                alias_score = 0.95  # Slightly lower than exact name
                break
            score = fuzz.ratio(name_lower, alias_lower) / 100.0
            alias_score = max(alias_score, score)

        return max(name_score, alias_score)

    def find_existing_entity(
        self,
        name: str,
        entity_type: EntityType,
    ) -> Optional[dict]:
        """Find an existing entity by name and type.

        Args:
            name: Entity name to search for.
            entity_type: Type of entity.

        Returns:
            Graph node dict or None.
        """
        if not self._cache_loaded:
            self.refresh_cache()

        candidates = self.entity_cache.get(entity_type.value, [])
        name_lower = name.lower()

        for candidate in candidates:
            if candidate["name"].lower() == name_lower:
                return candidate

            aliases = candidate.get("aliases", [])
            if isinstance(aliases, str):
                aliases = [aliases]
            if name_lower in [a.lower() for a in aliases]:
                return candidate

        return None
