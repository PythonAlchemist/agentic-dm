"""Shop management API endpoints."""

import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from backend.core.config import settings
from backend.discord.npc_registry import NPCRegistry
from backend.shop.generator import ShopGenerator
from backend.shop.models import (
    ItemCategory,
    ItemRarity,
    ShopChatRequest,
    ShopChatResponse,
    ShopGenerateRequest,
    ShopItem,
    ShopProfile,
    ShopSize,
    ShopSpecialty,
)
from backend.shop.registry import ShopRegistry

router = APIRouter()
logger = logging.getLogger(__name__)

# Singletons
_shop_registry: Optional[ShopRegistry] = None
_shop_generator: Optional[ShopGenerator] = None
_npc_registry: Optional[NPCRegistry] = None
_openai_client: Optional[AsyncOpenAI] = None


def get_shop_registry() -> ShopRegistry:
    global _shop_registry
    if _shop_registry is None:
        _shop_registry = ShopRegistry()
    return _shop_registry


def get_shop_generator() -> ShopGenerator:
    global _shop_generator
    if _shop_generator is None:
        _shop_generator = ShopGenerator()
    return _shop_generator


def get_npc_registry() -> NPCRegistry:
    global _npc_registry
    if _npc_registry is None:
        _npc_registry = NPCRegistry()
    return _npc_registry


def get_openai() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _openai_client


# ===================
# Shopkeeper Tool Definitions
# ===================

SHOPKEEPER_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "sell_items",
            "description": (
                "Complete a sale when the customer confirms they want to buy. "
                "Call this ONLY after the customer agrees to purchase. "
                "ONLY include items the customer EXPLICITLY asked for in their LATEST message. "
                "NEVER include items from earlier in the conversation that were already sold."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "item_name": {"type": "string"},
                                "quantity": {"type": "integer", "minimum": 1},
                                "price_each": {"type": "number"},
                            },
                            "required": ["item_name", "quantity", "price_each"],
                        },
                    }
                },
                "required": ["items"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_stock",
            "description": "Check current stock quantity and price for an item.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_name": {"type": "string"},
                },
                "required": ["item_name"],
            },
        },
    },
]


def _item_mentioned_in_message(item_name: str, message: str) -> bool:
    """Check if an item is referenced in the customer's message."""
    msg_lower = message.lower()
    name_lower = item_name.lower()
    # Exact match
    if name_lower in msg_lower:
        return True
    # Match without "potion of", "oil of", etc. prefix
    for prefix in ("potion of ", "oil of ", "philter of ", "elixir of ", "scroll of "):
        if name_lower.startswith(prefix):
            short = name_lower[len(prefix):]
            if short in msg_lower:
                return True
    return False


def _handle_sell_items(
    args: dict, shop: ShopProfile, registry: ShopRegistry,
    customer_message: str = "",
) -> dict:
    """Execute a sale: decrement inventory, increase shop gold, return summary."""
    sales = []
    errors = []

    for entry in args.get("items", []):
        item_name = entry["item_name"]
        qty = entry["quantity"]
        price_each = entry["price_each"]

        # Guard: only sell items the customer actually asked for
        if customer_message and not _item_mentioned_in_message(item_name, customer_message):
            errors.append(
                f"Skipped {item_name} — customer did not request this item."
            )
            continue

        # Find matching inventory item (case-insensitive)
        inv_item = None
        for item in shop.inventory:
            if item.name.lower() == item_name.lower():
                inv_item = item
                break

        if not inv_item or not inv_item.entity_id:
            errors.append(f"{item_name} not found in inventory.")
            continue

        # Clamp qty to available stock
        actual_qty = min(qty, inv_item.quantity)
        if actual_qty <= 0:
            errors.append(f"{inv_item.name} is out of stock.")
            continue

        actual_total = actual_qty * price_each

        # Update item quantity
        new_qty = inv_item.quantity - actual_qty
        registry.update_item(
            shop.entity_id, inv_item.entity_id, {"quantity": new_qty}
        )

        # Update shop gold reserves (shop gains gold from sale)
        new_gold = shop.gold_reserves + actual_total
        registry.update_shop(shop.entity_id, {"gold_reserves": new_gold})

        # Update in-memory shop object so subsequent tool calls see updated values
        inv_item.quantity = new_qty
        shop.gold_reserves = new_gold

        sales.append({
            "item": inv_item.name,
            "qty": actual_qty,
            "price_each": price_each,
            "total": actual_total,
            "action": "buy",
        })

        logger.info(
            f"[SHOP] Sale executed: {actual_qty}x {inv_item.name} "
            f"@ {price_each}gp = {actual_total}gp (shop: {shop.name})"
        )

    return {"sales": sales, "errors": errors}


