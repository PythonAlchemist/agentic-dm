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
the match offsets still index the original text -- so the evidence span quotes
the book's typography, not the folded copy.

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

#: How much of its section a mention may quote. Long enough to hold the sentence
#: the name is in with its neighbours, short enough that several hundred mentions
#: per chapter do not turn the graph into a second copy of the book.
EVIDENCE_MAX = 320


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
        heading string on a mention: evidence has to be quotable, and a quote
        that cannot be checked against the source is an assertion.

        No `chapter_title`: the `:Chapter` this hangs off carries it, and a
        second copy would be the same defect class as the `description` this
        change deletes -- one fact in two places, free to drift.
        """
        props = {
            "chapter_slug": self.chapter_slug,
            "plane": CANON_PLANE,
            "heading": self.heading,
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
    """One entity, named in one section, with the words that say so."""

    id: str
    entity_id: str
    section_id: str
    chapter_slug: str
    #: A literal substring of the section, never assembled or elided -- see
    #: `evidence_span`.
    evidence: str
    #: How many times the entity is named in this section, counting a run of
    #: text once however many recorded forms match it. The mention is still one
    #: node; this says how loudly the section says it.
    occurrences: int
    #: Character offset of the FIRST occurrence, into the section's own text.
    offset: int
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
        """
        return {
            "plane": CANON_PLANE,
            "chapter_slug": self.chapter_slug,
            "evidence": self.evidence,
            "occurrences": self.occurrences,
            "offset": self.offset,
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


def mention_pattern(name: str) -> re.Pattern[str] | None:
    """The one matcher. Whole-word, exact, and case-folded only when multi-word.

    `(?<!\\w)` / `(?!\\w)` rather than `\\b`, because a name can end in a
    character `\\b` treats as a boundary in its own right -- `Bildrath's
    Mercantile` and `Doru's Bedroom` are ordinary names in this book -- and the
    lookarounds say exactly what is meant: not preceded or followed by more word.

    CASE-SENSITIVE FOR ONE WORD. `Light` is a real LORE entity in this book, and
    a case-insensitive match would give it a mention in every section containing
    a lit torch or a shaft of light. A capitalised single word in running prose
    is a proper noun; a lowercase one is not, and that is the whole signal.

    CASE-INSENSITIVE FOR TWO OR MORE. The run of words is itself the evidence --
    nothing accidentally says "blood of the vine tavern" -- and the book's own
    capitalisation of a multi-word name is not stable, so requiring the
    extractor's casing would drop real appearances.

    Returns None for a name with nothing in it. A name that folds to the empty
    string would compile to a pattern matching at every position in every
    section, which is the one way this scan could produce a mention per
    character rather than per entity.
    """
    folded = fold_apostrophe(name).strip()
    if not folded:
        return None
    flags = 0 if len(folded.split()) == 1 else re.IGNORECASE
    return re.compile(rf"(?<!\w){re.escape(folded)}(?!\w)", flags)


def evidence_span(text: str, start: int, end: int) -> str:
    """The words around a match, as a LITERAL substring of `text`.

    Never assembled, never elided, and deliberately carrying no ellipsis: "the
    evidence quotes its section" is then checkable by `evidence in section.text`
    rather than merely intended. A quote that has been edited is an assertion
    about the book, and this module's entire claim is that it makes none.

    The enclosing paragraph when that fits, because a paragraph is the unit the
    book actually wrote. When it does not fit, a window CENTRED on the match --
    truncating from the left would produce an evidence span that cut off the very
    name it is evidence for, which is worse than no span at all -- snapped
    outward-in to whitespace so the quote does not begin mid-word.
    """
    para_start = text.rfind("\n\n", 0, start)
    para_start = 0 if para_start < 0 else para_start + 2
    para_end = text.find("\n\n", end)
    para_end = len(text) if para_end < 0 else para_end

    if para_end - para_start <= EVIDENCE_MAX:
        return text[para_start:para_end].strip()

    slack = max(EVIDENCE_MAX - (end - start), 0)
    low = max(para_start, start - slack // 2)
    high = min(para_end, low + EVIDENCE_MAX)
    low = max(para_start, min(low, high - EVIDENCE_MAX))

    # Snap inwards to a whitespace boundary, but never past the match itself:
    # the name is the reason this span exists.
    if low > para_start:
        space = text.find(" ", low, start)
        low = space + 1 if space >= 0 else low
    if high < para_end:
        space = text.rfind(" ", end, high)
        high = space if space >= 0 else high

    return text[low:high].strip()


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
    """Every (entity, section) pair the text supports, with its evidence.

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
            start, end, _ = spans[0]
            used = Counter(form for _, _, form in spans)
            mentions.append(
                WriteMention(
                    id=mention_id(entity.id, section.id),
                    entity_id=entity.id,
                    section_id=section.id,
                    chapter_slug=chapter_slug,
                    evidence=evidence_span(section.text, start, end),
                    occurrences=len(spans),
                    offset=start,
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
