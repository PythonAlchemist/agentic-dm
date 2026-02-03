"""Enhanced hybrid RAG pipeline with query planning and reranking."""

from typing import Optional

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from backend.core.config import settings
from backend.rag.query_planner import QueryPlanner, QueryPlan, QueryType
from backend.rag.enhanced_retriever import EnhancedRetriever, RetrievalResult
from backend.rag.reranker import Reranker, RankedResult


# System prompts
ASSISTANT_PROMPT = """You are a knowledgeable D&D Dungeon Master assistant. Your role is to help DMs run their games.

When answering:
- Be concise but thorough
- Cite sources when referencing rules (e.g., "PHB p.123")
- If unsure, say so
- For homebrew questions, offer balanced perspectives
- Use the provided context to inform your answers

If the context doesn't contain relevant information, use your general D&D knowledge but note when you're doing so."""

DM_PROMPT = """You are an AI Dungeon Master running a D&D 5th Edition game.

Guidelines:
- Narrate scenes vividly but concisely (2-3 sentences unless dramatic)
- Roleplay NPCs with distinct personalities
- Ask for dice rolls when appropriate
- Track game state changes
- Balance challenge with fun
- Use campaign context to maintain consistency

Use the provided campaign knowledge to stay consistent with established facts."""


class HybridRAGResponse(BaseModel):
    """Response from hybrid RAG pipeline."""

    response: str
    query_type: QueryType
    sources: list[dict] = Field(default_factory=list)
    context_used: bool = False
    entities_found: list[str] = Field(default_factory=list)
    processing_info: dict = Field(default_factory=dict)


class HybridRAGPipeline:
    """Enhanced RAG pipeline with intelligent query routing."""

    def __init__(self):
        """Initialize the hybrid pipeline."""
        self.openai = AsyncOpenAI(api_key=settings.openai_api_key)
        self.model = settings.openai_model
        self.query_planner = QueryPlanner(use_ner=True)
        self.retriever = EnhancedRetriever(use_query_planning=False)  # We plan externally
        self.reranker = Reranker()

    async def query(
        self,
        question: str,
        conversation_history: Optional[list[dict]] = None,
        mode: str = "assistant",
        max_results: int = 10,
    ) -> HybridRAGResponse:
        """Process a query through the hybrid RAG pipeline.

        Args:
            question: User's question.
            conversation_history: Previous messages.
            mode: "assistant" or "dm".
            max_results: Maximum context items.

        Returns:
            HybridRAGResponse with answer and metadata.
        """
        conversation_history = conversation_history or []

        # Step 1: Plan the query
        query_plan = await self.query_planner.plan(question)

        # Step 2: Retrieve context based on plan
        retrieval_result = await self.retriever.retrieve(
            query=question,
            strategy=query_plan.strategy,
        )

        # Step 3: Rerank results
        query_entities = query_plan.extracted_entities
        ranked_results = self.reranker.merge_results(
            vector_results=retrieval_result.vector_results,
            graph_results=retrieval_result.graph_entities,
            query=question,
            query_entities=query_entities,
            max_results=max_results,
        )

        # Step 4: Format context
        context = self._format_ranked_context(ranked_results)

        # Step 5: Build messages
        messages = self._build_messages(
            question=question,
            context=context,
            conversation_history=conversation_history,
            mode=mode,
            query_type=query_plan.query_type,
        )

        # Step 6: Generate response
        response = await self.openai.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.7 if mode == "dm" else 0.3,
            max_tokens=1000,
        )

        # Build sources list
        sources = self._build_sources(ranked_results)

        # Extract entity names found
        entities_found = [e.normalized_name for e in query_entities]

        return HybridRAGResponse(
            response=response.choices[0].message.content,
            query_type=query_plan.query_type,
            sources=sources,
            context_used=bool(context),
            entities_found=entities_found,
            processing_info={
                "query_confidence": query_plan.confidence,
                "total_results": len(ranked_results),
                "vector_results": len(retrieval_result.vector_results),
                "graph_results": len(retrieval_result.graph_entities),
            },
        )

    def _format_ranked_context(self, results: list[RankedResult]) -> str:
        """Format ranked results into context string.

        Args:
            results: Ranked results.

        Returns:
            Formatted context string.
        """
        if not results:
            return ""

        parts = []
        for i, result in enumerate(results[:10], 1):  # Top 10
            source_info = ""
            if result.metadata:
                source = result.metadata.get("source", "")
                page = result.metadata.get("page", "")
                if source:
                    source_info = f"[{source}"
                    if page:
                        source_info += f", p.{page}"
                    source_info += "] "

            # Show boost reasons for transparency
            boost_info = ""
            if result.boost_reasons:
                boost_info = f" ({', '.join(result.boost_reasons)})"

            parts.append(f"{i}. {source_info}{result.content}{boost_info}")

        return "\n\n".join(parts)

    def _build_messages(
        self,
        question: str,
        context: str,
        conversation_history: list[dict],
        mode: str,
        query_type: QueryType,
    ) -> list[dict]:
        """Build message list for LLM.

        Args:
            question: User's question.
            context: Retrieved context.
            conversation_history: Previous messages.
            mode: assistant or dm.
            query_type: Classified query type.

        Returns:
            List of messages.
        """
        system_prompt = DM_PROMPT if mode == "dm" else ASSISTANT_PROMPT

        # Add query-type specific guidance
        if query_type == QueryType.RULES_LOOKUP:
            system_prompt += "\n\nThis appears to be a rules question. Prioritize accuracy and cite page numbers."
        elif query_type == QueryType.CAMPAIGN_STATE:
            system_prompt += "\n\nThis is asking about current campaign state. Focus on the campaign knowledge provided."
        elif query_type == QueryType.CAMPAIGN_HISTORY:
            system_prompt += "\n\nThis is asking about past events. Reference specific sessions or events if available."

        messages = [{"role": "system", "content": system_prompt}]

        # Add conversation history (last 10)
        for msg in conversation_history[-10:]:
            messages.append({
                "role": msg["role"],
                "content": msg["content"],
            })

        # Add context and question
        if context:
            user_content = f"""Relevant context:
{context}

Question: {question}"""
        else:
            user_content = question

        messages.append({"role": "user", "content": user_content})

        return messages

    def _build_sources(self, results: list[RankedResult]) -> list[dict]:
        """Build sources list from ranked results.

        Args:
            results: Ranked results.

        Returns:
            List of source dicts.
        """
        sources = []
        for result in results:
            source = {
                "type": result.source_type,
                "score": result.final_score,
            }

            if result.metadata:
                source["source"] = result.metadata.get("source", "unknown")
                if "page" in result.metadata:
                    source["page"] = result.metadata["page"]
                if "entity_type" in result.metadata:
                    source["entity_type"] = result.metadata["entity_type"]

            sources.append(source)

        return sources

    async def get_campaign_context(self, entity_names: list[str]) -> str:
        """Get context about specific campaign entities.

        Args:
            entity_names: Names of entities to look up.

        Returns:
            Formatted context string.
        """
        context_parts = []

        for name in entity_names:
            entity_context = await self.retriever.get_entity_context(name)
            if entity_context:
                entity = entity_context["entity"]
                neighbors = entity_context.get("neighbors", [])

                part = f"**{entity['name']}** ({entity.get('entity_type', 'Entity')})"
                if entity.get("description"):
                    part += f": {entity['description']}"

                if neighbors:
                    related = [n["name"] for n in neighbors[:5]]
                    part += f"\n  Related: {', '.join(related)}"

                context_parts.append(part)

        return "\n\n".join(context_parts) if context_parts else ""
