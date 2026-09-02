"""Asking for a picture, in the book's own words.

THE PROMPT IS BUILT FROM WHAT THE BOOK SAYS. Handed only a name, an image model
draws its idea of a D&D NPC: a generic fantasy portrait that happens to be
called Ismark. The graph already holds the sentences that name him, so the
prompt is assembled from those -- and the result is at least anchored to the
text a DM could check it against.

AND THE PROMPT IS STORED, which is the whole reason this module is separate
from the call that runs it. `assets.store_generated` refuses an asset that
cannot say what produced it, and the eighth invariant catches any that slip in.
An image with no record of what it was asked for is a claim nobody can check,
in the most persuasive medium the product has.

IT IS NOT A STYLE ENGINE. There is no lighting, no lens, no artist name and no
"trending on" -- those are how a prompt stops describing the subject and starts
describing a picture, and this one has to stay readable as evidence: a DM
looking at a stored prompt should see the book's claims, not a recipe.
"""

from __future__ import annotations

#: How much of the book to put in a prompt.
#:
#: THREE SENTENCES, NOT THE SECTION. A whole chapter drowns the subject -- the
#: model starts drawing the tavern the person is standing in -- and one sentence
#: is usually the one that merely names them.
SENTENCES = 3

#: The frame the book's words are set in. Deliberately plain.
FRAME = (
    "A character portrait for a tabletop roleplaying game. "
    "Head and shoulders, plain background, no text, no border, no lettering."
)

PLACE_FRAME = (
    "An illustration of a place for a tabletop roleplaying game. "
    "No text, no border, no lettering, no people in the foreground."
)


def frame_for(labels: list[str]) -> str:
    """A portrait of a person, or a view of a place.

    TWO FRAMES, NOT FIVE. A monster is a portrait, an item is a portrait of an
    object on a plain ground, and only a LOCATION genuinely wants a different
    composition. Splitting further would be inventing distinctions the graph
    does not draw.
    """
    return PLACE_FRAME if "LOCATION" in labels else FRAME


def prompt_for(*, name: str, labels: list[str], role: str = "",
               says: list[str] | None = None, note: str = "") -> str:
    """What to ask for, and what the stored record will say it asked for.

    ORDERED BOOK-FIRST, DM-LAST. The published sentences carry the most weight
    because they are the thing a reader can check the picture against; the DM's
    note comes last so it refines rather than replaces them.

    A NAME ALONE IS ALLOWED AND IS THE WEAK CASE. An entity with no prose gets a
    prompt saying so little that the result is visibly invented -- which is the
    honest outcome, and better than padding it with detail nobody wrote.
    """
    parts = [frame_for(labels), f"Subject: {name}."]
    kinds = [l for l in labels if l != "Entity"]
    if kinds:
        parts.append(f"It is a {kinds[0].lower()}.")
    if role:
        parts.append(role.rstrip(".") + ".")
    for line in (says or [])[:SENTENCES]:
        cleaned = " ".join(line.split())
        if cleaned:
            parts.append(f"The source text says: {cleaned}")
    if note.strip():
        parts.append(f"The DM adds: {note.strip()}")
    return " ".join(parts)
