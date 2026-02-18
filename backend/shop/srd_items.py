"""D&D 5e SRD item pools, rarity weights, and shop name templates."""

import random
from typing import Optional

from backend.shop.models import ItemCategory, ItemRarity, ShopSize, ShopSpecialty


# =====================
# SRD Item Pools
# =====================

# Items organized by category with SRD-accurate pricing
WEAPONS: list[dict] = [
    {"name": "Club", "price_gp": 0.1, "weight": 2, "rarity": "common", "category": "weapon"},
    {"name": "Dagger", "price_gp": 2, "weight": 1, "rarity": "common", "category": "weapon"},
    {"name": "Greatclub", "price_gp": 0.2, "weight": 10, "rarity": "common", "category": "weapon"},
    {"name": "Handaxe", "price_gp": 5, "weight": 2, "rarity": "common", "category": "weapon"},
    {"name": "Javelin", "price_gp": 0.5, "weight": 2, "rarity": "common", "category": "weapon"},
    {"name": "Light Hammer", "price_gp": 2, "weight": 2, "rarity": "common", "category": "weapon"},
    {"name": "Mace", "price_gp": 5, "weight": 4, "rarity": "common", "category": "weapon"},
    {"name": "Quarterstaff", "price_gp": 0.2, "weight": 4, "rarity": "common", "category": "weapon"},
    {"name": "Sickle", "price_gp": 1, "weight": 2, "rarity": "common", "category": "weapon"},
    {"name": "Spear", "price_gp": 1, "weight": 3, "rarity": "common", "category": "weapon"},
    {"name": "Battleaxe", "price_gp": 10, "weight": 4, "rarity": "common", "category": "weapon"},
    {"name": "Flail", "price_gp": 10, "weight": 2, "rarity": "common", "category": "weapon"},
    {"name": "Glaive", "price_gp": 20, "weight": 6, "rarity": "common", "category": "weapon"},
    {"name": "Greataxe", "price_gp": 30, "weight": 7, "rarity": "common", "category": "weapon"},
    {"name": "Greatsword", "price_gp": 50, "weight": 6, "rarity": "common", "category": "weapon"},
    {"name": "Halberd", "price_gp": 20, "weight": 6, "rarity": "common", "category": "weapon"},
    {"name": "Lance", "price_gp": 10, "weight": 6, "rarity": "common", "category": "weapon"},
    {"name": "Longsword", "price_gp": 15, "weight": 3, "rarity": "common", "category": "weapon"},
    {"name": "Maul", "price_gp": 10, "weight": 10, "rarity": "common", "category": "weapon"},
    {"name": "Morningstar", "price_gp": 15, "weight": 4, "rarity": "common", "category": "weapon"},
    {"name": "Pike", "price_gp": 5, "weight": 18, "rarity": "common", "category": "weapon"},
    {"name": "Rapier", "price_gp": 25, "weight": 2, "rarity": "common", "category": "weapon"},
    {"name": "Scimitar", "price_gp": 25, "weight": 3, "rarity": "common", "category": "weapon"},
    {"name": "Shortsword", "price_gp": 10, "weight": 2, "rarity": "common", "category": "weapon"},
    {"name": "Trident", "price_gp": 5, "weight": 4, "rarity": "common", "category": "weapon"},
    {"name": "War Pick", "price_gp": 5, "weight": 2, "rarity": "common", "category": "weapon"},
    {"name": "Warhammer", "price_gp": 15, "weight": 2, "rarity": "common", "category": "weapon"},
    {"name": "Whip", "price_gp": 2, "weight": 3, "rarity": "common", "category": "weapon"},
    {"name": "Light Crossbow", "price_gp": 25, "weight": 5, "rarity": "common", "category": "weapon"},
    {"name": "Shortbow", "price_gp": 25, "weight": 2, "rarity": "common", "category": "weapon"},
    {"name": "Longbow", "price_gp": 50, "weight": 2, "rarity": "common", "category": "weapon"},
    {"name": "Heavy Crossbow", "price_gp": 50, "weight": 18, "rarity": "common", "category": "weapon"},
    {"name": "Hand Crossbow", "price_gp": 75, "weight": 3, "rarity": "common", "category": "weapon"},
]