def _handle_check_stock(args: dict, shop: ShopProfile) -> dict:
    """Look up current stock for an item by name."""
    item_name = args.get("item_name", "")
    for item in shop.inventory:
        if item.name.lower() == item_name.lower():
            return {
                "found": True,
                "name": item.name,
                "quantity": item.quantity,
                "price_gp": item.price_gp,
                "rarity": item.rarity.value,
            }
    return {"found": False, "name": item_name}


def _execute_tool(
    tool_name: str, arguments: str, shop: ShopProfile, registry: ShopRegistry,
    customer_message: str = "",
) -> dict:
    """Dispatch a tool call to the appropriate handler."""
    args = json.loads(arguments)
    if tool_name == "sell_items":
        return _handle_sell_items(args, shop, registry, customer_message)
    elif tool_name == "check_stock":
        return _handle_check_stock(args, shop)
    else:
        return {"error": f"Unknown tool: {tool_name}"}


# ===================
# Request/Response Models
# ===================


class ShopUpdateRequest(BaseModel):
    """Request to update a shop."""

    name: Optional[str] = None
    description: Optional[str] = None
    gold_reserves: Optional[float] = None


class AddItemRequest(BaseModel):
    """Request to add an item to inventory."""

    name: str
    description: Optional[str] = None
    price_gp: float = Field(ge=0)
    quantity: int = Field(ge=1, default=1)
    rarity: str = "common"
    category: str = "gear"
    magical: bool = False
    weight: Optional[float] = None


class UpdateItemRequest(BaseModel):
    """Request to update an inventory item."""

    name: Optional[str] = None
    description: Optional[str] = None
    price_gp: Optional[float] = None
    quantity: Optional[int] = None
    rarity: Optional[str] = None
    category: Optional[str] = None
    magical: Optional[bool] = None
    weight: Optional[float] = None


# ===================
# Shop Endpoints
# ===================


@router.post("/shop/generate")
async def generate_shop(request: ShopGenerateRequest):
    """Generate a new shop with LLM-enhanced descriptions and inventory."""
    try:
        generator = get_shop_generator()
        shop = await generator.generate_shop(request)
        return shop.model_dump()
    except Exception as e:
        logger.error(f"Error generating shop: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/shop/{shop_id}")
async def get_shop(shop_id: str):
    """Get a shop with its inventory and shopkeeper info."""
    registry = get_shop_registry()
    shop = registry.get_shop(shop_id)
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")
    return shop.model_dump()


@router.get("/shops")
async def list_shops(limit: int = 50):
    """List all shops."""
    registry = get_shop_registry()
    shops = registry.list_shops(limit=limit)
    return [s.model_dump() for s in shops]


@router.put("/shop/{shop_id}")
async def update_shop(shop_id: str, request: ShopUpdateRequest):
    """Update shop details."""
    registry = get_shop_registry()
    updates = request.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No updates provided")

    shop = registry.update_shop(shop_id, updates)
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")
    return shop.model_dump()


@router.delete("/shop/{shop_id}")
async def delete_shop(shop_id: str):
    """Delete a shop and its inventory."""
    registry = get_shop_registry()
    if not registry.delete_shop(shop_id):
        raise HTTPException(status_code=404, detail="Shop not found")
    return {"success": True}


# ===================
# Inventory Endpoints
# ===================


