"""Derive spatial containment from the document hierarchy.

Sourcebooks encode location structure typographically: a keyed area is a section,
and everything described inside it is there. That relationship is never written as
a sentence, so an LLM reading one section in isolation cannot state it -- it is in
the shape of the document, not its prose.

Deriving it is deterministic and free, and unlike extraction it cannot hallucinate:
every edge here is a restatement of where the text physically sits.
"""

from backend.canon.models import CandidateEdge, CandidateNode, Section

# One definition, shared with the splitter that decides what a section IS --
# see the comment on KEYED_HEADING in sections.py. Two copies of this pattern
# that must agree is a defect waiting to happen.
from backend.canon.sections import KEYED_HEADING

STRUCTURAL_EVIDENCE = "derived from document structure"


def place_of_section(section: Section) -> str | None:
    """The place a keyed section names, or None if it names no place.

    Keyed areas carry an identifier prefix; prose sections like "Approaching the
    Village" do not, and treating those as locations would invent places the book
    never keys.
    """
    match = KEYED_HEADING.match(section.heading.strip())
    return match.group("name").strip() if match else None


def structural_edges(
    sections: list[Section],
    nodes: list[CandidateNode],
    chapter_place: str | None,
) -> list[CandidateEdge]:
    """Containment implied by the chapter/section hierarchy.

    Two derivations:
    - each keyed section's place is CONTAINS-ed by its parent -- the section
      named by its key's stem (`E5g. Undercroft` is inside `E5. Church`) when
      one exists, otherwise the chapter's place
    - a non-location entity extracted from a keyed section is LOCATED_IN it

    The stem rule reads the hierarchy off the key because the key is the only
    place it survives: heading depth was assigned by a vision transcription that
    put `E5. Church` at H2 and `E6. Cemetery` at H1 in the same chapter, so
    depth encodes nothing. Letter suffixes are authored and reliable.

    A chapter with no containing place (an appendix, say) yields no
    chapter-level CONTAINS edges: inventing a parent would be a fabrication,
    which is exactly what this module exists to avoid. A stem parent is not an
    invention -- it is another section of the same document -- so it stands
    even there.
    """
    # Keyed on section_index, not heading text: `(chapter_slug, heading)` is
    # not a unique key -- duplicate H2 headings occur within a chapter (four
    # sections named "Treasure" in Chapter 4, three named "Actions" in
    # Appendix D), and a heading-keyed dict silently keeps only the last.
    by_index = {s.index: place_of_section(s) for s in sections}
    edges: list[CandidateEdge] = []

    def add(
        source: str,
        target: str,
        rel_type: str,
        *,
        section_index: int = -1,
        section_heading: str = "",
    ) -> None:
        edges.append(
            CandidateEdge(
                source_name=source,
                target_name=target,
                rel_type=rel_type,
                evidence=STRUCTURAL_EVIDENCE,
                layer="spatial",
                chapter_slug=sections[0].chapter_slug if sections else "",
                section_index=section_index,
                section_heading=section_heading,
            )
        )

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
        match = KEYED_HEADING.match(s.heading.strip())
        # Fall back to the chapter place when the stem section is absent
        # (`K20a` with no `K20`): dropping the edge would lose a containment
        # the chapter place can still state correctly.
        parent = chapter_place
        if match and match.group("suffix"):
            parent = stems.get(match.group("stem"), chapter_place)
        # A place does not contain itself. The transcription repeats a parent's
        # name onto its sub-area often enough for this to be real.
        if parent and parent != place:
            add(
                parent, place, "CONTAINS",
                section_index=s.index, section_heading=s.heading,
            )

    for node in nodes:
        place = by_index.get(node.section_index)
        if not place:
            continue
        # A place is not located in itself, and a section's own location node
        # names the same place the heading does.
        if node.entity_type == "LOCATION":
            continue
        add(
            node.name, place, "LOCATED_IN",
            section_index=node.section_index, section_heading=node.section_heading,
        )

    # `section_index` is part of the key for the same reason `by_index` is keyed
    # on it: name text does not identify a section, and since sections split on
    # the key rather than on heading level, same-named rooms are common -- one
    # chapter has two `Closet`s (K44, K51), two `Forgotten Treasure`s and three
    # `Empty Cell`s. On name alone, 103 keyed places yielded 100 CONTAINS edges,
    # and the drop was undetectable downstream because the survivor's provenance
    # named the other room. Duplicates worth collapsing -- the three layer passes
    # naming one node repeatedly in one section -- share a section_index, so they
    # still collapse.
    seen: set[tuple[str, str, str, int]] = set()
    unique: list[CandidateEdge] = []
    for edge in edges:
        key = (edge.source_name, edge.target_name, edge.rel_type, edge.section_index)
        if key not in seen:
            seen.add(key)
            unique.append(edge)
    return unique
