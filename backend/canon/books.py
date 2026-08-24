"""Which book an id belongs to, and how far a name reaches inside it.

`mint_id` used to read a module constant, `BOOK = "cos"`, so every id in every
graph this code could write began `cos:`. One book was the whole world.

TWO BOOKS NEED TWO ANSWERS, AND NOT ONLY ABOUT THE PREFIX.

**A campaign is one continuous world.** Curse of Strahd names Madam Eva in the
introduction and again in chapter 3, and she is one woman both times, so an
unkeyed entity is global to the book -- that is `mint_id`'s stated rule and it
is right for a campaign. Scoping her per chapter gave "one node per chapter,
nine duplicated names across three chapters, and a major NPC heading for twenty
nodes by chapter 25, each holding a slice of her edges".

**An anthology is thirteen separate worlds.** Keys from the Golden Vault holds
thirteen heists that share no continuity: measured on the harvest, thirteen
adventures each head `Conclusion`, `Adventure Background` and `Using the Golden
Vault`, seven head `General Features`, five head `Doors`. A guard in heist one
and a guard in heist seven are two people, and the global rule would fuse them
-- the same defect as Madam Eva's, running the other way.

So the rule is a property of the BOOK, not of this code, and it travels with
the prefix in one value rather than as a second flag somebody can forget.

**EXCEPT FOR WHAT IS GENUINELY BOOK-WIDE.** The Golden Vault is one
organisation across all thirteen heists -- it is named 88 times in 14 harvested
chapters and is the only thing connecting them. An anthology rule with no
exception would make it thirteen organisations. `global_names` is that
exception, hand-authored, because nothing in the text distinguishes "recurs
because it is one thing" from "recurs because the word is common".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(frozen=True)
class BookScheme:
    """One book's id prefix and its scoping rule."""

    #: Short slug leading every id from this book: `cos`, `kftgv`.
    prefix: str
    #: What the `:Book` node is called. Beside the prefix rather than in a
    #: second constant, because `BOOK` and `BOOK_TITLE` were two hardcoded
    #: facts about one book and nothing kept them agreeing.
    title: str = ""
    #: True when the book is a collection of unconnected adventures, so an
    #: unkeyed entity belongs to the chapter that names it rather than to the
    #: book. False for a campaign, which is one continuous world.
    anthology: bool = False
    #: Names that stay book-wide even in an anthology, folded for comparison.
    global_names: frozenset[str] = field(default_factory=frozenset)
    #: This book's structural-heading seed, by filename inside the seeds
    #: directory. Per book because books organise themselves differently:
    #: nothing in Barovia heads `Planning the Heist` and nothing in the heist
    #: anthology heads `Fortunes of Ravenloft`, so one shared seed would be
    #: each book carrying the other's exceptions.
    structural_headings: str = "structural-headings.yaml"
    #: Path to this book's name index, or empty when it has none. Curse of
    #: Strahd has a 677-entry wiki index; the heist anthology's wiki page
    #: carries no `==Index==` at all, so the field is empty there and
    #: `plan_write` falls back to filtering by name shape.
    gazetteer: str = ""

    def __post_init__(self) -> None:
        """Normalise the allowlist HERE, so no caller has to remember to.

        `load` did it and a directly-constructed scheme did not, which meant a
        test could pass `the golden vault` and get a set that `is_global` could
        never match -- the invariant living in one of two construction paths.
        It belongs on the type.
        """
        from backend.canon.duplicates import normalize

        object.__setattr__(
            self, "global_names", frozenset(normalize(n) for n in self.global_names)
        )

    def is_global(self, name: str) -> bool:
        """Is this one of the few names an anthology shares?

        Case-folded AND article-stripped, the same normalisation
        `duplicates.normalize` uses, because an allowlist that matched a
        SPELLING did the opposite of its job. Written exact, `The Golden Vault`
        made the entity spelled that way global and left every `Golden Vault`
        to be scoped per chapter -- so the one line meant to keep the
        organisation whole shattered it into thirteen, one per adventure, while
        a fourteenth held the 35 mentions that happened to use the article.

        An allowlist names a THING. Anything a reader would spell it as has to
        match, or the entry is a trap.
        """
        from backend.canon.duplicates import normalize

        return normalize(name) in self.global_names

    def scopes_to_chapter(self, name: str) -> bool:
        """Should an UNKEYED entity of this name be scoped to its chapter?

        A keyed place never asks this: it already resolves to (book, chapter,
        key) and has done since long before books were a parameter.
        """
        return self.anthology and not self.is_global(name)


#: What every call meant before books were a parameter. Named `LEGACY` rather
#: than `DEFAULT` for the reason `sections.LEGACY_SCHEME` is: a default is
#: something to reach for, and this is something to stop needing. The CLI
#: always passes a scheme explicitly.
LEGACY = BookScheme(prefix="cos")


def load(path: Path) -> BookScheme:
    """Read a scheme from YAML.

    The file carries slugs and a handful of proper nouns -- no book text -- so
    it is committed, unlike everything under `data/`.
    """
    raw = yaml.safe_load(path.read_text()) or {}
    return BookScheme(
        prefix=raw["prefix"],
        title=raw.get("title", ""),
        anthology=bool(raw.get("anthology", False)),
        global_names=frozenset(raw.get("global_names", [])),
        structural_headings=raw.get(
            "structural_headings", "structural-headings.yaml"
        ),
        gazetteer=raw.get("gazetteer", ""),
    )