MAGIC_WEAPONS: list[dict] = [
    {"name": "Longsword +1", "price_gp": 1000, "weight": 3, "rarity": "uncommon", "category": "weapon", "magical": True, "description": "A finely-crafted longsword with a faint magical aura. +1 to attack and damage rolls."},
    {"name": "Shortbow +1", "price_gp": 1000, "weight": 2, "rarity": "uncommon", "category": "weapon", "magical": True, "description": "An elven-crafted shortbow that hums with magic. +1 to attack and damage rolls."},
    {"name": "Dagger +1", "price_gp": 500, "weight": 1, "rarity": "uncommon", "category": "weapon", "magical": True, "description": "A slim dagger with runes along the blade. +1 to attack and damage rolls."},
    {"name": "Battleaxe +1", "price_gp": 1000, "weight": 4, "rarity": "uncommon", "category": "weapon", "magical": True, "description": "A dwarven battleaxe that gleams with enchantment. +1 to attack and damage rolls."},
    {"name": "Flame Tongue Sword", "price_gp": 5000, "weight": 3, "rarity": "rare", "category": "weapon", "magical": True, "description": "A sword that bursts into flame on command, dealing an extra 2d6 fire damage."},
    {"name": "Vicious Rapier", "price_gp": 2500, "weight": 2, "rarity": "rare", "category": "weapon", "magical": True, "description": "When you roll a 20, the target takes an extra 7 damage."},
    {"name": "Javelin of Lightning", "price_gp": 1500, "weight": 2, "rarity": "uncommon", "category": "weapon", "magical": True, "description": "Transforms into a bolt of lightning when thrown, dealing 4d6 lightning damage in a line."},
]

ARMOR: list[dict] = [
    {"name": "Padded Armor", "price_gp": 5, "weight": 8, "rarity": "common", "category": "armor"},
    {"name": "Leather Armor", "price_gp": 10, "weight": 10, "rarity": "common", "category": "armor"},
    {"name": "Studded Leather Armor", "price_gp": 45, "weight": 13, "rarity": "common", "category": "armor"},
    {"name": "Hide Armor", "price_gp": 10, "weight": 12, "rarity": "common", "category": "armor"},
    {"name": "Chain Shirt", "price_gp": 50, "weight": 20, "rarity": "common", "category": "armor"},
    {"name": "Scale Mail", "price_gp": 50, "weight": 45, "rarity": "common", "category": "armor"},
    {"name": "Breastplate", "price_gp": 400, "weight": 20, "rarity": "common", "category": "armor"},
    {"name": "Half Plate", "price_gp": 750, "weight": 40, "rarity": "common", "category": "armor"},
    {"name": "Ring Mail", "price_gp": 30, "weight": 40, "rarity": "common", "category": "armor"},
    {"name": "Chain Mail", "price_gp": 75, "weight": 55, "rarity": "common", "category": "armor"},
    {"name": "Splint Armor", "price_gp": 200, "weight": 60, "rarity": "common", "category": "armor"},
    {"name": "Plate Armor", "price_gp": 1500, "weight": 65, "rarity": "common", "category": "armor"},
    {"name": "Shield", "price_gp": 10, "weight": 6, "rarity": "common", "category": "armor"},
]

MAGIC_ARMOR: list[dict] = [
    {"name": "Chain Shirt +1", "price_gp": 1500, "weight": 20, "rarity": "uncommon", "category": "armor", "magical": True, "description": "A chain shirt that provides an extra +1 bonus to AC."},
    {"name": "Shield +1", "price_gp": 1500, "weight": 6, "rarity": "uncommon", "category": "armor", "magical": True, "description": "A shield with a magical barrier. +1 AC beyond normal shield bonus."},
    {"name": "Mithral Breastplate", "price_gp": 800, "weight": 10, "rarity": "uncommon", "category": "armor", "magical": True, "description": "Light as leather yet strong as steel. No disadvantage on Stealth."},
    {"name": "Adamantine Chain Mail", "price_gp": 1500, "weight": 55, "rarity": "uncommon", "category": "armor", "magical": True, "description": "Any critical hit becomes a normal hit while wearing this armor."},
    {"name": "Plate Armor +1", "price_gp": 5500, "weight": 65, "rarity": "rare", "category": "armor", "magical": True, "description": "Enchanted plate armor providing an extra +1 bonus to AC."},
    {"name": "Cloak of Protection", "price_gp": 3500, "weight": 1, "rarity": "uncommon", "category": "armor", "magical": True, "description": "+1 bonus to AC and saving throws while wearing this cloak."},
]

