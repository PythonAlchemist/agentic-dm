"""DM Agent for running games and assisting DMs."""

from enum import Enum
from typing import Optional

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from backend.core.config import settings
from backend.rag import HybridRAGPipeline, QueryType
from backend.agents.tools import DMTools, DiceResult, EncounterResult, NPCResult
from backend.agents.conversation import ConversationManager, MessageRole
from backend.agents.prompts import (
    ASSISTANT_SYSTEM_PROMPT,
    AUTONOMOUS_SYSTEM_PROMPT,
)


class DMMode(str, Enum):
    """Operating modes for the DM Agent."""

    ASSISTANT = "assistant"  # Helps a human DM
    AUTONOMOUS = "autonomous"  # Runs the game


class DMResponse(BaseModel):
    """Response from the DM Agent."""

    message: str
    query_type: Optional[QueryType] = None
    tool_results: list[dict] = Field(default_factory=list)
    sources: list[dict] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


class DMAgent:
    """AI Dungeon Master agent.

    Operates in two modes:
    - Assistant: Reactive, helps human DM with lookups and generation
    - Autonomous: Proactive, runs the game session
    """

    def __init__(
        self,
        mode: DMMode = DMMode.ASSISTANT,
        campaign_id: Optional[str] = None,
    ):
        """Initialize the DM Agent.

        Args:
            mode: Operating mode (assistant or autonomous).
            campaign_id: Optional campaign to load context from.
        """
        self.mode = mode
        self.campaign_id = campaign_id

        # Initialize components
        self.openai = AsyncOpenAI(api_key=settings.openai_api_key)
        self.model = settings.openai_model
        self.rag_pipeline = HybridRAGPipeline()
        self.tools = DMTools()
        self.conversation = ConversationManager()

        # Set system prompt based on mode
        self._set_system_prompt()

    def _set_system_prompt(self) -> None:
        """Set the system prompt based on mode."""
        if self.mode == DMMode.ASSISTANT:
            self.conversation.set_system_prompt(ASSISTANT_SYSTEM_PROMPT)
        else:
            self.conversation.set_system_prompt(AUTONOMOUS_SYSTEM_PROMPT)

    def set_mode(self, mode: DMMode) -> None:
        """Change the operating mode.

        Args:
            mode: New operating mode.
        """
        self.mode = mode
        self._set_system_prompt()

    async def process_message(
        self,
        user_input: str,
        use_rag: bool = True,
    ) -> DMResponse:
        """Process a user message.

        Args:
            user_input: User's input text.
            use_rag: Whether to use RAG for context.

        Returns:
            DMResponse with the agent's response.
        """
        # Add user message to history
        self.conversation.add_user_message(user_input)

        # Check for tool commands first
        tool_result = self._check_tool_commands(user_input)
        if tool_result:
            response = await self._generate_tool_response(user_input, tool_result)
            self.conversation.add_assistant_message(response.message)
            return response

        # Use RAG pipeline for context
        rag_response = None
        if use_rag:
            rag_response = await self.rag_pipeline.query(
                question=user_input,
                conversation_history=self.conversation.get_context(include_system=False),
                mode=self.mode.value,
            )

        # Generate response
        response = await self._generate_response(user_input, rag_response)

        # Add to history
        self.conversation.add_assistant_message(
            response.message,
            metadata={"sources": response.sources},
        )

        return response

    def _check_tool_commands(self, user_input: str) -> Optional[dict]:
        """Check if input is a tool command.

        Args:
            user_input: User's input text.

        Returns:
            Tool result if command detected, None otherwise.
        """
        input_lower = user_input.lower().strip()

        # Dice rolling
        if input_lower.startswith(("roll ", "/roll ", "/r ")):
            expression = user_input.split(" ", 1)[1] if " " in user_input else "1d20"
            result = self.tools.roll_dice(expression)
            return {"type": "dice", "result": result}

        # NPC generation
        if input_lower.startswith(("generate npc", "create npc", "/npc")):
            # Parse role from command
            parts = user_input.split(" ")
            role = parts[-1] if len(parts) > 2 else "merchant"
            result = self.tools.generate_npc(role=role)
            return {"type": "npc", "result": result}

        # Encounter generation
        if input_lower.startswith(("generate encounter", "create encounter", "/encounter")):
            # Default encounter params
            result = self.tools.generate_encounter(
                difficulty="medium",
                environment="dungeon",
                party_level=3,
            )
            return {"type": "encounter", "result": result}

        # Start combat
        if input_lower.startswith(("/combat", "start combat")):
            return {"type": "combat_start", "result": None}

        # Next turn in combat
        if input_lower.startswith(("/next", "next turn")):
            result = self.tools.next_turn()
            return {"type": "combat_next", "result": result}

        return None

    async def _generate_tool_response(
        self,
        user_input: str,
        tool_result: dict,
    ) -> DMResponse:
        """Generate response for a tool command.

        Args:
            user_input: Original user input.
            tool_result: Result from tool execution.

        Returns:
            DMResponse with formatted tool output.
        """
        tool_type = tool_result["type"]
        result = tool_result["result"]

        if tool_type == "dice":
            dice: DiceResult = result
            message = f"**Rolled {dice.expression}:** {dice.rolls}"
            if dice.modifier != 0:
                message += f" + {dice.modifier}" if dice.modifier > 0 else f" - {abs(dice.modifier)}"
            message += f" = **{dice.total}**"
            if dice.critical:
                message += " (Critical!)" if dice.total > 10 else " (Critical Fail!)"

            return DMResponse(
                message=message,
                tool_results=[{"type": "dice", "result": dice.model_dump()}],
            )

        elif tool_type == "npc":
            npc: NPCResult = result
            message = f"**{npc.name}** ({npc.race} {npc.role})\n\n"
            message += f"*Appearance:* {npc.appearance}\n"
            message += f"*Personality:* {', '.join(npc.personality)}\n"
            message += f"*Motivations:* {', '.join(npc.motivations)}\n"
            message += f"*Voice Notes:* {npc.voice_notes}"
            if npc.secret:
                message += f"\n\n*Secret:* {npc.secret}"

            return DMResponse(
                message=message,
                tool_results=[{"type": "npc", "result": npc.model_dump()}],
            )

        elif tool_type == "encounter":
            enc: EncounterResult = result
            message = f"**{enc.difficulty.title()} Encounter** ({enc.environment}, Level {enc.party_level})\n\n"
            message += "*Monsters:*\n"
            for m in enc.monsters:
                message += f"- {m['name']} (CR {m['cr']})\n"
            message += f"\n*Total XP:* {enc.total_xp}\n"
            message += f"*Description:* {enc.description}\n"
            message += f"*Tactics:* {enc.tactics}"

            return DMResponse(
                message=message,
                tool_results=[{"type": "encounter", "result": enc.model_dump()}],
            )

        elif tool_type == "combat_next":
            if result:
                current = result["current"]
                message = f"**Round {result['round']}** - {current['name']}'s turn"
                message += f" ({current['hp']}/{current['max_hp']} HP)"
            else:
                message = "No combat active. Use /combat to start."

            return DMResponse(
                message=message,
                tool_results=[{"type": "combat", "result": result}] if result else [],
            )

        return DMResponse(message="Command processed.")

    async def _generate_response(
        self,
        user_input: str,
        rag_response=None,
    ) -> DMResponse:
        """Generate a response using the LLM.

        Args:
            user_input: User's input.
            rag_response: Optional RAG response with context.

        Returns:
            DMResponse with generated content.
        """
        # Build context for the prompt
        context = self.conversation.get_context(include_system=True)

        # Add RAG context if available
        if rag_response and rag_response.context_used:
            sources_text = "\n".join([
                f"- {s.get('source', 'unknown')}: {s.get('type', 'unknown')}"
                for s in rag_response.sources[:5]
            ])
            context_note = {
                "role": "system",
                "content": f"Relevant context has been retrieved. Sources consulted:\n{sources_text}",
            }
            context.insert(1, context_note)  # After system prompt

        # Generate response
        response = await self.openai.chat.completions.create(
            model=self.model,
            messages=context,
            temperature=0.7 if self.mode == DMMode.AUTONOMOUS else 0.3,
            max_tokens=1000,
        )

        message = response.choices[0].message.content

        # Build suggestions based on mode and query type
        suggestions = []
        if self.mode == DMMode.ASSISTANT and rag_response:
            suggestions = self._generate_suggestions(rag_response.query_type)

        return DMResponse(
            message=message,
            query_type=rag_response.query_type if rag_response else None,
            sources=rag_response.sources if rag_response else [],
            suggestions=suggestions,
        )

    def _generate_suggestions(self, query_type: Optional[QueryType]) -> list[str]:
        """Generate contextual suggestions.

        Args:
            query_type: The classified query type.

        Returns:
            List of suggested follow-up actions.
        """
        if not query_type:
            return []

        suggestions_map = {
            QueryType.RULES_LOOKUP: [
                "Roll for it?",
                "See related rules",
                "Common mistakes to avoid",
            ],
            QueryType.ENCOUNTER_GENERATION: [
                "Generate another encounter",
                "Adjust difficulty",
                "Add terrain features",
            ],
            QueryType.NPC_GENERATION: [
                "Generate another NPC",
                "Create a rival for this NPC",
                "Add a secret or hook",
            ],
            QueryType.CAMPAIGN_STATE: [
                "View related NPCs",
                "Check location details",
                "Review recent events",
            ],
            QueryType.CAMPAIGN_HISTORY: [
                "Full session recap",
                "Find related events",
                "Check NPC involvement",
            ],
        }

        return suggestions_map.get(query_type, [])

    def roll_dice(self, expression: str) -> DiceResult:
        """Roll dice using standard notation.

        Args:
            expression: Dice expression like "2d6+3".

        Returns:
            DiceResult with the roll outcome.
        """
        return self.tools.roll_dice(expression)

    def generate_npc(
        self,
        role: str,
        race: Optional[str] = None,
    ) -> NPCResult:
        """Generate a random NPC.

        Args:
            role: NPC's role.
            race: Optional race.

        Returns:
            NPCResult with NPC details.
        """
        return self.tools.generate_npc(role=role, race=race)

    def generate_encounter(
        self,
        difficulty: str = "medium",
        environment: str = "dungeon",
        party_level: int = 3,
        party_size: int = 4,
    ) -> EncounterResult:
        """Generate a combat encounter.

        Args:
            difficulty: Encounter difficulty.
            environment: Environment type.
            party_level: Average party level.
            party_size: Number of party members.

        Returns:
            EncounterResult with encounter details.
        """
        return self.tools.generate_encounter(
            difficulty=difficulty,
            environment=environment,
            party_level=party_level,
            party_size=party_size,
        )

    def get_conversation_history(self) -> list[dict]:
        """Get conversation history.

        Returns:
            List of message dicts.
        """
        return self.conversation.export_history()

    def clear_history(self) -> None:
        """Clear conversation history."""
        self.conversation.clear()
