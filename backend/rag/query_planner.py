"""Query understanding and routing for hybrid RAG."""

import re
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from backend.graph.schema import EntityType
from backend.ner import NERPipeline, NERConfig, ExtractedEntity


class QueryType(str, Enum):
    """Types of queries for routing."""

    RULES_LOOKUP = "rules_lookup"  # "How does grappling work?"
    CAMPAIGN_STATE = "campaign_state"  # "Where is Thorin right now?"
    CAMPAIGN_HISTORY = "campaign_history"  # "What happened with the dragon?"
    ENTITY_INFO = "entity_info"  # "Tell me about the Harpers"
    ENCOUNTER_GENERATION = "encounter_generation"  # "Create a goblin ambush"
    NPC_GENERATION = "npc_generation"  # "Generate a mysterious merchant"
    GENERAL_DM = "general_dm"  # "What should I do if players argue?"
    UNKNOWN = "unknown"


class RetrievalStrategy(BaseModel):
    """Strategy for retrieving context."""

    use_vector: bool = True
    use_graph: bool = True
    vector_sources: list[str] = Field(default_factory=list)  # Filter to specific sources
    entity_types: list[EntityType] = Field(default_factory=list)  # Focus on specific types
    graph_depth: int = 2  # How many hops for graph traversal
    vector_k: int = 5  # Number of vector results
    graph_k: int = 5  # Number of graph results
    require_entities: bool = False  # Must have entity matches


class QueryPlan(BaseModel):
    """Plan for processing a query."""

    query_type: QueryType
    strategy: RetrievalStrategy
    extracted_entities: list[ExtractedEntity] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    confidence: float = 0.5


