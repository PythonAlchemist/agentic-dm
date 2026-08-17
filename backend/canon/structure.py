"""Derive spatial containment from the document hierarchy.

Sourcebooks encode location structure typographically: a keyed area is a section,
and everything described inside it is there. That relationship is never written as
a sentence, so an LLM reading one section in isolation cannot state it -- it is in
the shape of the document, not its prose.

Deriving it is deterministic and free, and unlike extraction it cannot hallucinate:
every edge here is a restatement of where the text physically sits.

**Depth first, key second.** Containment comes from nesting -- a section is
contained by the nearest section it is nested inside that names a place. The key
stem (`E5g` inside `E5`) is kept only as a correction, for the 16 sub-area pairs
the book renders at the *same* depth as their parent, where nesting has nothing
to say. Reading the key first would put the pipeline back where it started: a
book with no keyed rooms would derive nothing.
"""

import re
from dataclasses import dataclass

from backend.canon.models import CandidateEdge, CandidateNode, Section

# One definition, shared with the splitter -- see the comment on KEYED_HEADING
# in sections.py. Two copies of this pattern that must agree is a defect waiting
# to happen. Note what it is NOT used for any more: finding sections.
from backend.canon.sections import KEYED_HEADING

STRUCTURAL_EVIDENCE = "derived from document structure"

# "Chapter 3: The Village of Barovia" -> "The Village of Barovia". The numbering
# is the book's table of contents talking, not a place.
_CHAPTER_PREFIX = re.compile(r"^(chapter\s+\d+|appendix\s+[a-z])\s*[:.]\s*", re.IGNORECASE)


def place_from_chapter_title(title: str) -> str | None:
    """The place a chapter's title names, or None if it names nothing.

    Lives here, beside the deriver that USES the result as an edge's source
    name, rather than in either caller. The extractor derives the chapter place
    to build the CONTAINS edges; the writer derives it again to mint the node
    those edges point out of. Two copies of this rule would put the writer's
    node name out of step with the deriver's edge, and every chapter-level
    CONTAINS would dangle -- which is exactly the defect this repairs.

    The article is kept: "The Village of Barovia" is how the book writes it.
    """
    stripped = _CHAPTER_PREFIX.sub("", title).strip()
    return stripped or None


@dataclass
class StructureResult:
    """Derived edges, and which mechanism produced each CONTAINS.

    The split is the evidence for whether removing the key coupling actually
    worked. If `key_derived` were carrying most of the containment, the
    document's nesting would not in fact be doing the job and the generalisation
    to books with no keyed rooms would be a claim rather than a result.
    """

    edges: list[CandidateEdge]
    depth_derived: int
    key_derived: int
    chapter_derived: int
    #: Kept at 0 and no longer counted from anything. The derivation it
    #: described -- an entity named in a section is LOCATED_IN that place --
    #: was removed 2026-08-17 as unsound. The field stays so an older run
    #: artifact still parses, and stays ZERO so a new one cannot claim
    #: placements nobody derived.
    located_in: int = 0


def _same_place(a: str, b: str) -> bool:
    """Whether two names denote the same place, ignoring case and edge spacing.

    Casing is not stable in this corpus -- `undercroft` appears beside
    `Undercroft` in one chapter's candidates -- so an exact comparison would let
    a self-loop through on a capital letter.
    """
    return a.strip().lower() == b.strip().lower()


def place_of_section(section: Section) -> str | None:
    """The place a keyed section names, or None if it names no place.

    Keyed areas carry an identifier prefix; prose sections like "Approaching the
    Village" do not, and treating those as locations would invent places the book
    never keys. This is the one thing the key is still the primary evidence for:
    nesting can say what is inside what, but only the key says that a heading
    denotes a room at all. "Creatures (A-H)" nests three levels of Appendix D
    under it and is not a place.
    """
    match = KEYED_HEADING.match(section.heading.strip())
    return match.group("name").strip() if match else None


