#!/usr/bin/env python3
"""Seed basic enemies (goblins and orcs) for combat testing."""

import json
import sys
sys.path.insert(0, "/Users/csinger/projects/agentic-dm")

from backend.graph.operations import CampaignGraphOps
from backend.graph.schema import EntityType


def create_goblin(graph_ops: CampaignGraphOps, name: str, variant: str = "warrior") -> dict:
    """Create a goblin NPC with combat stats."""

    stat_block = {
        "armor_class": 15,  # Leather armor + shield
        "hit_points": 7,
        "max_hit_points": 7,
        "speed": 30,
        "initiative_bonus": 2,
        "challenge_rating": 0.25,
        "attacks": [
            {
                "name": "Scimitar",
                "bonus": 4,
                "damage": "1d6+2",
                "damage_type": "slashing",
            },
            {
                "name": "Shortbow",
                "bonus": 4,
                "damage": "1d6+2",
                "damage_type": "piercing",
                "range": "80/320",
            },
        ],
        "special_abilities": [
            {
                "name": "Nimble Escape",
                "description": "Can take Disengage or Hide as a bonus action",
            }
        ],
    }

    personality = {
        "personality_traits": ["cowardly", "greedy", "cruel to the weak"],
        "combat_style": "opportunistic",
        "aggression_level": 0.6,
        "retreat_threshold": 0.3,
        "speech_style": "broken common, high-pitched",
        "catchphrases": [
            "Shinies! Give us the shinies!",
            "Stab stab stab!",
            "Run away! Run away!",
            "Goblin strong! You weak!",
        ],
    }

    entity = graph_ops.create_entity(
        name=name,
        entity_type=EntityType.NPC,
        description=f"A sneaky {variant} goblin with beady yellow eyes and sharp teeth.",
        properties={
            "race": "goblin",
            "role": variant,
            "disposition": "hostile",
            "importance": "minor",
            "stat_block": json.dumps(stat_block),
            "personality_config": json.dumps(personality),
        },
    )

    return entity


def create_orc(graph_ops: CampaignGraphOps, name: str, variant: str = "warrior") -> dict:
    """Create an orc NPC with combat stats."""

    stat_block = {
        "armor_class": 13,  # Hide armor
        "hit_points": 15,
        "max_hit_points": 15,
        "speed": 30,
        "initiative_bonus": 1,
        "challenge_rating": 0.5,
        "attacks": [
            {
                "name": "Greataxe",
                "bonus": 5,
                "damage": "1d12+3",
                "damage_type": "slashing",
            },
            {
                "name": "Javelin",
                "bonus": 5,
                "damage": "1d6+3",
                "damage_type": "piercing",
                "range": "30/120",
            },
        ],
        "special_abilities": [
            {
                "name": "Aggressive",
                "description": "Can move up to speed toward hostile creature as bonus action",
            }
        ],
    }

    personality = {
        "personality_traits": ["brutal", "aggressive", "respects strength"],
        "combat_style": "aggressive",
        "aggression_level": 0.9,
        "retreat_threshold": 0.15,
        "speech_style": "guttural, broken common",
        "catchphrases": [
            "GRUUMSH!",
            "Blood and thunder!",
            "Weak flesh! Strong orc!",
            "Die, puny one!",
            "For the horde!",
        ],
    }

    entity = graph_ops.create_entity(
        name=name,
        entity_type=EntityType.NPC,
        description=f"A hulking {variant} orc with grey-green skin and prominent tusks.",
        properties={
            "race": "orc",
            "role": variant,
            "disposition": "hostile",
            "importance": "minor",
            "stat_block": json.dumps(stat_block),
            "personality_config": json.dumps(personality),
        },
    )

    return entity


