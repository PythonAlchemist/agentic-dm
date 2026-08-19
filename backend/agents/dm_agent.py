"""DM Agent for running games and assisting DMs."""

import logging
from typing import Optional

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from backend.core.config import settings
from backend.rag import HybridRAGPipeline, QueryType
from backend.agents import canon_context
from backend.agents.tools import DMTools, DiceResult, EncounterResult, NPCResult
from backend.agents.conversation import ConversationManager, MessageRole
from backend.agents.prompts import SYSTEM_PROMPT
from backend.agents.subgraph import Subgraph, seed as seed_subgraph
from backend.canon.retrieval import (
    PATH_GRAPH,
    PATH_TEXT,
    CanonRetriever,
    Retrieval,
)
from backend.core.pricing import Usage, estimate

logger = logging.getLogger(__name__)


class DMResponse(BaseModel):
    """Response from the DM Agent."""

    message: str
    query_type: Optional[QueryType] = None
    tool_results: list[dict] = Field(default_factory=list)
    sources: list[dict] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    #: Tokens the call consumed and what the rate table says that cost. Absent
    #: on a tool command, which never reaches a model. Reported rather than
    #: merely logged: the number that matters to somebody paying for this is the
    #: one attached to the answer they just read.
    usage: Optional[dict] = None
    cost: Optional[dict] = None
    #: What retrieval did -- which names anchored, which path answered, what the
    #: budget cut. The dashboard shows it beside the answer so a thin answer can
    #: be traced to thin context rather than blamed on the model.
    retrieval: Optional[dict] = None


