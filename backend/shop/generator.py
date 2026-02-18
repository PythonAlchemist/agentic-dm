"""Shop generator with LLM-enhanced descriptions and inventory."""

import json
import logging
import random
from typing import Optional

from openai import AsyncOpenAI

from backend.core.config import settings
from backend.discord.models import NPCPersonality
from backend.discord.npc_registry import NPCRegistry
from backend.shop.models import (
    ItemCategory,
    ItemRarity,
    ShopGenerateRequest,
    ShopItem,
    ShopProfile,
    ShopSize,
    ShopSpecialty,
)
from backend.shop.registry import ShopRegistry
from backend.shop.srd_items import (
    generate_shop_name,
    get_gold_reserves,
    get_personality_template,
    select_items,
)

logger = logging.getLogger(__name__)

# Shopkeeper race options weighted by commonality
SHOPKEEPER_RACES = [
    "human", "human", "human", "human",
    "dwarf", "dwarf", "dwarf",
    "elf", "elf",
    "halfling", "halfling",
    "gnome", "gnome",
    "half-elf",
    "half-orc",
    "tiefling",
    "dragonborn",
]

# Role mappings by specialty
SPECIALTY_ROLES: dict[str, list[str]] = {
    "weapons": ["weaponsmith", "arms dealer", "retired soldier"],
    "armor": ["armorsmith", "plate maker", "former guard"],
    "potions": ["alchemist", "herbalist", "apothecary"],
    "general": ["merchant", "trader", "shopkeeper"],
    "magic_items": ["arcane dealer", "enchanter", "collector"],
    "curiosities": ["collector", "antiquarian", "curiosity dealer"],
    "scrolls": ["scribe", "wizard", "librarian"],
    "adventuring_gear": ["outfitter", "retired adventurer", "quartermaster"],
    "blacksmith": ["blacksmith", "master smith", "metalworker"],
}


