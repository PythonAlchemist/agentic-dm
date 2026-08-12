"""Stage B: re-decide an extracted pair's relationship in a focused call.

EXPERIMENT, NOT PIPELINE. Nothing in `extract_canon.py` imports this. It exists
to answer one question against artifacts already on disk: is the pipeline's edge
error rate a TYPING failure that a second, narrower call can fix?

The diagnosis it is testing. Roughly half of the pipeline's LLM edges are false
as stated, and the failures are systematic rather than random -- three of the
worst appeared in 5 of 5 consensus samples. Every one of them quotes real book
prose and then attaches a relationship the prose does not support: the model
READS correctly and TYPES wrongly. The extraction prompt asks one call to
discover entities, find relationships, choose a type and choose a direction, and
it is the typing that fails.

So this keeps the pair the extractor found and throws its `rel_type` away.

FOUR PROPERTIES CARRY THE EXPERIMENT. Each is load-bearing; weakening any one
makes the measured numbers mean something other than what they appear to.

1. THE ORIGINAL `rel_type` IS NEVER VISIBLE. `Pair` has no field for it, so a
   prompt cannot render it. Showing it would anchor the answer on the very
   decision being re-made, and the before/after comparison would be measuring
   agreement with itself. Note that "the prompt does not contain the string
   KNOWS" is NOT the property -- KNOWS is frequently a legal option and appears
   for that reason. The property is that two edges differing ONLY in `rel_type`
   render the identical prompt, which is what the tests assert.

2. THE ENDPOINT ORDER IS CANONICAL, NOT THE EDGE'S. `pair_from_edge` sorts the
   two names, so the pair presented first is decided by the alphabet and not by
   which endpoint the extractor happened to call the source. Presenting the
   original source first would list the original direction first in every option
   block -- a positional anchor on the second thing being re-decided.

3. ONLY TYPE-LEGAL RELATIONS ARE OFFERED. `RELATIONSHIP_DOMAIN_RANGE` decides
   which types admit `(a -> b)` and which admit `(b -> a)`; the prompt offers
   exactly those, each with its `RELATIONSHIP_GLOSS` and its direction spelled
   out. This shrinks a 46-way choice (23 types x 2 directions) to a measured
   median of about 7 options, and makes type-impossible answers unrepresentable
   rather than merely detectable.

   WHICH IS ALSO A MEASUREMENT TRAP, stated here so nobody later mistakes it for
   a result: the constraint-violation rate of this module's output is ZERO BY
   CONSTRUCTION. That is a property of the design. It is not evidence that the
   typing improved.

4. `NONE` IS ALWAYS AVAILABLE AND EXPLICITLY EASY TO CHOOSE. The extractor has
   no way to decline, and declining is where precision comes from. If the
   decline rate comes back near zero, the experiment changed nothing.

TWO CORRECTIONS FROM THE FIRST MEASURED RUN, both found by a hand read of the
30-edge fabrication sample it produced.

A. A SELF-PAIR ADMITS NOTHING. `Helga Ruvak -IDENTITY_OF-> Helga Ruvak` survived
   the first run and shipped in the sample. Nothing should spend a token
   deciding whether a thing relates to itself, and the failure class has been
   known on this project since its first fabrication check. `offered_options`
   now returns `[]` for a pair whose two names fold equal, so a self-pair can
   neither be rendered nor answered. It is counted in `self_loops`, apart from
   `no_legal_relation`: one is a fact about the names, the other about the type
   table, and summing them would describe neither.

B. A PAIR MAY CARRY MORE THAN ONE RELATION, up to `max_relations`. Of the three
   golden edges the first run lost, one was a single sentence stating TWO true
   relations -- "Ismark seeks to protect his adopted sister, Ireena Kolyana" is
   both RELATED_TO and GUARDS -- where the design permitted one answer. That was
   not a typing failure but a shape failure, so the shape changed: `classify`
   returns a LIST of decisions per pair.

   The cap is deliberately low and the prompt demands each relation be
   INDEPENDENTLY stated rather than merely legal, because the obvious failure
   mode is a model filling the slots. `capped` records how often the cap
   actually bound; if the extra slot is used almost always, the cap is doing the
   work rather than the evidence, and the number says so.

Endpoint types come from the candidate NODES by folded name, exactly as
`constraints.py` resolves them, and via the same `fold_name`. A name may carry
more than one type (a coined QUEST sharing a LOCATION's name is a measured
occurrence in this corpus); `Pair` records that as `"A|B"`, the same rendering
`Violation` uses, and a type set satisfies a domain or range when ANY of its
members does -- the `_fits` rule, so an ambiguity cannot silently forbid a
relation the edge may well be about.

Failure handling follows `extract.py`: never raise, return a per-pair
non-answer, and surface the count, so a partial run cannot masquerade as a high
decline rate.
"""