POTIONS: list[dict] = [
    {"name": "Potion of Healing", "price_gp": 50, "weight": 0.5, "rarity": "common", "category": "potion", "description": "Restores 2d4+2 hit points."},
    {"name": "Potion of Greater Healing", "price_gp": 150, "weight": 0.5, "rarity": "uncommon", "category": "potion", "description": "Restores 4d4+4 hit points."},
    {"name": "Potion of Superior Healing", "price_gp": 500, "weight": 0.5, "rarity": "rare", "category": "potion", "description": "Restores 8d4+8 hit points."},
    {"name": "Antitoxin", "price_gp": 50, "weight": 0, "rarity": "common", "category": "potion", "description": "Advantage on saves vs. poison for 1 hour."},
    {"name": "Potion of Fire Resistance", "price_gp": 300, "weight": 0.5, "rarity": "uncommon", "category": "potion", "description": "Resistance to fire damage for 1 hour."},
    {"name": "Potion of Invisibility", "price_gp": 500, "weight": 0.5, "rarity": "very_rare", "category": "potion", "description": "Become invisible for 1 hour or until you attack/cast a spell."},
    {"name": "Potion of Speed", "price_gp": 400, "weight": 0.5, "rarity": "very_rare", "category": "potion", "description": "Effects of the Haste spell for 1 minute."},
    {"name": "Potion of Water Breathing", "price_gp": 100, "weight": 0.5, "rarity": "uncommon", "category": "potion", "description": "Breathe underwater for 1 hour."},
    {"name": "Potion of Climbing", "price_gp": 75, "weight": 0.5, "rarity": "common", "category": "potion", "description": "Gain climbing speed equal to walking speed for 1 hour."},
    {"name": "Potion of Heroism", "price_gp": 180, "weight": 0.5, "rarity": "rare", "category": "potion", "description": "Gain 10 temp HP and bless effect for 1 hour."},
    {"name": "Oil of Slipperiness", "price_gp": 200, "weight": 0.5, "rarity": "uncommon", "category": "potion", "description": "Freedom of movement effect for 8 hours."},
    {"name": "Philter of Love", "price_gp": 90, "weight": 0.5, "rarity": "uncommon", "category": "potion", "description": "Charmed by the first creature seen for 1 hour."},
]

SCROLLS: list[dict] = [
    {"name": "Spell Scroll (Cantrip)", "price_gp": 15, "weight": 0, "rarity": "common", "category": "scroll", "magical": True, "description": "Contains a single cantrip."},
    {"name": "Spell Scroll (1st Level)", "price_gp": 50, "weight": 0, "rarity": "common", "category": "scroll", "magical": True, "description": "Contains a single 1st-level spell."},
    {"name": "Spell Scroll (2nd Level)", "price_gp": 150, "weight": 0, "rarity": "uncommon", "category": "scroll", "magical": True, "description": "Contains a single 2nd-level spell."},
    {"name": "Spell Scroll (3rd Level)", "price_gp": 300, "weight": 0, "rarity": "uncommon", "category": "scroll", "magical": True, "description": "Contains a single 3rd-level spell."},
    {"name": "Spell Scroll (4th Level)", "price_gp": 500, "weight": 0, "rarity": "rare", "category": "scroll", "magical": True, "description": "Contains a single 4th-level spell."},
    {"name": "Spell Scroll (5th Level)", "price_gp": 1000, "weight": 0, "rarity": "rare", "category": "scroll", "magical": True, "description": "Contains a single 5th-level spell."},
    {"name": "Scroll of Protection", "price_gp": 180, "weight": 0, "rarity": "uncommon", "category": "scroll", "magical": True, "description": "Protection from a chosen creature type for 5 minutes."},
]

