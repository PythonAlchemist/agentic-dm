"""The narrative spine, and the scan that finds where an entity actually appears.

Two things live here, and they are separated on purpose.

**The spine** is the document's own skeleton -- `(:Book)-[:HAS_CHAPTER]->(:Chapter)
-[:HAS_SECTION]->(:Section)` -- read straight off `split_sections`. Nothing in it
is a judgment: a chapter has the sections it has, in the order it has them, and
`(chapter.index, section.index)` is therefore the order the book reveals things.
A section carries its own text so that a mention can quote it.

**The scan** is why this module exists. Mentions used to record where an entity
was *extracted* -- wherever the model happened to emit a candidate -- rather than
where it *appears*, and the two are not close: Strahd is named across eight of
chapter 3's twenty-two sections and had one `MENTIONED_IN` edge to show for it.
So mentions are now found by reading every section and looking for every known
entity's name in it. Deterministic, free, and it cannot hallucinate.

**A markdown emphasis delimiter is a boundary, not a letter.** `_` is a word
character to Python's `\\w`, which made the book's own italics opaque to the
scan: `_Tome of Strahd_` is how this corpus sets an item name, and the artifact
the campaign turns on had zero mentions for exactly that reason. `WORD_CHAR`
below is `\\w` minus the underscore, so `_` and `*` delimit a name the way a
space or a comma already did. That is a change to WHICH CHARACTERS BOUND a name
and to nothing else -- `Ismar` still does not find `Ismark`.

**Matching is whole-word and exact, and there is no fourth rule.** Case-SENSITIVE
for a single-word name, so the LORE entity `Light` does not claim every lit
torch; case-INSENSITIVE for a multi-word one, where the run of words is itself
the evidence and the book's own capitalisation drifts (`Blood on the Vine
tavern`). No edit distance, no token subsets, no substring containment. This
project has twice been damaged by loose matching -- a token-subset grader let a
candidate `Ireena` credit the quest `Escort Ireena to Vallaki`, which is how a
regex shotgun came to outscore a real extractor.

The single liberty is `fold_apostrophe`, and it is a one-for-one character
substitution rather than a normalisation: the DDB corpus preserves the book's
U+2019 while the extractor emits an ASCII quote, so without it `Bildrath's
Mercantile` scores zero against its own shop. A silent zero is the exact failure
this module exists to remove, and because the substitution is single-character
the match offsets still index the original text -- so the passage derived from
an offset quotes the book's typography, not the folded copy.

**Junk is not filtered.** A `Trapdoor` entity matching forty sections makes the
junk MORE visible, not less, the same way merging duplicate nodes did. Report the
top entities by mention count and anything absurd surfaces immediately; suppress
them and the graph merely looks tidy.

**An entity is matched under every RECORDED name it has**, canonical or alias,
and `backend/canon/aliases.py` holds the rule for what counts as one. That is
what takes Strahd from one mention in chapter 3 to eight: the aliases are
authored by hand, and the matcher below is untouched by their arrival. Nothing
here infers that `Strahd` and `Strahd von Zarovich` are the same person -- a
human wrote it down.

Where two recorded names hit the SAME RUN OF TEXT, the longer one wins and the
occurrence is counted once. `Strahd` matches inside `Strahd von Zarovich`, and a
section that spells him out in full said his name once, not twice. Nothing about
that is a similarity judgment: both spans are exact whole-word matches, and the
only decision is which of two exact matches to attribute an overlap to.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Container, Iterable, Mapping, Sequence
from dataclasses import dataclass

from backend.canon.models import Section
from backend.canon.sections import KEYED_HEADING
from backend.canon.structure import place_of_section
from backend.canon.writer import BOOK, CANON_PLANE, mint_id

#: The right single quotation mark the book sets its possessives with, and the
#: ASCII apostrophe the extractor emits instead. The WHOLE of the folding, and a
#: substitution rather than a normalisation -- one character for one character,
#: so offsets into the folded text index the original exactly.
CURLY_APOSTROPHE = "’"
STRAIGHT_APOSTROPHE = "'"

#: What counts as MORE OF THE SAME WORD on either side of a name -- the whole
#: of the boundary rule, and the only thing the lookarounds in `mention_pattern`
#: refuse.
#:
#: `[^\W_]` is `\w` MINUS the underscore: every letter and digit Unicode knows,
#: and nothing else. `\w` itself cannot be used, because `_` is a word character
#: to Python and an EMPHASIS DELIMITER to the book -- `_Tome of Strahd_` is how
#: this corpus sets an item name, and under `\w` the artifact the campaign turns
#: on scanned to zero mentions. `*` needs no mention here: it was never a `\w`
#: character, so bold and star-italic always delimited correctly, and this class
#: keeps them delimiting.
#:
#: A BOUNDARY RULE, NOT A STRICTNESS ONE. Nothing here loosens what a whole word
#: is: `Ismar` still does not find `Ismark` and `Strah` still does not find
#: `Strahd`, emphasised or not, because `k` and `d` are still more word. The
#: single change is that a delimiter now delimits, exactly as a space or a comma
#: already did.
#:
#: The deliberate cost: an underscore is a boundary wherever it appears, so a
#: `snake_case` token would split into names. This corpus is the book's prose in
#: markdown, where an underscore is always emphasis and never an identifier.
WORD_CHAR = r"[^\W_]"

def fold_apostrophe(text: str) -> str:
    """U+2019 -> `'`. Nothing else, and never a distance."""
    return text.replace(CURLY_APOSTROPHE, STRAIGHT_APOSTROPHE)


def section_id(chapter_slug: str, index: int) -> str:
    """`cos:<chapter>#<index>`.

    Keyed on the INDEX rather than the heading, because `(chapter, heading)` is
    not unique -- chapter 4 has four sections headed "Treasure" and appendix D
    three headed "Actions" -- and a heading-keyed id would silently merge them.

    Prefixed from `BOOK` rather than from `plan_spine`'s `book_slug`, for the
    same reason `mint_id` is: it is the prefix every entity id in this graph
    already carries, and one id scheme with two sources of the book is how two
    halves of a graph end up disagreeing about which book they are.
    """
    return f"{BOOK}:{chapter_slug}#{index}"


def mention_id(entity_id: str, section_id_: str) -> str:
    """`<entity>@<section>`. The pair IS the identity.

    One node per (entity, section), never per occurrence: two sentences about
    Ireena in one section are one mention of her there. Composing the id out of
    both endpoints is what makes a re-scan MERGE onto the same node rather than
    doubling it.
    """
    return f"{entity_id}@{section_id_}"


@dataclass(frozen=True)
class WriteSection:
    """One section of the spine, carrying its own text."""

    id: str
    chapter_slug: str
    heading: str
    index: int
    depth: int
    parent_index: int
    text: str
    #: The place this section's heading keys, or `""`. Kept beside the heading
    #: rather than re-parsed downstream, so the one `KEYED_HEADING` match that
    #: produced it is the only one anything relies on.
    key: str = ""

    @property
    def properties(self) -> dict:
        """What lands on the node. `id` is the MERGE key, so it is not here.

        `text` travels, and it is the reason this node exists rather than a
        heading string on a mention: it is the ONLY copy of the prose in the
        graph, and every mention's passage is derived from it plus an offset.
        A quote that cannot be checked against the source is an assertion.

        No `chapter_title`: the `:Chapter` this hangs off carries it, and a
        second copy would be the same defect class as the `description` this
        change deletes -- one fact in two places, free to drift.
        """
        props = {
            "chapter_slug": self.chapter_slug,
            "plane": CANON_PLANE,
            "heading": self.heading,
            # The graph-wide caption property. See `WriteNode.properties` for
            # why every node kind carries one; here it is the heading, because
            # a section IS its heading to a reader.
            "display_name": self.heading,
            "index": self.index,
            "depth": self.depth,
            "parent_index": self.parent_index,
            "text": self.text,
        }
        # Absent rather than empty: a prose section genuinely keys nothing, and
        # `key: ""` would make it look like a keyed section whose key was lost.
        if self.key:
            props["key"] = self.key
        return props


@dataclass(frozen=True)
class EntityNames:
    """An entity and every surface form recorded for it.

    `name` is what the census prints and what `:Entity.name` holds; `aliases` is
    what `ALIAS_OF` records, which INCLUDES the canonical name in the graph.
    `forms` deduplicates the two, so a caller cannot construct an entity the
    scan will not look for under its own name -- the silent zero this module
    exists to remove.
    """

    id: str
    name: str
    aliases: tuple[str, ...] = ()

    @property
    def forms(self) -> tuple[str, ...]:
        """The canonical name first, then every alias, deduplicated exactly.

        Exactly, not by `normalize`: `Bildrath's Mercantile` and
        `Bildrath’s Mercantile` are two surface forms that normalize alike, and
        which one a section set is the thing `USES_ALIAS` is for.
        """
        seen: dict[str, None] = {}
        for form in (self.name, *self.aliases):
            seen.setdefault(form, None)
        return tuple(seen)


@dataclass(frozen=True)
class AliasUse:
    """One surface form the book used at one mention, and how often.

    An edge rather than a property, which is why `WriteMention` has never had a
    `surface` scalar: a section can name someone under two spellings at once --
    "the devil Strahd" and "Strahd von Zarovich" -- so which names were used is
    a SET, and a scalar would have to pick one of them and throw the rest away.
    """

    name: str
    occurrences: int


@dataclass(frozen=True)
class WriteMention:
    """One entity, named in one section, and where in it.

    NO `evidence`. The mention carries `offset` and its `:Section` carries
    `text`, so the passage is already in the graph -- storing it again put
    35,383 characters of prose onto 153 nodes, 9,894 of them literal
    duplicates, because a paragraph naming three entities stored itself once
    per entity. `backend/canon/passage.py` derives it on read from exactly the
    pair this node and its section already hold.

    What remains are FACTS rather than copies. `occurrences` is what the scan
    counted; `offset` is where the section first says the name, and it is the
    anchor the derivation expands from.
    """

    id: str
    entity_id: str
    section_id: str
    chapter_slug: str
    #: How many times the entity is named in this section, counting a run of
    #: text once however many recorded forms match it. The mention is still one
    #: node; this says how loudly the section says it.
    occurrences: int
    #: Character offset of the FIRST occurrence, into the section's own text.
    offset: int
    #: The name of the entity this mention refers to, carried for one purpose:
    #: `display_name`. REQUIRED rather than defaulted to `""`, because a
    #: defaulted caption is the silent-zero shape this module exists to remove
    #: -- it would render as a blank circle and look like a styling problem
    #: rather than a missing plumb.
    entity_name: str
    #: Which surface forms did the naming, most-used first. Empty is impossible
    #: for a scanned mention -- something matched, or there would be no mention.
    uses: tuple[AliasUse, ...] = ()

    @property
    def properties(self) -> dict:
        """What lands on the node. `id` is the MERGE key, so it is not here.

        `chapter_slug` and `plane` travel for the same reason an edge's do: the
        replace path scopes deletes on exactly that pair, and a mention that did
        not declare its chapter could not be replaced with the chapter that made
        it.

        `display_name` is the ENTITY's name, not the section's. A mention hangs
        off a section that is captioned already, so the question its own circle
        has to answer is *who appears here* -- and `occurrences` rides along so
        a glance distinguishes a passing reference from the section that is
        really about someone.
        """
        loud = f" x{self.occurrences}" if self.occurrences > 1 else ""
        return {
            "plane": CANON_PLANE,
            "chapter_slug": self.chapter_slug,
            "occurrences": self.occurrences,
            "offset": self.offset,
            "display_name": f"{self.entity_name}{loud}",
        }


@dataclass(frozen=True)
class ChapterSpine:
    """One chapter's skeleton: its place in the book, its sections, its places."""

    book_slug: str
    book_title: str
    chapter_slug: str
    chapter_title: str
    chapter_index: int
    sections: tuple[WriteSection, ...]
    #: `(section_id, location_id)` for every keyed section that IS the place it
    #: names. A list of pairs rather than a field on the section, because a
    #: section describing nothing is the common case and an empty scalar there
    #: would be indistinguishable from a resolution that failed.
    describes: tuple[tuple[str, str], ...]


