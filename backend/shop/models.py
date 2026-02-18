"""Pydantic models for the shop system."""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ShopSize(str, Enum):
    """Shop size determines inventory count and rarity distribution."""

    SMALL = "small"      # 5-10 items
    MEDIUM = "medium"    # 10-20 items
    LARGE = "large"      # 20-40 items


class ShopSpecialty(str, Enum):
    """Shop specialty determines item pool and shopkeeper personality."""

    WEAPONS = "weapons"
    ARMOR = "armor"
    POTIONS = "potions"
    GENERAL = "general"
    MAGIC_ITEMS = "magic_items"
    CURIOSITIES = "curiosities"
    SCROLLS = "scrolls"
    ADVENTURING_GEAR = "adventuring_gear"
    BLACKSMITH = "blacksmith"


class ItemRarity(str, Enum):
    """D&D 5e item rarity tiers."""

    COMMON = "common"
    UNCOMMON = "uncommon"
    RARE = "rare"
    VERY_RARE = "very_rare"
    LEGENDARY = "legendary"


class ItemCategory(str, Enum):
    """Item categories for organization."""

    WEAPON = "weapon"
    ARMOR = "armor"
    POTION = "potion"
    SCROLL = "scroll"
    WONDROUS = "wondrous"
    GEAR = "gear"
    TOOL = "tool"
    AMMUNITION = "ammunition"


class ShopItem(BaseModel):
    """An item in a shop's inventory."""

    name: str
    description: Optional[str] = None
    price_gp: float = Field(ge=0)
    quantity: int = Field(ge=0, default=1)
    rarity: ItemRarity = ItemRarity.COMMON
    category: ItemCategory = ItemCategory.GEAR
    magical: bool = False
    weight: Optional[float] = None

    # Graph entity ID (set after persistence)
    entity_id: Optional[str] = None


class ShopProfile(BaseModel):
    """Complete shop profile."""

    # Identity
    entity_id: str
    name: str
    description: Optional[str] = None

    # Configuration
    shop_size: ShopSize = ShopSize.MEDIUM
    shop_specialty: ShopSpecialty = ShopSpecialty.GENERAL
    gold_reserves: float = 500.0

    # Relationships
    shopkeeper_id: Optional[str] = None
    location_id: Optional[str] = None

    # Inventory (populated from graph)
    inventory: list[ShopItem] = Field(default_factory=list)

    # Shopkeeper info (populated from NPC registry)
    shopkeeper_name: Optional[str] = None
    shopkeeper_race: Optional[str] = None
    shopkeeper_description: Optional[str] = None
    shopkeeper_personality: Optional[dict] = None


class ShopGenerateRequest(BaseModel):
    """Request to generate a new shop."""

    size: ShopSize = ShopSize.MEDIUM
    specialty: ShopSpecialty = ShopSpecialty.GENERAL
    name: Optional[str] = None
    shopkeeper_name: Optional[str] = None
    shopkeeper_race: Optional[str] = None
    location_id: Optional[str] = None


class ShopChatMessage(BaseModel):
    """A single message in the shop chat history."""

    role: str  # "user" or "shopkeeper"
    content: str


class ShopChatRequest(BaseModel):
    """Request to chat with a shopkeeper."""

    message: str
    player_name: Optional[str] = None
    conversation_history: list[ShopChatMessage] = Field(default_factory=list)


class ShopChatResponse(BaseModel):
    """Response from a shopkeeper chat."""

    response: str
    transactions: list[dict] = Field(default_factory=list)
