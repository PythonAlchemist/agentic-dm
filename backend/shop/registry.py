"""Shop registry for Neo4j CRUD operations on shops and inventory."""

import json
from typing import Optional

from backend.discord.models import NPCPersonality
from backend.discord.npc_registry import NPCRegistry
from backend.graph.operations import CampaignGraphOps
from backend.graph.schema import EntityType, RelationshipType
from backend.shop.models import (
    ItemCategory,
    ItemRarity,
    ShopItem,
    ShopProfile,
    ShopSize,
    ShopSpecialty,
)


class ShopRegistry:
    """Registry for shop CRUD operations with Neo4j."""

    def __init__(self):
        self.graph_ops = CampaignGraphOps()
        self._shop_cache: dict[str, ShopProfile] = {}
        self._npc_registry = NPCRegistry()

    def create_shop(
        self,
        name: str,
        description: Optional[str] = None,
        shop_size: ShopSize = ShopSize.MEDIUM,
        shop_specialty: ShopSpecialty = ShopSpecialty.GENERAL,
        gold_reserves: float = 500.0,
        shopkeeper_id: Optional[str] = None,
        location_id: Optional[str] = None,
        items: Optional[list[ShopItem]] = None,
    ) -> ShopProfile:
        """Create a new shop with inventory in a batched transaction.

        Args:
            name: Shop name.
            description: Shop description.
            shop_size: Size category.
            shop_specialty: Specialty category.
            gold_reserves: Starting gold.
            shopkeeper_id: NPC entity ID for shopkeeper.
            location_id: Optional location entity ID.
            items: Initial inventory items.

        Returns:
            Created ShopProfile.
        """
        # Create shop entity
        shop_entity = self.graph_ops.create_entity(
            name=name,
            entity_type=EntityType.SHOP,
            description=description,
            properties={
                "shop_size": shop_size.value,
                "shop_specialty": shop_specialty.value,
                "gold_reserves": gold_reserves,
                "shopkeeper_id": shopkeeper_id or "",
            },
        )

        shop_id = shop_entity["id"]

        # Create relationships
        if shopkeeper_id:
            self.graph_ops.create_relationship(
                source_id=shopkeeper_id,
                target_id=shop_id,
                relationship_type=RelationshipType.OWNS,
            )

        if location_id:
            self.graph_ops.create_relationship(
                source_id=shop_id,
                target_id=location_id,
                relationship_type=RelationshipType.LOCATED_IN,
            )

        # Create item entities and link to shop
        created_items = []
        if items:
            for item in items:
                item_entity = self.graph_ops.create_entity(
                    name=item.name,
                    entity_type=EntityType.ITEM,
                    description=item.description,
                    properties={
                        "price_gp": item.price_gp,
                        "quantity": item.quantity,
                        "rarity": item.rarity.value,
                        "category": item.category.value,
                        "magical": item.magical,
                        "weight": item.weight or 0,
                        "shop_id": shop_id,
                    },
                )

                self.graph_ops.create_relationship(
                    source_id=shop_id,
                    target_id=item_entity["id"],
                    relationship_type=RelationshipType.CONTAINS,
                )

                created_items.append(ShopItem(
                    entity_id=item_entity["id"],
                    name=item.name,
                    description=item.description,
                    price_gp=item.price_gp,
                    quantity=item.quantity,
                    rarity=item.rarity,
                    category=item.category,
                    magical=item.magical,
                    weight=item.weight,
                ))

        # Build profile
        shopkeeper_name = None
        shopkeeper_race = None
        shopkeeper_description = None
        shopkeeper_personality = None

        if shopkeeper_id:
            keeper = self._npc_registry.get_npc(shopkeeper_id)
            if keeper:
                shopkeeper_name = keeper.name
                shopkeeper_race = keeper.race
                shopkeeper_description = keeper.description
                shopkeeper_personality = keeper.personality.model_dump()

        profile = ShopProfile(
            entity_id=shop_id,
            name=name,
            description=description,
            shop_size=shop_size,
            shop_specialty=shop_specialty,
            gold_reserves=gold_reserves,
            shopkeeper_id=shopkeeper_id,
            location_id=location_id,
            inventory=created_items,
            shopkeeper_name=shopkeeper_name,
            shopkeeper_race=shopkeeper_race,
            shopkeeper_description=shopkeeper_description,
            shopkeeper_personality=shopkeeper_personality,
        )

        self._shop_cache[shop_id] = profile
        return profile

    def get_shop(self, shop_id: str) -> Optional[ShopProfile]:
        """Get a shop profile by ID with inventory.

        Args:
            shop_id: Shop entity ID.

        Returns:
            ShopProfile or None.
        """
        if shop_id in self._shop_cache:
            return self._shop_cache[shop_id]

        entity = self.graph_ops.get_entity(shop_id)
        if not entity or entity.get("entity_type") != EntityType.SHOP.value:
            return None

        profile = self._entity_to_profile(entity)
        self._shop_cache[shop_id] = profile
        return profile

    def list_shops(self, limit: int = 50) -> list[ShopProfile]:
        """List all shops.

        Args:
            limit: Maximum results.

        Returns:
            List of ShopProfiles.
        """
        entities = self.graph_ops.list_entities(
            entity_type=EntityType.SHOP.value,
            limit=limit,
        )

        return [self._entity_to_profile(e) for e in entities]

    def update_shop(self, shop_id: str, updates: dict) -> Optional[ShopProfile]:
        """Update shop properties.

        Args:
            shop_id: Shop entity ID.
            updates: Properties to update (name, description, gold_reserves).

        Returns:
            Updated ShopProfile or None.
        """
        allowed_fields = {"name", "description", "gold_reserves", "shop_size", "shop_specialty"}
        filtered = {k: v for k, v in updates.items() if k in allowed_fields}

        if not filtered:
            return self.get_shop(shop_id)

        self.graph_ops.update_entity(shop_id, filtered)

        # Invalidate cache
        self._shop_cache.pop(shop_id, None)

        return self.get_shop(shop_id)

    def delete_shop(self, shop_id: str) -> bool:
        """Delete a shop and its inventory items.

        Args:
            shop_id: Shop entity ID.

        Returns:
            True if deleted.
        """
        # Delete inventory items first
        items = self._get_inventory_entities(shop_id)
        for item in items:
            self.graph_ops.delete_entity(item["id"])

        # Delete shop
        result = self.graph_ops.delete_entity(shop_id)

        # Invalidate cache
        self._shop_cache.pop(shop_id, None)

        return result

    def add_item(self, shop_id: str, item: ShopItem) -> Optional[ShopItem]:
        """Add an item to a shop's inventory.

        Args:
            shop_id: Shop entity ID.
            item: Item to add.

        Returns:
            Created ShopItem with entity_id or None.
        """
        shop = self.get_shop(shop_id)
        if not shop:
            return None

        item_entity = self.graph_ops.create_entity(
            name=item.name,
            entity_type=EntityType.ITEM,
            description=item.description,
            properties={
                "price_gp": item.price_gp,
                "quantity": item.quantity,
                "rarity": item.rarity.value,
                "category": item.category.value,
                "magical": item.magical,
                "weight": item.weight or 0,
                "shop_id": shop_id,
            },
        )

        self.graph_ops.create_relationship(
            source_id=shop_id,
            target_id=item_entity["id"],
            relationship_type=RelationshipType.CONTAINS,
        )

        # Invalidate cache
        self._shop_cache.pop(shop_id, None)

        return ShopItem(
            entity_id=item_entity["id"],
            name=item.name,
            description=item.description,
            price_gp=item.price_gp,
            quantity=item.quantity,
            rarity=item.rarity,
            category=item.category,
            magical=item.magical,
            weight=item.weight,
        )

    def update_item(
        self,
        shop_id: str,
        item_id: str,
        updates: dict,
    ) -> Optional[ShopItem]:
        """Update an item in a shop's inventory.

        Args:
            shop_id: Shop entity ID.
            item_id: Item entity ID.
            updates: Properties to update.

        Returns:
            Updated ShopItem or None.
        """
        allowed_fields = {
            "name", "description", "price_gp", "quantity",
            "rarity", "category", "magical", "weight",
        }
        filtered = {k: v for k, v in updates.items() if k in allowed_fields}

        if not filtered:
            return None

        entity = self.graph_ops.update_entity(item_id, filtered)
        if not entity:
            return None

        # Invalidate cache
        self._shop_cache.pop(shop_id, None)

        return self._entity_to_item(entity)

    def remove_item(self, shop_id: str, item_id: str) -> bool:
        """Remove an item from a shop's inventory.

        Args:
            shop_id: Shop entity ID.
            item_id: Item entity ID.

        Returns:
            True if deleted.
        """
        result = self.graph_ops.delete_entity(item_id)

        # Invalidate cache
        self._shop_cache.pop(shop_id, None)

        return result

    def get_shopkeeper(self, shop_id: str) -> Optional[dict]:
        """Get the shopkeeper NPC for a shop.

        Args:
            shop_id: Shop entity ID.

        Returns:
            NPCFullProfile dict or None.
        """
        shop = self.get_shop(shop_id)
        if not shop or not shop.shopkeeper_id:
            return None

        keeper = self._npc_registry.get_npc(shop.shopkeeper_id)
        if not keeper:
            return None

        return keeper.model_dump()

    def _get_inventory_entities(self, shop_id: str) -> list[dict]:
        """Get raw inventory item entities for a shop.

        Args:
            shop_id: Shop entity ID.

        Returns:
            List of item entity dicts.
        """
        neighbors = self.graph_ops.get_neighbors(
            entity_id=shop_id,
            max_hops=1,
            relationship_types=["CONTAINS"],
        )

        return [
            n for n in neighbors
            if n.get("entity_type") == EntityType.ITEM.value
        ]

    def _entity_to_profile(self, entity: dict) -> ShopProfile:
        """Convert a Neo4j entity to ShopProfile.

        Args:
            entity: Entity dict from Neo4j.

        Returns:
            ShopProfile instance.
        """
        shop_id = entity["id"]

        # Get inventory
        item_entities = self._get_inventory_entities(shop_id)
        items = [self._entity_to_item(ie) for ie in item_entities]

        # Get shopkeeper info
        shopkeeper_id = entity.get("shopkeeper_id")
        shopkeeper_name = None
        shopkeeper_race = None
        shopkeeper_description = None
        shopkeeper_personality = None

        if shopkeeper_id:
            keeper = self._npc_registry.get_npc(shopkeeper_id)
            if keeper:
                shopkeeper_name = keeper.name
                shopkeeper_race = keeper.race
                shopkeeper_description = keeper.description
                shopkeeper_personality = keeper.personality.model_dump()

        # Parse enums with fallback
        try:
            shop_size = ShopSize(entity.get("shop_size", "medium"))
        except ValueError:
            shop_size = ShopSize.MEDIUM

        try:
            shop_specialty = ShopSpecialty(entity.get("shop_specialty", "general"))
        except ValueError:
            shop_specialty = ShopSpecialty.GENERAL

        return ShopProfile(
            entity_id=shop_id,
            name=entity["name"],
            description=entity.get("description"),
            shop_size=shop_size,
            shop_specialty=shop_specialty,
            gold_reserves=entity.get("gold_reserves", 500.0),
            shopkeeper_id=shopkeeper_id,
            location_id=entity.get("location_id"),
            inventory=items,
            shopkeeper_name=shopkeeper_name,
            shopkeeper_race=shopkeeper_race,
            shopkeeper_description=shopkeeper_description,
            shopkeeper_personality=shopkeeper_personality,
        )

    def _entity_to_item(self, entity: dict) -> ShopItem:
        """Convert a Neo4j item entity to ShopItem.

        Args:
            entity: Item entity dict.

        Returns:
            ShopItem instance.
        """
        try:
            rarity = ItemRarity(entity.get("rarity", "common"))
        except ValueError:
            rarity = ItemRarity.COMMON

        try:
            category = ItemCategory(entity.get("category", "gear"))
        except ValueError:
            category = ItemCategory.GEAR

        return ShopItem(
            entity_id=entity.get("id"),
            name=entity.get("name", "Unknown Item"),
            description=entity.get("description"),
            price_gp=entity.get("price_gp", 0),
            quantity=entity.get("quantity", 1),
            rarity=rarity,
            category=category,
            magical=entity.get("magical", False),
            weight=entity.get("weight"),
        )