def _key_of(heading: str) -> str:
    """`e5g` for `E5g. Undercroft`, `""` for a prose heading.

    The same `KEYED_HEADING` the splitter and `structure.py` share, and the same
    lowercase-and-join `writer.keyed_index` performs -- so the key here and the
    key that minted the place's id are one computation, not two that must agree.
    """
    match = KEYED_HEADING.match(heading.strip())
    if not match:
        return ""
    return f"{match.group('stem')}{match.group('suffix') or ''}".strip().lower()


def plan_spine(
    *,
    book_slug: str,
    book_title: str,
    chapter_slug: str,
    chapter_title: str,
    chapter_index: int,
    sections: Sequence[Section],
    location_ids: Container[str],
) -> ChapterSpine:
    """The spine for one chapter, and the places its sections describe.

    `location_ids` is the ids of the entities that actually carry `:LOCATION` --
    the writer's own plan, handed in rather than looked up, so this stays pure
    and so a section can only describe a place that exists. `E5d. Trapdoor` is a
    keyed heading the extractor typed an ITEM; the `DESCRIBES` range is
    `:LOCATION`, so it correctly describes nothing rather than being promoted
    into a room by the shape of its heading.

    `place_of_section` decides whether a heading names a place at all, reused
    from `structure.py` rather than re-derived: it is the same question the
    containment deriver asks, and two implementations of "is this a room" would
    eventually disagree about one.
    """
    written = tuple(
        WriteSection(
            id=section_id(chapter_slug, section.index),
            chapter_slug=chapter_slug,
            heading=section.heading,
            index=section.index,
            depth=section.depth,
            parent_index=section.parent_index,
            text=section.markdown,
            key=_key_of(section.heading),
        )
        for section in sections
    )

    describes: list[tuple[str, str]] = []
    for section, plain in zip(written, sections, strict=True):
        place = place_of_section(plain)
        if not place:
            continue
        place_id = mint_id(chapter_slug, place, section.key)
        if place_id in location_ids:
            describes.append((section.id, place_id))

    return ChapterSpine(
        book_slug=book_slug,
        book_title=book_title,
        chapter_slug=chapter_slug,
        chapter_title=chapter_title,
        chapter_index=chapter_index,
        sections=written,
        describes=tuple(describes),
    )