def _ancestor_place(
    index: int, by_index: dict[int, str | None], parents: dict[int, int]
) -> str | None:
    """The nearest enclosing section that names a place, walking outwards.

    Skipping past placeless ancestors is what lets `E1` inside the unkeyed
    divider "Areas of the Village" reach the chapter, and what lets a node in
    `#### Roleplaying Ismark` reach `E2. Blood of the Vine Tavern` above it.
    Stopping at the first ancestor instead would answer "nowhere" in both cases.

    Depth 0 sections have `parent_index == -1`, so for the `key` splitter -- whose
    heading levels are noise and which therefore reports no depths at all -- this
    walk terminates immediately and contributes nothing.
    """
    seen: set[int] = set()
    current = parents.get(index, -1)
    while current >= 0 and current not in seen:
        seen.add(current)
        place = by_index.get(current)
        if place:
            return place
        current = parents.get(current, -1)
    return None


def derive_structure(
    sections: list[Section],
    nodes: list[CandidateNode],
    chapter_place: str | None,
) -> StructureResult:
    """Containment implied by the chapter/section hierarchy, with its provenance.

    Three derivations, in priority order:

    - a keyed section is CONTAINS-ed by the nearest section it nests inside that
      names a place (**depth**)
    - failing that, by the section its key stem names, if one exists (**key**) --
      the correction for `K20a` rendered as a sibling of `K20`
    - failing both, by the chapter's own place (**chapter**)

    and NOTHING ELSE. In particular no `LOCATED_IN` is derived from an entity
    being named in a section -- see the note where that derivation used to be.

    Exactly one parent per place: a room with two parents is a fabrication
    dressed as thoroughness. The one exception is a stem parent that disagrees
    with a nesting parent, which is containment the depth genuinely missed rather
    than a duplicate of it -- it does not occur in this corpus, and if a book
    ever does render a sub-area inside some area other than its stem's, both
    facts are worth keeping.

    A chapter with no containing place (an appendix, say) yields no chapter-level
    CONTAINS edges: inventing a parent would be a fabrication, which is exactly
    what this module exists to avoid.
    """
    # Keyed on section_index, not heading text: `(chapter_slug, heading)` is
    # not a unique key -- duplicate headings occur within a chapter (four
    # sections named "Treasure" in Chapter 4, three named "Actions" in
    # Appendix D), and a heading-keyed dict silently keeps only the last.
    by_index = {s.index: place_of_section(s) for s in sections}
    parents = {s.index: s.parent_index for s in sections}
    tagged: list[tuple[str, CandidateEdge]] = []

    def add(
        source: str,
        target: str,
        rel_type: str,
        origin: str,
        *,
        section_index: int = -1,
        section_heading: str = "",
    ) -> None:
        tagged.append((
            origin,
            CandidateEdge(
                source_name=source,
                target_name=target,
                rel_type=rel_type,
                evidence=STRUCTURAL_EVIDENCE,
                layer="spatial",
                chapter_slug=sections[0].chapter_slug if sections else "",
                section_index=section_index,
                section_heading=section_heading,
            ),
        ))

    # Only a suffix-LESS section can be a stem: `E5a` is not the parent of
    # `E5b`, they are siblings under `E5`. First occurrence wins, since a
    # duplicated key is a transcription artifact rather than two parents.
    stems: dict[str, str] = {}
    for s in sections:
        match = KEYED_HEADING.match(s.heading.strip())
        if match and not match.group("suffix"):
            stems.setdefault(match.group("stem"), match.group("name").strip())

    for s in sections:
        place = by_index[s.index]
        if not place:
            continue
        nested = _ancestor_place(s.index, by_index, parents)
        match = KEYED_HEADING.match(s.heading.strip())
        keyed = stems.get(match.group("stem")) if match and match.group("suffix") else None

        # The parent is chosen first and self-containment checked second, in
        # that order. A cascade that fell through on the self-check would reach
        # PAST the real parent to the chapter: `E5a. church` inside `E5. Church`
        # would be dropped by the church and then claimed by the village, which
        # is a fabricated containment produced by a guard against fabrication.
        if nested:
            origin, parent = "depth", nested
        elif keyed:
            origin, parent = "key", keyed
        elif chapter_place:
            origin, parent = "chapter", chapter_place
        else:
            continue

        # A place does not contain itself. The corpus repeats a parent's name
        # onto its sub-area often enough for this to be real.
        candidates: list[tuple[str, str]] = []
        if not _same_place(parent, place):
            candidates.append((origin, parent))
        if (
            origin == "depth"
            and keyed
            and not _same_place(keyed, parent)
            and not _same_place(keyed, place)
        ):
            candidates.append(("key", keyed))

        for origin, parent in candidates:
            add(
                parent, place, "CONTAINS", origin,
                section_index=s.index, section_heading=s.heading,
            )

    # NO `LOCATED_IN` IS DERIVED HERE, AND THE ABSENCE IS THE POINT.
    #
    # This module used to place every non-LOCATION entity extracted from a
    # section into that section's place. It reads like structure and it is not:
    # it says BEING NAMED IN A SECTION IS BEING THERE, which is the same
    # conflation `MENTIONED_IN` made when it recorded where an entity was
    # extracted rather than where it appears -- and it was worse here, because
    # the anchor was `node.section_index`, the section the EXTRACTOR emitted the
    # candidate from.
    #
    # Hand-checked against the book, roughly half of the 26 NPC placements it
    # produced for chapter 3 were false, and they were false in the way that
    # matters most:
    #
    #   Madam Eva  -> Blood of the Vine Tavern   she is at Tser Pool, two
    #                                            chapters away, and is merely
    #                                            suggested as someone to visit
    #   Gertruda   -> Mad Mary's Townhouse       she is MISSING; her absence is
    #                                            the entire hook of that scene
    #   Donavich   -> Burgomaster's Mansion      he is at the church, and is
    #                                            named only as who receives the
    #                                            burgomaster's body
    #
    # All of them shipped as `accepted`, carrying `derived from document
    # structure` -- the provenance this project treats as trustworthy, tells the
    # DM agent to rely on, and describes as the only layer a fabrication check
    # found clean. A false edge in the distrusted bucket costs a reviewer a
    # minute; a false edge here is stated to a DM as fact.
    #
    # What remains derived is the book's KEY NESTING -- `E5` contains `E5a`
    # through `E5g` -- which is a real property of the document rather than an
    # inference from one. Where an entity is NAMED is not lost: `:Mention`
    # records exactly that, with an offset and a section, and never claims it
    # means presence. Where an entity IS may be proposed by an extractor and
    # accepted by a human, which is what the review queue is for.
    #
    # *Removed 2026-08-17*, after the DM agent hedged on "who owns the Blood of
    # the Vine Tavern" -- a true `OWNS` edge with 5 of 5 votes sat in `proposed`
    # while `Madam Eva LOCATED_IN` the same tavern sat in `accepted`.

    # `section_index` is part of the key for the same reason `by_index` is keyed
    # on it: name text does not identify a section, and same-named rooms are
    # common -- one chapter has two `Closet`s (K44, K51), two `Forgotten
    # Treasure`s and three `Empty Cell`s. On name alone, 103 keyed places yielded
    # 100 CONTAINS edges, and the drop was undetectable downstream because the
    # survivor's provenance named the other room. Duplicates worth collapsing --
    # the three layer passes naming one node repeatedly in one section -- share a
    # section_index, so they still collapse. Counted after dedup, so the reported
    # split describes the edges that actually ship.
    seen: set[tuple[str, str, str, int]] = set()
    unique: list[CandidateEdge] = []
    counts = {"depth": 0, "key": 0, "chapter": 0}
    for origin, edge in tagged:
        key = (edge.source_name, edge.target_name, edge.rel_type, edge.section_index)
        if key not in seen:
            seen.add(key)
            unique.append(edge)
            counts[origin] += 1

    return StructureResult(
        edges=unique,
        depth_derived=counts["depth"],
        key_derived=counts["key"],
        chapter_derived=counts["chapter"],
    )


def structural_edges(
    sections: list[Section],
    nodes: list[CandidateNode],
    chapter_place: str | None,
) -> list[CandidateEdge]:
    """Containment implied by the chapter/section hierarchy."""
    return derive_structure(sections, nodes, chapter_place).edges