class DMAgent:
    """AI Dungeon Master agent."""

    def __init__(
        self,
        campaign_id: Optional[str] = None,
        campaign_context: Optional[dict] = None,
        canon: Optional[CanonRetriever] = None,
        model: Optional[str] = None,
        depth: Optional[canon_context.Depth] = None,
    ):
        """Initialize the DM Agent.

        Args:
            campaign_id: Optional campaign to load context from.
            campaign_context: Optional campaign context fields to inject into system prompt.
            canon: Read path into the canon graph. Injectable so a test can
                exercise the grounding without a live Neo4j.
        """
        self.campaign_id = campaign_id
        self.campaign_context = campaign_context

        # Initialize components
        self.openai = AsyncOpenAI(api_key=settings.openai_api_key)
        self.model = model or settings.openai_model
        self.depth = depth or canon_context.Depth()
        self.rag_pipeline = HybridRAGPipeline()
        self.tools = DMTools()
        self.canon = canon or CanonRetriever(
            limit=self.depth.passages, passage_width=self.depth.passage_width
        )
        self.conversation = ConversationManager()
        #: What this conversation is holding, as graph entities. The transcript
        #: is bounded and short; THIS is how a follow-up knows who "him" is.
        self.subgraph = Subgraph()

        # Set system prompt
        self._set_system_prompt()

    def _set_system_prompt(self) -> None:
        """Set the system prompt, optionally enriched with campaign context."""
        prompt = SYSTEM_PROMPT

        if self.campaign_context:
            context_parts = []
            field_labels = {
                "name": "Campaign",
                "setting": "Setting",
                "world_description": "World",
                "theme": "Theme",
                "rule_system": "Rule System",
                "level_range": "Level Range",
                "house_rules": "House Rules",
                "allowed_sources": "Allowed Sources",
                "premise": "Premise",
                "current_story_arc": "Current Story Arc",
                "dm_notes": "DM Notes",
            }
            for key, label in field_labels.items():
                value = self.campaign_context.get(key)
                if value:
                    context_parts.append(f"- **{label}:** {value}")

            if context_parts:
                prompt += "\n\n**Active Campaign Context:**\n" + "\n".join(context_parts)

        self.conversation.set_system_prompt(prompt)

    async def process_message(
        self,
        user_input: str,
        use_rag: bool = True,
        use_canon: bool = True,
    ) -> DMResponse:
        """Process a user message.

        Args:
            user_input: User's input text.
            use_rag: Whether to use RAG for context.
            use_canon: Whether to ground the answer in the canon graph.

        Returns:
            DMResponse with the agent's response.
        """
        # A turn is one exchange, and everything touched during it is pinned
        # against eviction -- see `Subgraph.evict`.
        self.subgraph.turn += 1

        # Add user message to history
        self.conversation.add_user_message(user_input)

        # Check for tool commands first
        tool_result = self._check_tool_commands(user_input)
        if tool_result:
            response = await self._generate_tool_response(user_input, tool_result)
            self.conversation.add_assistant_message(response.message)
            return response

        # Retrieve canon BEFORE the RAG pipeline, and unconditionally when
        # enabled. It is deterministic and costs no API call, so there is
        # nothing to gate it on -- and a heuristic deciding when a question is
        # "about the book" would fail exactly on the questions a DM most needs
        # grounded. A question naming nothing simply retrieves little.
        retrieval = self._retrieve_canon(user_input) if use_canon else None
        if retrieval is not None:
            seed_subgraph(self.subgraph, retrieval)
            self.subgraph.evict(self.depth.subgraph_budget)

        # Use RAG pipeline for context
        rag_response = None
        if use_rag:
            rag_response = await self.rag_pipeline.query(
                question=user_input,
                conversation_history=self.conversation.get_context(include_system=False),
            )

        # Generate response
        response = await self._generate_response(user_input, rag_response, retrieval)

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

    def _retrieve_canon(self, user_input: str) -> Retrieval:
        """Canon for this question. An EMPTY retrieval if the graph is unreachable.

        Empty rather than None, and the difference is the whole point of the
        `except`. A DM mid-session should get a degraded answer rather than a
        stack trace -- but "degraded" must mean the model is TOLD the canon
        covers nothing, which is what an empty retrieval renders to. Returning
        None would omit the block entirely, and a model with no canon block and
        no instruction about one answers from its own memory of the published
        adventure. That is the failure this whole path exists to prevent, and it
        would appear exactly when the database is down: silently, and only in
        production.
        """
        try:
            return self.canon.retrieve(user_input)
        except Exception:  # noqa: BLE001 - degraded answer beats a crash mid-session
            logger.warning("canon retrieval failed; answering without it", exc_info=True)
            return Retrieval(question=user_input)

    async def _generate_response(
        self,
        user_input: str,
        rag_response=None,
        retrieval=None,
    ) -> DMResponse:
        """Generate a response using the LLM.

        Args:
            user_input: User's input.
            rag_response: Optional RAG response with context.
            retrieval: Optional canon retrieval to ground the answer in.

        Returns:
            DMResponse with generated content.
        """
        # Build context for the prompt
        context = self.conversation.get_context(include_system=True)

        # The canon block carries the PASSAGES THEMSELVES, not a list of what
        # was consulted. Inserted after the system prompt and before the
        # conversation, so the model reads the book's words before the question
        # rather than after its own previous answers.
        canon_sources: list[dict] = []
        retrieval_report: Optional[dict] = None
        if retrieval is not None:
            shown = canon_context.apply(retrieval, self.depth)
            context.insert(
                1,
                {
                    "role": "system",
                    "content": canon_context.render(shown, max_edges=self.depth.max_edges),
                },
            )
            # AFTER the canon block, so the model reads the book's words
            # first and then what the conversation has been about -- the same
            # ordering argument as inserting canon before the question.
            summary = self.subgraph.render(self.depth.include_proposed)
            if summary:
                context.insert(2, {"role": "system", "content": summary})

            canon_sources = canon_context.sources(shown)
            # Reported off the UNFILTERED retrieval on purpose: a reader needs
            # to see that 30 proposed edges existed and were withheld, not that
            # there were none.
            retrieval_report = {
                # How the QUESTION resolved -- on a name, or on nothing. This
                # says nothing about which path produced any given passage.
                "path": retrieval.path,
                # WHICH PATH PUT EACH PASSAGE THERE. A result that anchored on a
                # name now also carries text passages, because `TEXT_SLOTS`
                # reserves room for them, so `path` alone reported `graph` for a
                # mixed result and the panel showed "by name" over passages
                # Lucene had found. The same mislabelling was fixed in
                # `canon_context.sources` and in the evaluation harness, which
                # had been crediting a resolved name for answers a keyword
                # match earned; this was the third copy of it.
                "passages_by_path": {
                    PATH_GRAPH: sum(
                        1 for p in shown.passages if p.path == PATH_GRAPH
                    ),
                    PATH_TEXT: sum(1 for p in shown.passages if p.path == PATH_TEXT),
                },
                "anchors": [f"{a.surface} → {a.name}" for a in retrieval.anchors],
                "passages": len(shown.passages),
                "dropped": retrieval.dropped,
                "accepted_edges": len(retrieval.accepted),
                "proposed_edges": len(retrieval.proposed),
                "proposed_withheld": not self.depth.include_proposed,
                "loose": retrieval.loose,
                "terms": list(retrieval.terms),
                "miss_reason": retrieval.miss_reason,
            }

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
            messages=self._trim(context),
            temperature=0.5,
            max_tokens=1000,
        )

        message = response.choices[0].message.content
        usage = Usage.from_response(response)
        cost = estimate(self.model, usage)

        # Always generate suggestions
        suggestions = []
        if rag_response:
            suggestions = self._generate_suggestions(rag_response.query_type)

        # Canon citations FIRST: they are the ones a DM can open the book to.
        return DMResponse(
            message=message,
            query_type=rag_response.query_type if rag_response else None,
            sources=canon_sources + (rag_response.sources if rag_response else []),
            suggestions=suggestions,
            usage={"input": usage.input_tokens, "output": usage.output_tokens,
                   "total": usage.total},
            cost=cost.as_dict(),
            retrieval=retrieval_report,
        )

    def _trim(self, context: list[dict]) -> list[dict]:
        """The system messages, plus the current question. THE TRANSCRIPT IS
        NOT THE MEMORY.

        This used to keep `history_turns` exchanges, defaulting to six. That is
        both too little to reach session 3 from session 7 and the wrong thing
        to enlarge: a bigger number re-sends old dialogue on every turn in the
        hope the answer is somewhere in it. What carries instead is the
        SUBGRAPH -- what the conversation is about, as entities with ids -- and
        the campaign plane, which the graph already holds. A long campaign
        grows the graph rather than the context.

        THE COST, ACCEPTED DELIBERATELY: conversational repair. "No, the other
        one", "shorter", "explain that again" are about the dialogue rather
        than about entities, and nothing in the subgraph holds them. Reference
        resolution is unaffected -- "him" works because Rictavio is a node with
        an id, not because the previous message is still in view.

        System messages are never trimmed: they carry the canon block, the
        subgraph, and the instructions for reading both.
        """
        system = [m for m in context if m["role"] == "system"]
        rest = [m for m in context if m["role"] != "system"]
        keep = 1  # the current question
        return system + rest[-keep:] if keep < len(rest) else system + rest

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