class QueryPlanner:
    """Analyze queries and plan retrieval strategy."""

    # Keywords that indicate rules questions
    RULES_KEYWORDS = {
        "how does", "how do", "what is", "what are", "explain",
        "rule", "rules", "mechanic", "mechanics", "work",
        "can i", "can you", "is it possible", "allowed",
        "damage", "attack", "saving throw", "ability check",
        "spell", "spells", "casting", "concentration",
        "action", "bonus action", "reaction", "movement",
        "condition", "conditions", "advantage", "disadvantage",
    }

    # Keywords for campaign state
    CAMPAIGN_STATE_KEYWORDS = {
        "where is", "where are", "current", "now", "right now",
        "status", "location", "what does", "who is",
        "inventory", "have", "possess", "carrying",
    }

    # Keywords for campaign history
    HISTORY_KEYWORDS = {
        "what happened", "when did", "last time", "previously",
        "remember", "before", "history", "past", "session",
        "did we", "did they", "did i",
    }

    # Keywords for generation
    ENCOUNTER_KEYWORDS = {
        "create", "generate", "design", "build", "make",
        "encounter", "combat", "fight", "battle", "ambush",
    }

    NPC_KEYWORDS = {
        "npc", "character", "person", "merchant", "innkeeper",
        "villain", "ally", "contact", "quest giver",
    }

    def __init__(self, use_ner: bool = True):
        """Initialize the query planner.

        Args:
            use_ner: Whether to use NER for entity extraction.
        """
        self.use_ner = use_ner
        if use_ner:
            config = NERConfig(
                use_llm_extraction=False,  # Fast mode for queries
                link_to_graph=False,
            )
            self.ner_pipeline = NERPipeline(config)
        else:
            self.ner_pipeline = None

    async def plan(self, query: str) -> QueryPlan:
        """Create a plan for processing the query.

        Args:
            query: The user's query.

        Returns:
            QueryPlan with routing and extraction info.
        """
        query_lower = query.lower()

        # Classify query type
        query_type, confidence = self._classify_query(query_lower)

        # Extract entities using NER
        entities = []
        if self.ner_pipeline:
            result = await self.ner_pipeline.extract(query)
            entities = result.entities

        # Extract keywords
        keywords = self._extract_keywords(query_lower)

        # Build retrieval strategy based on query type
        strategy = self._build_strategy(query_type, entities, keywords)

        return QueryPlan(
            query_type=query_type,
            strategy=strategy,
            extracted_entities=entities,
            keywords=keywords,
            confidence=confidence,
        )

    def _classify_query(self, query_lower: str) -> tuple[QueryType, float]:
        """Classify the query type.

        Args:
            query_lower: Lowercase query string.

        Returns:
            Tuple of (QueryType, confidence).
        """
        scores = {
            QueryType.RULES_LOOKUP: 0.0,
            QueryType.CAMPAIGN_STATE: 0.0,
            QueryType.CAMPAIGN_HISTORY: 0.0,
            QueryType.ENCOUNTER_GENERATION: 0.0,
            QueryType.NPC_GENERATION: 0.0,
            QueryType.ENTITY_INFO: 0.0,
            QueryType.GENERAL_DM: 0.0,
        }

        # Score based on keywords
        for keyword in self.RULES_KEYWORDS:
            if keyword in query_lower:
                scores[QueryType.RULES_LOOKUP] += 1.0

        for keyword in self.CAMPAIGN_STATE_KEYWORDS:
            if keyword in query_lower:
                scores[QueryType.CAMPAIGN_STATE] += 1.5

        for keyword in self.HISTORY_KEYWORDS:
            if keyword in query_lower:
                scores[QueryType.CAMPAIGN_HISTORY] += 1.5

        # Check for generation words
        has_generation_word = any(
            kw in query_lower for kw in ["create", "generate", "design", "build", "make"]
        )
        has_combat_word = any(
            kw in query_lower for kw in ["encounter", "combat", "fight", "battle", "ambush"]
        )
        has_npc_word = any(
            kw in query_lower for kw in self.NPC_KEYWORDS
        )

        # Score encounter generation
        for keyword in self.ENCOUNTER_KEYWORDS:
            if keyword in query_lower:
                scores[QueryType.ENCOUNTER_GENERATION] += 2.0

        # Score NPC generation - boost if generation word + NPC word (without combat words)
        for keyword in self.NPC_KEYWORDS:
            if keyword in query_lower:
                scores[QueryType.NPC_GENERATION] += 1.5

        # If we have generation word + NPC word but no combat word, this is NPC generation
        if has_generation_word and has_npc_word and not has_combat_word:
            scores[QueryType.NPC_GENERATION] += 2.5  # Strong boost for NPC

        # Check for entity info patterns
        if re.search(r"(tell me about|what is|who is|describe)\s+\w+", query_lower):
            scores[QueryType.ENTITY_INFO] += 1.0

        # Find best match
        best_type = max(scores, key=scores.get)
        best_score = scores[best_type]

        if best_score < 0.5:
            return QueryType.UNKNOWN, 0.3

        # Normalize confidence
        confidence = min(1.0, best_score / 3.0)

        return best_type, confidence

    def _extract_keywords(self, query_lower: str) -> list[str]:
        """Extract important keywords from query.

        Args:
            query_lower: Lowercase query.

        Returns:
            List of keywords.
        """
        # Remove common words
        stop_words = {
            "the", "a", "an", "is", "are", "was", "were", "be",
            "been", "being", "have", "has", "had", "do", "does",
            "did", "will", "would", "could", "should", "may",
            "might", "must", "shall", "can", "need", "dare",
            "to", "of", "in", "for", "on", "with", "at", "by",
            "from", "as", "into", "through", "during", "before",
            "after", "above", "below", "between", "under", "again",
            "further", "then", "once", "here", "there", "when",
            "where", "why", "how", "all", "each", "few", "more",
            "most", "other", "some", "such", "no", "nor", "not",
            "only", "own", "same", "so", "than", "too", "very",
            "just", "and", "but", "if", "or", "because", "until",
            "while", "about", "against", "what", "which", "who",
            "whom", "this", "that", "these", "those", "am", "i",
            "me", "my", "myself", "we", "our", "ours", "you",
            "your", "he", "him", "his", "she", "her", "it", "its",
            "they", "them", "their",
        }

        words = re.findall(r'\b[a-z]+\b', query_lower)
        keywords = [w for w in words if w not in stop_words and len(w) > 2]

        return keywords[:10]  # Limit to top 10

    def _build_strategy(
        self,
        query_type: QueryType,
        entities: list[ExtractedEntity],
        keywords: list[str],
    ) -> RetrievalStrategy:
        """Build retrieval strategy based on query type.

        Args:
            query_type: Classified query type.
            entities: Extracted entities.
            keywords: Extracted keywords.

        Returns:
            RetrievalStrategy.
        """
        if query_type == QueryType.RULES_LOOKUP:
            return RetrievalStrategy(
                use_vector=True,
                use_graph=False,  # Rules are in PDFs, not graph
                vector_sources=["phb", "dmg", "mm", "rules"],  # Prioritize rulebooks
                vector_k=7,
                graph_k=0,
            )

        elif query_type == QueryType.CAMPAIGN_STATE:
            # Focus on graph for current state
            entity_types = [e.entity_type for e in entities] if entities else []
            return RetrievalStrategy(
                use_vector=False,
                use_graph=True,
                entity_types=entity_types or [
                    EntityType.PC, EntityType.NPC, EntityType.LOCATION
                ],
                graph_depth=2,
                vector_k=0,
                graph_k=10,
                require_entities=True,
            )

        elif query_type == QueryType.CAMPAIGN_HISTORY:
            # Hybrid - check graph for entities, vector for session notes
            return RetrievalStrategy(
                use_vector=True,
                use_graph=True,
                entity_types=[EntityType.EVENT, EntityType.SESSION],
                graph_depth=2,
                vector_k=5,
                graph_k=5,
            )

        elif query_type == QueryType.ENTITY_INFO:
            # Graph-heavy for entity info
            entity_types = [e.entity_type for e in entities] if entities else []
            return RetrievalStrategy(
                use_vector=True,
                use_graph=True,
                entity_types=entity_types,
                graph_depth=3,  # Get more context
                vector_k=3,
                graph_k=8,
            )

        elif query_type == QueryType.ENCOUNTER_GENERATION:
            return RetrievalStrategy(
                use_vector=True,
                use_graph=False,
                vector_sources=["mm", "monsters"],  # Monster Manual
                vector_k=10,
                graph_k=0,
            )

        elif query_type == QueryType.NPC_GENERATION:
            return RetrievalStrategy(
                use_vector=False,
                use_graph=True,
                entity_types=[EntityType.NPC, EntityType.FACTION, EntityType.LOCATION],
                graph_depth=1,
                vector_k=0,
                graph_k=5,  # Get campaign context
            )

        else:
            # Default balanced strategy
            return RetrievalStrategy(
                use_vector=True,
                use_graph=True,
                vector_k=5,
                graph_k=5,
            )