import asyncio
import json
import logging
from dataclasses import dataclass

from openai import AsyncOpenAI

from backend.canon.constraints import fold_name, types_by_name
from backend.canon.extract import EXTRACTION_MODEL, EXTRACTION_SEED
from backend.canon.models import CandidateEdge, CandidateNode
from backend.core.config import settings
from backend.graph.schema import (
    RELATIONSHIP_DOMAIN_RANGE,
    RELATIONSHIP_GLOSS,
    EntityType,
    RelationshipType,
)

logger = logging.getLogger(__name__)

#: The model's answer when the evidence states no offered relationship. A real
#: decision, and the whole precision mechanism -- counted, never discarded.
NONE_RELATION = "NONE"

#: No usable answer came back for this pair: the call failed, the batch skipped
#: the number, or the answer named endpoints or a type that were never offered.
#: Distinct from NONE_RELATION on purpose -- a silence must never be counted as
#: a decline, because that would let a broken run report a flattering precision
#: mechanism. Every one of these is counted in `RelationClassifier.failures`.
NO_ANSWER = ""

#: Pairs per call. 457 chapter-4 edges become ~46 calls at this size.
BATCH_SIZE = 10

#: How many relations one pair may carry. Two, not three: the demonstrated loss
#: needs exactly one extra slot, and precision is the fragile side of this trade
#: -- an under-extracted edge can be recovered later, a junk canon edge cannot.
#: Raising it is a measurement, not a default; `capped` says whether it binds.
MAX_RELATIONS = 2

_TYPE_SEPARATOR = "|"


@dataclass(frozen=True)
class Pair:
    """Two entities the extractor found together, and the evidence it quoted.

    Deliberately carries NO relationship type and NO notion of which endpoint
    was the source: see properties 1 and 2 in the module docstring. `a_type` and
    `b_type` are `"|"`-joined `EntityType` values, or `""` for an endpoint no
    candidate node typed.
    """

    a_name: str
    a_type: str
    b_name: str
    b_type: str
    evidence: str
    section_heading: str
    chapter_slug: str
    section_index: int


@dataclass(frozen=True)
class Decision:
    """What stage B decided for one pair.

    `rel_type` is a relationship type, `NONE_RELATION`, or `NO_ANSWER`.
    `source_name` and `target_name` are `""` for both of the latter -- a pair
    with no relationship has no direction to record.

    `confidence` is the model's own word, kept as written and lowercased. It is
    descriptive metadata for a human reading the sample; nothing branches on it,
    so an unexpected word is recorded rather than coerced into a known one.
    """

    source_name: str
    target_name: str
    rel_type: str
    confidence: str


def parse_types(spec: str) -> frozenset[EntityType]:
    """`"LOCATION|QUEST"` -> the two types. Unknown members are dropped.

    An empty result means the endpoint is untyped, which `legal_relations`
    treats as unconstrained -- the same rule `constraints._fits` applies, for
    the same reason: refusing to offer anything for an endpoint we merely failed
    to type would turn a typing failure into a fabricated absence of relation.
    """
    found: set[EntityType] = set()
    for part in spec.split(_TYPE_SEPARATOR):
        try:
            found.add(EntityType(part.strip()))
        except ValueError:
            continue
    return frozenset(found)


def render_types(types: frozenset[EntityType]) -> str:
    """The inverse of `parse_types`, sorted so a pair renders reproducibly."""
    return _TYPE_SEPARATOR.join(sorted(t.value for t in types))


def legal_relations(
    source_types: frozenset[EntityType], target_types: frozenset[EntityType]
) -> list[RelationshipType]:
    """Every relationship type whose domain and range admit `source -> target`.

    Sorted by name so the offered vocabulary is deterministic. An untyped side
    admits everything (see `parse_types`).
    """
    return sorted(
        (
            rel
            for rel, (domain, range_) in RELATIONSHIP_DOMAIN_RANGE.items()
            if (not source_types or source_types & domain)
            and (not target_types or target_types & range_)
        ),
        key=lambda rel: rel.value,
    )