def mention_pattern(name: str, *, fold_case: bool = False) -> re.Pattern[str] | None:
    """The one matcher. Whole-word, exact, and case-folded only when multi-word.

    Lookarounds rather than `\\b`, because a name can end in a character `\\b`
    treats as a boundary in its own right -- `Bildrath's Mercantile` and `Doru's
    Bedroom` are ordinary names in this book -- and they say exactly what is
    meant: not preceded or followed by more word.

    What "more word" means is `WORD_CHAR`, which is `\\w` without the
    underscore. See it for why: markdown emphasis has to delimit a name rather
    than glue itself onto one.

    CASE-SENSITIVE FOR ONE WORD. `Light` is a real LORE entity in this book, and
    a case-insensitive match would give it a mention in every section containing
    a lit torch or a shaft of light. A capitalised single word in running prose
    is a proper noun; a lowercase one is not, and that is the whole signal.

    CASE-INSENSITIVE FOR TWO OR MORE. The run of words is itself the evidence --
    nothing accidentally says "blood of the vine tavern" -- and the book's own
    capitalisation of a multi-word name is not stable, so requiring the
    extractor's casing would drop real appearances.

    `fold_case` DROPS the single-word case rule, and NOTHING IN THE SCAN MAY
    PASS IT. It exists for one caller: matching names inside a QUESTION someone
    typed. The case rule above is an inference about PROSE -- a capitalised word
    in running text is a proper noun -- and that inference is simply false about
    a question, where nobody types "who is Strahd" with the capitals in the
    right places. Measured on the evaluation set: three questions naming
    `Trapdoor`, `Office` and `Cemetery` in lowercase resolved to nothing at all.

    It is a parameter here rather than a second regex in the calling module
    because there must stay exactly ONE definition of "this name appears in this
    text". The rule that varies is which signal the caller's text carries, not
    what a match is.

    Returns None for a name with nothing in it. A name that folds to the empty
    string would compile to a pattern matching at every position in every
    section, which is the one way this scan could produce a mention per
    character rather than per entity.
    """
    folded = fold_apostrophe(name).strip()
    if not folded:
        return None
    flags = re.IGNORECASE if fold_case or len(folded.split()) > 1 else 0
    return re.compile(rf"(?<!{WORD_CHAR}){re.escape(folded)}(?!{WORD_CHAR})", flags)


