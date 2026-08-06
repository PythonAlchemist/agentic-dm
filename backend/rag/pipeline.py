"""RAG pipeline for D&D DM Assistant."""

from typing import Optional

from openai import AsyncOpenAI

from backend.core.config import settings
from backend.rag.retriever import HybridRetriever


# Unified system prompt for RAG
SYSTEM_PROMPT = """You are a knowledgeable D&D Dungeon Master. Your role is to help DMs run their games and run game sessions by:

1. Answering rules questions accurately, citing sources when available
2. Providing information about monsters, spells, items, and game mechanics
3. Helping with campaign management and tracking
4. Suggesting creative ideas for encounters, NPCs, and plot hooks
5. Narrating scenes vividly but concisely
6. Roleplaying NPCs with distinct personalities

When answering:
- Be concise but thorough
- Cite page numbers or sources when referencing rules
- If you're not sure about something, say so
- For homebrew or interpretation questions, offer balanced perspectives
- Use the campaign context to maintain consistency with established facts

Use the provided context to inform your answers. If the context doesn't contain relevant information, use your general D&D knowledge but note when you're doing so."""


class RAGPipeline:
    """Main RAG pipeline combining retrieval and generation."""

    def __init__(self):
        """Initialize the RAG pipeline."""
        self.openai = AsyncOpenAI(api_key=settings.openai_api_key)
        self.retriever = HybridRetriever()
        self.model = settings.openai_model

    def _format_vector_context(self, results: list[dict]) -> str:
        """Format vector search results into context string."""
        if not results:
            return ""

        context_parts = []
        for i, result in enumerate(results, 1):
            source = result["metadata"].get("source", "Unknown")
            page = result["metadata"].get("page", "?")
            content = result["content"]
            context_parts.append(f"[Source: {source}, Page {page}]\n{content}")

        return "\n\n---\n\n".join(context_parts)

    def _format_graph_context(self, results: list[dict]) -> str:
        """Format graph search results into context string."""
        if not results:
            return ""

        context_parts = []
        for entity in results:
            entity_type = entity.get("entity_type", "Entity")
            name = entity.get("name", "Unknown")
            description = entity.get("description", "No description")
            context_parts.append(f"[{entity_type}] {name}: {description}")

        return "\n".join(context_parts)

    def _build_messages(
        self,
        question: str,
        context: str,
        conversation_history: list[dict],
    ) -> list[dict]:
        """Build the message list for the LLM."""
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]

        # Add conversation history
        for msg in conversation_history[-10:]:  # Keep last 10 messages
            messages.append({
                "role": msg["role"],
                "content": msg["content"],
            })

        # Add context and question
        if context:
            user_content = f"""Context:
{context}

Question: {question}"""
        else:
            user_content = question

        messages.append({"role": "user", "content": user_content})

        return messages

    async def query(
        self,
        question: str,
        conversation_history: Optional[list[dict]] = None,
        use_graph: bool = True,
        use_vector: bool = True,
    ) -> dict:
        """Process a query through the RAG pipeline.

        Args:
            question: User's question
            conversation_history: Previous messages in conversation
            use_graph: Whether to search the knowledge graph
            use_vector: Whether to search vector database

        Returns:
            Response with generated answer and sources
        """
        conversation_history = conversation_history or []
        sources = []
        context_parts = []

        # Retrieve context from vector database
        if use_vector:
            vector_results = await self.retriever.search(
                query=question,
                top_k=settings.retrieval_top_k,
            )
            if vector_results:
                context_parts.append(
                    "=== Reference Materials ===\n" +
                    self._format_vector_context(vector_results)
                )
                sources.extend([
                    {
                        "type": "document",
                        "source": r["metadata"].get("source"),
                        "page": r["metadata"].get("page"),
                        "chunk_id": r["id"],
                        "score": r["score"],
                    }
                    for r in vector_results
                ])

        # Retrieve context from knowledge graph
        if use_graph:
            graph_results = await self.retriever.search_graph(
                query=question,
                limit=5,
            )
            if graph_results:
                context_parts.append(
                    "=== Campaign Knowledge ===\n" +
                    self._format_graph_context(graph_results)
                )
                sources.extend([
                    {
                        "type": "entity",
                        "entity_type": r.get("entity_type"),
                        "name": r.get("name"),
                        "id": r.get("id"),
                    }
                    for r in graph_results
                ])

        # Combine context
        context = "\n\n".join(context_parts) if context_parts else ""

        # Build messages
        messages = self._build_messages(
            question=question,
            context=context,
            conversation_history=conversation_history,
        )

        # Generate response
        response = await self.openai.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.5,
            max_tokens=1000,
        )

        return {
            "response": response.choices[0].message.content,
            "sources": sources,
            "context_used": bool(context),
        }

    async def generate_encounter(
        self,
        difficulty: str,
        environment: str,
        party_level: int,
        party_size: int = 4,
    ) -> dict:
        """Generate a combat encounter.

        Args:
            difficulty: easy, medium, hard, deadly
            environment: dungeon, forest, urban, etc.
            party_level: Average party level
            party_size: Number of party members

        Returns:
            Generated encounter details
        """
        # Search for relevant monsters
        monster_results = await self.retriever.search(
            query=f"{environment} monsters CR {party_level}",
            top_k=10,
        )

        context = self._format_vector_context(monster_results)

        prompt = f"""Generate a {difficulty} combat encounter for a party of {party_size} level {party_level} characters in a {environment} environment.

Available monster information:
{context}

Provide:
1. Encounter description (2-3 sentences setting the scene)
2. Monsters (list with quantities)
3. Tactical notes (how the monsters fight)
4. Terrain features (2-3 interesting terrain elements)
5. Possible rewards"""

        response = await self.openai.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "You are a D&D encounter designer."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.8,
            max_tokens=800,
        )

        return {
            "encounter": response.choices[0].message.content,
            "difficulty": difficulty,
            "environment": environment,
            "party_level": party_level,
        }

    async def generate_npc(
        self,
        role: str,
        context: Optional[str] = None,
    ) -> dict:
        """Generate an NPC.

        Args:
            role: NPC's role (innkeeper, merchant, villain, etc.)
            context: Optional campaign context

        Returns:
            Generated NPC details
        """
        prompt = f"""Create a memorable D&D NPC who is a {role}.

{f'Campaign context: {context}' if context else ''}

Provide:
1. Name
2. Race and appearance (2 sentences)
3. Personality (2-3 key traits)
4. Motivation (what do they want?)
5. Secret (something hidden about them)
6. Voice/mannerism (how to roleplay them)
7. Useful information they might share"""

        response = await self.openai.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "You are a creative D&D NPC designer."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.9,
            max_tokens=600,
        )

        return {
            "npc": response.choices[0].message.content,
            "role": role,
        }
