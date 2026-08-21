"""Which entities the book names in the same sentence.

    (:Mention)-[:CO_OCCURS_WITH]->(:Entity)

Two mentions sharing a `:Section` is weak evidence -- a section is often a whole
room description, and chapter 3's longest runs to several thousand characters.
Two entities named in the same SENTENCE is strong, and the offsets to compute it
are already on the nodes: a `:Mention` carries `offsets`, its `:Section` carries
`text`.

**THE SPAN RULE IS IMPORTED, NOT RESTATED.** `passage.sentence_bounds` is what
decides where a sentence begins and ends, here and in `lookup`, and it was
written to return offsets for exactly this caller. A second definition of "the
same sentence" would drift within a chapter, and the drift would surface as a
co-occurrence edge whose passage does not contain both names -- a fact the graph
asserts and the prose refuses. Nothing in this module looks at punctuation.

**RECORD THE CO-OCCURRENCE; INFER NOTHING FROM IT.** That Strahd, Barovia,
Madam Eva and the tarokka deck appear in one sentence is a FACT, checkable
against the book by slicing the section. Whether it means `SEEKS` or `THREATENS`
is a judgment this project has failed to automate four separate ways --
consensus voting, a wiki oracle, type constraints, two-stage classification --
and each failure was expensive. So there is no relationship type in here, no
weight, no score, and nothing that could be mistaken for one. This is the raw
material; the judgment is somebody else's, later, or nobody's.

**IT BELONGS WITH `REFERS_TO`, `IN_SECTION` AND `DESCRIBES`, NOT IN THE TRUST
SPLIT.** The `accepted`/`proposed` partition exists because a model guessed a
typed relationship and roughly a third of those guesses were wrong. This is
arithmetic over offsets the scan already found: the same text produces the same
edges every time, and there is nothing for a reviewer to accept. So no `status`.

(The design named `MENTIONED_IN` as the company this keeps. That edge no longer
exists -- `:Mention` is what replaced it, for recording where an entity was
EXTRACTED rather than where it appears -- so the peers are named above as the
graph actually holds them. Same side, edges that are still here.)

**THE COUNT IS THE THING TO WATCH.** A sentence naming n entities produces
n(n-1) pairs, so the total is quadratic in the widest span the boundary rule
admits, and a rule that quietly swallowed a paragraph would show up here as a
"sentence" naming eight things long before it showed up as a slow query. Every
write prints the ratio and the widest sentence; `widest_sentence` says what
those two numbers are worth and how one of them once lied.

**WHAT IT COULD NOT SEE, AND NOW CAN.** A `:Mention` used to store ONE offset,
where the section first says the name, so an entity named in sentences 1 and 5
was anchored in sentence 1 and any pairing it made in sentence 5 was invisible.
That cost more than it looked: 2,970 of the corpus's 6,966 spans were unstored,
and 478 of 907 entities co-occurred with nothing at all. The measured case is
the tavern -- "Three Vistani spies named Alenka, Mirabel, and Sorvia" names
four entities in ONE sentence and produced no pairs, because `Vistani` had been
anchored 3,300 characters earlier.

A `:Mention` now stores every span, and this pairs on all of them. THE SENTENCE
RULE IS UNCHANGED: the old note was right that a rule swallowing a paragraph
would square the graph, and the window is still one sentence. What widened is
what the window may look at, not the window.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from backend.canon.passage import derive_passage, sentence_bounds
from backend.canon.spine import WriteMention, WriteSection


@dataclass(frozen=True, order=True)
class CoOccurrence:
    """One mention, and one other entity its sentence also names.

    A MENTION on one end and an ENTITY on the other, deliberately asymmetric in
    shape. The mention end is where the evidence is -- it names the section and
    the offset, so the sentence can be sliced out and read -- while the far end
    is the thing named, which is global to the book and has no one place. An
    entity-to-entity edge would lose the sentence; a mention-to-mention edge
    would claim a locality for the far entity that the far entity does not have.

    Frozen and ordered so a plan can be compared, sorted and deduplicated by
    value. The pair IS the identity: one row per (mention, entity), however many
    sentences of that section put them together.
    """

    mention_id: str
    entity_id: str


def plan_co_occurrences(
    sections: Iterable[WriteSection], mentions: Iterable[WriteMention]
) -> list[CoOccurrence]:
    """Every (mention, entity) pair the sentences support, in a stable order.

    THREE RULES, AND ALL OF THEM ARE ARITHMETIC.

    **A mention never co-occurs with its own entity.** A sentence naming Ireena
    twice names one entity, and a self-edge would say the book relates her to
    herself. The check is on `entity_id` rather than on mention identity because
    that is the claim being refused -- although within one section the two are
    the same test, since a `:Mention` is one per (entity, section).

    **A pair is written once per (mention, entity), not once per sentence.** The
    same two entities paired in two sentences of one section still have only two
    mentions to hang an edge off, and emitting the pair twice would make the
    count a count of sentences wearing the name of a count of pairs.

    **A pair is mutual or it is nothing.** Two offsets pair when EITHER falls
    inside the other's span, which matters only above `passage.PASSAGE_MAX`:
    below the cap both offsets in one sentence derive the identical span and the
    condition is one test written twice. Above it, `sentence_bounds` returns a
    window placed around the offset it was asked about, so for a long enough
    sentence A's window holds B while B's window does not hold A. That is an
    artefact of a cap that exists to keep a RENDERED passage short, and a
    rendering budget may not decide which direction of a symmetric fact the
    graph records. The corpus has exactly one such pair: `tinderbox` and an
    87-character book title, both inside one 300-plus-character sentence in
    chapter 3.

    A mention whose section is not among `sections` RAISES rather than being
    skipped, for the reason `_write_edge` raises on a missing endpoint: a silent
    skip is how a chapter acquires fewer edges than it planned with nothing
    appearing to have failed.
    """
    text_by_section = {section.id: section.text for section in sections}

    in_section: dict[str, list[WriteMention]] = {}
    for mention in mentions:
        if mention.section_id not in text_by_section:
            raise ValueError(
                f"no section {mention.section_id!r} for mention {mention.id!r}"
            )
        in_section.setdefault(mention.section_id, []).append(mention)

    planned: list[CoOccurrence] = []
    for section_id, here in sorted(in_section.items()):
        text = text_by_section[section_id]
        # Once per OFFSET rather than once per pair: the span depends only on
        # the offset, and computing it inside the inner loop would run the
        # boundary scan n times for the same answer.
        spans = {
            mention.id: [sentence_bounds(text, o) for o in mention.offsets]
            for mention in here
        }
        ordered = sorted(here, key=lambda m: m.id)
        for mention in ordered:
            for other in ordered:
                if other.entity_id == mention.entity_id:
                    continue
                if _share_a_sentence(
                    spans[mention.id], mention.offsets,
                    spans[other.id], other.offsets,
                ):
                    planned.append(
                        CoOccurrence(mention_id=mention.id, entity_id=other.entity_id)
                    )
    return planned


def _share_a_sentence(
    spans: list[tuple[int, int]],
    offsets: tuple[int, ...],
    other_spans: list[tuple[int, int]],
    other_offsets: tuple[int, ...],
) -> bool:
    """Does ANY sentence of one hold ANY naming of the other?

    ANY, and still at most one pair per (mention, entity): two entities named
    together in three sentences of a section have the same two mentions to hang
    an edge off as if they were named together once, and emitting it three
    times would make the count a count of sentences wearing the name of a count
    of pairs. That invariant is why this returns a bool rather than the spans
    that matched.

    Mutual, for the reason `plan` gives at length: above `PASSAGE_MAX` a long
    sentence can put B inside A's window without putting A inside B's, and a
    rendering budget may not decide which direction of a symmetric fact the
    graph records.
    """
    return any(
        low <= other < high for low, high in spans for other in other_offsets
    ) or any(
        low <= own < high for low, high in other_spans for own in offsets
    )


def co_occurrence_counts(
    planned: Iterable[CoOccurrence], names_by_id: Mapping[str, str]
) -> list[tuple[str, int]]:
    """`(name, pairs)` for the entities most sentences reach, most first.

    Printed on every write for the same reason `mention_counts` is: nothing
    filters junk out of the scan, so a common noun promoted to an entity is
    invisible in a total and unmissable in a ranking. `light` and `vampire` are
    the known cases, and if either heads this list that is a finding about those
    two nodes rather than about co-occurrence.

    Counts the INCOMING end -- how many mentions name something in a sentence
    that also names this entity. Ties broken by name so the order is total.
    """
    counts = Counter(pair.entity_id for pair in planned)
    return sorted(
        ((names_by_id.get(entity_id, entity_id), count) for entity_id, count in counts.items()),
        key=lambda pair: (-pair[1], pair[0]),
    )


@dataclass(frozen=True)
class WidestSentence:
    """The single sentence that pairs the most entities, and its passage.

    THE NUMBER THE DESIGN ASKS TO BE WATCHED. A sentence naming n entities is
    n(n-1) edges, so this is the term the total is quadratic in, and one loose
    boundary anywhere in the span rule would show up here first -- as a
    "sentence" that is really a paragraph, naming eight things.

    `passage` is the prose itself rather than only a count, so the judgment
    "is that one sentence?" is available to a reader without a query.
    """

    entities: int
    passage: str
    names: tuple[str, ...]


def widest_sentence(
    sections: Iterable[WriteSection],
    mentions: Iterable[WriteMention],
    planned: Iterable[CoOccurrence],
    names_by_id: Mapping[str, str],
) -> WidestSentence | None:
    """The densest sentence in this chapter, or None if nothing paired.

    THIS USED TO BE DERIVED FROM THE PLAN -- the mention with the most partners,
    plus itself -- on the reasoning that a figure computed from the edges cannot
    disagree with the edge count printed beside it. That held only while a
    mention had ONE offset, which made "this mention's partners" and "the
    entities in this sentence" the same set.

    They are not the same set now. A mention has an offset in every sentence
    that names it, so its partners are the UNION across all of them, while the
    quoted passage is still one sentence. On the village chapter that reported
    "widest sentence: 10 entities (90 edges)" above a sentence naming three --
    a watchdog that cried wolf about the one thing it exists to watch, which is
    worse than no watchdog.

    So this re-scans, per SENTENCE. It is the same boundary rule and the same
    offsets `plan` pairs on -- `sentence_bounds` either way -- so the second
    traversal the old note feared cannot drift from the first without
    `sentence_bounds` itself changing under both.
    """
    text_by_section = {section.id: section.text for section in sections}
    in_section: dict[str, list[WriteMention]] = {}
    for mention in mentions:
        in_section.setdefault(mention.section_id, []).append(mention)

    best: WidestSentence | None = None
    for section_id, here in sorted(in_section.items()):
        text = text_by_section[section_id]
        for mention in sorted(here, key=lambda m: m.id):
            for offset in mention.offsets:
                low, high = sentence_bounds(text, offset)
                named = {
                    other.entity_id
                    for other in here
                    if any(low <= o < high for o in other.offsets)
                }
                if len(named) < 2 or (best and len(named) <= best.entities):
                    continue
                best = WidestSentence(
                    entities=len(named),
                    passage=derive_passage(text, offset),
                    names=tuple(sorted(
                        names_by_id.get(entity_id, entity_id) for entity_id in named
                    )),
                )
    return best