def _spell_rank(form: str, raw: str) -> int:
    """How closely a recorded form spells the text it matched. Lower is closer.

    Three tiers, and every one of them is an EXACT string equality under a
    transformation named in full above -- there is no distance here and there
    must never be one:

    0. identical, character for character, typography and case included;
    1. identical once U+2019 is folded -- the ASCII form of a curly possessive;
    2. identical once case is also dropped, which is the only way a multi-word
       form can match text it does not equal.

    Every form that matched a span reaches tier 2 by construction, so this
    refines an attribution rather than deciding one.
    """
    if form == raw:
        return 0
    if fold_apostrophe(form) == fold_apostrophe(raw):
        return 1
    return 2


def attribute_spans(
    text: str, folded: str, forms: Sequence[str]
) -> list[tuple[int, int, str]]:
    """The occurrences of an entity in one section, one form per run of text.

    Returns `(start, end, form)` in reading order, over `text`'s own offsets.

    TWO RULES, AND NEITHER IS A SIMILARITY JUDGMENT.

    **The longest match wins an overlap.** `Strahd` matches inside `Strahd von
    Zarovich`, so a section that spells him out in full produces two exact
    whole-word matches over one run of text -- and the section named him once.
    Counting both would make `occurrences` a count of recorded aliases rather
    than of appearances, and would put a `USES_ALIAS` edge on a spelling the
    book did not use. Ties in length go to the earlier span, then to the
    alphabetically first form, so the output is fully determined.

    **A span attributes to the form that spells it best**, by `_spell_rank`.
    Both `Bildrath's Mercantile` and `Bildrath’s Mercantile` match the book's
    curly setting -- the scan folds -- and only one of them is what the section
    actually says.
    """
    by_span: dict[tuple[int, int], list[str]] = {}
    for form in forms:
        pattern = mention_pattern(form)
        if pattern is None:
            continue
        for match in pattern.finditer(folded):
            by_span.setdefault((match.start(), match.end()), []).append(form)

    chosen = {
        span: min(candidates, key=lambda f: (_spell_rank(f, text[span[0]:span[1]]), f))
        for span, candidates in by_span.items()
    }

    kept: list[tuple[int, int, str]] = []
    taken: list[tuple[int, int]] = []
    for start, end in sorted(chosen, key=lambda s: (s[0] - s[1], s[0], chosen[s])):
        if any(start < high and low < end for low, high in taken):
            continue
        taken.append((start, end))
        kept.append((start, end, chosen[(start, end)]))
    return sorted(kept)