class ShopGenerator:
    """Generates shops with LLM-enhanced descriptions."""

    def __init__(self):
        self.openai = AsyncOpenAI(api_key=settings.openai_api_key)
        self.model = settings.openai_model
        self.npc_registry = NPCRegistry()
        self.shop_registry = ShopRegistry()

    async def generate_shop(self, request: ShopGenerateRequest) -> ShopProfile:
        """Generate a complete shop with inventory and shopkeeper.

        Args:
            request: Shop generation parameters.

        Returns:
            Complete ShopProfile with inventory and shopkeeper.
        """
        # 1. Select items from SRD pools
        raw_items = select_items(
            specialty=request.specialty.value,
            size=request.size.value,
        )

        items = [
            ShopItem(
                name=item["name"],
                description=item.get("description"),
                price_gp=item["price_gp"],
                quantity=item.get("quantity", 1),
                rarity=ItemRarity(item.get("rarity", "common")),
                category=ItemCategory(item.get("category", "gear")),
                magical=item.get("magical", False),
                weight=item.get("weight"),
            )
            for item in raw_items
        ]

        # 2. Generate shop name
        shop_name = request.name or generate_shop_name(
            specialty=request.specialty.value,
            keeper_name=request.shopkeeper_name,
        )

        # 3. Determine shopkeeper details
        keeper_race = request.shopkeeper_race or random.choice(SHOPKEEPER_RACES)
        keeper_role = random.choice(
            SPECIALTY_ROLES.get(request.specialty.value, ["merchant"])
        )

        # 4. Generate shopkeeper personality from specialty template
        personality_template = get_personality_template(request.specialty.value)
        personality = NPCPersonality(
            personality_traits=personality_template.get("personality_traits", []),
            speech_style=personality_template.get("speech_style", "casual"),
            catchphrases=personality_template.get("catchphrases", []),
            knowledge_domains=personality_template.get("knowledge_domains", []),
            helpfulness=0.8,
            talkativeness=0.7,
            aggression_level=0.1,
            combat_style="cowardly",
            retreat_threshold=0.8,
        )

        # 5. LLM call for descriptions
        descriptions = await self._generate_descriptions(
            shop_name=shop_name,
            specialty=request.specialty.value,
            size=request.size.value,
            keeper_race=keeper_race,
            keeper_role=keeper_role,
            keeper_name=request.shopkeeper_name,
            items=items,
        )

        keeper_name = descriptions.get(
            "shopkeeper_name",
            request.shopkeeper_name or shop_name.split("'s")[0],
        )
        shop_description = descriptions.get("shop_description", "")
        keeper_description = descriptions.get("shopkeeper_backstory", "")

        # Update personality with LLM-generated catchphrases if present
        if descriptions.get("catchphrases"):
            personality.catchphrases = descriptions["catchphrases"]

        # 6. Create shopkeeper NPC via registry
        shopkeeper = self.npc_registry.create_npc_with_discord(
            name=keeper_name,
            race=keeper_race,
            role=keeper_role,
            description=keeper_description,
            personality=personality,
        )

        # 7. Calculate gold reserves
        gold = get_gold_reserves(request.size.value)

        # 8. Persist shop and inventory to graph
        shop = self.shop_registry.create_shop(
            name=shop_name,
            description=shop_description,
            shop_size=request.size,
            shop_specialty=request.specialty,
            gold_reserves=gold,
            shopkeeper_id=shopkeeper.entity_id,
            location_id=request.location_id,
            items=items,
        )

        return shop

    async def _generate_descriptions(
        self,
        shop_name: str,
        specialty: str,
        size: str,
        keeper_race: str,
        keeper_role: str,
        keeper_name: Optional[str],
        items: list[ShopItem],
    ) -> dict:
        """Use LLM to generate shop and shopkeeper descriptions.

        Args:
            shop_name: Name of the shop.
            specialty: Shop specialty.
            size: Shop size.
            keeper_race: Shopkeeper race.
            keeper_role: Shopkeeper role.
            keeper_name: Optional shopkeeper name.
            items: Selected inventory items.

        Returns:
            Dict with shop_description, shopkeeper_name, shopkeeper_backstory, catchphrases.
        """
        # Build item summary for context
        notable_items = [
            i for i in items
            if i.rarity in (ItemRarity.UNCOMMON, ItemRarity.RARE, ItemRarity.VERY_RARE, ItemRarity.LEGENDARY)
        ][:5]
        item_summary = ", ".join(i.name for i in notable_items) if notable_items else "standard fare"

        prompt = f"""Generate details for a D&D 5e {specialty} shop.

Shop: "{shop_name}" ({size} shop)
Shopkeeper: {keeper_race} {keeper_role}{f' named {keeper_name}' if keeper_name else ''}
Notable inventory: {item_summary}

Respond with JSON:
{{
  "shop_description": "2-3 sentence atmospheric description of the shop interior and vibe",
  "shopkeeper_name": "a fitting {keeper_race} name{f' (use: {keeper_name})' if keeper_name else ''}",
  "shopkeeper_backstory": "2-3 sentence backstory for the shopkeeper explaining how they came to own this shop",
  "catchphrases": ["phrase1", "phrase2", "phrase3"]
}}"""

        try:
            response = await self.openai.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a creative D&D worldbuilder. Generate vivid, concise descriptions. Respond with valid JSON only.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.9,
                max_tokens=500,
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content
            return json.loads(content)

        except Exception as e:
            logger.error(f"Error generating shop descriptions: {e}")
            # Fallback descriptions
            return {
                "shop_description": f"A {size} {specialty} shop with a well-stocked inventory.",
                "shopkeeper_name": keeper_name or "Merchant",
                "shopkeeper_backstory": f"A {keeper_race} {keeper_role} who has run this shop for years.",
                "catchphrases": get_personality_template(specialty).get("catchphrases", []),
            }