def is_self_pair(pair: Pair) -> bool:
    """Whether both endpoints are the same entity, by the shared name fold.

    Folded, not compared raw: `Strahd` and `strahd ` are one entity, and an
    extractor that emitted the second spelling has still produced a self-loop.
    """
    return fold_name(pair.a_name) == fold_name(pair.b_name)


def offered_options(pair: Pair) -> list[tuple[str, str, RelationshipType]]:
    """Every `(source_name, target_name, rel_type)` the ontology allows here.

    Both directions, ordered by relationship name and then by source name. The
    secondary key is the SOURCE NAME rather than the direction, so no direction
    is systematically listed first (property 2): `a` precedes `b` because the
    alphabet put it there, not because the extractor called it the source.

    A SELF-PAIR IS OFFERED NOTHING. `Helga Ruvak -IDENTITY_OF-> Helga Ruvak`
    survived the first run and shipped in its fabrication sample. No relation in
    this ontology says anything by relating a thing to itself, so the empty list
    is the correct vocabulary, and returning it here -- rather than filtering
    later -- means a self-pair can never be rendered into a prompt or matched
    against an answer. One rule, one implementation.
    """
    if is_self_pair(pair):
        return []
    a_types, b_types = parse_types(pair.a_type), parse_types(pair.b_type)
    options = {
        (pair.a_name, pair.b_name, rel) for rel in legal_relations(a_types, b_types)
    } | {(pair.b_name, pair.a_name, rel) for rel in legal_relations(b_types, a_types)}
    return sorted(options, key=lambda option: (option[2].value, option[0], option[1]))


def pair_from_edge(edge: CandidateEdge, by_name: dict[str, frozenset[EntityType]]) -> Pair:
    """The pair an edge is about, with its direction and type deliberately lost.

    The two endpoints are sorted, so an edge and its reverse produce the SAME
    pair and therefore the same prompt. That is what makes direction a decision
    stage B makes rather than one it inherits.
    """
    endpoints = sorted(
        ((edge.source_name, by_name.get(fold_name(edge.source_name), frozenset())),
         (edge.target_name, by_name.get(fold_name(edge.target_name), frozenset()))),
        key=lambda endpoint: (fold_name(endpoint[0]), endpoint[0]),
    )
    (a_name, a_types), (b_name, b_types) = endpoints
    return Pair(
        a_name=a_name,
        a_type=render_types(a_types),
        b_name=b_name,
        b_type=render_types(b_types),
        evidence=edge.evidence,
        section_heading=edge.section_heading,
        chapter_slug=edge.chapter_slug,
        section_index=edge.section_index,
    )


def pairs_from_edges(nodes: list[CandidateNode], edges: list[CandidateEdge]) -> list[Pair]:
    """One pair per edge, in edge order, so decisions realign positionally."""
    by_name = types_by_name(nodes)
    return [pair_from_edge(edge, by_name) for edge in edges]


_INSTRUCTIONS_TEMPLATE = """\
You are re-reading relationships in a D&D sourcebook.

Each numbered item below gives two entities that were mentioned together, the
span of book text they were mentioned in, and the section it came from. For each
item, choose the options listed under that item that the evidence states, or
answer NONE.

MOST PAIRS OF ENTITIES MENTIONED NEAR EACH OTHER HAVE NO RELATIONSHIP. NONE is
the right answer whenever the evidence does not state one of the offered
relationships, and it is expected to be a common answer. Choose a relationship
only when the evidence asserts it; if the evidence merely makes one plausible,
answer NONE.

ALMOST EVERY ITEM THAT HAS A RELATIONSHIP AT ALL HAS EXACTLY ONE. You may name
up to {max_relations} for a single item, but only when the evidence makes each
of them separately -- when it asserts one thing about the two entities and then
asserts a further, different thing about them. Do NOT add a second because it is
also legal, because it follows from the first, or because it seems likely. A
second relation that restates or elaborates the first is wrong.

Judge only the quoted evidence, as written. Do not use outside knowledge of the
setting, and do not use the section heading as evidence -- it is context only.

Direction matters, and each option spells out which entity is the source. The
options listed for an item are the only ones permitted for it; an option not
listed is not available, however true it may seem.

Report your own confidence for the item:
  "clear"   - the evidence states the relationship outright
  "implied" - the evidence entails it without stating it
  "unsure"  - you are guessing; prefer NONE

Return JSON with exactly one entry per numbered item, every number answered once
and no numbers invented. `relations` is always a LIST. Copy each option you
choose EXACTLY as it is written, without its explanation in brackets. Answer
["NONE"] to decline:
{{"answers": [
  {{"n": 1, "relations": ["NONE"]}},
  {{"n": 2, "relations": ["Halvard -KNOWS-> Emberhall"], "confidence": "clear"}},
  {{"n": 3, "relations": ["Halvard -OWNS-> Emberhall", "Halvard -LOCATED_IN-> Emberhall"],
   "confidence": "clear"}}
]}}
"""

