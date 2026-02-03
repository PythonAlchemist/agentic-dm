"""Gazetteer loading from YAML files."""

from pathlib import Path
from typing import Optional

import yaml

from backend.graph.schema import EntityType
from backend.ner.config import default_config
from backend.ner.models import GazetteerEntry


class GazetteerLoader:
    """Load gazetteers from YAML files."""

    # Map file names to entity types
    FILE_TYPE_MAP = {
        "spells.yaml": EntityType.SPELL,
        "monsters.yaml": EntityType.MONSTER,
        "items.yaml": EntityType.ITEM,
        "classes.yaml": EntityType.CLASS,
        "races.yaml": EntityType.RACE,
        "locations.yaml": EntityType.LOCATION,
        "factions.yaml": EntityType.FACTION,
        "characters.yaml": None,  # Contains both PC and NPC
    }

    def __init__(
        self,
        canonical_dir: Optional[Path] = None,
        campaign_dir: Optional[Path] = None,
    ):
        self.canonical_dir = canonical_dir or default_config.canonical_gazetteer_dir
        self.campaign_dir = campaign_dir or default_config.campaign_gazetteer_dir

    def load_all(self) -> list[GazetteerEntry]:
        """Load all gazetteers from both canonical and campaign directories."""
        entries = []

        # Load canonical gazetteers
        if self.canonical_dir.exists():
            entries.extend(self._load_directory(self.canonical_dir))

        # Load campaign gazetteers (may override canonical)
        if self.campaign_dir.exists():
            entries.extend(self._load_directory(self.campaign_dir))

        return entries

    def _load_directory(self, directory: Path) -> list[GazetteerEntry]:
        """Load all YAML files from a directory."""
        entries = []

        for yaml_file in directory.glob("*.yaml"):
            file_entries = self._load_file(yaml_file)
            entries.extend(file_entries)

        return entries

    def _load_file(self, filepath: Path) -> list[GazetteerEntry]:
        """Load a single YAML gazetteer file."""
        entries = []

        with open(filepath, "r") as f:
            data = yaml.safe_load(f)

        if not data:
            return entries

        # Determine entity type from filename or entry
        default_type = self.FILE_TYPE_MAP.get(filepath.name)

        for item in data:
            entry = self._parse_entry(item, default_type)
            if entry:
                entries.append(entry)

        return entries

    def _parse_entry(
        self,
        item: dict,
        default_type: Optional[EntityType],
    ) -> Optional[GazetteerEntry]:
        """Parse a single gazetteer entry from dict."""
        # Required fields
        if "name" not in item:
            return None

        # Get entity type
        if "entity_type" in item:
            try:
                entity_type = EntityType(item["entity_type"])
            except ValueError:
                entity_type = default_type
        else:
            entity_type = default_type

        if not entity_type:
            # Try to infer from label field (existing YAML format)
            label = item.get("label", "").upper()
            entity_type = self._label_to_entity_type(label)

        if not entity_type:
            return None

        # Build entry
        entry_id = item.get("id", f"{entity_type.value.lower()}_{item['name'].lower().replace(' ', '_')}")

        # Collect aliases
        aliases = item.get("aliases", [])
        if "short_name" in item:
            aliases.append(item["short_name"])

        return GazetteerEntry(
            id=entry_id,
            name=item["name"],
            entity_type=entity_type,
            aliases=aliases,
            patterns=item.get("patterns", []),
            metadata={
                k: v
                for k, v in item.items()
                if k not in ("id", "name", "entity_type", "aliases", "patterns", "label")
            },
        )

    def _label_to_entity_type(self, label: str) -> Optional[EntityType]:
        """Convert a label string to EntityType."""
        label_map = {
            "PC": EntityType.PC,
            "NPC": EntityType.NPC,
            "MONSTER": EntityType.MONSTER,
            "LOCATION": EntityType.LOCATION,
            "ITEM": EntityType.ITEM,
            "SPELL": EntityType.SPELL,
            "FACTION": EntityType.FACTION,
            "QUEST": EntityType.QUEST,
            "EVENT": EntityType.EVENT,
            "CLASS": EntityType.CLASS,
            "RACE": EntityType.RACE,
        }
        return label_map.get(label)

    def load_by_type(self, entity_type: EntityType) -> list[GazetteerEntry]:
        """Load gazetteers for a specific entity type."""
        all_entries = self.load_all()
        return [e for e in all_entries if e.entity_type == entity_type]