ADVENTURING_GEAR: list[dict] = [
    {"name": "Backpack", "price_gp": 2, "weight": 5, "rarity": "common", "category": "gear"},
    {"name": "Bedroll", "price_gp": 1, "weight": 7, "rarity": "common", "category": "gear"},
    {"name": "Rope, Hempen (50 ft)", "price_gp": 1, "weight": 10, "rarity": "common", "category": "gear"},
    {"name": "Rope, Silk (50 ft)", "price_gp": 10, "weight": 5, "rarity": "common", "category": "gear"},
    {"name": "Torch (10)", "price_gp": 0.1, "weight": 10, "rarity": "common", "category": "gear"},
    {"name": "Rations (1 day)", "price_gp": 0.5, "weight": 2, "rarity": "common", "category": "gear"},
    {"name": "Waterskin", "price_gp": 0.2, "weight": 5, "rarity": "common", "category": "gear"},
    {"name": "Tinderbox", "price_gp": 0.5, "weight": 1, "rarity": "common", "category": "gear"},
    {"name": "Lantern, Hooded", "price_gp": 5, "weight": 2, "rarity": "common", "category": "gear"},
    {"name": "Lantern, Bullseye", "price_gp": 10, "weight": 2, "rarity": "common", "category": "gear"},
    {"name": "Oil (flask)", "price_gp": 0.1, "weight": 1, "rarity": "common", "category": "gear"},
    {"name": "Piton (10)", "price_gp": 0.5, "weight": 2.5, "rarity": "common", "category": "gear"},
    {"name": "Grappling Hook", "price_gp": 2, "weight": 4, "rarity": "common", "category": "gear"},
    {"name": "Crowbar", "price_gp": 2, "weight": 5, "rarity": "common", "category": "gear"},
    {"name": "Chain (10 ft)", "price_gp": 5, "weight": 10, "rarity": "common", "category": "gear"},
    {"name": "Manacles", "price_gp": 2, "weight": 6, "rarity": "common", "category": "gear"},
    {"name": "Mirror, Steel", "price_gp": 5, "weight": 0.5, "rarity": "common", "category": "gear"},
    {"name": "Caltrops (bag of 20)", "price_gp": 1, "weight": 2, "rarity": "common", "category": "gear"},
    {"name": "Ball Bearings (bag of 1000)", "price_gp": 1, "weight": 2, "rarity": "common", "category": "gear"},
    {"name": "Tent, Two-Person", "price_gp": 2, "weight": 20, "rarity": "common", "category": "gear"},
    {"name": "Climbing Kit", "price_gp": 25, "weight": 12, "rarity": "common", "category": "gear"},
    {"name": "Healer's Kit", "price_gp": 5, "weight": 3, "rarity": "common", "category": "gear"},
    {"name": "Holy Water (flask)", "price_gp": 25, "weight": 1, "rarity": "common", "category": "gear"},
    {"name": "Spyglass", "price_gp": 1000, "weight": 1, "rarity": "uncommon", "category": "gear"},
    {"name": "Component Pouch", "price_gp": 25, "weight": 2, "rarity": "common", "category": "gear"},
    {"name": "Arcane Focus (Crystal)", "price_gp": 10, "weight": 1, "rarity": "common", "category": "gear"},
]

AMMUNITION: list[dict] = [
    {"name": "Arrows (20)", "price_gp": 1, "weight": 1, "rarity": "common", "category": "ammunition"},
    {"name": "Crossbow Bolts (20)", "price_gp": 1, "weight": 1.5, "rarity": "common", "category": "ammunition"},
    {"name": "Sling Bullets (20)", "price_gp": 0.04, "weight": 1.5, "rarity": "common", "category": "ammunition"},
    {"name": "Blowgun Needles (50)", "price_gp": 1, "weight": 1, "rarity": "common", "category": "ammunition"},
    {"name": "Silvered Arrows (5)", "price_gp": 50, "weight": 0.25, "rarity": "uncommon", "category": "ammunition"},
    {"name": "Arrows +1 (6)", "price_gp": 150, "weight": 0.3, "rarity": "uncommon", "category": "ammunition", "magical": True, "description": "+1 to attack and damage rolls."},
]