# Invented names, and a relation pair the corpus never produces, so the worked
# example cannot teach the answer to any measured case. The first draft of this
# used `Ismark RELATED_TO/GUARDS Ireena` -- which is one of the three golden
# edges the previous run LOST, and the exact case this change exists to recover.
# Shipping that would have made its recovery worthless as evidence.
_EXAMPLE_NAMES = ("Halvard", "Emberhall")


def _instructions(max_relations: int) -> str:
    return _INSTRUCTIONS_TEMPLATE.format(max_relations=max_relations)


def render_option(source: str, target: str, rel: RelationshipType) -> str:
    """The one wire form for an answer: exactly how the option is offered.

    A structured `{source, target, rel_type}` triple was tried first and the
    model ignored it, packing the whole rendered option into `rel_type` instead
    -- 8 of 20 pairs unparseable in a smoke run. Asking it to echo the string it
    was shown is what it does unprompted, and it makes validation an EXACT match
    against the offered set rather than three fields that can disagree.
    """
    return f"{source} -{rel.value}-> {target}"


def _fold_option(text: str) -> str:
    """Whitespace-normalised and case-folded, so an echo with different spacing
    or casing still has to name an option that was actually offered."""
    return " ".join(text.split()).casefold()


def render_pair(number: int, pair: Pair) -> str:
    """One numbered item, options included. Never mentions any prior typing."""
    options = "\n".join(
        f"     - {render_option(source, target, rel)}   ({RELATIONSHIP_GLOSS[rel]})"
        for source, target, rel in offered_options(pair)
    )
    return (
        f"{number}. {pair.a_name} ({pair.a_type or 'type unknown'}) "
        f"and {pair.b_name} ({pair.b_type or 'type unknown'})\n"
        f"   Section: {pair.section_heading}\n"
        f"   Evidence: {pair.evidence}\n"
        f"   Options:\n{options}\n     - NONE\n"
    )


def render_prompt(batch: list[Pair], max_relations: int = MAX_RELATIONS) -> str:
    """The full text sent for one batch. Exposed so a test can read it."""
    items = "\n".join(render_pair(i + 1, pair) for i, pair in enumerate(batch))
    return f"{_instructions(max_relations)}\n--- ITEMS ---\n\n{items}"