@router.post("/shop/{shop_id}/inventory")
async def add_item(shop_id: str, request: AddItemRequest):
    """Add an item to a shop's inventory."""
    registry = get_shop_registry()

    try:
        rarity = ItemRarity(request.rarity)
    except ValueError:
        rarity = ItemRarity.COMMON

    try:
        category = ItemCategory(request.category)
    except ValueError:
        category = ItemCategory.GEAR

    item = ShopItem(
        name=request.name,
        description=request.description,
        price_gp=request.price_gp,
        quantity=request.quantity,
        rarity=rarity,
        category=category,
        magical=request.magical,
        weight=request.weight,
    )

    created = registry.add_item(shop_id, item)
    if not created:
        raise HTTPException(status_code=404, detail="Shop not found")

    return created.model_dump()


@router.put("/shop/{shop_id}/inventory/{item_id}")
async def update_item(shop_id: str, item_id: str, request: UpdateItemRequest):
    """Update an item in the shop's inventory."""
    registry = get_shop_registry()
    updates = request.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No updates provided")

    item = registry.update_item(shop_id, item_id, updates)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    return item.model_dump()


@router.delete("/shop/{shop_id}/inventory/{item_id}")
async def remove_item(shop_id: str, item_id: str):
    """Remove an item from the shop's inventory."""
    registry = get_shop_registry()
    if not registry.remove_item(shop_id, item_id):
        raise HTTPException(status_code=404, detail="Item not found")
    return {"success": True}


# ===================
# Shopkeeper Endpoints
# ===================


@router.get("/shop/{shop_id}/shopkeeper")
async def get_shopkeeper(shop_id: str):
    """Get the shopkeeper NPC profile for a shop."""
    registry = get_shop_registry()
    keeper = registry.get_shopkeeper(shop_id)
    if not keeper:
        raise HTTPException(status_code=404, detail="Shopkeeper not found")
    return keeper