TOOLS: list[dict] = [
    {"name": "Thieves' Tools", "price_gp": 25, "weight": 1, "rarity": "common", "category": "tool"},
    {"name": "Smith's Tools", "price_gp": 20, "weight": 8, "rarity": "common", "category": "tool"},
    {"name": "Herbalism Kit", "price_gp": 5, "weight": 3, "rarity": "common", "category": "tool"},
    {"name": "Alchemist's Supplies", "price_gp": 50, "weight": 8, "rarity": "common", "category": "tool"},
    {"name": "Brewer's Supplies", "price_gp": 20, "weight": 9, "rarity": "common", "category": "tool"},
    {"name": "Carpenter's Tools", "price_gp": 8, "weight": 6, "rarity": "common", "category": "tool"},
    {"name": "Cartographer's Tools", "price_gp": 15, "weight": 6, "rarity": "common", "category": "tool"},
    {"name": "Leatherworker's Tools", "price_gp": 5, "weight": 5, "rarity": "common", "category": "tool"},
    {"name": "Tinker's Tools", "price_gp": 50, "weight": 10, "rarity": "common", "category": "tool"},
    {"name": "Disguise Kit", "price_gp": 25, "weight": 3, "rarity": "common", "category": "tool"},
    {"name": "Forgery Kit", "price_gp": 15, "weight": 5, "rarity": "common", "category": "tool"},
    {"name": "Poisoner's Kit", "price_gp": 50, "weight": 2, "rarity": "common", "category": "tool"},
]

WONDROUS_ITEMS: list[dict] = [
    {"name": "Bag of Holding", "price_gp": 4000, "weight": 15, "rarity": "uncommon", "category": "wondrous", "magical": True, "description": "Interior is much larger than outside. Holds up to 500 lbs."},
    {"name": "Boots of Elvenkind", "price_gp": 2500, "weight": 1, "rarity": "uncommon", "category": "wondrous", "magical": True, "description": "Your steps make no sound. Advantage on Stealth checks."},
    {"name": "Cloak of Elvenkind", "price_gp": 5000, "weight": 1, "rarity": "uncommon", "category": "wondrous", "magical": True, "description": "Advantage on Stealth checks and disadvantage on Perception vs. you."},
    {"name": "Goggles of Night", "price_gp": 1500, "weight": 0, "rarity": "uncommon", "category": "wondrous", "magical": True, "description": "Darkvision out to 60 feet."},
    {"name": "Ring of Protection", "price_gp": 3500, "weight": 0, "rarity": "rare", "category": "wondrous", "magical": True, "description": "+1 bonus to AC and saving throws."},
    {"name": "Amulet of Health", "price_gp": 8000, "weight": 1, "rarity": "rare", "category": "wondrous", "magical": True, "description": "Constitution score becomes 19 while wearing this amulet."},
    {"name": "Gauntlets of Ogre Power", "price_gp": 8000, "weight": 1, "rarity": "uncommon", "category": "wondrous", "magical": True, "description": "Strength score becomes 19 while wearing these gauntlets."},
    {"name": "Pearl of Power", "price_gp": 6000, "weight": 0, "rarity": "uncommon", "category": "wondrous", "magical": True, "description": "Regain one expended spell slot up to 3rd level."},
    {"name": "Immovable Rod", "price_gp": 5000, "weight": 2, "rarity": "uncommon", "category": "wondrous", "magical": True, "description": "Magically fixes itself in place when activated."},
    {"name": "Decanter of Endless Water", "price_gp": 4000, "weight": 2, "rarity": "uncommon", "category": "wondrous", "magical": True, "description": "Produces fresh or salt water on command."},
    {"name": "Drift Globe", "price_gp": 750, "weight": 1, "rarity": "uncommon", "category": "wondrous", "magical": True, "description": "Glass orb that casts Light or Daylight on command."},
    {"name": "Sending Stones", "price_gp": 2000, "weight": 0, "rarity": "uncommon", "category": "wondrous", "magical": True, "description": "Paired stones that allow casting Sending once per day."},
]