class RelationClassifier:
    """Runs stage B over pairs. Never raises: a bad batch yields non-answers.

    `classify` returns a LIST of decisions per pair -- see correction B in the
    module docstring. A decline is `[Decision(rel_type=NONE_RELATION)]` and a
    non-answer is `[Decision(rel_type=NO_ANSWER)]`, both single-element: a
    decline is a decision the model made and must stay countable as one, so it
    is never represented by an empty list.

    Counters are read after `classify` and belong in any report of its output.
    The three ways a pair can end up without an answer are counted APART,
    because they mean three different things and only one of them is a defect
    in the run:

    - `call_failures` -- the API call for the batch failed. A run problem.
    - `unanswered` -- the call succeeded but skipped this item's number, or gave
      it nothing usable to read. A model problem.
    - `unusable` -- every relation the model named for this pair was off its
      offered list, so nothing survived. Not a run defect.

    `failures` is their sum, and is what a report must place next to the decline
    rate -- both look like "no edge" in the output, and conflating them would
    let a broken run advertise a precision mechanism it does not have.

    Two counters describe individual RELATIONS rather than pairs, and must not
    be added to the three above:

    - `off_vocabulary` -- relation strings rejected because they were not on the
      item's list. NOT a defect: it is the type constraint biting, and its size
      is evidence for how much work the constraint does. A pair can lose one
      relation this way and still keep another.
    - `capped` -- pairs where the model named MORE relations than the cap
      allowed. This is the number that says whether the cap or the evidence is
      deciding how many relations a pair carries.

    - `self_loops` -- pairs whose two endpoints are the same entity. Declined
      without a call, and apart from `no_legal_relation`: one is a fact about
      the names, the other about the type table.
    - `no_legal_relation` -- pairs the ontology admits nothing for, in either
      direction. Answered `NONE` without a call, and counted separately because
      they are a decision of the TABLE, not of the model.
    - `calls` / `input_tokens` / `output_tokens` -- what the run cost.
    """

    def __init__(
        self,
        client: AsyncOpenAI | None = None,
        model: str | None = None,
        concurrency: int = 8,
        temperature: float = 0.0,
        seed: int = EXTRACTION_SEED,
        batch_size: int = BATCH_SIZE,
        max_relations: int = MAX_RELATIONS,
    ):
        self.client = client or AsyncOpenAI(api_key=settings.openai_api_key)
        self.model = model or EXTRACTION_MODEL
        self.temperature = temperature
        self.seed = seed
        self.batch_size = batch_size
        self.max_relations = max_relations
        self._semaphore = asyncio.Semaphore(concurrency)
        self.calls = 0
        self.call_failures = 0
        self.unanswered = 0
        self.unusable = 0
        self.off_vocabulary = 0
        self.capped = 0
        self.self_loops = 0
        self.no_legal_relation = 0
        self.input_tokens = 0
        self.output_tokens = 0

    @property
    def failures(self) -> int:
        """Every PAIR that got no usable answer, however it got there."""
        return self.call_failures + self.unanswered + self.unusable

    async def classify(self, pairs: list[Pair]) -> list[list[Decision]]:
        """The decisions for each pair, in the order the pairs were given."""
        decisions: list[list[Decision] | None] = [None] * len(pairs)

        askable: list[tuple[int, Pair]] = []
        for index, pair in enumerate(pairs):
            # Two reasons a pair is never asked, kept apart because they are
            # different facts: the names are the same entity, or no type admits
            # any relation between them in either direction. Either way there is
            # nothing to offer, so there is nothing to ask.
            if is_self_pair(pair):
                self.self_loops += 1
                decisions[index] = [Decision("", "", NONE_RELATION, "")]
            elif not offered_options(pair):
                self.no_legal_relation += 1
                decisions[index] = [Decision("", "", NONE_RELATION, "")]
            else:
                askable.append((index, pair))

        batches = [
            askable[start : start + self.batch_size]
            for start in range(0, len(askable), self.batch_size)
        ]
        results = await asyncio.gather(
            *(self._classify_batch([pair for _, pair in batch]) for batch in batches),
            return_exceptions=True,
        )

        for batch, result in zip(batches, results, strict=True):
            if isinstance(result, BaseException):
                # `_classify_batch` already swallows its own errors, so reaching
                # here means the task itself died. Charge every pair in it.
                logger.warning("classification task failed: %s", result)
                self.call_failures += len(batch)
                result = [[Decision("", "", NO_ANSWER, "")] for _ in batch]
            for (index, _), decision in zip(batch, result, strict=True):
                decisions[index] = decision

        # Every slot is filled by construction. This guards a PROGRAMMING error
        # (a future edit dropping a batch), not a run failure -- the "never
        # raises" rule is about the API, and returning a short or None-holed
        # list would misalign every decision after the gap with a different
        # edge, which is the one failure mode that would corrupt the
        # measurement silently.
        if any(decision is None for decision in decisions):
            raise RuntimeError("a pair was left undecided: batch/pair alignment is broken")
        return [decision for decision in decisions if decision is not None]

    async def _classify_batch(self, batch: list[Pair]) -> list[list[Decision]]:
        try:
            async with self._semaphore:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {
                            "role": "user",
                            "content": render_prompt(batch, self.max_relations),
                        }
                    ],
                    response_format={"type": "json_object"},
                    temperature=self.temperature,
                    seed=self.seed,
                )
            self.calls += 1
            usage = getattr(response, "usage", None)
            self.input_tokens += int(getattr(usage, "prompt_tokens", 0) or 0)
            self.output_tokens += int(getattr(usage, "completion_tokens", 0) or 0)
            payload = json.loads(response.choices[0].message.content or "{}")
        except Exception as exc:  # one batch must not abort a chapter
            logger.warning("classification failed for %d pairs: %s", len(batch), exc)
            self.call_failures += len(batch)
            return [[Decision("", "", NO_ANSWER, "")] for _ in batch]

        return self._parse(payload, batch)

    def _parse(self, payload: dict, batch: list[Pair]) -> list[list[Decision]]:
        """Answers keyed by their number, so one bad item cannot shift the rest.

        Reading the answer list positionally would make a batch that answered 7
        of 10 items silently mis-assign three decisions to the wrong pairs --
        a corruption that looks exactly like a low agreement rate.
        """
        by_number: dict[int, dict] = {}
        raw = payload.get("answers")
        for answer in raw if isinstance(raw, list) else []:
            if not isinstance(answer, dict):
                continue
            try:
                number = int(answer.get("n"))
            except (TypeError, ValueError):
                continue
            # First answer for a number wins; a duplicate is not a second vote.
            by_number.setdefault(number, answer)

        return [
            self._decide(by_number.get(position), pair)
            for position, pair in enumerate(batch, start=1)
        ]

    def _decide(self, answer: dict | None, pair: Pair) -> list[Decision]:
        if answer is None:
            logger.warning("no answer for %s / %s", pair.a_name, pair.b_name)
            self.unanswered += 1
            return [Decision("", "", NO_ANSWER, "")]

        raw = answer.get("relations")
        if not isinstance(raw, list):
            logger.warning(
                "relations for %s / %s is %s, not a list",
                pair.a_name, pair.b_name, type(raw).__name__,
            )
            self.unanswered += 1
            return [Decision("", "", NO_ANSWER, "")]

        confidence = str(answer.get("confidence", "") or "").strip().lower()
        chosen = [_fold_option(entry) for entry in raw if isinstance(entry, str)]
        declined = NONE_RELATION.casefold() in chosen
        wanted = [entry for entry in chosen if entry and entry != NONE_RELATION.casefold()]

        # An empty list is a decline, not a malformation: "I chose nothing" is
        # unambiguous in meaning even though the prompt asks for ["NONE"].
        # Counting it as a failure would understate the decline rate, which is
        # the number this experiment turns on.
        if not wanted:
            return [Decision("", "", NONE_RELATION, confidence)]

        # NONE alongside real relations is a contradiction. The relations are
        # taken and the NONE ignored: the model named something specific, and
        # reading that as a decline would discard a positive answer it gave.
        if declined:
            logger.warning(
                "NONE alongside %d relation(s) for %s / %s -- taking the relations",
                len(wanted), pair.a_name, pair.b_name,
            )

        # Matched EXACTLY against the strings this item offered, so a relation
        # naming an entity that was not in the item, or a type that was not on
        # its list, cannot be accepted and is never recorded as a decline.
        by_option = {
            _fold_option(render_option(source, target, rel)): (source, target, rel)
            for source, target, rel in offered_options(pair)
        }
        decisions: list[Decision] = []
        seen: set[str] = set()
        for entry in wanted:
            option = by_option.get(entry)
            if option is None:
                logger.warning(
                    "relation %r for %s / %s names no offered option",
                    entry, pair.a_name, pair.b_name,
                )
                self.off_vocabulary += 1
                continue
            if entry in seen:  # the same relation twice is one relation
                continue
            seen.add(entry)
            source, target, rel = option
            decisions.append(Decision(source, target, rel.value, confidence))

        if not decisions:
            # Everything named was off the list. Distinct from a decline: the
            # model asserted relations, they were all refused, and nothing it
            # said survives to be counted either way.
            self.unusable += 1
            return [Decision("", "", NO_ANSWER, "")]

        if len(decisions) > self.max_relations:
            # Recorded, then truncated. The count is the evidence for whether
            # the cap or the evidence is deciding how many relations a pair
            # carries -- if it is large, the cap is doing the work.
            self.capped += 1
            logger.warning(
                "%d relations for %s / %s, capped to %d",
                len(decisions), pair.a_name, pair.b_name, self.max_relations,
            )
            decisions = decisions[: self.max_relations]
        return decisions