@router.post("/shop/{shop_id}/chat")
async def chat_with_shopkeeper(shop_id: str, request: ShopChatRequest):
    """Chat with the shopkeeper NPC in character.

    The shopkeeper responds based on their personality and shop inventory.
    Transactions are suggested but not executed (DM approves via inventory UI).

    Uses a direct OpenAI call (not NPCAgent) to keep full conversation history
    and shop inventory context without any sliding-window truncation.
    """
    registry = get_shop_registry()
    shop = registry.get_shop(shop_id)
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")

    if not shop.shopkeeper_id:
        raise HTTPException(status_code=400, detail="Shop has no shopkeeper")

    npc_registry = get_npc_registry()
    keeper = npc_registry.get_npc(shop.shopkeeper_id)
    if not keeper:
        raise HTTPException(status_code=404, detail="Shopkeeper NPC not found")

    # Build the system prompt with full shop + personality context
    personality = keeper.personality
    inventory_context = _build_inventory_context(shop)

    # Identity and personality first
    system_prompt = (
        f"You are {keeper.name}, a {keeper.race} {keeper.role} in a D&D 5e campaign.\n"
        f"You own and operate '{shop.name}', a {shop.shop_specialty.value} shop.\n"
    )
    if shop.description:
        system_prompt += f"{shop.description}\n"
    if keeper.description:
        system_prompt += f"\n**Your Backstory:** {keeper.description}\n"

    if personality.personality_traits:
        system_prompt += f"\n**Personality:** {', '.join(personality.personality_traits)}"
    if personality.speech_style and personality.speech_style != "normal":
        style_map = {
            "formal": "You speak formally and properly.",
            "casual": "You speak casually and informally.",
            "gruff": "You speak in short, gruff sentences.",
            "mysterious": "You speak cryptically, often in riddles.",
            "eloquent": "You speak eloquently with flowery language.",
        }
        system_prompt += f"\n**Speech Style:** {style_map.get(personality.speech_style, f'You speak in a {personality.speech_style} manner.')}"
    if personality.catchphrases:
        system_prompt += f"\n**Catchphrases:** {', '.join(f'"{p}"' for p in personality.catchphrases[:3])}"

    # Inventory in the middle
    system_prompt += (
        f"\n\n**YOUR INVENTORY (these are the ONLY items you sell):**\n"
        f"{inventory_context}\n\n"
        f"**Gold Reserves:** {shop.gold_reserves} gp"
    )

    # Rules at the END of the system prompt (recency bias — model pays most attention here)
    system_prompt += (
        f"\n\n**STRICT RULES — follow these exactly:**\n"
        f"1. ONLY sell items listed in YOUR INVENTORY. NEVER invent items.\n"
        f"2. Quote exact prices. You may negotiate 10-20% off for persuasive customers.\n"
        f"3. QUANTITY: You can ONLY sell up to the stock quantity shown. If a customer asks for "
        f"more than you have, tell them exactly how many you have and offer that amount instead.\n"
        f"4. Stay in character. Keep responses to 2-4 sentences.\n"
        f"5. NEVER mention the DM, the game, players, or anything out-of-character. You are a real shopkeeper.\n"
        f"6. DO NOT say \"welcome\", \"greetings\", \"well met\", or any greeting/introduction "
        f"after your very first reply. Just respond to what the customer said.\n"
        f"7. When calling sell_items, ONLY include items the customer explicitly requests in their "
        f"CURRENT message. NEVER re-sell items from earlier in the conversation."
    )

    # Build full message list: system + all prior messages + current message
    messages: list[dict] = [{"role": "system", "content": system_prompt}]

    has_history = len(request.conversation_history) > 0

    # Add full conversation history (no truncation)
    for msg in request.conversation_history:
        if msg.role == "user":
            messages.append({"role": "user", "content": msg.content})
        else:
            messages.append({"role": "assistant", "content": msg.content})

    # For follow-up messages, inject a system reminder right before the new message.
    # gpt-4o-mini needs this reinforcement to stay on track.
    player_name = request.player_name or "Adventurer"
    if has_history:
        messages.append({
            "role": "system",
            "content": (
                "Continue the conversation naturally. "
                "Do NOT greet or welcome the customer — you already did that. "
                "Do NOT sell more items than your stock quantity allows. "
                "When calling sell_items, ONLY include items the customer asks for in "
                "their NEXT message. Do NOT re-sell items from earlier messages."
            ),
        })
        messages.append({"role": "user", "content": f"{request.message}"})
    else:
        messages.append({"role": "user", "content": f"[{player_name}]: {request.message}"})

    try:
        client = get_openai()
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            tools=SHOPKEEPER_TOOLS,
            tool_choice="auto",
            temperature=0.7,
            max_tokens=300,
        )

        # Tool-calling loop: keep going while the model wants to call tools
        transactions = []
        while response.choices[0].finish_reason == "tool_calls":
            tool_calls = response.choices[0].message.tool_calls
            messages.append(response.choices[0].message)

            for tc in tool_calls:
                result = _execute_tool(
                    tc.function.name, tc.function.arguments, shop, registry,
                    customer_message=request.message,
                )
                if tc.function.name == "sell_items":
                    transactions.extend(result.get("sales", []))
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result),
                })

            response = await client.chat.completions.create(
                model="gpt-4o",
                messages=messages,
                tools=SHOPKEEPER_TOOLS,
                tool_choice="auto",
                temperature=0.7,
                max_tokens=300,
            )

        reply = response.choices[0].message.content.strip()

        # Strip self-referencing name prefix (e.g. "**Milo Tealeaf:** ...")
        # that gpt-4o sometimes adds when roleplaying
        stripped = reply.lstrip('*')
        if stripped.startswith(keeper.name):
            idx = reply.index(keeper.name) + len(keeper.name)
            while idx < len(reply) and reply[idx] in '*: \n':
                idx += 1
            reply = reply[idx:].strip()

        return ShopChatResponse(
            response=reply,
            transactions=transactions,
        ).model_dump()

    except Exception as e:
        logger.error(f"Error in shopkeeper chat: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate response")


def _build_inventory_context(shop: ShopProfile) -> str:
    """Build a text summary of shop inventory for LLM context."""
    if not shop.inventory:
        return "The shop is currently empty."

    lines = []
    for item in shop.inventory:
        magical_tag = " [MAGICAL]" if item.magical else ""
        lines.append(
            f"- {item.name}{magical_tag}: {item.price_gp} gp each, "
            f"QTY IN STOCK: {item.quantity} ({item.rarity.value})"
        )

    return "\n".join(lines)
