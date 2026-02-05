"""DM Tools for game management and rules lookup."""

import random
import re
from typing import Optional

from pydantic import BaseModel, Field

from backend.graph.schema import EntityType


class DiceResult(BaseModel):
    """Result of a dice roll."""

    expression: str
    rolls: list[int] = Field(default_factory=list)
    modifier: int = 0
    total: int = 0
    critical: bool = False  # Natural 20 or natural 1


class NPCResult(BaseModel):
    """Generated NPC."""

    name: str
    role: str
    race: str
    personality: list[str] = Field(default_factory=list)
    motivations: list[str] = Field(default_factory=list)
    appearance: str = ""
    voice_notes: str = ""
    secret: Optional[str] = None


class EncounterResult(BaseModel):
    """Generated encounter."""

    difficulty: str
    environment: str
    party_level: int
    monsters: list[dict] = Field(default_factory=list)
    total_xp: int = 0
    description: str = ""
    tactics: str = ""


class Combatant(BaseModel):
    """Individual combatant in combat."""

    name: str
    initiative: int = 0
    initiative_bonus: int = 0
    hp: int = 10
    max_hp: int = 10
    is_player: bool = False
    player_id: Optional[str] = None
    player_name: Optional[str] = None
    pc_id: Optional[str] = None
    character_name: Optional[str] = None
    conditions: list[str] = Field(default_factory=list)


class CombatState(BaseModel):
    """Combat state tracking."""

    round: int = 0
    initiative_order: list[dict] = Field(default_factory=list)
    current_turn_idx: int = 0
    active: bool = False
    grid_width: int = 20
    grid_height: int = 15

    def current_combatant(self) -> Optional[dict]:
        """Get the current combatant."""
        if not self.initiative_order:
            return None
        return self.initiative_order[self.current_turn_idx]

    def current_player_info(self) -> Optional[dict]:
        """Get current player info if it's a player's turn."""
        current = self.current_combatant()
        if current and current.get("is_player"):
            return {
                "player_id": current.get("player_id"),
                "player_name": current.get("player_name"),
                "character_name": current.get("character_name"),
                "pc_id": current.get("pc_id"),
            }
        return None