def create_wizard(graph_ops: CampaignGraphOps, name: str, school: str = "evocation", friendly: bool = False) -> dict:
    """Create a level 3 wizard NPC with spellcasting."""

    stat_block = {
        "armor_class": 12,  # Mage Armor not active by default
        "hit_points": 18,   # 6 + 2d6 + 6 (Con 14)
        "max_hit_points": 18,
        "speed": 30,
        "initiative_bonus": 2,  # Dex 14
        "challenge_rating": 2,
        # Ability scores
        "strength": 8,
        "dexterity": 14,
        "constitution": 14,
        "intelligence": 16,
        "wisdom": 12,
        "charisma": 10,
        "proficiency_bonus": 2,
        "spell_save_dc": 13,  # 8 + 2 + 3
        "spell_attack_bonus": 5,  # 2 + 3
        "attacks": [
            {
                "name": "Dagger",
                "bonus": 4,
                "damage": "1d4+2",
                "damage_type": "piercing",
                "range": "20/60",
            },
        ],
        "cantrips": [
            {
                "name": "Fire Bolt",
                "damage": "1d10",
                "damage_type": "fire",
                "range": 120,
                "attack_type": "ranged spell attack",
            },
            {
                "name": "Ray of Frost",
                "damage": "1d8",
                "damage_type": "cold",
                "range": 60,
                "attack_type": "ranged spell attack",
                "effect": "Speed reduced by 10ft until start of your next turn",
            },
            {
                "name": "Shocking Grasp",
                "damage": "1d8",
                "damage_type": "lightning",
                "range": 5,
                "attack_type": "melee spell attack",
                "effect": "Target can't take reactions until start of its next turn. Advantage if target wearing metal armor.",
            },
        ],
        "spell_slots": {
            "1st": 4,
            "2nd": 2,
        },
        "spells_known": [
            {
                "name": "Magic Missile",
                "level": 1,
                "damage": "3d4+3",
                "damage_type": "force",
                "description": "Three darts of magical force automatically hit. Each deals 1d4+1 force damage.",
                "auto_hit": True,
            },
            {
                "name": "Shield",
                "level": 1,
                "description": "Reaction: +5 AC until start of next turn, including against triggering attack.",
                "casting_time": "reaction",
            },
            {
                "name": "Mage Armor",
                "level": 1,
                "description": "AC becomes 13 + Dex modifier for 8 hours. Requires no armor.",
                "duration": "8 hours",
            },
            {
                "name": "Burning Hands",
                "level": 1,
                "damage": "3d6",
                "damage_type": "fire",
                "save": "DEX",
                "area": "15-foot cone",
                "description": "Each creature in cone makes DEX save. 3d6 fire on fail, half on success.",
            },
            {
                "name": "Scorching Ray",
                "level": 2,
                "damage": "2d6",
                "damage_type": "fire",
                "description": "Three rays, each requires ranged spell attack. 2d6 fire damage per ray. Can target same or different creatures.",
                "num_attacks": 3,
            },
            {
                "name": "Misty Step",
                "level": 2,
                "description": "Bonus action: Teleport up to 30 feet to unoccupied space you can see.",
                "casting_time": "bonus action",
            },
        ],
        "special_abilities": [
            {
                "name": "Arcane Recovery",
                "description": "Once per day during short rest, recover spell slots up to half wizard level (1 slot).",
            },
            {
                "name": "Evocation Savant" if school == "evocation" else "School Savant",
                "description": "Copying evocation spells costs half time and gold." if school == "evocation" else f"Specializes in {school} magic.",
            },
            {
                "name": "Sculpt Spells" if school == "evocation" else "School Feature",
                "description": "When casting evocation spell, can choose Int mod (3) creatures to auto-succeed on saves and take no damage." if school == "evocation" else "School-specific ability.",
            },
        ],
    }

    personality = {
        "personality_traits": ["cunning", "arrogant", "values knowledge above all"],
        "combat_style": "tactical",
        "aggression_level": 0.5,
        "retreat_threshold": 0.4,  # Wizards are smart about retreating
        "speech_style": "eloquent, condescending",
        "preferred_tactics": [
            "Open with Scorching Ray against biggest threat",
            "Use Burning Hands if enemies cluster",
            "Save Shield for incoming attacks",
            "Misty Step to escape melee",
            "Fire Bolt for consistent damage",
            "Magic Missile to finish low HP targets",
        ],
        "catchphrases": [
            "You dare challenge a master of the arcane?",
            "How quaint. You think steel can match sorcery?",
            "Burn!",
            "Your ignorance is your undoing.",
            "I've read about creatures like you. Disappointing in person.",
            "Knowledge is power, and I have plenty of both!",
        ],
    }

    disposition = "friendly" if friendly else "hostile"
    faction = "friendly" if friendly else "hostile"

    entity = graph_ops.create_entity(
        name=name,
        entity_type=EntityType.NPC,
        description=f"A cunning {school} wizard in dark robes, arcane symbols glowing faintly on the fabric. Eyes gleam with dangerous intelligence.",
        properties={
            "race": "human",
            "class": "wizard",
            "level": 3,
            "role": f"{school} wizard",
            "disposition": disposition,
            "importance": "notable",
            "stat_block": json.dumps(stat_block),
            "personality_config": json.dumps(personality),
            "default_faction": faction,
        },
    )

    return entity


