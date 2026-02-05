"""D&D 5e SRD weapon data and distance utilities."""

from typing import Optional


# SRD Weapon Table
# Keys are lowercase weapon names.
# "category": "melee" | "ranged"
# "reach": feet (melee only, default 5)
# "range": (normal, long) in feet (ranged only)
# "thrown": (normal, long) if weapon can be thrown
SRD_WEAPONS: dict[str, dict] = {
    # Simple Melee
    "club":           {"category": "melee", "reach": 5},
    "dagger":         {"category": "melee", "reach": 5, "thrown": (20, 60)},
    "greatclub":      {"category": "melee", "reach": 5},
    "handaxe":        {"category": "melee", "reach": 5, "thrown": (20, 60)},
    "javelin":        {"category": "melee", "reach": 5, "thrown": (30, 120)},
    "light hammer":   {"category": "melee", "reach": 5, "thrown": (20, 60)},
    "mace":           {"category": "melee", "reach": 5},
    "quarterstaff":   {"category": "melee", "reach": 5},
    "sickle":         {"category": "melee", "reach": 5},
    "spear":          {"category": "melee", "reach": 5, "thrown": (20, 60)},
    "unarmed strike": {"category": "melee", "reach": 5},

    # Martial Melee
    "battleaxe":      {"category": "melee", "reach": 5},
    "flail":          {"category": "melee", "reach": 5},
    "glaive":         {"category": "melee", "reach": 10},
    "greataxe":       {"category": "melee", "reach": 5},
    "greatsword":     {"category": "melee", "reach": 5},
    "halberd":        {"category": "melee", "reach": 10},
    "lance":          {"category": "melee", "reach": 10},
    "longsword":      {"category": "melee", "reach": 5},
    "maul":           {"category": "melee", "reach": 5},
    "morningstar":    {"category": "melee", "reach": 5},
    "pike":           {"category": "melee", "reach": 10},
    "rapier":         {"category": "melee", "reach": 5},
    "scimitar":       {"category": "melee", "reach": 5},
    "shortsword":     {"category": "melee", "reach": 5},
    "trident":        {"category": "melee", "reach": 5, "thrown": (20, 60)},
    "war pick":       {"category": "melee", "reach": 5},
    "warhammer":      {"category": "melee", "reach": 5},
    "whip":           {"category": "melee", "reach": 10},

    # Simple Ranged
    "light crossbow": {"category": "ranged", "range": (80, 320)},
    "dart":           {"category": "ranged", "range": (20, 60)},
    "shortbow":       {"category": "ranged", "range": (80, 320)},
    "sling":          {"category": "ranged", "range": (30, 120)},

    # Martial Ranged
    "blowgun":        {"category": "ranged", "range": (25, 100)},
    "hand crossbow":  {"category": "ranged", "range": (30, 120)},
    "heavy crossbow": {"category": "ranged", "range": (100, 400)},
    "longbow":        {"category": "ranged", "range": (150, 600)},
    "net":            {"category": "ranged", "range": (5, 15)},

    # Common monster attacks
    "bite":           {"category": "melee", "reach": 5},
    "claw":           {"category": "melee", "reach": 5},
    "claws":          {"category": "melee", "reach": 5},
    "slam":           {"category": "melee", "reach": 5},
    "tail":           {"category": "melee", "reach": 10},
    "tail attack":    {"category": "melee", "reach": 10},
    "tentacle":       {"category": "melee", "reach": 10},
    "gore":           {"category": "melee", "reach": 5},
    "sting":          {"category": "melee", "reach": 5},
    "fist":           {"category": "melee", "reach": 5},
}


def get_weapon_info(attack_name: str) -> dict:
    """Look up SRD weapon data for an attack name.

    Falls back to default melee (reach 5ft) for unknown weapons.
    Handles fuzzy matching: "Greataxe +1" -> "greataxe".

    Args:
        attack_name: The name from the attack dict.

    Returns:
        Weapon info dict with category, reach/range.
    """
    name = attack_name.lower().strip()

    # Direct match
    if name in SRD_WEAPONS:
        return SRD_WEAPONS[name]

    # Try to find a weapon name contained in the attack name
    for weapon_name, info in SRD_WEAPONS.items():
        if weapon_name in name or name.startswith(weapon_name):
            return info

    # Default: assume melee, reach 5
    return {"category": "melee", "reach": 5}


def get_attack_range(attack: dict) -> tuple[str, int, Optional[int]]:
    """Get the effective range of an attack dict.

    Checks for explicit 'reach' or 'range' fields in the attack dict first,
    then falls back to SRD lookup by name.

    Args:
        attack: Attack dict {"name": ..., "bonus": ..., "damage": ..., ...}

    Returns:
        (category, normal_range_ft, long_range_ft_or_None)
        e.g. ("melee", 5, None) or ("ranged", 80, 320)
    """
    # Honor explicit fields if present
    if "reach" in attack:
        return ("melee", attack["reach"], None)
    if "range" in attack:
        r = attack["range"]
        if isinstance(r, (list, tuple)) and len(r) == 2:
            return ("ranged", r[0], r[1])
        elif isinstance(r, int):
            return ("ranged", r, r * 4)
        elif isinstance(r, str):
            # Parse "80/320" or "80ft/320ft" format
            parts = r.replace("ft", "").replace(" ", "").split("/")
            try:
                normal = int(parts[0])
                long = int(parts[1]) if len(parts) > 1 else normal * 4
                return ("ranged", normal, long)
            except ValueError:
                pass

    # SRD lookup
    info = get_weapon_info(attack.get("name", ""))
    if info["category"] == "ranged":
        r = info.get("range", (80, 320))
        return ("ranged", r[0], r[1])
    else:
        return ("melee", info.get("reach", 5), None)


def parse_spell_range(spell_range: str) -> tuple[str, int, Optional[int]]:
    """Parse a spell's range string into (category, range_ft, None).

    Args:
        spell_range: e.g. "touch", "120ft", "30 ft", "self"

    Returns:
        (category, range_ft, None)
    """
    r = spell_range.lower().strip()
    if r in ("touch", "self", "5ft", "5 ft"):
        return ("melee", 5, None)
    # Strip "ft" and parse number
    try:
        feet = int(r.replace("ft", "").replace(" ", ""))
        return ("ranged", feet, feet)
    except ValueError:
        return ("ranged", 120, 120)  # Default spell range


def grid_distance_ft(x1: int, y1: int, x2: int, y2: int) -> int:
    """Calculate D&D 5e grid distance in feet (Chebyshev distance).

    Each square = 5 feet. Diagonals cost the same as orthogonal moves
    per the D&D 5e standard grid rules.

    Args:
        x1, y1: Position of first combatant.
        x2, y2: Position of second combatant.

    Returns:
        Distance in feet.
    """
    return max(abs(x2 - x1), abs(y2 - y1)) * 5


def distance_category(feet: int) -> str:
    """Convert distance in feet to a category label.

    Args:
        feet: Distance in feet.

    Returns:
        "melee" (0-5ft), "close" (10-15ft), "nearby" (20-30ft), "far" (35+ft)
    """
    if feet <= 5:
        return "melee"
    elif feet <= 15:
        return "close"
    elif feet <= 30:
        return "nearby"
    else:
        return "far"