CURIOSITIES: list[dict] = [
    {"name": "Crystal Ball (non-magical)", "price_gp": 50, "weight": 3, "rarity": "common", "category": "wondrous", "description": "A beautiful crystal sphere. Purely decorative."},
    {"name": "Taxidermied Owlbear Head", "price_gp": 75, "weight": 20, "rarity": "common", "category": "wondrous", "description": "A mounted owlbear head, slightly moth-eaten."},
    {"name": "Bottled Faerie Fire", "price_gp": 200, "weight": 0.5, "rarity": "uncommon", "category": "wondrous", "description": "A jar of glowing fey energy. Pretty but harmless."},
    {"name": "Map to Nowhere", "price_gp": 15, "weight": 0, "rarity": "common", "category": "gear", "description": "An ancient map covered in mysterious symbols. Probably fake."},
    {"name": "Ever-Smoking Bottle", "price_gp": 1000, "weight": 1, "rarity": "uncommon", "category": "wondrous", "magical": True, "description": "Opens to release a thick cloud of smoke in 60-ft radius."},
    {"name": "Clockwork Songbird", "price_gp": 300, "weight": 1, "rarity": "uncommon", "category": "wondrous", "description": "A tiny mechanical bird that sings when wound up."},
    {"name": "Mysterious Locked Box", "price_gp": 25, "weight": 3, "rarity": "common", "category": "wondrous", "description": "A sturdy box with no visible lock mechanism. Something rattles inside."},
    {"name": "Preserved Dragon Scale", "price_gp": 500, "weight": 1, "rarity": "rare", "category": "wondrous", "description": "A single iridescent scale from a young dragon."},
    {"name": "Potion of Unknown Effect", "price_gp": 100, "weight": 0.5, "rarity": "uncommon", "category": "potion", "description": "A bubbling purple liquid. Effects unknown."},
    {"name": "Deck of Illusions", "price_gp": 6000, "weight": 0, "rarity": "uncommon", "category": "wondrous", "magical": True, "description": "Draw a card to create an illusion of the creature depicted."},
]


# =====================
# Specialty Item Pools
# =====================

SPECIALTY_POOLS: dict[str, list[list[dict]]] = {
    "weapons": [WEAPONS, MAGIC_WEAPONS, AMMUNITION],
    "armor": [ARMOR, MAGIC_ARMOR],
    "potions": [POTIONS],
    "general": [ADVENTURING_GEAR, TOOLS, POTIONS[:3], AMMUNITION[:3]],
    "magic_items": [MAGIC_WEAPONS, MAGIC_ARMOR, WONDROUS_ITEMS, SCROLLS],
    "curiosities": [CURIOSITIES, WONDROUS_ITEMS, POTIONS],
    "scrolls": [SCROLLS, WONDROUS_ITEMS[:4]],
    "adventuring_gear": [ADVENTURING_GEAR, TOOLS, AMMUNITION],
    "blacksmith": [WEAPONS, ARMOR, AMMUNITION, TOOLS[:3]],
}


# =====================
# Rarity Weights by Size
# =====================

RARITY_WEIGHTS: dict[str, dict[str, float]] = {
    "small": {
        "common": 0.80,
        "uncommon": 0.18,
        "rare": 0.02,
        "very_rare": 0.0,
        "legendary": 0.0,
    },
    "medium": {
        "common": 0.60,
        "uncommon": 0.25,
        "rare": 0.12,
        "very_rare": 0.03,
        "legendary": 0.0,
    },
    "large": {
        "common": 0.45,
        "uncommon": 0.30,
        "rare": 0.17,
        "very_rare": 0.06,
        "legendary": 0.02,
    },
}


# =====================
# Item Count Ranges
# =====================

ITEM_COUNT_RANGE: dict[str, tuple[int, int]] = {
    "small": (5, 10),
    "medium": (10, 20),
    "large": (20, 40),
}


# =====================
# Gold Reserves
# =====================

GOLD_RESERVES: dict[str, tuple[float, float]] = {
    "small": (100, 300),
    "medium": (300, 1000),
    "large": (1000, 5000),
}


# =====================
# Shop Name Templates
# =====================

