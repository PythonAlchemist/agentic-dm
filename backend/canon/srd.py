"""Reading the SRD, which does not need a model to be understood.

THE ADVENTURES NEEDED ONE AND THIS DOES NOT. `transcriber.py` sends page images
to a vision model because Curse of Strahd is a designed book -- two columns,
sidebars, art bleeding across the gutter -- and because finding the ENTITIES in
narrative prose is genuinely inference: "the burgomaster" is a person the text
never names in that sentence.

None of that is true here. The SRD is a text-layer PDF with a four-level font
ladder, and every reference entry announces itself as a heading: `Fireball` is a
heading, `Blinded` is a heading, `Adamantine Armor` is a heading. Asking a model
to guess what is already printed would cost money to introduce error.

SO THE RULE IS STATED, NOT INFERRED. `ENTRIES` below says which heading level
holds the entries in which chapter, because the answer differs -- spells and
magic items are the fourth level, monsters the third -- and a rule that guessed
"the deepest heading present" would quietly reclassify a chapter the day its
formatting varied.

WHAT IS DROPPED, AND WHY IT IS COUNTED. The running footer and the page number
are furniture, not text. They are removed by their own font and size rather than
by matching their words, and the counts come back in the report: silent
filtering has twice hidden a defect in this project for weeks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: The ladder, measured off the file rather than assumed. `GillSans-SemiBold`
#: at four sizes carries every heading in the document; `Cambria` carries the
#: prose.
LADDER = {25.9: 1, 18.0: 2, 13.9: 3, 12.0: 4}

#: The page number, which shares the heading font and is not a heading.
PAGE_NUMBER_SIZE = 10.8

#: The running footer, in its own face.
FOOTER_FONTS = ("Calibri-Italic",)

HEADING_FONT = "GillSans"

#: What this file leaves on every line between words: a tab, a carriage return,
#: a space and a non-breaking space. An artefact of how the PDF was typeset,
#: and invisible until a name fails to match.
SPACING = re.compile(r"[\t\r\u00a0 ]+")

#: THREE HYPHENS WHERE ONE BELONGS. The file writes a real hyphen, then a soft
#: hyphen, a HYPHEN and a NON-BREAKING HYPHEN -- all left by the typesetter's
#: line-breaking. A reader sees a smear where "3rd-level" should be, and a
#: person typing "3rd-level" into a search box finds nothing, which is the
#: worse half of the same defect.
#:
#: THE SOFT HYPHEN IS DELETED, THE OTHERS BECOME `-`. A soft hyphen marks a
#: place a word MAY break and is not part of the word; keeping one turns
#: `with` into something no query will ever match.
SOFT_HYPHEN = "\u00ad"
HYPHENS = re.compile("[\u2010\u2011\u2012\u2013]")

#: Curly quotes folded to straight ones, for the reason `fold_apostrophe` folds
#: them in `spine.py`: two spellings of one word are two things that will not
#: match each other.
CURLY = {"\u2019": "'", "\u2018": "'", "\u201c": '"', "\u201d": '"'}


@dataclass(frozen=True)
class Span:
    """One run of text with the font that drew it."""

    text: str
    font: str
    size: float
    page: int


@dataclass
class Entry:
    """One thing the SRD defines, and the prose defining it."""

    name: str
    kind: str
    chapter: str
    page: int
    text: str = ""


@dataclass
class Report:
    """What came out, and what did not."""

    entries: list[Entry] = field(default_factory=list)
    chapters: list[str] = field(default_factory=list)
    dropped_footers: int = 0
    dropped_page_numbers: int = 0
    #: Headings inside an entry-bearing chapter that sat at the wrong level to
    #: be an entry. Counted so a chapter whose formatting differs shows up as a
    #: number rather than as silence.
    passed_over: int = 0


#: THE SRD IS TYPESET TWICE. Prose chapters are Cambria with GillSans
#: headings; stat blocks are Calibri with their own bold headings. A monster's
#: name is `Calibri-Bold` at 12pt and a spell's is `GillSans-SemiBold` at 12pt
#: -- the same size, a different system -- so a rule written in sizes alone
#: reads one of them wrong.
STATBLOCK_FONT = "Calibri-Bold"
STATBLOCK_SIZE = 12.0


@dataclass(frozen=True)
class Spec:
    """Where a chapter keeps its entries, and what they are."""

    kind: str
    #: The level-2 section the entries sit under. Empty means the whole
    #: chapter -- the conditions appendix has no container.
    #:
    #: REQUIRED WHERE IT EXISTS, because `Spellcasting` opens with the rules
    #: for casting a spell -- `Bonus Action`, `Reactions` -- set at exactly the
    #: level a spell name uses. Without the container those become 100 spells
    #: nobody can cast.
    under: tuple[str, ...] = ()
    #: A prefix the open container must start with. The monster chapter runs
    #: `Monsters (A)` through `Monsters (Z)`, and naming all twenty-six would
    #: be a list to keep in step with the file for no gain.
    #:
    #: IT IS DOING THE SAME WORK AS `under`: the chapter opens with tables --
    #: `Size Categories`, `Hit Dice by Size` -- whose captions are set in the
    #: stat-block face, so without a container four tables became monsters.
    under_prefix: str = ""
    #: The heading level, for chapters set as prose.
    level: int = 4
    #: True where an entry is a stat block rather than a heading.
    statblock: bool = False


#: A TABLE RATHER THAN A HEURISTIC. "The deepest heading present" would get
#: today's file right and reclassify a chapter the day a heading is added. The
#: labels are `EntityType` members, so nothing here invents a kind.
ENTRIES: dict[str, Spec] = {
    "Spellcasting": Spec("SPELL", under=("Spell Descriptions",), level=4),
    "Magic Items": Spec("ITEM", under=("Magic Items A-Z",), level=4),
    "Appendix PH-A: Conditions": Spec("RULE", level=4),
    "Monsters": Spec("MONSTER", statblock=True, under_prefix="Monsters ("),
    "Appendix MM-A: Miscellaneous Creatures": Spec("MONSTER", statblock=True),
    "Appendix MM-B: Nonplayer Characters": Spec("MONSTER", statblock=True),
}


def clean(text: str) -> str:
    """One space between words and one hyphen between syllables.

    EVERY SUBSTITUTION HERE IS A SEARCH THAT WOULD OTHERWISE FAIL. The reader
    sees the mess; the person typing "3rd-level" into a search box sees
    nothing at all, and has no way to find out why.
    """
    text = text.replace(SOFT_HYPHEN, "")
    text = HYPHENS.sub("-", text)
    for odd, plain in CURLY.items():
        text = text.replace(odd, plain)
    # A HYPHEN FOLLOWED BY ITS OWN REPLACEMENTS collapses to one: the file
    # writes a real hyphen and then two more characters meaning the same
    # break, so `3rd---level` is what the substitutions above leave behind.
    text = re.sub(r"-{2,}", "-", text)
    return SPACING.sub(" ", text).strip()


def is_heading(span: Span) -> int:
    """The heading level of this span, or 0.

    THE PAGE NUMBER IS EXCLUDED BY SIZE AND BY SHAPE. It is set in the heading
    face, so the font alone would make every page number a heading called "96".
    """
    if HEADING_FONT not in span.font:
        return 0
    if abs(span.size - PAGE_NUMBER_SIZE) < 0.2:
        return 0
    for size, level in LADDER.items():
        if abs(span.size - size) < 0.2:
            return level
    return 0


def read_spans(spans: list[Span]) -> Report:
    """Everything the SRD defines, with the prose that defines it.

    A HEADING SPLIT ACROSS TWO LINES IS ONE HEADING. `Amulet of Proof against
    Detection and Location` arrives as two spans at the same size, and treating
    them as two entries would mint an item called `Location`.
    """
    report = Report()
    chapter = ""
    #: The level-2 heading currently open, which is what `Spec.under` names.
    container = ""
    current: Entry | None = None
    pending_level = 0
    pending_page = 0

    for span in spans:
        text = clean(span.text)
        if not text:
            continue
        if any(f in span.font for f in FOOTER_FONTS):
            report.dropped_footers += 1
            continue

        level = is_heading(span)
        if level == 0 and HEADING_FONT in span.font:
            report.dropped_page_numbers += 1
            continue

        spec = ENTRIES.get(chapter)

        # A STAT BLOCK NAMES ITSELF IN ITS OWN FACE, so in a monster chapter
        # the entry is found by font rather than by heading level.
        if (spec and spec.statblock and STATBLOCK_FONT in span.font
                and abs(span.size - STATBLOCK_SIZE) < 0.2):
            if spec.under_prefix and not container.startswith(spec.under_prefix):
                report.passed_over += 1
                continue
            if current is not None and current.name == text:
                continue
            current = Entry(name=text, kind=spec.kind, chapter=chapter,
                            page=span.page)
            report.entries.append(current)
            pending_level = 0
            continue

        if level == 0:
            if current is not None:
                current.text = f"{current.text} {text}".strip()
            pending_level = 0
            continue

        # A CONTINUATION, not a new heading: the same level twice running with
        # no prose between. `Amulet of Proof against Detection and Location` is
        # two spans, and reading them apart mints an item called `Location`.
        #
        # ON THE SAME PAGE, because that is what a wrapped line is. Without it,
        # a chapter that happens to end where the next begins would swallow its
        # neighbour's title -- which cannot happen in this file today and is
        # the kind of thing a file changes about itself.
        if level == pending_level and span.page == pending_page:
            if level == 1 and report.chapters:
                report.chapters[-1] = f"{report.chapters[-1]} {text}"
                chapter = report.chapters[-1]
            elif current is not None and not current.text:
                current.name = f"{current.name} {text}"
            elif level == 2:
                container = f"{container} {text}"
            continue

        pending_level, pending_page = level, span.page

        if level == 1:
            chapter, container, current = text, "", None
            report.chapters.append(text)
            continue

        if level == 2:
            container, current = text, None
            continue

        if spec and not spec.statblock and level == spec.level:
            # THE CONTAINER IS THE GATE. Without it, `Spellcasting`'s rules for
            # casting -- set at exactly a spell's level -- become spells.
            if spec.under and container not in spec.under:
                report.passed_over += 1
                continue
            current = Entry(name=text, kind=spec.kind, chapter=chapter,
                            page=span.page)
            report.entries.append(current)
            continue

        if current is not None:
            # Deeper than an entry, so part of the entry it sits inside: a
            # spell's "At Higher Levels", a monster's "Actions".
            current.text = f"{current.text} {text}.".strip()
        elif spec:
            report.passed_over += 1

    return report


def read(path) -> Report:
    """Read the PDF. The only part that touches a file."""
    import pymupdf

    spans: list[Span] = []
    with pymupdf.open(path) as document:
        for number, page in enumerate(document, 1):
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    for span in line["spans"]:
                        spans.append(Span(
                            text=span["text"], font=span["font"],
                            size=round(span["size"], 1), page=number))
    return read_spans(spans)