class DMTools:
    """Tools for DM operations."""

    # CR to XP conversion table
    CR_XP_TABLE = {
        0: 10, 0.125: 25, 0.25: 50, 0.5: 100,
        1: 200, 2: 450, 3: 700, 4: 1100, 5: 1800,
        6: 2300, 7: 2900, 8: 3900, 9: 5000, 10: 5900,
        11: 7200, 12: 8400, 13: 10000, 14: 11500, 15: 13000,
        16: 15000, 17: 18000, 18: 20000, 19: 22000, 20: 25000,
    }

    # Difficulty XP thresholds per character level
    DIFFICULTY_THRESHOLDS = {
        1: {"easy": 25, "medium": 50, "hard": 75, "deadly": 100},
        2: {"easy": 50, "medium": 100, "hard": 150, "deadly": 200},
        3: {"easy": 75, "medium": 150, "hard": 225, "deadly": 400},
        4: {"easy": 125, "medium": 250, "hard": 375, "deadly": 500},
        5: {"easy": 250, "medium": 500, "hard": 750, "deadly": 1100},
        6: {"easy": 300, "medium": 600, "hard": 900, "deadly": 1400},
        7: {"easy": 350, "medium": 750, "hard": 1100, "deadly": 1700},
        8: {"easy": 450, "medium": 900, "hard": 1400, "deadly": 2100},
        9: {"easy": 550, "medium": 1100, "hard": 1600, "deadly": 2400},
        10: {"easy": 600, "medium": 1200, "hard": 1900, "deadly": 2800},
    }

    # Personality traits for NPC generation
    PERSONALITY_TRAITS = [
        "friendly", "suspicious", "nervous", "confident", "greedy",
        "generous", "scholarly", "superstitious", "pragmatic", "idealistic",
        "cynical", "optimistic", "cautious", "reckless", "patient",
        "impatient", "formal", "casual", "secretive", "talkative",
    ]

    NPC_MOTIVATIONS = [
        "wealth", "power", "knowledge", "revenge", "protection",
        "freedom", "love", "duty", "curiosity", "survival",
        "redemption", "legacy", "justice", "pleasure", "faith",
    ]

    FANTASY_NAMES = {
        "human": ["Aldric", "Beren", "Cedric", "Elara", "Fiona", "Gwendolyn",
                  "Helena", "Isolde", "Marcus", "Nora", "Roland", "Theron"],
        "elf": ["Aelindra", "Caelynn", "Elrond", "Faelyn", "Galadriel",
                "Legolas", "Miriel", "Silvan", "Thranduil", "Vanya"],
        "dwarf": ["Balin", "Dain", "Gimli", "Kili", "Thorin", "Bombur",
                  "Helga", "Brina", "Dagna", "Rurik"],
        "halfling": ["Bilbo", "Frodo", "Merry", "Pippin", "Rosie",
                     "Cora", "Nilo", "Tansy", "Wren", "Brandy"],
        "tiefling": ["Akta", "Damaia", "Kallista", "Mephistopheles",
                     "Nemeia", "Orianna", "Therai", "Zariel"],
    }

    def __init__(self):
        """Initialize DM tools."""
        self.combat_state: Optional[CombatState] = None

    def roll_dice(self, expression: str) -> DiceResult:
        """Roll dice using standard notation.

        Args:
            expression: Dice notation like "2d6+3", "1d20", "4d6 drop lowest".

        Returns:
            DiceResult with rolls and total.
        """
        expression = expression.lower().strip()

        # Parse basic dice notation: NdM+X or NdM-X
        match = re.match(r"(\d+)d(\d+)([+-]\d+)?", expression)
        if not match:
            return DiceResult(expression=expression, total=0)

        num_dice = int(match.group(1))
        die_size = int(match.group(2))
        modifier = int(match.group(3)) if match.group(3) else 0

        # Roll the dice
        rolls = [random.randint(1, die_size) for _ in range(num_dice)]

        # Handle "drop lowest" for ability scores
        if "drop" in expression and num_dice > 1:
            rolls.sort()
            rolls = rolls[1:]  # Remove lowest

        total = sum(rolls) + modifier

        # Check for critical on d20
        critical = False
        if die_size == 20 and num_dice == 1:
            critical = rolls[0] in (1, 20)

        return DiceResult(
            expression=expression,
            rolls=rolls,
            modifier=modifier,
            total=total,
            critical=critical,
        )

    def generate_npc(
        self,
        role: str,
        race: Optional[str] = None,
        context: Optional[str] = None,
    ) -> NPCResult:
        """Generate a random NPC.

        Args:
            role: NPC's role (merchant, guard, innkeeper, etc.).
            race: Optional race, random if not specified.
            context: Optional context for generation.

        Returns:
            NPCResult with generated NPC details.
        """
        # Pick race if not specified
        if not race:
            race = random.choice(list(self.FANTASY_NAMES.keys()))

        # Generate name
        name_pool = self.FANTASY_NAMES.get(race.lower(), self.FANTASY_NAMES["human"])
        name = random.choice(name_pool)

        # Generate personality
        traits = random.sample(self.PERSONALITY_TRAITS, 2)
        motivations = random.sample(self.NPC_MOTIVATIONS, 2)

        # Generate appearance based on race
        appearances = {
            "human": "average height, weathered features",
            "elf": "tall and graceful, pointed ears",
            "dwarf": "stocky, thick beard",
            "halfling": "short, cheerful face",
            "tiefling": "horns, unusual skin tone",
        }
        appearance = appearances.get(race.lower(), "unremarkable appearance")

        # Voice notes based on traits
        voice_notes = self._generate_voice_notes(traits)

        # Generate a secret
        secrets = [
            "is secretly a member of a thieves guild",
            "knows the location of a hidden treasure",
            "is being blackmailed by a local noble",
            "has a gambling debt to pay off",
            "is hiding from their past",
            "has witnessed a murder",
            "knows a dangerous secret about the local lord",
            None,  # Some NPCs have no secrets
        ]
        secret = random.choice(secrets)

        return NPCResult(
            name=name,
            role=role,
            race=race,
            personality=traits,
            motivations=motivations,
            appearance=appearance,
            voice_notes=voice_notes,
            secret=secret,
        )

    def _generate_voice_notes(self, traits: list[str]) -> str:
        """Generate voice notes based on personality traits."""
        notes = []
        if "nervous" in traits:
            notes.append("speaks quickly, stammers")
        if "confident" in traits:
            notes.append("speaks slowly and deliberately")
        if "suspicious" in traits:
            notes.append("speaks in hushed tones, glances around")
        if "friendly" in traits:
            notes.append("warm, welcoming tone")
        if "formal" in traits:
            notes.append("proper speech, uses titles")
        if "casual" in traits:
            notes.append("uses slang, relaxed speech")
        if "scholarly" in traits:
            notes.append("uses complex vocabulary")

        return "; ".join(notes) if notes else "neutral tone"

    def generate_encounter(
        self,
        difficulty: str,
        environment: str,
        party_level: int,
        party_size: int = 4,
    ) -> EncounterResult:
        """Generate a balanced combat encounter.

        Args:
            difficulty: easy, medium, hard, or deadly.
            environment: dungeon, forest, urban, etc.
            party_level: Average party level.
            party_size: Number of party members.

        Returns:
            EncounterResult with monster selection.
        """
        # Get XP budget
        level = min(party_level, 10)  # Cap at level 10 in our table
        thresholds = self.DIFFICULTY_THRESHOLDS.get(level, self.DIFFICULTY_THRESHOLDS[1])
        target_xp = thresholds.get(difficulty.lower(), thresholds["medium"])
        total_budget = target_xp * party_size

        # Environment-appropriate monsters
        env_monsters = self._get_environment_monsters(environment)

        # Select monsters to fill budget
        selected = []
        remaining_xp = total_budget
        attempts = 0

        while remaining_xp > 50 and attempts < 10:
            # Pick a monster that fits the budget
            valid_monsters = [
                m for m in env_monsters
                if self.CR_XP_TABLE.get(m["cr"], 0) <= remaining_xp
            ]
            if not valid_monsters:
                break

            monster = random.choice(valid_monsters)
            monster_xp = self.CR_XP_TABLE.get(monster["cr"], 0)
            selected.append(monster)
            remaining_xp -= monster_xp
            attempts += 1

        # Calculate actual XP (with multiplier for multiple monsters)
        total_xp = sum(self.CR_XP_TABLE.get(m["cr"], 0) for m in selected)
        if len(selected) > 1:
            multiplier = 1.5 if len(selected) <= 2 else 2.0 if len(selected) <= 6 else 2.5
            total_xp = int(total_xp * multiplier)

        # Generate description and tactics
        description = self._generate_encounter_description(selected, environment)
        tactics = self._generate_tactics(selected)

        return EncounterResult(
            difficulty=difficulty,
            environment=environment,
            party_level=party_level,
            monsters=selected,
            total_xp=total_xp,
            description=description,
            tactics=tactics,
        )

    def _get_environment_monsters(self, environment: str) -> list[dict]:
        """Get monsters appropriate for an environment."""
        # Basic monster pool - in production, query from database
        monsters = {
            "dungeon": [
                {"name": "Goblin", "cr": 0.25, "type": "humanoid"},
                {"name": "Skeleton", "cr": 0.25, "type": "undead"},
                {"name": "Zombie", "cr": 0.25, "type": "undead"},
                {"name": "Hobgoblin", "cr": 0.5, "type": "humanoid"},
                {"name": "Ghoul", "cr": 1, "type": "undead"},
                {"name": "Bugbear", "cr": 1, "type": "humanoid"},
                {"name": "Ogre", "cr": 2, "type": "giant"},
                {"name": "Minotaur", "cr": 3, "type": "monstrosity"},
            ],
            "forest": [
                {"name": "Wolf", "cr": 0.25, "type": "beast"},
                {"name": "Giant Spider", "cr": 1, "type": "beast"},
                {"name": "Dire Wolf", "cr": 1, "type": "beast"},
                {"name": "Owlbear", "cr": 3, "type": "monstrosity"},
                {"name": "Green Hag", "cr": 3, "type": "fey"},
            ],
            "urban": [
                {"name": "Bandit", "cr": 0.125, "type": "humanoid"},
                {"name": "Thug", "cr": 0.5, "type": "humanoid"},
                {"name": "Spy", "cr": 1, "type": "humanoid"},
                {"name": "Assassin", "cr": 8, "type": "humanoid"},
            ],
            "underdark": [
                {"name": "Drow", "cr": 0.25, "type": "humanoid"},
                {"name": "Giant Spider", "cr": 1, "type": "beast"},
                {"name": "Drider", "cr": 6, "type": "monstrosity"},
            ],
        }

        return monsters.get(environment.lower(), monsters["dungeon"])

    def _generate_encounter_description(
        self,
        monsters: list[dict],
        environment: str,
    ) -> str:
        """Generate a brief encounter description."""
        if not monsters:
            return "An empty area."

        monster_names = [m["name"] for m in monsters]
        unique_monsters = list(set(monster_names))

        if len(unique_monsters) == 1:
            count = len(monsters)
            name = unique_monsters[0]
            return f"{count} {name}{'s' if count > 1 else ''} lurk in the {environment}."
        else:
            names = ", ".join(unique_monsters[:-1]) + f" and {unique_monsters[-1]}"
            return f"A group of {names} block your path."

    def _generate_tactics(self, monsters: list[dict]) -> str:
        """Generate basic combat tactics."""
        if not monsters:
            return "No combat expected."

        tactics = []
        types = set(m["type"] for m in monsters)

        if "undead" in types:
            tactics.append("Undead attack mindlessly, focusing nearest targets")
        if "humanoid" in types:
            tactics.append("Humanoids work together, flanking when possible")
        if "beast" in types:
            tactics.append("Beasts target isolated or wounded prey")
        if "monstrosity" in types:
            tactics.append("Use terrain and ambush tactics")

        return ". ".join(tactics) if tactics else "Standard combat tactics."

    def start_combat(
        self,
        combatants: list[dict],
    ) -> CombatState:
        """Start a new combat encounter.

        Args:
            combatants: List of combatants with name, initiative bonus, and optional
                        player info (player_id, player_name, pc_id, character_name).

        Returns:
            CombatState with initiative order.
        """
        # Roll initiative for each combatant
        initiative_order = []
        for c in combatants:
            roll = self.roll_dice("1d20")
            init_total = roll.total + c.get("initiative_bonus", 0)
            initiative_order.append({
                "name": c["name"],
                "initiative": init_total,
                "initiative_bonus": c.get("initiative_bonus", 0),
                "hp": c.get("hp", 10),
                "max_hp": c.get("max_hp", c.get("hp", 10)),
                "ac": c.get("ac", 10),
                "is_player": c.get("is_player", False),
                "is_npc": c.get("is_npc", False),
                "is_friendly": c.get("is_friendly", False),
                "npc_id": c.get("npc_id"),
                "player_id": c.get("player_id"),
                "player_name": c.get("player_name"),
                "pc_id": c.get("pc_id"),
                "character_name": c.get("character_name"),
                "conditions": [],
            })

        # Sort by initiative (descending)
        initiative_order.sort(key=lambda x: x["initiative"], reverse=True)

        self.combat_state = CombatState(
            round=1,
            initiative_order=initiative_order,
            current_turn_idx=0,
            active=True,
        )

        # Auto-place combatants on the grid
        self._auto_place_combatants()

        return self.combat_state

    def start_combat_from_session(
        self,
        session_attendees: list[dict],
        additional_combatants: Optional[list[dict]] = None,
    ) -> CombatState:
        """Start combat with session attendees as combatants.

        Args:
            session_attendees: List of players from get_session_attendees().
                Each should have id, name, and optionally active_pc.
            additional_combatants: Optional list of monsters/NPCs to add.

        Returns:
            CombatState with initiative order.
        """
        combatants = []

        # Add player characters
        for player in session_attendees:
            if player.get("active_pc"):
                pc = player["active_pc"]
                combatants.append({
                    "name": pc.get("name", "Unknown"),
                    "initiative_bonus": pc.get("initiative_bonus", 0),
                    "hp": pc.get("hp", 10),
                    "max_hp": pc.get("max_hp", 10),
                    "is_player": True,
                    "player_id": player.get("id"),
                    "player_name": player.get("name"),
                    "pc_id": pc.get("id"),
                    "character_name": pc.get("name"),
                })

        # Add monsters/NPCs
        if additional_combatants:
            for c in additional_combatants:
                combatants.append({
                    "name": c.get("name", "Monster"),
                    "initiative_bonus": c.get("initiative_bonus", 0),
                    "hp": c.get("hp", 10),
                    "max_hp": c.get("max_hp", c.get("hp", 10)),
                    "is_player": False,
                })

        return self.start_combat(combatants)

    def next_turn(self) -> Optional[dict]:
        """Advance to the next turn in combat.

        Returns:
            Dict with current combatant info and player details, or None if combat ended.
        """
        if not self.combat_state or not self.combat_state.active:
            return None

        # Move to next combatant
        self.combat_state.current_turn_idx += 1

        # Check for new round
        if self.combat_state.current_turn_idx >= len(self.combat_state.initiative_order):
            self.combat_state.current_turn_idx = 0
            self.combat_state.round += 1

        # Skip dead combatants
        current = self.combat_state.initiative_order[self.combat_state.current_turn_idx]
        attempts = 0
        while current["hp"] <= 0 and attempts < len(self.combat_state.initiative_order):
            self.combat_state.current_turn_idx += 1
            if self.combat_state.current_turn_idx >= len(self.combat_state.initiative_order):
                self.combat_state.current_turn_idx = 0
                self.combat_state.round += 1
            current = self.combat_state.initiative_order[self.combat_state.current_turn_idx]
            attempts += 1

        # Check if combat is over (all combatants down)
        if attempts >= len(self.combat_state.initiative_order):
            self.combat_state.active = False
            return {"combat_ended": True, "reason": "All combatants down"}

        result = {
            "round": self.combat_state.round,
            "current": current,
            "initiative_order": self.combat_state.initiative_order,
        }

        # Add player info if it's a player's turn
        if current.get("is_player"):
            result["player_info"] = {
                "player_id": current.get("player_id"),
                "player_name": current.get("player_name"),
                "character_name": current.get("character_name"),
            }

        return result

    def apply_damage(self, target_name: str, damage: int) -> dict:
        """Apply damage to a combatant.

        Args:
            target_name: Name of the target.
            damage: Amount of damage.

        Returns:
            Dict with target status.
        """
        if not self.combat_state:
            return {"error": "No combat active"}

        for c in self.combat_state.initiative_order:
            if c["name"].lower() == target_name.lower():
                c["hp"] = max(0, c["hp"] - damage)
                return {
                    "name": c["name"],
                    "damage_taken": damage,
                    "current_hp": c["hp"],
                    "max_hp": c["max_hp"],
                    "status": "down" if c["hp"] <= 0 else "active",
                }

        return {"error": f"Combatant '{target_name}' not found"}

    def get_combat_status(self) -> Optional[dict]:
        """Get current combat status without advancing turn.

        Returns:
            Current combat state or None if no combat active.
        """
        if not self.combat_state or not self.combat_state.active:
            return None

        current = self.combat_state.current_combatant()
        result = {
            "round": self.combat_state.round,
            "current": current,
            "initiative_order": self.combat_state.initiative_order,
            "active": self.combat_state.active,
        }

        if current and current.get("is_player"):
            result["player_info"] = self.combat_state.current_player_info()

        return result

    def add_condition(self, target_name: str, condition: str) -> dict:
        """Add a condition to a combatant.

        Args:
            target_name: Name of the target.
            condition: Condition to add (e.g., "poisoned", "stunned").

        Returns:
            Dict with target status.
        """
        if not self.combat_state:
            return {"error": "No combat active"}

        for c in self.combat_state.initiative_order:
            if c["name"].lower() == target_name.lower():
                if "conditions" not in c:
                    c["conditions"] = []
                if condition not in c["conditions"]:
                    c["conditions"].append(condition)
                return {
                    "name": c["name"],
                    "conditions": c["conditions"],
                }

        return {"error": f"Combatant '{target_name}' not found"}

    def remove_condition(self, target_name: str, condition: str) -> dict:
        """Remove a condition from a combatant.

        Args:
            target_name: Name of the target.
            condition: Condition to remove.

        Returns:
            Dict with target status.
        """
        if not self.combat_state:
            return {"error": "No combat active"}

        for c in self.combat_state.initiative_order:
            if c["name"].lower() == target_name.lower():
                if "conditions" in c and condition in c["conditions"]:
                    c["conditions"].remove(condition)
                return {
                    "name": c["name"],
                    "conditions": c.get("conditions", []),
                }

        return {"error": f"Combatant '{target_name}' not found"}

    def apply_healing(self, target_name: str, healing: int) -> dict:
        """Apply healing to a combatant.

        Args:
            target_name: Name of the target.
            healing: Amount of healing.

        Returns:
            Dict with target status.
        """
        if not self.combat_state:
            return {"error": "No combat active"}

        for c in self.combat_state.initiative_order:
            if c["name"].lower() == target_name.lower():
                c["hp"] = min(c["max_hp"], c["hp"] + healing)
                return {
                    "name": c["name"],
                    "healing_received": healing,
                    "current_hp": c["hp"],
                    "max_hp": c["max_hp"],
                    "status": "active" if c["hp"] > 0 else "down",
                }

        return {"error": f"Combatant '{target_name}' not found"}

    def end_combat(self) -> dict:
        """End the current combat.

        Returns:
            Combat summary with player info.
        """
        if not self.combat_state:
            return {"message": "No combat to end"}

        survivors = [c for c in self.combat_state.initiative_order if c["hp"] > 0]
        defeated = [c for c in self.combat_state.initiative_order if c["hp"] <= 0]

        summary = {
            "rounds": self.combat_state.round,
            "survivors": survivors,
            "defeated": defeated,
            "player_survivors": [
                {
                    "player_name": c.get("player_name"),
                    "character_name": c.get("character_name"),
                    "hp": c["hp"],
                    "max_hp": c["max_hp"],
                }
                for c in survivors if c.get("is_player")
            ],
            "player_casualties": [
                {
                    "player_name": c.get("player_name"),
                    "character_name": c.get("character_name"),
                }
                for c in defeated if c.get("is_player")
            ],
        }

        self.combat_state = None
        return summary

    def _auto_place_combatants(self) -> None:
        """Auto-place combatants on the grid: players left, enemies right."""
        if not self.combat_state:
            return

        grid = self.combat_state
        player_side = [c for c in grid.initiative_order
                       if c.get("is_player") or c.get("is_friendly")]
        enemy_side = [c for c in grid.initiative_order
                      if not c.get("is_player") and not c.get("is_friendly")]

        player_col = 3
        enemy_col = grid.grid_width - 4

        def place_group(group: list[dict], col: int) -> None:
            start_row = max(0, (grid.grid_height - len(group)) // 2)
            for i, c in enumerate(group):
                c["x"] = col
                c["y"] = start_row + i

        place_group(player_side, player_col)
        place_group(enemy_side, enemy_col)

    def move_combatant(self, name: str, x: int, y: int) -> dict:
        """Move a combatant to a new grid position.

        Args:
            name: Combatant name.
            x: Target column.
            y: Target row.

        Returns:
            Result dict with new position or error.
        """
        if not self.combat_state:
            return {"error": "No combat active"}

        grid = self.combat_state

        # Bounds check
        if x < 0 or x >= grid.grid_width or y < 0 or y >= grid.grid_height:
            return {"error": f"Position ({x}, {y}) is out of bounds"}

        # Collision check
        for c in grid.initiative_order:
            if c["name"] != name and c.get("x") == x and c.get("y") == y and c["hp"] > 0:
                return {"error": f"Cell ({x}, {y}) is occupied by {c['name']}"}

        # Find and move
        for c in grid.initiative_order:
            if c["name"] == name:
                c["x"] = x
                c["y"] = y
                return {"name": name, "x": x, "y": y}

        return {"error": f"Combatant '{name}' not found"}

    def add_combatant_mid_combat(self, combatant: dict) -> dict:
        """Add a combatant to an active combat.

        Rolls initiative and inserts at the correct position.

        Args:
            combatant: Combatant dict with name, hp, etc.

        Returns:
            Result dict with new combatant info.
        """
        if not self.combat_state or not self.combat_state.active:
            return {"error": "No active combat"}

        # Roll initiative
        roll = self.roll_dice("1d20")
        init_total = roll.total + combatant.get("initiative_bonus", 0)

        new_entry = {
            "name": combatant["name"],
            "initiative": init_total,
            "initiative_bonus": combatant.get("initiative_bonus", 0),
            "hp": combatant.get("hp", 10),
            "max_hp": combatant.get("max_hp", combatant.get("hp", 10)),
            "ac": combatant.get("ac", 10),
            "is_player": combatant.get("is_player", False),
            "is_npc": combatant.get("is_npc", False),
            "is_friendly": combatant.get("is_friendly", False),
            "npc_id": combatant.get("npc_id"),
            "player_id": combatant.get("player_id"),
            "player_name": combatant.get("player_name"),
            "pc_id": combatant.get("pc_id"),
            "character_name": combatant.get("character_name"),
            "conditions": [],
            "x": combatant.get("x"),
            "y": combatant.get("y"),
        }

        # Find insertion index to maintain initiative order
        order = self.combat_state.initiative_order
        insert_idx = len(order)
        for i, c in enumerate(order):
            if c["initiative"] < init_total:
                insert_idx = i
                break

        # Adjust current_turn_idx if inserting before current
        if insert_idx <= self.combat_state.current_turn_idx:
            self.combat_state.current_turn_idx += 1

        order.insert(insert_idx, new_entry)

        return {
            "name": new_entry["name"],
            "initiative": new_entry["initiative"],
            "hp": new_entry["hp"],
            "max_hp": new_entry["max_hp"],
            "x": new_entry.get("x"),
            "y": new_entry.get("y"),
            "index": insert_idx,
        }

    def remove_combatant_mid_combat(self, name: str) -> dict:
        """Remove a combatant from active combat.

        Adjusts current_turn_idx as needed.

        Args:
            name: Combatant name to remove.

        Returns:
            Result dict or error.
        """
        if not self.combat_state or not self.combat_state.active:
            return {"error": "No active combat"}

        order = self.combat_state.initiative_order
        remove_idx = None
        for i, c in enumerate(order):
            if c["name"] == name:
                remove_idx = i
                break

        if remove_idx is None:
            return {"error": f"Combatant '{name}' not found"}

        removed = order.pop(remove_idx)

        # Adjust current_turn_idx
        if remove_idx < self.combat_state.current_turn_idx:
            self.combat_state.current_turn_idx -= 1
        elif remove_idx == self.combat_state.current_turn_idx:
            # Current combatant was removed, stay at same index (next combatant)
            if self.combat_state.current_turn_idx >= len(order):
                self.combat_state.current_turn_idx = 0

        return {"removed": removed["name"], "remaining": len(order)}