def scan_mentions(
    sections: Iterable[WriteSection],
    entities: Iterable[EntityNames],
    chapter_slug: str,
) -> list[WriteMention]:
    """Every (entity, section) pair the text supports, with where it says so.

    `entities` is every canon entity the graph knows -- not only this chapter's.
    An entity is global to the book, so chapter 3 naming Castle Ravenloft is a
    fact about chapter 3 whatever chapter minted the castle, and scanning only
    the chapter's own nodes would rebuild the defect this replaces one level up.

    Each entity is looked for under EVERY form recorded for it, which is where
    the eight comes from and the only reason the number moves. The matcher is
    the same one, applied once per form.

    ORDERED BY (section, entity id), not by whatever order the caller or a Cypher
    result happened to arrive in. A diff between two runs then reads as a diff of
    the book rather than of a dict's iteration.

    Nothing is filtered. See the module docstring: junk mentions make junk
    entities visible, and that is the point of not having a filter here.
    """
    ordered_entities = sorted(set(entities), key=lambda e: e.id)

    mentions: list[WriteMention] = []
    for section in sections:
        # Folded once per section rather than once per form: a single-character
        # substitution, so every offset below indexes `section.text` unchanged.
        folded = fold_apostrophe(section.text)
        for entity in ordered_entities:
            spans = attribute_spans(section.text, folded, entity.forms)
            if not spans:
                continue
            start, _, _ = spans[0]
            used = Counter(form for _, _, form in spans)
            mentions.append(
                WriteMention(
                    id=mention_id(entity.id, section.id),
                    entity_id=entity.id,
                    section_id=section.id,
                    chapter_slug=chapter_slug,
                    occurrences=len(spans),
                    offset=start,
                    entity_name=entity.name,
                    # Most-used first, ties by name: a stable order, and the
                    # form the section leans on reads first.
                    uses=tuple(
                        AliasUse(name=form, occurrences=count)
                        for form, count in sorted(used.items(), key=lambda p: (-p[1], p[0]))
                    ),
                )
            )
    return mentions


def mention_counts(
    mentions: Iterable[WriteMention], names_by_id: Mapping[str, str]
) -> list[tuple[str, int]]:
    """`(name, mentions)`, most-mentioned first, ties broken by name.

    Exists so the top of the list is printed on every write. An entity with an
    absurd count -- a bare noun the gazetteer let through -- is invisible in a
    node census and obvious here, which is the whole argument for not filtering
    junk out of the scan.
    """
    counts = Counter(m.entity_id for m in mentions)
    return sorted(
        ((names_by_id.get(entity_id, entity_id), count) for entity_id, count in counts.items()),
        key=lambda pair: (-pair[1], pair[0]),
    )
