"""NPC Agent for AI-controlled NPCs."""

import json
import logging
from typing import Optional

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from backend.core.config import settings
from backend.discord.models import NPCFullProfile, NPCPersonality
from backend.discord.combat_models import (
    CombatActionType,
    NPCCombatDecision,
)
from backend.discord.context_builder import NPCContextBuilder

logger = logging.getLogger(__name__)


class NPCResponse(BaseModel):
    """Response from an NPC."""

    message: str
    emotion: Optional[str] = None
    action: Optional[str] = None


class NPCAgent:
    """AI-powered NPC decision engine.

    Generates personality-consistent responses and combat decisions
    for NPCs based on their profile and campaign context.
    """

    def __init__(self):
        """Initialize the NPC agent."""
        self.openai = AsyncOpenAI(api_key=settings.openai_api_key)
        self.model = settings.openai_model
        self.context_builder = NPCContextBuilder()

    def _build_system_prompt(self, npc: NPCFullProfile) -> str:
        """Build a system prompt for the NPC.

        Args:
            npc: The NPC's full profile.

        Returns:
            System prompt string for LLM.
        """
        personality = npc.personality

        # Base identity
        prompt_parts = [
            f"You are {npc.name}, a {npc.race} {npc.role} in a D&D 5e campaign.",
        ]

        # Add description if present
        if npc.description:
            prompt_parts.append(f"\n**Background:** {npc.description}")

        # Personality traits
        if personality.personality_traits:
            traits = ", ".join(personality.personality_traits)
            prompt_parts.append(f"\n**Personality Traits:** {traits}")

        # Speech style
        if personality.speech_style and personality.speech_style != "normal":
            style_descriptions = {
                "formal": "You speak formally and properly, with sophisticated vocabulary.",
                "casual": "You speak casually and informally, like talking to friends.",
                "archaic": "You speak in an old-fashioned manner, using 'thee', 'thou', and archaic phrases.",
                "broken": "You speak broken Common, with simple sentences and occasional grammatical errors.",
                "eloquent": "You speak eloquently and poetically, with flowery language.",
                "gruff": "You speak in short, gruff sentences. You don't waste words.",
                "mysterious": "You speak cryptically and mysteriously, often in riddles or half-truths.",
            }
            style_desc = style_descriptions.get(
                personality.speech_style,
                f"You speak in a {personality.speech_style} manner.",
            )
            prompt_parts.append(f"\n**Speech Style:** {style_desc}")

        # Catchphrases
        if personality.catchphrases:
            phrases = ", ".join(f'"{p}"' for p in personality.catchphrases[:3])
            prompt_parts.append(
                f"\n**Catchphrases:** You occasionally use phrases like {phrases}"
            )

        # Secrets (NPC knows but shouldn't reveal easily)
        if personality.secrets:
            secrets = "; ".join(personality.secrets[:2])
            prompt_parts.append(
                f"\n**Secrets (don't reveal easily):** {secrets}"
            )

        # Relationships
        if npc.allied_with:
            allies = ", ".join(npc.allied_with[:5])
            prompt_parts.append(f"\n**Allies:** {allies}")
        if npc.hostile_to:
            enemies = ", ".join(npc.hostile_to[:5])
            prompt_parts.append(f"\n**Enemies:** {enemies}")

        # Combat disposition (brief summary)
        prompt_parts.append(f"\n**Combat Style:** {personality.combat_style}")
        prompt_parts.append(
            f"**Aggression:** {'High' if personality.aggression_level > 0.7 else 'Moderate' if personality.aggression_level > 0.3 else 'Low'}"
        )

        # Core instructions
        prompt_parts.append(
            "\n\n**IMPORTANT RULES:**\n"
            "- Stay in character at ALL times\n"
            "- Respond as this character would, not as a helpful AI\n"
            "- Never break character or reference being an AI\n"
            "- React based on your personality and relationships\n"
            "- Keep responses concise (1-3 sentences for casual talk)\n"
            "- You can express emotions, make threats, or be rude if in character"
        )

        return "".join(prompt_parts)

    def _build_combat_system_prompt(self, npc: NPCFullProfile) -> str:
        """Build a system prompt for combat decision-making.

        Args:
            npc: The NPC's full profile.

        Returns:
            System prompt for combat decisions.
        """
        personality = npc.personality
        stat_block = npc.stat_block

        prompt_parts = [
            f"You are deciding combat actions for {npc.name}, a {npc.race} {npc.role}.",
            f"\n\n**Combat Style:** {personality.combat_style}",
            f"**Aggression Level:** {personality.aggression_level:.0%}",
            f"**Retreat Threshold:** Below {personality.retreat_threshold:.0%} HP",
        ]

        if personality.preferred_targets:
            prompt_parts.append(
                f"**Preferred Targets:** {', '.join(personality.preferred_targets)}"
            )

        # Available attacks
        prompt_parts.append("\n**Available Attacks:**")
        for attack in stat_block.attacks:
            prompt_parts.append(
                f"- {attack['name']}: +{attack['bonus']} to hit, {attack['damage']} damage"
            )

        # Special abilities
        if stat_block.special_abilities:
            prompt_parts.append("\n**Special Abilities:**")
            for ability in stat_block.special_abilities:
                prompt_parts.append(f"- {ability['name']}: {ability['description']}")

        # Spells
        if stat_block.spells:
            prompt_parts.append("\n**Spells Available:**")
            for level, spells in stat_block.spells.items():
                if spells:
                    prompt_parts.append(f"- Level {level}: {', '.join(spells)}")

        # Combat behavior guidance
        style_guidance = {
            "aggressive": "Attack the biggest threat. Press the advantage. Don't retreat easily.",
            "defensive": "Protect allies. Focus on staying alive. Use cover and defensive abilities.",
            "tactical": "Analyze the situation. Target weak enemies first. Use abilities strategically.",
            "cowardly": "Avoid direct confrontation. Attack from safety. Flee if threatened.",
            "berserker": "Attack the nearest enemy. Ignore defense. Never retreat.",
            "balanced": "Adapt to the situation. Balance offense and defense.",
        }
        guidance = style_guidance.get(
            personality.combat_style,
            "Fight according to your training and instincts.",
        )
        prompt_parts.append(f"\n**Combat Guidance:** {guidance}")

        # Output format
        prompt_parts.append(
            "\n\n**Response Format:**\n"
            "You must respond with a JSON object containing:\n"
            '- "action_type": one of [attack, cast_spell, use_ability, move, dash, dodge, disengage, help, hide, ready, use_item, multiattack, flee, surrender, dialogue]\n'
            '- "action_name": specific attack/spell/ability name (if applicable)\n'
            '- "target_name": target name (if applicable)\n'
            '- "movement_description": brief movement description (if moving)\n'
            '- "reasoning": brief tactical reasoning (1 sentence)\n'
            '- "combat_dialogue": something the NPC says (optional, in character)\n'
        )

        return "".join(prompt_parts)

    async def generate_response(
        self,
        npc: NPCFullProfile,
        user_message: str,
        user_name: str,
        conversation_history: Optional[list[dict]] = None,
    ) -> NPCResponse:
        """Generate an in-character response from the NPC.

        Args:
            npc: The NPC's full profile.
            user_message: What the user/player said.
            user_name: Who said it.
            conversation_history: Optional recent conversation context.

        Returns:
            NPCResponse with the character's response.
        """
        # Build context from knowledge graph
        campaign_context = await self.context_builder.build_context(
            npc=npc,
            user_message=user_message,
            user_name=user_name,
        )

        # Build messages
        messages = [
            {"role": "system", "content": self._build_system_prompt(npc)},
        ]

        # Add campaign context if available
        if campaign_context:
            messages.append({
                "role": "system",
                "content": f"**Relevant Context:**\n{campaign_context}",
            })

        # Add conversation history
        if conversation_history:
            for msg in conversation_history[-5:]:  # Last 5 messages
                messages.append({
                    "role": msg.get("role", "user"),
                    "content": msg.get("content", ""),
                })

        # Add current message
        messages.append({
            "role": "user",
            "content": f"[{user_name}]: {user_message}",
        })

        try:
            response = await self.openai.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.8,  # Higher for more personality
                max_tokens=300,
            )

            message = response.choices[0].message.content.strip()

            # Parse emotion/action hints if present
            emotion = None
            action = None
            if message.startswith("*"):
                # Parse action/emotion in asterisks
                end = message.find("*", 1)
                if end > 0:
                    action = message[1:end].strip()
                    message = message[end + 1:].strip()

            return NPCResponse(
                message=message,
                emotion=emotion,
                action=action,
            )

        except Exception as e:
            logger.error(f"Error generating NPC response for {npc.name}: {e}")
            # Fallback to a generic in-character response
            return NPCResponse(
                message=f"*{npc.name} regards you silently.*",
                action="silence",
            )

    async def decide_combat_action(
        self,
        npc: NPCFullProfile,
        combat_state: dict,
        available_targets: list[dict],
    ) -> NPCCombatDecision:
        """Decide what action the NPC takes in combat.

        Args:
            npc: The NPC's full profile.
            combat_state: Current combat state (round, initiative order, etc.).
            available_targets: List of valid targets with their stats.

        Returns:
            NPCCombatDecision describing the action to take.
        """
        # Build combat context
        combat_context = await self.context_builder.build_combat_context(
            npc=npc,
            combat_state=combat_state,
            available_targets=available_targets,
        )

        messages = [
            {"role": "system", "content": self._build_combat_system_prompt(npc)},
            {"role": "user", "content": f"**Current Situation:**\n{combat_context}\n\nWhat action do you take?"},
        ]

        try:
            response = await self.openai.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.5,  # Lower for more consistent decisions
                max_tokens=500,
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content
            decision_data = json.loads(content)

            # Map action type
            action_type_str = decision_data.get("action_type", "attack").lower()
            try:
                action_type = CombatActionType(action_type_str)
            except ValueError:
                action_type = CombatActionType.ATTACK

            # Build rolls needed
            rolls_needed = []
            if action_type == CombatActionType.ATTACK:
                # Find the attack being used
                attack_name = decision_data.get("action_name")
                attack = self._find_attack(npc, attack_name)
                if attack:
                    rolls_needed = [
                        {"type": "attack", "expression": f"1d20+{attack['bonus']}"},
                        {"type": "damage", "expression": attack["damage"]},
                    ]

            return NPCCombatDecision(
                npc_id=npc.entity_id,
                round=combat_state.get("round", 1),
                action_type=action_type,
                action_name=decision_data.get("action_name"),
                target_name=decision_data.get("target_name"),
                target_id=self._find_target_id(
                    decision_data.get("target_name"),
                    available_targets,
                ),
                movement_description=decision_data.get("movement_description"),
                reasoning=decision_data.get("reasoning", "No reasoning provided."),
                combat_dialogue=decision_data.get("combat_dialogue"),
                rolls_needed=rolls_needed,
            )

        except Exception as e:
            logger.error(f"Error deciding combat action for {npc.name}: {e}")
            # Fallback to basic attack
            return self._fallback_combat_decision(npc, combat_state, available_targets)

    def _find_attack(self, npc: NPCFullProfile, attack_name: Optional[str]) -> Optional[dict]:
        """Find an attack by name or return the first available.

        Args:
            npc: The NPC profile.
            attack_name: Name of the attack to find.

        Returns:
            Attack dict or None.
        """
        attacks = npc.stat_block.attacks
        if not attacks:
            return None

        if attack_name:
            for attack in attacks:
                if attack["name"].lower() == attack_name.lower():
                    return attack

        # Return first attack as fallback
        return attacks[0]

    def _find_target_id(
        self,
        target_name: Optional[str],
        available_targets: list[dict],
    ) -> Optional[str]:
        """Find target ID by name.

        Args:
            target_name: Name to search for.
            available_targets: List of available targets.

        Returns:
            Target ID or None.
        """
        if not target_name:
            return None

        for target in available_targets:
            if target.get("name", "").lower() == target_name.lower():
                return target.get("id")

        return None

    def _fallback_combat_decision(
        self,
        npc: NPCFullProfile,
        combat_state: dict,
        available_targets: list[dict],
    ) -> NPCCombatDecision:
        """Generate a fallback combat decision when LLM fails.

        Args:
            npc: The NPC profile.
            combat_state: Current combat state.
            available_targets: Available targets.

        Returns:
            Basic attack decision.
        """
        # Pick first target
        target = available_targets[0] if available_targets else None
        attack = self._find_attack(npc, None)

        rolls_needed = []
        if attack:
            rolls_needed = [
                {"type": "attack", "expression": f"1d20+{attack['bonus']}"},
                {"type": "damage", "expression": attack["damage"]},
            ]

        return NPCCombatDecision(
            npc_id=npc.entity_id,
            round=combat_state.get("round", 1),
            action_type=CombatActionType.ATTACK,
            action_name=attack["name"] if attack else "Unarmed Strike",
            target_name=target["name"] if target else None,
            target_id=target.get("id") if target else None,
            reasoning="Attacking the nearest enemy.",
            rolls_needed=rolls_needed,
        )

    async def generate_combat_dialogue(
        self,
        npc: NPCFullProfile,
        situation: str,
    ) -> str:
        """Generate combat dialogue for a specific situation.

        Args:
            npc: The NPC profile.
            situation: Description of what just happened.

        Returns:
            In-character combat dialogue.
        """
        messages = [
            {"role": "system", "content": self._build_system_prompt(npc)},
            {
                "role": "user",
                "content": (
                    f"You are in combat. {situation}\n\n"
                    "Generate a short (1 sentence) combat quip or reaction. "
                    "Stay in character. Be dramatic but brief."
                ),
            },
        ]

        try:
            response = await self.openai.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.9,
                max_tokens=100,
            )

            return response.choices[0].message.content.strip()

        except Exception as e:
            logger.error(f"Error generating combat dialogue for {npc.name}: {e}")
            return ""

    async def evaluate_retreat(
        self,
        npc: NPCFullProfile,
        current_hp: int,
        combat_state: dict,
    ) -> bool:
        """Evaluate whether the NPC should retreat.

        Args:
            npc: The NPC profile.
            current_hp: Current hit points.
            combat_state: Current combat state.

        Returns:
            True if NPC should retreat.
        """
        max_hp = npc.stat_block.max_hit_points
        hp_percent = current_hp / max_hp if max_hp > 0 else 0

        # Below retreat threshold?
        if hp_percent <= npc.personality.retreat_threshold:
            # Combat style affects retreat
            if npc.personality.combat_style == "berserker":
                return False  # Never retreats
            if npc.personality.combat_style == "cowardly":
                return True  # Always retreats when threshold hit

            # Others consider allies
            allies_alive = sum(
                1 for c in combat_state.get("initiative_order", [])
                if c.get("side") == "enemy" and c.get("hp", 0) > 0
            )

            # Retreat if alone and hurt
            return allies_alive <= 1

        return False