SHOP_NAME_TEMPLATES: dict[str, list[str]] = {
    "weapons": [
        "The {adj} Blade",
        "{name}'s Armory",
        "The Steel {noun}",
        "Swords & {noun}",
        "The War {noun}",
        "The {adj} Edge",
    ],
    "armor": [
        "The Iron {noun}",
        "{name}'s Forge",
        "The {adj} Shield",
        "Plate & Mail",
        "The Armored {noun}",
    ],
    "potions": [
        "The Bubbling {noun}",
        "{name}'s Apothecary",
        "The {adj} Brew",
        "Elixirs & Essences",
        "The Healing {noun}",
    ],
    "general": [
        "The {adj} Merchant",
        "{name}'s General Goods",
        "The Trading {noun}",
        "The {adj} Market",
        "Odds & Ends",
    ],
    "magic_items": [
        "The Arcane {noun}",
        "{name}'s Enchantments",
        "The {adj} Wand",
        "Mystic Emporium",
        "The Enchanted {noun}",
    ],
    "curiosities": [
        "The Peculiar {noun}",
        "{name}'s Oddities",
        "The {adj} Collection",
        "Wonders & Curios",
        "The Wandering Eye",
    ],
    "scrolls": [
        "The Scholar's {noun}",
        "{name}'s Scrollworks",
        "The {adj} Library",
        "Ink & Incantation",
        "The Written Word",
    ],
    "adventuring_gear": [
        "The {adj} Outfitter",
        "{name}'s Supply Co.",
        "The Explorer's {noun}",
        "Trail & Pack",
        "The Ready {noun}",
    ],
    "blacksmith": [
        "The {adj} Anvil",
        "{name}'s Smithy",
        "Hammer & Tongs",
        "The Forge of {noun}",
        "Ironworks",
    ],
}

NAME_ADJECTIVES = [
    "Golden", "Silver", "Rusty", "Gleaming", "Hidden", "Wandering",
    "Lucky", "Crimson", "Gilded", "Sturdy", "Ancient", "Jolly",
    "Honest", "Crooked", "Shining", "Dusty", "Prancing", "Sleeping",
]

NAME_NOUNS = [
    "Dragon", "Griffin", "Phoenix", "Raven", "Wolf", "Bear",
    "Crown", "Helm", "Gauntlet", "Tower", "Gate", "Lantern",
    "Fox", "Stag", "Serpent", "Hawk", "Lion", "Anvil",
]

KEEPER_NAMES = [
    "Thorne", "Grimshaw", "Aldric", "Mira", "Brom", "Elara",
    "Dorin", "Kestra", "Voss", "Lysara", "Grundy", "Nessa",
    "Bartholomew", "Isadora", "Mortimer", "Zephyra", "Gundrik", "Selene",
]


# =====================
# Specialty → Personality Mapping
# =====================

SPECIALTY_PERSONALITY: dict[str, dict] = {
    "weapons": {
        "speech_style": "gruff",
        "personality_traits": ["proud", "competitive", "blunt"],
        "knowledge_domains": ["warfare", "metallurgy", "martial history"],
        "catchphrases": ["A fine weapon for a fine warrior.", "Steel doesn't lie."],
    },
    "armor": {
        "speech_style": "formal",
        "personality_traits": ["meticulous", "patient", "detail-oriented"],
        "knowledge_domains": ["defense", "materials science", "craftsmanship"],
        "catchphrases": ["Protection is paramount.", "Measure twice, forge once."],
    },
    "potions": {
        "speech_style": "mysterious",
        "personality_traits": ["eccentric", "absent-minded", "curious"],
        "knowledge_domains": ["alchemy", "herbalism", "medicine"],
        "catchphrases": ["Drink carefully, dear.", "The brew knows what you need."],
    },
    "general": {
        "speech_style": "casual",
        "personality_traits": ["friendly", "chatty", "shrewd"],
        "knowledge_domains": ["local gossip", "trade routes", "bargaining"],
        "catchphrases": ["Something for everyone!", "Let me tell you what I heard..."],
    },
    "magic_items": {
        "speech_style": "eloquent",
        "personality_traits": ["secretive", "knowledgeable", "cautious"],
        "knowledge_domains": ["arcana", "history", "planar lore"],
        "catchphrases": ["Handle with care.", "This one has a story to tell."],
    },
    "curiosities": {
        "speech_style": "mysterious",
        "personality_traits": ["whimsical", "evasive", "theatrical"],
        "knowledge_domains": ["planes", "oddities", "forbidden lore"],
        "catchphrases": ["Curious, isn't it?", "Not everything is as it seems."],
    },
    "scrolls": {
        "speech_style": "formal",
        "personality_traits": ["scholarly", "precise", "pedantic"],
        "knowledge_domains": ["magic theory", "languages", "history"],
        "catchphrases": ["Knowledge is the truest power.", "Read the fine print."],
    },
    "adventuring_gear": {
        "speech_style": "casual",
        "personality_traits": ["practical", "experienced", "no-nonsense"],
        "knowledge_domains": ["survival", "travel", "dungeon delving"],
        "catchphrases": ["You'll need this where you're going.", "Preparation saves lives."],
    },
    "blacksmith": {
        "speech_style": "gruff",
        "personality_traits": ["strong", "honest", "hardworking"],
        "knowledge_domains": ["crafting", "repair", "metallurgy"],
        "catchphrases": ["Built to last.", "I put my name behind every piece."],
    },
}


