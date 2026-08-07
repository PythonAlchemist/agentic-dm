"""Derive spatial containment from the document hierarchy.

Sourcebooks encode location structure typographically: a keyed area is a section,
and everything described inside it is there. That relationship is never written as
a sentence, so an LLM reading one section in isolation cannot state it -- it is in
the shape of the document, not its prose.

Deriving it is deterministic and free, and unlike extraction it cannot hallucinate:
every edge here is a restatement of where the text physically sits.
"""

import re

from backend.canon.models import CandidateEdge, CandidateNode, Section

# "E1. Bildrath's Mercantile", "E5g. Undercroft". A letter prefix is required:
# the book's only bare-number keys are chapter 1's Tarokka card list and
# Appendix B's Death House rooms, neither of which name a physical room.
_KEYED = re.compile(r"^[A-Z]\d+[a-z]?\.\s*(.+)$")

STRUCTURAL_EVIDENCE = "derived from document structure"


def place_of_section(section: Section) -> str | None:
    """The place a keyed section names, or None if it names no place.

    Keyed areas carry an identifier prefix; prose sections like "Approaching the
    Village" do not, and treating those as locations would invent places the book
    never keys.
    """
    match = _KEYED.match(section.heading.strip())
    return match.group(1).strip() if match else None


def structural_edges(
    sections: list[Section],
    nodes: list[CandidateNode],
    chapter_place: str | None,
) -> list[CandidateEdge]:
    """Containment implied by the chapter/section hierarchy.

    Two derivations:
    - the chapter's place CONTAINS each keyed section's place
    - a non-location entity extracted from a keyed section is LOCATED_IN it

    A chapter with no containing place (an appendix, say) yields no CONTAINS
    edges: inventing a parent would be a fabrication, which is exactly what this
    module exists to avoid.
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

    if chapter_place:
        for s in sections:
            place = by_index[s.index]
            if place:
                add(
                    chapter_place, place, "CONTAINS",
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

    seen: set[tuple[str, str, str]] = set()
    unique: list[CandidateEdge] = []
    for edge in edges:
        key = (edge.source_name, edge.target_name, edge.rel_type)
        if key not in seen:
            seen.add(key)
            unique.append(edge)
    return unique
