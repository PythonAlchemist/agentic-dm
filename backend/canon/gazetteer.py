"""Look names up in the harvested canon gazetteer.

The gazetteer exists to *reject* things. A candidate node named `skeleton` or `K20` is
not a canon entity, and the only way a lookup table can say so is by refusing to match
anything it was not told about. So matching is exact, then case-insensitive, then
recorded aliases, and it stops there -- no fuzzy distance, no token subsets, no
substring containment. The grader learned that lesson the expensive way: token-subset
matching let a candidate `Ireena` credit both the NPC and the quest `Escort Ireena to
Vallaki`, which is how a regex shotgun came to outscore a real extractor. A gazetteer
that matched as loosely as that would launder junk into legitimacy.

Deliberately does not import `backend/canon/grade.py`: the pipeline must not depend on
the module that scores it, so the normalisation below is this module's own.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from backend.graph.schema import RelationshipType

#: Infobox field -> relationship type. `home` is where the entity lives; the kinship
#: fields are all RELATED_TO because the ontology has no parent/spouse/sibling edges and
#: inventing a direction the schema does not define would be worse than saying "related".
FIELD_RELATIONS: dict[str, RelationshipType] = {
    "home": RelationshipType.LOCATED_IN,
    "parents": RelationshipType.RELATED_TO,
    "spouses": RelationshipType.RELATED_TO,
    "siblings": RelationshipType.RELATED_TO,
    "children": RelationshipType.RELATED_TO,
}


def normalize(name: str) -> str:
    """Lowercase-and-strip. The only liberty taken with a name anywhere in this module."""
    return name.strip().lower()


@dataclass(frozen=True)
class GazetteerEntry:
    """One canon entity as the wiki index typed it."""

    name: str
    entity_type: str
    wiki_category: str
    aliases: tuple[str, ...] = ()
    page_exists: bool = False
    redirect_to: str | None = None
    index_pages: str | None = None
    cited_pages: tuple[str, ...] = ()
    fields: dict[str, list[str] | str] = field(default_factory=dict)


class Gazetteer:
    """A closed set of canon names. Everything outside it is unknown, by design."""

    def __init__(self, entries: list[GazetteerEntry], source: dict | None = None) -> None:
        self.entries = list(entries)
        self.source = source or {}
        self._exact: dict[str, GazetteerEntry] = {}
        self._by_name: dict[str, GazetteerEntry] = {}
        self._by_alias: dict[str, GazetteerEntry] = {}
        for entry in self.entries:
            self._exact.setdefault(entry.name, entry)
            self._by_name.setdefault(normalize(entry.name), entry)
        # Aliases are indexed after every canonical name, and never overwrite one.
        for entry in self.entries:
            for alias in entry.aliases:
                if normalize(alias) not in self._by_name:
                    self._by_alias.setdefault(normalize(alias), entry)

    def __len__(self) -> int:
        return len(self.entries)

    def lookup(self, name: str) -> GazetteerEntry | None:
        """Exact, then case-insensitive, then recorded aliases. Nothing else.

        A canonical name always wins over another entry's alias: the wiki chose the
        canonical name, an alias is only a pointer to one.
        """
        key = normalize(name)
        return self._exact.get(name) or self._by_name.get(key) or self._by_alias.get(key)

    def entity_type(self, name: str) -> str | None:
        entry = self.lookup(name)
        return entry.entity_type if entry else None

    def is_known(self, name: str) -> bool:
        return self.lookup(name) is not None

    def relations(self, name: str) -> list[tuple[str, str, str]]:
        """Infobox relations as (source, rel_type, target), markup already stripped.

        Targets are the wiki's own display names. They are not re-pointed at whichever
        entry they happen to resemble -- that would be resolution, which is a later
        stage's job and not something a lookup table should quietly do.
        """
        entry = self.lookup(name)
        if entry is None:
            return []
        relations: list[tuple[str, str, str]] = []
        for field_name, rel_type in FIELD_RELATIONS.items():
            values = entry.fields.get(field_name) or []
            if isinstance(values, str):
                values = [values]
            for target in values:
                relation = (entry.name, rel_type.value, target)
                if relation not in relations:
                    relations.append(relation)
        return relations


def load_gazetteer(path: str | Path) -> Gazetteer:
    """Read a harvested gazetteer document from disk."""
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    entries = [
        GazetteerEntry(
            name=raw["name"],
            entity_type=raw["entity_type"],
            wiki_category=raw["wiki_category"],
            aliases=tuple(raw.get("aliases", ())),
            page_exists=bool(raw.get("page_exists")),
            redirect_to=raw.get("redirect_to"),
            index_pages=raw.get("index_pages"),
            cited_pages=tuple(raw.get("cited_pages", ())),
            fields=raw.get("fields", {}),
        )
        for raw in document.get("entries", [])
    ]
    return Gazetteer(entries, source=document.get("source", {}))