# =====================
# Helper Functions
# =====================


def get_item_pool(specialty: str) -> list[dict]:
    """Get the flattened item pool for a specialty.

    Args:
        specialty: Shop specialty value.

    Returns:
        List of item dicts from all relevant pools.
    """
    pools = SPECIALTY_POOLS.get(specialty, SPECIALTY_POOLS["general"])
    items = []
    for pool in pools:
        items.extend(pool)
    return items


def select_items(
    specialty: str,
    size: str,
    count: Optional[int] = None,
) -> list[dict]:
    """Select items for a shop based on specialty and size.

    Respects rarity weights so smaller shops have fewer rare items.

    Args:
        specialty: Shop specialty.
        size: Shop size (small/medium/large).
        count: Override item count (otherwise random within range).

    Returns:
        List of selected item dicts with quantity added.
    """
    pool = get_item_pool(specialty)
    if not pool:
        return []

    weights = RARITY_WEIGHTS.get(size, RARITY_WEIGHTS["medium"])
    min_count, max_count = ITEM_COUNT_RANGE.get(size, (10, 20))
    target_count = count or random.randint(min_count, max_count)

    # Group pool by rarity
    by_rarity: dict[str, list[dict]] = {}
    for item in pool:
        r = item.get("rarity", "common")
        by_rarity.setdefault(r, []).append(item)

    selected = []
    seen_names: set[str] = set()

    for _ in range(target_count):
        # Pick a rarity tier based on weights
        rarities = list(weights.keys())
        probs = [weights[r] for r in rarities]

        # Normalize in case probabilities don't sum to 1
        total = sum(probs)
        probs = [p / total for p in probs]

        chosen_rarity = random.choices(rarities, weights=probs, k=1)[0]

        # Get items from that rarity
        candidates = by_rarity.get(chosen_rarity, [])
        if not candidates:
            # Fall back to common
            candidates = by_rarity.get("common", pool)

        # Pick a random item, avoiding duplicates when possible
        available = [c for c in candidates if c["name"] not in seen_names]

        # Add quantity based on rarity
        if chosen_rarity in ("rare", "very_rare", "legendary"):
            qty = 1
        elif chosen_rarity == "uncommon":
            qty = random.randint(1, 3)
        else:
            qty = random.randint(1, 10)

        if not available:
            # Pool exhausted — merge quantity into an existing entry
            existing = [s for s in selected if s.get("rarity", "common") == chosen_rarity]
            if existing:
                target = random.choice(existing)
                target["quantity"] = target.get("quantity", 1) + qty
                continue
            # No existing items of this rarity either, skip this slot
            continue

        item = random.choice(available)
        seen_names.add(item["name"])
        selected.append({**item, "quantity": qty})

    return selected


def generate_shop_name(specialty: str, keeper_name: Optional[str] = None) -> str:
    """Generate a random shop name for a given specialty.

    Args:
        specialty: Shop specialty.
        keeper_name: Optional shopkeeper name to include.

    Returns:
        Generated shop name.
    """
    templates = SHOP_NAME_TEMPLATES.get(specialty, SHOP_NAME_TEMPLATES["general"])
    template = random.choice(templates)

    name = keeper_name or random.choice(KEEPER_NAMES)
    adj = random.choice(NAME_ADJECTIVES)
    noun = random.choice(NAME_NOUNS)

    return template.format(name=name, adj=adj, noun=noun)


def get_gold_reserves(size: str) -> float:
    """Get random gold reserves for a shop size.

    Args:
        size: Shop size.

    Returns:
        Gold amount.
    """
    min_gold, max_gold = GOLD_RESERVES.get(size, (300, 1000))
    return round(random.uniform(min_gold, max_gold), 0)


def get_personality_template(specialty: str) -> dict:
    """Get personality template for a specialty.

    Args:
        specialty: Shop specialty.

    Returns:
        Personality dict matching NPCPersonality fields.
    """
    return SPECIALTY_PERSONALITY.get(specialty, SPECIALTY_PERSONALITY["general"])
