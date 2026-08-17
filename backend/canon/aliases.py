"""The names a thing is called by, recorded rather than guessed.

The graph held one node named `Strahd von Zarovich`, and that exact string
occurs in exactly one of chapter 3's twenty-two sections. The other seven write
`Strahd`. Nothing connected the two strings, so the scan found one appearance of
the book's central antagonist in the chapter he haunts.

An `:Alias` is one node per distinct SURFACE FORM -- the literal spelling the
book uses -- hanging off the entity it names::

    (:Entity) <-[:ALIAS_OF]- (:Alias {name, normalized})
    (:Mention) -[:USES_ALIAS]-> (:Alias)

**The entity's own canonical name is itself an `:Alias`**, always, and
`writer._backfill_aliases` makes that true of every canon entity in the plane
rather than only of the ones a chapter happens to author. That is what lets a
lookup be ONE path -- resolve a name through `:Alias` -- instead of "check
`e.name`, then check the aliases", which is two paths free to disagree about
which names an entity answers to.

`normalized` IS THE WHOLE NORMALISATION: lowercase, trimmed, U+2019 folded to
`'`. There is no edit distance, no prefix rule, no token subset, and no
"first token of a multi-word name". Each of those would have turned `Strahd`
into `Strahd von Zarovich` here and been right, and each has already damaged
this project once -- most memorably a token-subset grader that let a candidate
`Ireena` credit the quest `Escort Ireena to Vallaki`, which is how a ten-line
regex came to outscore a real extractor. An alias node exists precisely so that
a variant is AUTHORED rather than inferred.

Authoring is therefore by hand, in `seeds/location-subtypes.yaml`, beside the
location rungs and the artifact list -- one file of hand-authored claims, read
one way. The extractor does emit `Ismark` and `Ismark Kolyanovich` as separate
candidates, and folding those together by string similarity is exactly the
inference this module refuses. Extractor-PROPOSED aliases are a later question
and deliberately not attempted here.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from backend.canon.assembler import slugify
from backend.canon.spine import fold_apostrophe, strip_soft_hyphens


def normalize(name: str) -> str:
    """Lowercase, trimmed, U+2019 folded to `'`, U+00AD dropped. Nothing else.

    Written out as three named steps rather than a chain, because the whole
    claim this module makes is that a reader can see the entire rule in one
    place and check that nothing fuzzy has crept into it.

    NOT slug equality, which `mint_id` and the location seed both use. A slug
    discards punctuation and case together, so `Blood on the Vine` and
    `blood-on-the-vine` collapse -- fine for minting an id, wrong for a name a
    caller typed, because it would also collapse names that differ by a colon
    or a comma. `normalized` keeps every character the book wrote except the
    ones that are genuinely typographic.

    The soft hyphen is one of those: U+00AD is a hint about where a line MAY
    break and renders as nothing, so `Ismark Kol<AD>yanovich` and
    `Ismark Kolyanovich` are the same name written twice. Dropping it changes
    length, which would be unsafe on section text -- offsets index that -- and
    is safe here, where a name is only ever compared.
    """
    folded = strip_soft_hyphens(fold_apostrophe(name))
    trimmed = folded.strip()
    return trimmed.lower()


@dataclass(frozen=True)
class WriteAlias:
    """One surface form, and the entity it names.

    `name` is the identity of the `:Alias` node and is GLOBAL: two entities that
    answer to one spelling share the node, which is how the graph says out loud
    that `Barovia` names both a region and a village. The `ALIAS_OF` edge is
    what is per-entity.

    Carries no `chapter_slug`. "This entity is called X" is not a claim any one
    chapter owns -- the same reason the entity node itself is global -- and
    stamping a chapter on it would make the first chapter to name a thing the
    owner of what it is called.
    """

    entity_id: str
    name: str

    @property
    def normalized(self) -> str:
        return normalize(self.name)

    @property
    def properties(self) -> dict:
        """What lands on the node. `name` is the MERGE key, so it is not here.

        `display_name` restates the merge key, which is the one place in the
        graph where that is redundant -- and it is written anyway, because the
        value of a single Browser caption rule is that it has no exceptions.
        """
        return {"normalized": self.normalized, "display_name": self.name}


def _forms(name: str, authored: Sequence[str]) -> list[str]:
    """The canonical name first, then the authored forms, deduplicated.

    Deduplicated on the EXACT string rather than on `normalized`, because two
    spellings that normalize alike are still two surface forms: the book sets
    `Bildrath’s Mercantile` with U+2019 and the extractor emits an ASCII quote,
    and which one a section actually used is the thing `USES_ALIAS` records.
    Collapsing them here would leave the graph unable to say.

    An empty or whitespace-only form is dropped. `mention_pattern` already
    refuses to compile one, so keeping it would create an `:Alias` node that
    nothing can ever match and that no lookup could resolve.
    """
    seen: dict[str, None] = {}
    for form in (name, *authored):
        if form and form.strip():
            seen.setdefault(form, None)
    return list(seen)


def plan_aliases(
    entities: Iterable[tuple[str, str]],
    authored: Mapping[str, Sequence[str]] | None = None,
) -> list[WriteAlias]:
    """Every `(entity, surface form)` this chapter's write is responsible for.

    `entities` is `(id, name)` for the nodes the write plan holds. `authored` is
    the seed, keyed on the SLUG of a name -- the same match the location rungs
    and the artifact list use, so one entry covers a straight and a curly
    apostrophe without listing both, and so the seed does not have to know which
    spelling `provenance_rank` happened to mint the node under.

    An entity with no seed entry still gets exactly one alias: its own name.
    That is the invariant lookup rests on, and it is not conditional on anyone
    having authored anything.

    Sorted by `(entity_id, name)`, so a diff of two runs is a diff of the
    authoring rather than of a dict's iteration order.
    """
    authored = authored or {}
    planned: list[WriteAlias] = []
    for entity_id, name in entities:
        forms = _forms(name, authored.get(slugify(name), ()))
        planned.extend(WriteAlias(entity_id=entity_id, name=form) for form in forms)
    return sorted(set(planned), key=lambda a: (a.entity_id, a.name))


#: Resolve a name to entities. THE read path, and the only one there should be.
#:
#: `e.name` is deliberately not in it. An entity's canonical name is itself an
#: `:Alias` -- `writer._BACKFILL_ALIASES` makes that true of every canon entity
#: in the plane -- so this one traversal answers under the canonical name, under
#: every authored spelling, and under either apostrophe. A caller that also
#: checked `e.name` would be maintaining a second answer to the same question,
#: free to disagree with this one the moment a node is renamed.
#:
#: Matched on `normalized`, which is lowercase, trimmed and U+2019-folded and
#: NOTHING else. No CONTAINS, no STARTS WITH, no fulltext index, no edit
#: distance. A caller who wants `Strahd` to reach `Strahd von Zarovich` records
#: `Strahd` as an alias; that is the whole mechanism, and it is the mechanism
#: precisely because the alternatives have twice put wrong answers in this
#: graph.
RESOLVE_BY_NAME = """
MATCH (a:Alias {normalized:$normalized})-[:ALIAS_OF]->(e:Entity {plane:$plane})
RETURN DISTINCT e.id AS id
ORDER BY id
"""


def resolve_name(session, name: str, plane: str = "canon") -> list[str]:
    """The ids of every entity that answers to `name`. Empty if none does.

    A LIST, not one id, and never a best guess. `Barovia` names a region and a
    village; `Tatyana` is an NPC and a piece of lore. Collapsing those to one
    would be the graph choosing on a reader's behalf between two things the book
    genuinely distinguishes, which is the same move as a fuzzy match wearing
    different clothes.
    """
    return [
        record["id"]
        for record in session.run(
            RESOLVE_BY_NAME, {"normalized": normalize(name), "plane": plane}
        )
    ]