def create_guard(graph_ops: CampaignGraphOps, name: str, rank: str = "guard") -> dict:
    """Create a friendly guard NPC that fights alongside players."""

    stat_block = {
        "armor_class": 16,  # Chain mail + shield
        "hit_points": 22,
        "max_hit_points": 22,
        "speed": 30,
        "initiative_bonus": 1,
        "challenge_rating": 0.5,
        "strength": 14,
        "dexterity": 12,
        "constitution": 14,
        "intelligence": 10,
        "wisdom": 12,
        "charisma": 10,
        "attacks": [
            {
                "name": "Longsword",
                "bonus": 4,
                "damage": "1d8+2",
                "damage_type": "slashing",
            },
            {
                "name": "Crossbow",
                "bonus": 3,
                "damage": "1d8+1",
                "damage_type": "piercing",
                "range": "80/320",
            },
        ],
        "special_abilities": [
            {
                "name": "Protection",
                "description": "Can impose disadvantage on attack roll against adjacent ally as reaction",
            }
        ],
    }

    personality = {
        "personality_traits": ["dutiful", "protective", "brave"],
        "combat_style": "defensive",
        "aggression_level": 0.5,
        "retreat_threshold": 0.2,  # Guards are trained to hold the line
        "speech_style": "formal, professional",
        "catchphrases": [
            "Stand behind me!",
            "For the realm!",
            "Hold the line!",
            "I'll cover you!",
            "None shall pass!",
        ],
    }

    entity = graph_ops.create_entity(
        name=name,
        entity_type=EntityType.NPC,
        description=f"A disciplined {rank} in polished armor, standing ready to protect those under their charge.",
        properties={
            "race": "human",
            "role": rank,
            "disposition": "friendly",
            "importance": "minor",
            "stat_block": json.dumps(stat_block),
            "personality_config": json.dumps(personality),
            "default_faction": "friendly",  # Automatically friendly in combat
        },
    )

    return entity


def main():
    """Seed the database with test enemies."""
    graph_ops = CampaignGraphOps()

    print("Seeding enemies for combat testing...\n")

    # Create goblins
    goblins = [
        ("Snikt", "scout"),
        ("Grubnak", "warrior"),
        ("Skree", "archer"),
    ]

    print("Creating Goblins:")
    for name, variant in goblins:
        entity = create_goblin(graph_ops, name, variant)
        print(f"  - {name} ({variant}): {entity['id']}")

    # Create orcs
    orcs = [
        ("Groknak the Crusher", "berserker"),
        ("Urzog", "warrior"),
        ("Thrak Bloodfist", "champion"),
    ]

    print("\nCreating Orcs:")
    for name, variant in orcs:
        entity = create_orc(graph_ops, name, variant)
        print(f"  - {name} ({variant}): {entity['id']}")

    # Create hostile wizards
    wizards = [
        ("Malachar the Burning", "evocation", False),
        ("Vex Shadowmind", "illusion", False),
    ]

    print("\nCreating Enemy Wizards:")
    for name, school, friendly in wizards:
        entity = create_wizard(graph_ops, name, school, friendly)
        print(f"  - {name} ({school}): {entity['id']}")

    # Create friendly allies
    allies = [
        ("Captain Aldric", "captain"),
        ("Guardsman Theron", "guard"),
    ]

    print("\nCreating Friendly Allies:")
    for name, rank in allies:
        entity = create_guard(graph_ops, name, rank)
        print(f"  - {name} ({rank}): {entity['id']} [FRIENDLY]")

    # Create a friendly wizard ally
    entity = create_wizard(graph_ops, "Elara the Wise", "abjuration", friendly=True)
    print(f"  - Elara the Wise (abjuration wizard): {entity['id']} [FRIENDLY]")

    print("\nDone! NPCs created with full stat blocks and personalities.")
    print("\n=== FACTIONS ===")
    print("HOSTILE (default): Goblins, Orcs, Malachar, Vex")
    print("FRIENDLY: Captain Aldric, Guardsman Theron, Elara the Wise")
    print("\nFriendly NPCs automatically fight alongside players!")
    print("\nTo use in combat:")
    print("1. Add players and NPCs via /api/combat/start")
    print("2. Friendly NPCs auto-join player side")
    print("3. Override with is_friendly: true/false if needed")


if __name__ == "__main__":
    main()
