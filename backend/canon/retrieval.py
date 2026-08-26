"""Question in, grounded canon out. No model anywhere in the path.

`CanonLookup` answers three questions about a NAME the caller already has.
This answers a question in a DM's own words, which needs one thing the lookup
does not: finding the names inside it. That step -- and only that step -- is
what this module adds. Everything downstream is the lookup's queries.

WHY NO EMBEDDINGS. A similarity score cannot be argued with. When a graph-native
retrieval misses, the miss points at a specific missing thing -- an alias that
was never recorded, a section the scan skipped, an edge nobody wrote -- and that
is a repairable defect. A vector miss points at a number.

*Corrected 2026-08-18.* This paragraph used to continue "the graph's mentions
and aliases already encode what a text index would have to guess, and at 36
sections there is nothing for an index to do that a scan cannot". At 835
sections that is measurably false. Over the 46-question set the BM25 index alone
retrieves the right section 78% of the time against the graph path's 67%, and
seven of the nine questions the graph anchored and then missed were sitting in
the index. The argument against embeddings survives -- a keyword hit can still
be read back to the words that caused it -- but the claim that the graph makes a
text index redundant did not, and `TEXT_SLOTS` is what was done about it.

WHY NO ANSWER GENERATION. Retrieval returns passages; it never writes prose. A
model asked to answer will paper over a retrieval hole with something plausible,
and the entire point of this module is to make the holes countable. Generation
belongs to whatever calls this, after the numbers say retrieval works.

THE MATCHER IS THE SCAN'S MATCHER. `spine.mention_pattern` finds names in a
question exactly as it finds them in a section -- whole-word, apostrophe-folded.
Writing a second "find a name in some text" here would be the same mistake as a
second definition of "the same sentence", which `passage.py` exists to prevent.

The one rule that differs is case, and it differs because the TEXT differs. The
scan's single-word case rule reads a capital as evidence of a proper noun, which
is true of prose and false of a typed question. So retrieval runs the scan's
rule first and falls back to a case-folded pass ONLY when the first finds
nothing at all -- and marks the result `loose` when it does, so a weaker match
is never invisible. Measured: the fallback is what rescues "the trapdoor in the
church", while a question that names anything properly never reaches it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace

from backend.campaign.chain import adjacent_homebrew
from backend.campaign.model import is_campaign_id
from backend.canon.aliases import normalize
from backend.canon.lookup import (
    CANON_PLANE,
    EDGES,
    MENTIONS,
    rung_of,
    split_by_status,
    type_labels,
)
from backend.canon.passage import derive_passage, derive_section
from backend.canon.questions import content_terms, lucene_query, terms_present
from backend.canon.spine import mention_pattern

#: Every recorded surface form in the plane, longest first. Length ordering is
#: what makes "Ireena Kolyana" win over "Ireena" in a question containing both:
#: the longer form is the more specific claim, and a question that spells a name
#: out in full should not resolve as though it had not.
#: The entity id travels with the form because `anchorable_forms` decides per
#: ENTITY: a thing the book writes as a common noun is not a name under any of
#: its spellings, so one lower-case alias disqualifies all of them.
ALL_ALIASES = """
MATCH (a:Alias)-[:ALIAS_OF]->(e:Entity)
WHERE (e.plane = $plane AND ($book IS NULL OR e.id STARTS WITH $book))
   OR ($campaign_prefix IS NOT NULL AND e.id STARTS WITH $campaign_prefix)
RETURN DISTINCT a.name AS name, e.id AS entity_id
"""

#: Which entities a surface form names. Several is a legitimate answer --
#: `Barovia` is a region and a village -- and the ambiguity travels rather than
#: being resolved by a coin flip.
BY_ALIAS = """
MATCH (a:Alias)-[:ALIAS_OF]->(e:Entity)
WHERE a.normalized = $normalized
  AND ((e.plane = $plane AND ($book IS NULL OR e.id STARTS WITH $book))
       OR ($campaign_prefix IS NOT NULL AND e.id STARTS WITH $campaign_prefix))
RETURN DISTINCT e.id AS id, e.name AS name, labels(e) AS labels, e.status AS node_status
ORDER BY e.id
"""

#: The prose fallback, over the full-text index `GRAPH_SCHEMA` declares. Reached
#: ONLY when nothing in the question resolves to an entity.
#:
#: `db.index.fulltext.queryNodes` returns a Lucene score, and that score is
#: deliberately not merged into the graph path's ranking. A name resolved
#: through `:Alias` is a fact about the book; a score is a guess about a
#: question. Blending them produces one ordering in which nobody can tell which
#: answered, and this project's whole method is being able to tell.
SEARCH_SECTIONS = """
CALL db.index.fulltext.queryNodes('section_text', $query) YIELD node AS s, score
MATCH (:Book {slug:$book_slug})-[:HAS_CHAPTER]->(c:Chapter {plane:$plane})-[:HAS_SECTION]->(s)
RETURN s.id AS section_id, s.heading AS section, s.index AS section_index,
       s.text AS text, c.slug AS chapter, c.index AS chapter_index, score
ORDER BY score DESC
LIMIT $limit
"""

#: The campaign's own sections, searched separately and NEVER merged into the
#: canon ranking. Two orderings in different units are not comparable, so they
#: are concatenated and labelled -- `combine_passages`' rule, applied to a third
#: source. Scoped through the Campaign container, which is also why the canon
#: search above cannot reach these: it matches through the BOOK spine.
SEARCH_CAMPAIGN_SECTIONS = """
CALL db.index.fulltext.queryNodes('section_text', $query) YIELD node AS s, score
MATCH (:Campaign {slug:$campaign})-[:HAS_SECTION]->(s)
RETURN s.id AS section_id, s.heading AS section, s.index AS section_index,
       s.text AS text, score
ORDER BY score DESC
LIMIT $limit
"""

#: What the DM chained immediately around a retrieved canon section.
#:
#: THE RIDE-ALONG, AND WHY IT IS A WALK RATHER THAN A SEARCH. A scene inserted
#: into the voyage may share no vocabulary at all with "what happens on the way
#: to the prison" -- so no Lucene score and no occurrence count can find it. Its
#: relevance is POSITIONAL, and the chain records that position as something the
#: DM asserted. Both directions, campaign sections only, stopping at the first
#: canon one: see `chain.adjacent_homebrew`, which decides the rule; this only
#: fetches the links it needs.
CHAIN_AROUND = """
MATCH (a:Section)-[r:NEXT {campaign:$campaign}]->(b:Section)
RETURN a.id AS source, b.id AS target
"""

#: The prose a campaign entity is described in, reached the way canon reaches
#: its own: through the mention triangle.
#:
#: A SEPARATE QUERY BECAUSE `MENTIONS` CANNOT DO IT, twice over. That one
#: filters `Entity {plane:'canon'}`, and it requires a `:Chapter` to hang the
#: section from -- a campaign section hangs off a `:Campaign`. So an anchored
#: campaign entity resolved by name and then returned NO PROSE: the DM could
#: say "tell me about Captain Saltmarrow", watch the name resolve, and get
#: nothing back about him. The ride-along hid this, because a scene chained
#: beside a retrieved canon section still arrived -- by position, never by name.
CAMPAIGN_MENTIONS = """
MATCH (e:Entity)<-[:REFERS_TO]-(m:Mention)-[:IN_SECTION]->(s:Section)
MATCH (:Campaign {slug:$campaign})-[:HAS_SECTION]->(s)
WHERE e.id IN $ids
RETURN DISTINCT s.id AS section_id, s.heading AS section, s.text AS text
"""

#: What the DM's own record says about an entity they made.
#:
#: NOT A PASSAGE, AND DELIBERATELY SO. A cluster element gets a node, a name
#: and a role, but the prose stored beside it is the SCENE's -- "Corsairs swarm
#: the deck at dawn" never says Captain Saltmarrow. So the passage arrived,
#: carried no mention of him, and a fresh session was told "the canon does not
#: cover any specific details about Captain Saltmarrow" about a character the
#: DM had invented an hour earlier. The node knew his kind, his role, what was
#: invented about him and which scene minted him, and none of it reached the
#: model.
CAMPAIGN_ENTITY_FACTS = """
MATCH (e:Entity {plane:'campaign', campaign:$campaign})
WHERE e.id IN $ids
OPTIONAL MATCH (e)<-[:REFERS_TO]-(:Mention)-[:IN_SECTION]->(s:Section)
RETURN e.id AS id, e.name AS name, e.kind AS kind, e.role AS role,
       e.invented AS invented, e.cluster AS cluster,
       collect(DISTINCT s.heading) AS described_in
"""

#: Sections this campaign has cut. Retrieved all the same -- the chain is the
#: running order, not the knowledge scope, and "what was in the bit I skipped"
#: is a real question -- but marked, so nothing reads as in play that is not.
CAMPAIGN_SKIPPED = """
MATCH (:Campaign {slug:$campaign})-[:SKIPPED]->(s:Section)
RETURN s.id AS id
"""

#: The entities a set of sections names. What the text path anchors on, having
#: no resolved name of its own.
#:
#: WITHOUT THIS, THE TEXT PATH THREW AWAY THE GRAPH. Asked "who owns the
#: tavern", it found section E2 -- exactly the right section -- and returned
#: prose alone, so the three `OWNS` edges a human had accepted about that very
#: room never reached the model, which then said the canon did not cover it.
#: Retrieving a section and ignoring what the graph knows about its occupants is
#: using the book as a text file.
#:
#: The fact/guess line is untouched: these edges keep their own status and are
#: rendered under the same two headings. What is a guess here is WHICH SECTIONS
#: to look at, and that was already labelled.
ENTITIES_IN_SECTIONS = """
MATCH (s:Section)<-[:IN_SECTION]-(:Mention)-[:REFERS_TO]->(e:Entity {plane:$plane})
WHERE s.id IN $section_ids
RETURN DISTINCT e.id AS id
"""

#: Retrieval returns at most this many passages unless told otherwise. A DM
#: reading an answer will not read twenty paragraphs, and an unbounded context
#: hides a ranking problem by making every miss a hit.
#:
#: RAISED FROM 5 TO 8 ON 2026-08-18, and it is a COST decision rather than a
#: tuned one. Recall rises with the budget and does not come back down --
#: 5 -> 35/46, 6 -> 35, 8 -> 38, 10 -> 38, 12 -> 40 -- so there is no peak to
#: find, only a point to stop at. 8 is where the curve has given up most of
#: what it has for about 1,700 tokens of context instead of 1,050.
#:
#: What it buys is coverage, NOT precision. MRR is 0.57 at every budget in that
#: sweep, so this is showing a DM more passages rather than putting the right
#: one higher, and every extra passage is also another distractor for a model
#: answering from them. Six of the misses it fixes were already sitting in the
#: text index's top 20; the graph path reaches none of them at any depth.
DEFAULT_LIMIT = 8

#: How much of a section a passage carries.
WIDTH_SENTENCE = "sentence"
WIDTH_SECTION = "section"

#: A whole-section passage is cut here. The corpus's largest section is 4,621
#: characters and its median 842, so this bounds the worst case without touching
#: the typical one. Truncation is reported on the passage, never silent.
SECTION_MAX = 4000

#: How a retrieval was answered. Carried on the result and reported by the
#: evaluation harness, because a text hit and a graph hit are not the same
#: quality of answer and an aggregate recall that hides which is which would
#: make the fallback look like an improvement to the graph.
PATH_GRAPH = "graph"
PATH_TEXT = "text"
PATH_NONE = ""

#: What one matched question word is worth against one naming of an anchor, when
#: ranking the graph path's candidate sections.
#:
#: CHOSEN FROM A PLATEAU, NOT FITTED TO A PEAK. Swept over the 24-question set:
#:
#:     weight   0     1     2     3     4     5     8    12    20   terms-only
#:     MRR     .690  .784  .787  .801  .801  .796  .796  .769  .759   .664
#:     hits   16/18 17/18 17/18 17/18 17/18 17/18 17/18 17/18 17/18  17/18
#:
#: Everything from 1 to 8 lands within .02 of the best, so what matters is that
#: the term signal is PRESENT, not what it is multiplied by -- and a constant
#: that only works at one value would be a number fitted to eighteen questions.
#: 3 is the middle of the flat region. `terms-only` is worse than either signal
#: combined, which is why occurrences are not simply replaced.
TERM_WEIGHT = 3

#: Added to a section's score when it sits in a chapter one of the anchors
#: BELONGS to, rather than merely a chapter that mentions it.
#:
#: WHY AN ANTHOLOGY NEEDS THIS AND A CAMPAIGN DOES NOT. A book-wide name in
#: thirteen unconnected adventures retrieves one near-identical section from
#: each: asked what the Golden Vault wants stolen in Fire and Darkness,
#: retrieval spent seven of eight slots on other heists' `Using the Golden
#: Vault` sections. The anchors themselves say which chapter the question is
#: about -- `kftgv:fire-and-darkness:...` names its own chapter in its id --
#: and nothing was reading it.
#:
#: A BONUS, NOT A GATE. It moves a section up; it never removes one and never
#: makes a candidate, so the fact/guess line holds here as it does for terms.
#:
#: THE VALUE IS MEASURED, AND THE RULE WAS CONFIRMED ON QUESTIONS IT WAS NOT
#: DERIVED FROM. Derived from one failing question, it fixed exactly that
#: question -- which is a hypothesis agreeing with its own training example and
#: worth nothing. Six more questions of the same shape were then written from
#: the chapter text, blind to the outcome; four of them failed with the rule
#: off and two of those four passed with it on. Over 34 Golden Vault questions:
#:
#:     weight   0    71% recall, MRR 0.43
#:     weight   3    79% recall, MRR 0.46
#:     weight   4    79% recall, MRR 0.47   <- plateau begins
#:     weight 6-8    79% recall, MRR 0.47
#:
#: Curse of Strahd is IDENTICAL at every weight -- 85% / 90% / MRR 0.61, the
#: same six misses. A campaign's anchors mostly live in the chapter that
#: answers, so the bonus applies uniformly there and reorders nothing. That is
#: the evidence this is an anthology repair and not a tuning knob.
#:
#: The plateau matters as much as the peak: anything from 4 upward behaves the
#: same, so this is not a number fitted to a sample.
CHAPTER_WEIGHT = 4

#: How many of the budget's passages are held for the text path when a question
#: DID anchor. The rest go to the graph, and any slack the graph does not use
#: goes to text as well.
#:
#: THE FALLBACK USED TO BE ALL-OR-NOTHING, and that was the single largest
#: defect in retrieval. Text ran only when NOTHING anchored, so a question that
#: anchored on the WRONG thing was dead: `coffin` resolved to an extracted prop
#: in Castle Ravenloft, and "who is lying in the coffin in the burgomaster's
#: mansion" went to the tombs. Forced onto the text path, seven of the nine
#: anchored-but-missed questions hit, two of them at rank 1.
#:
#: Swept over the 46-question set at limit 5. `reserve 0` is padding alone --
#: text fills only slots the graph left empty, so it displaces nothing and
#: cannot cost a hit:
#:
#:     reserve      0     1     2     3     4     5   graph only
#:     hits/46     33    35    34    35    35    36    31
#:     recall     72%   76%   74%   76%   76%   78%   67%
#:
#: 1 is chosen over the larger reserves because they buy nothing beyond it
#: while evicting more of the path that resolved a name. It was left at 1 when
#: `DEFAULT_LIMIT` rose to 8, where the whole range from 1 to 7 scores 38 or 39
#: of 46 -- one question wide. Moving it to the 39 would be fitting a constant
#: to noise, the mistake `TERM_WEIGHT` documents avoiding. Once the budget is
#: this wide the split stops mattering; the budget is doing the work.
#:
#: The last column is why
#: this constant exists at all; the 5 column is reported because it is
#: uncomfortable and hiding it would be dishonest -- BM25 alone outscores the
#: graph path on SECTION RECALL, which is the only thing this set measures. It
#: does not measure the edges, and the edges are what made the agent right
#: about the tavern's three owners where prose alone said canon did not cover it.
TEXT_SLOTS = 1


@dataclass(frozen=True)
class Anchor:
    """One entity a question named, and the spelling it used to name it."""

    entity_id: str
    name: str
    labels: tuple[str, ...]
    rung: str | None
    surface: str
    node_status: str | None = None


@dataclass(frozen=True)
class Passage:
    """One section a DM would read, and the sentence that anchors it."""

    section_id: str
    chapter: str
    chapter_index: int
    section: str
    section_index: int
    text: str
    occurrences: int
    entity_ids: tuple[str, ...]
    aliases: tuple[str, ...] = ()
    #: How many of the question's non-name words this section contains. The
    #: other half of the ranking, carried so a surprising order can be read
    #: rather than guessed at.
    term_hits: int = 0
    #: True when a whole-section passage hit `SECTION_MAX` and lost its tail.
    truncated: bool = False
    #: `canon` or `campaign`. The DM must be able to tell at a glance whose
    #: word a line is, and `sources()` hardcoded `"canon"` on every citation
    #: for as long as there was only one answer.
    origin: str = "canon"
    #: `in-chain`, `skipped`, or `` when no campaign is selected. Says whether
    #: this is in play at this table; never used to rank, only to label.
    chain_status: str = ""
    #: True when this section is in a chapter one of the anchors belongs to.
    #: Travels so a surprising order can be read rather than guessed at, the
    #: same reason `term_hits` does.
    home_chapter: bool = False
    #: Set on a passage that came along because of WHERE it sits, naming the
    #: section it rode with. Positional relevance is not lexical, so a reader
    #: seeing it among scored passages needs to know it was not scored.
    rode_with: str = ""
    #: Lucene's score, on a text-path passage only. `None` on a graph passage,
    #: and deliberately not defaulted to 0.0: a name match has no score, and a
    #: zero would read as "scored, badly".
    #:
    #: Carried because the text path CANNOT SAY IT DOES NOT KNOW. Any question
    #: sharing one word with any section returns that section -- "what is the
    #: capital of France?" returns the foreword, which discusses Byron in
    #: Switzerland. The score is the only signal a caller has that an answer is
    #: thin, so it travels rather than being consumed here.
    score: float | None = None
    #: Which path put THIS passage in front of the reader. One result now mixes
    #: both, so the label belongs on the passage rather than only on the
    #: `Retrieval`: a section that resolved a name is a fact about the book, a
    #: section Lucene scored is a guess about the question, and the two now sit
    #: side by side in one list.
    #:
    #: Defaulted rather than required so the callers and fixtures that build a
    #: graph passage by hand keep working. `_text_passages` sets it explicitly,
    #: and a test pins that every text passage carries the label.
    path: str = PATH_GRAPH


@dataclass(frozen=True)
class Retrieval:
    """What a question retrieved, and what it did not."""

    question: str
    anchors: tuple[Anchor, ...] = ()
    passages: tuple[Passage, ...] = ()
    accepted: tuple[dict, ...] = ()
    proposed: tuple[dict, ...] = ()
    #: Passages the budget cut. Counted rather than discarded: this project has
    #: twice had a defect hide for weeks behind a silent filter.
    dropped: int = 0
    miss_reason: str = ""
    ambiguous: tuple[str, ...] = field(default_factory=tuple)
    #: True when nothing matched under the scan's own case rule and the
    #: case-folded fallback was what anchored the question. Surfaced rather
    #: than swallowed: a fallback nobody can observe becomes the default.
    loose: bool = False
    #: How the QUESTION was answered: `graph` (a name resolved), `text` (nothing
    #: did and the prose was searched instead), or empty (nothing answered).
    #: Never inferred from whether `anchors` is empty -- a caller reading a text
    #: answer must be able to see that it is one.
    #:
    #: This is now the coarser of two labels. A `graph` result still contains
    #: text passages, because `TEXT_SLOTS` reserves room for them; which one put
    #: any PARTICULAR passage in front of the reader is `Passage.path`. Reading
    #: this field as "every passage below resolved a name" was true before that
    #: reservation existed and is not true now.
    path: str = PATH_NONE
    #: The terms the text fallback searched on, so a bad text answer can be read
    #: back to the question that produced it.
    terms: tuple[str, ...] = field(default_factory=tuple)
    #: True when the question resolved NOTHING and the anchors came from the
    #: conversation's own subjects instead. Surfaced rather than swallowed, for
    #: the same reason `loose` is: an answer that leant on what was said three
    #: turns ago is a different kind of answer, and a reader must be able to
    #: see which they got.
    carried: bool = False
    #: The DM's own record for campaign entities this question named: kind,
    #: role, what was invented, and where they were introduced. Carried apart
    #: from `passages` because it is not prose -- it is what the graph holds
    #: about a thing the DM made, which for a freshly minted element is
    #: everything there is.
    campaign_entities: tuple[dict, ...] = ()
    #: The display name of the book this came from, so a caller rendering a
    #: prompt does not have to know one. Two model-facing strings said "Curse
    #: of Strahd" unconditionally and went on saying it after a second book was
    #: loaded -- the same stale-constant defect as the chapter count, but told
    #: to the MODEL, where nobody could see it.
    book_title: str = ""

    @property
    def found(self) -> bool:
        return bool(self.passages)

    @property
    def section_ids(self) -> tuple[str, ...]:
        return tuple(p.section_id for p in self.passages)


def dedupe_edges(rows: list[dict]) -> list[dict]:
    """One row per edge, whichever endpoints were asked about.

    `EDGES` deliberately reads both directions, because half of what a DM wants
    about an NPC is written with the NPC as the TARGET. When only ONE endpoint
    is an anchor that yields one row per edge. When BOTH are -- which is now the
    normal case, since the text path anchors on every entity a section names --
    it yields two, and the rendered block showed six lines for the tavern's
    three owners.

    Deduplicated on the edge as the graph stores it, so the surviving row keeps
    its own direction and `_edge_line` still writes the arrow the right way
    round. Order is preserved: the first row seen wins, and the query is already
    ordered.
    """
    seen: set[tuple[str, str, str]] = set()
    unique: list[dict] = []
    for row in rows:
        entity, other = row.get("entity"), row.get("other")
        if row.get("direction") == "in":
            entity, other = other, entity
        key = (str(entity), str(row.get("relationship")), str(other))
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def combine_passages(
    graph: list[Passage],
    text: list[Passage],
    limit: int,
    reserve: int = TEXT_SLOTS,
) -> list[Passage]:
    """One budget, split between the path that resolved a name and the one that
    scored the prose. Concatenation, never a blended score.

    The two orderings are NOT comparable -- `occurrences + 3*terms` and Lucene's
    BM25 are different units -- so nothing here adds, scales or normalises them
    against each other. Each list arrives already ranked by its own rule, and
    this function only decides how many slots each gets. That is what keeps
    `Passage.path` meaningful: a reader can still say which path is responsible
    for any line, which a merged score would destroy.

    `reserve` slots are held for text. The graph takes the rest AND any slack
    text does not use, so the two effects the sweep measured apart are one rule
    here:

      * a graph path returning FEWER than `limit - reserve` candidates is padded
        out of text, displacing nothing -- 11 of the 46 questions
      * a graph path with more candidates than budget gives `reserve` of them up

    Order is graph-first because a resolved name outranks a guess at equal
    standing; `reserve=0` degenerates to padding alone.

    A section reached by both paths appears ONCE, keeping whichever came first
    -- which, for anything inside the graph's kept prefix, is the graph's copy
    with its occurrence count and entity ids intact.

    THE RESERVATION NEVER TAKES THE GRAPH'S LAST SLOT. At `limit=1` the
    arithmetic gave the graph `1 - 1 = 0`, so a question that resolved a name
    got back a single Lucene guess and both of its real candidates counted as
    dropped. A guess may fill what a name left empty and may take the tail of a
    long list; it may not evict the name entirely.
    """
    if graph:
        reserve = min(reserve, limit - 1)
    kept = graph[: max(0, limit - reserve)]
    out: list[Passage] = list(kept)
    seen = {p.section_id for p in kept}
    for passage in [*text, *graph[max(0, limit - reserve) :]]:
        if len(out) >= limit:
            break
        if passage.section_id in seen:
            continue
        seen.add(passage.section_id)
        out.append(passage)
    return out


def is_common_noun(form: str) -> bool:
    """Is this surface form a thing-word rather than a name?

    One word, no capital, as the book itself spells it. `coffin`, `wagon`,
    `key`, `light`, `vampire`.

    THE BOUNDARY IS SINGLE-WORD, AND IT IS THE ONE THE MATCHER ALREADY DRAWS.
    `mention_pattern` folds case for a multi-word form and not for a single one,
    because a multi-word match is specific enough to trust on its own. The same
    holds here: of 103 all-lowercase forms in the plane, 53 are multi-word and
    nearly all are spell or magic-item names -- `dispel magic`, `potion of
    healing`, `staff of power` -- which D&D writes lower case by convention and
    which a question naming them really is about. Refusing those would break
    anchoring on half the treasure in the book. It is the single words that are
    thing-words.
    """
    stripped = form.strip()
    return bool(stripped) and " " not in stripped and not any(
        character.isupper() for character in stripped
    )


def anchorable_forms(rows: list[dict]) -> list[str]:
    """The surface forms that may anchor a QUESTION, entity by entity.

    The extractor minted a global entity for a great many generic props and
    creature types -- `cos:coffin`, `cos:wagon`, `cos:key`, `cos:light`,
    `cos:vampire` -- and each carries an `:Alias` spelled the way the book
    writes it, in lower case. Fifty of them, and they anchored real questions:
    "who is lying in the coffin in the burgomaster's mansion" resolved `coffin`
    to a prop in Castle Ravenloft and went to the tombs; "which book records the
    vampire's own account of himself" anchored on `vampire` and missed.

    THE SCAN'S CASE RULE GIVES NO PROTECTION HERE. `mention_pattern` matches a
    single-word form case-sensitively, reading a capital as evidence of a proper
    noun -- that is what keeps the LORE entity `Light` off every lit torch. But
    an alias spelled `light` is already lower case, so the case-sensitive
    pattern matches the lower-case word in a question exactly. The rule guards
    against the wrong spelling of the problem.

    THE REFUSAL IS PER ENTITY, NOT PER FORM, and that is the whole reason this
    function groups. Dropping just the lower-case spelling was tried first and
    moved the defect rather than fixing it: with `wagon` gone nothing else
    matched, so `find_names` reached its case-folded second pass and matched the
    entity's OTHER alias, `Wagon`, against the same word. The anchor came back
    under a different spelling. An entity the book writes as a common noun is
    not a name under any casing, so the evidence disqualifies the entity.

    NOT A DELETION. The entity keeps its mentions, its edges, and its place in
    the scan; what it loses is being the handle a DM's question resolves
    through. A prop named in a section is a fact about that section. It was
    never a name.
    """
    by_entity: dict[str, list[str]] = {}
    for row in rows:
        by_entity.setdefault(row["entity_id"], []).append(row["name"])
    return sorted(
        {
            form
            for names in by_entity.values()
            if not any(is_common_noun(name) for name in names)
            for form in names
        }
    )


def find_names(question: str, forms: list[str], *, fold_case: bool = False) -> list[str]:
    """Every recorded form the question contains, longest first, non-overlapping.

    Non-overlapping is the load-bearing word. A question naming `Ireena Kolyana`
    contains `Ireena` too, and returning both would anchor twice on one entity
    and let a single name outvote everything else in the ranking. Longest match
    wins and consumes its span.

    Ordering by length here is what makes that greedy pass correct; the caller
    is not required to sort.
    """
    spans: list[tuple[int, int]] = []
    found: list[str] = []
    for form in sorted(forms, key=lambda f: (-len(f), f)):
        pattern = mention_pattern(form, fold_case=fold_case)
        if pattern is None:
            continue
        for match in pattern.finditer(question):
            start, end = match.span()
            if any(start < taken_end and taken_start < end for taken_start, taken_end in spans):
                continue
            spans.append((start, end))
            found.append(form)
            break  # one anchor per form; a question repeating a name means it once
    return found


class CanonRetriever:
    """Retrieve grounded canon for a question. Read-only, deterministic."""

    def __init__(
        self,
        limit: int = DEFAULT_LIMIT,
        passage_width: str = WIDTH_SECTION,
        book: str = "cos",
        campaign: str | None = None,
    ) -> None:
        """`book` is the ONE book this retriever reads.

        A second book in the graph made every query book-blind. Lucene ranges
        over the whole `section_text` index and the plane filter passes both,
        so a Barovia question came back with `Blood War Balance` and
        `Motherlode Tavern` -- 45 of 96 evaluation questions took at least one
        passage from the wrong book, 12% of all passage slots, and MRR fell
        from 0.61 to 0.56.

        A session reads one book, the way a table runs one adventure. Nothing
        blends them, and a question that would be answered by another book
        gets nothing rather than something plausible from the wrong world.
        """
        self.limit = limit
        self.passage_width = passage_width
        self.book = book
        self.campaign = campaign
        self._title: str | None = None

    def retrieve(
        self,
        question: str,
        *,
        limit: int | None = None,
        carry: Sequence[str] = (),
    ) -> Retrieval:
        """Canon for a question, plus this table's own material when it has any.

        A THIN WRAPPER so the title is attached in ONE place. `_retrieve` has
        four `return Retrieval(...)` sites and stamping each was four chances
        to forget -- the shape of defect this module already carries scars for.
        The campaign overlay hangs here for the same reason.

        WITH NO CAMPAIGN NOTHING BELOW RUNS. `campaign` is None by default and
        both evaluation harnesses build retrievers without one, so the 96
        questions cannot see a DM's material no matter what is in the graph --
        by construction, not by discipline.
        """
        found = replace(
            self._retrieve(question, limit=limit, carry=carry),
            book_title=self.title,
        )
        if not self.campaign:
            return found
        return self._with_campaign(found)

    def _with_campaign(self, found: Retrieval) -> Retrieval:
        """Label what came back, and bring along what the DM chained beside it.

        CONCATENATED, NEVER BLENDED. Canon keeps its own order and its own
        ranking; campaign passages follow, each labelled with why it is here.
        Three orderings -- graph occurrences, Lucene score, chain position --
        stay three, so a reader can always say which one is responsible for any
        line. Merging them into one number is the one thing this module has
        refused everywhere else.
        """
        with self._session() as session:
            links = frozenset(
                (row["source"], row["target"])
                for row in self._rows(session, CHAIN_AROUND)
            )
            skipped = {row["id"] for row in self._rows(session, CAMPAIGN_SKIPPED)}

        by_id = {p.section_id: p for p in found.passages}
        labelled: list[Passage] = []
        # A campaign entity the QUESTION named brings its own prose, before any
        # positional ride-along. Resolving a name and returning nothing about
        # it is the worse half of a miss: it looks like the graph knows the
        # thing and has nothing to say.
        named: list[Passage] = []
        # EVERY ANCHOR, CANON OR CAMPAIGN. A canon entity can appear in a
        # campaign scene -- that is exactly what choosing "use the book's"
        # records -- so asking about the book's Marta Marthannis has to surface
        # the scene the DM put her in. Filtering to `hb:` ids here made the
        # link decision unanswerable and so pointless.
        anchor_ids = [a.entity_id for a in found.anchors]
        campaign_ids = [a for a in anchor_ids if is_campaign_id(a)]
        if anchor_ids:
            with self._session() as session:
                for row in self._rows(session, CAMPAIGN_MENTIONS, {"ids": anchor_ids}):
                    if row["section_id"] not in by_id:
                        named.append(
                            Passage(
                                section_id=row["section_id"],
                                chapter=self.campaign or "",
                                chapter_index=0,
                                section=row["section"] or "",
                                section_index=0,
                                text=row["text"] or "",
                                occurrences=1,
                                entity_ids=(),
                                origin="campaign",
                                chain_status="in-chain",
                            )
                        )
                        by_id[row["section_id"]] = named[-1]
        riders: list[Passage] = []
        cut = 0
        for passage in found.passages:
            status = "skipped" if passage.section_id in skipped else "in-chain"
            labelled.append(
                replace(
                    passage,
                    origin="campaign" if is_campaign_id(passage.section_id) else "canon",
                    chain_status=status,
                )
            )
            before, after, dropped = adjacent_homebrew(links, passage.section_id)
            cut += dropped
            for section_id in before + after:
                if section_id in by_id or any(r.section_id == section_id for r in riders):
                    # Already retrieved on its own merits. Deduplicated by
                    # section id, `combine_passages`-style: the same passage
                    # twice is noise, and the scored copy is the better one.
                    continue
                rider = self._campaign_passage(section_id)
                if rider is not None:
                    riders.append(replace(rider, rode_with=passage.section_id))

        facts: list[dict] = []
        if campaign_ids:
            with self._session() as session:
                facts = self._rows(
                    session, CAMPAIGN_ENTITY_FACTS, {"ids": campaign_ids}
                )

        return replace(
            found,
            passages=tuple(labelled + named + riders),
            campaign_entities=tuple(facts),
            dropped=found.dropped + cut,
        )

    def _campaign_passage(self, section_id: str) -> Passage | None:
        """One campaign section, as a passage. None when it has vanished."""
        with self._session() as session:
            rows = self._rows(
                session,
                """
                MATCH (s:Section {id:$id, plane:'campaign'})
                RETURN s.id AS section_id, s.heading AS section, s.text AS text
                """,
                {"id": section_id},
            )
        if not rows:
            return None
        row = rows[0]
        return Passage(
            section_id=row["section_id"],
            chapter=self.campaign or "",
            chapter_index=0,
            section=row["section"] or "",
            section_index=0,
            text=row["text"] or "",
            occurrences=0,
            entity_ids=(),
            origin="campaign",
            chain_status="in-chain",
        )

    @property
    def title(self) -> str:
        """This book's display name, read from the graph and remembered.

        Falls back to the slug rather than raising: a prompt that says `kftgv`
        is worse than one that says Keys from the Golden Vault and better than
        no answer at all.
        """
        if self._title is None:
            try:
                with self._session() as session:
                    row = session.run(
                        "MATCH (b:Book {slug:$slug}) RETURN b.display_name AS title",
                        {"slug": self.book},
                    ).single()
                self._title = (dict(row)["title"] if row else "") or self.book
            except Exception:  # noqa: BLE001 - a title is not worth failing a question for
                self._title = self.book
        return self._title

    def _retrieve(
        self,
        question: str,
        *,
        limit: int | None = None,
        carry: Sequence[str] = (),
    ) -> Retrieval:
        """Canon for a question, optionally anchored on what came before.

        `carry` is the entity ids a CONVERSATION is already about -- the
        subgraph's subjects. Used ONLY when the question resolves nothing on
        its own, so a question that names something is never overridden by
        what was said three turns ago.

        THE CONVERSATION HAD TO REACH RETRIEVAL, NOT JUST THE PROMPT. Asked
        "who owns the tavern" and then "give me a list of everyone in the pub",
        the second question anchors nothing -- `pub` is no alias -- so it
        searched Lucene for `give, list, everyone, pub` and read `Tyger,
        Tyger`, `Foreshadowing`, `K81. Tunnel` and `Crypt 10`. The subgraph
        told the MODEL the subject was the Blood of the Vine Tavern, and the
        model duly said the canon did not cover who was in it, holding eight
        sections about something else. The book's E2 section lists exactly who
        is in that room. Knowing the referent is no use without its prose.
        """
        limit = self.limit if limit is None else limit
        with self._session() as session:
            # Filtered here rather than in the query, because this is a rule
            # about what may anchor a QUESTION and not about what the graph
            # holds. A prop named in a section is still a fact about that
            # section, and the scan and the edges go on using it.
            forms = anchorable_forms(self._rows(session, ALL_ALIASES))
            # Two passes, and the order is the whole point. The first is the
            # scan's own rule, so a question that spells names the way the book
            # does resolves exactly as the graph was built. Only when that finds
            # NOTHING does the second pass drop the single-word case rule --
            # which is what rescues "the trapdoor in the church" while leaving
            # "who is Ismark, and what about the light?" anchored on Ismark
            # alone rather than dragging in the LORE entity `Light`.
            #
            # `loose` travels on the result so a consumer can see which answers
            # needed the weaker rule. A fallback nobody can observe is how a
            # loose match becomes the default without anyone deciding it should.
            named = find_names(question, forms)
            loose = False
            if not named:
                named = find_names(question, forms, fold_case=True)
                loose = bool(named)
            carried = False
            if not named and carry:
                # The conversation's own subjects, as ids rather than as
                # spellings: no matching to do, no pronoun rule, no guess. A
                # question that resolved a name never reaches this.
                anchors = self._anchors_by_id(session, carry)
                if anchors:
                    return self._from_anchors(
                        session, question, anchors, limit, carried=True
                    )
            if not named:
                return self._by_text(session, question, limit)

            anchors: list[Anchor] = []
            ambiguous: list[str] = []
            for surface in named:
                rows = self._rows(session, BY_ALIAS, {"normalized": normalize(surface)})
                if len(rows) > 1:
                    ambiguous.append(surface)
                for row in rows:
                    anchors.append(
                        Anchor(
                            entity_id=row["id"],
                            name=row["name"],
                            labels=tuple(type_labels(row["labels"])),
                            rung=rung_of(row["labels"]),
                            surface=surface,
                            node_status=row["node_status"],
                        )
                    )

            if not anchors:
                # A recorded spelling that names nothing is a broken graph, not
                # a descriptive question, so this does NOT fall through to text.
                # Papering over it would turn a repairable defect into a
                # slightly-worse answer nobody investigates.
                return Retrieval(
                    question=question,
                    miss_reason=(
                        f"{named!r} matched a recorded spelling but resolved to no entity"
                    ),
                    ambiguous=tuple(ambiguous),
                    loose=loose,
                )

            return self._from_anchors(
                session, question, anchors, limit,
                ambiguous=tuple(ambiguous), loose=loose,
            )

    # -- internals ---------------------------------------------------------

    def _anchors_by_id(self, session, ids: Sequence[str]) -> list[Anchor]:
        """Anchors for entity ids the conversation already holds.

        No matching, because there is nothing to match: the subgraph holds ids,
        not spellings. `surface` is the entity's own name, since no wording in
        THIS question produced it -- and that is what the panel shows, so a
        reader can see the anchor came from the conversation rather than from
        anything they just typed.
        """
        rows = self._rows(
            session,
            """
            MATCH (e:Entity {plane:$plane}) WHERE e.id IN $ids
            RETURN e.id AS id, e.name AS name, labels(e) AS labels,
                   e.status AS node_status
            ORDER BY e.id
            """,
            {"ids": list(ids)},
        )
        return [
            Anchor(
                entity_id=row["id"],
                name=row["name"],
                labels=tuple(type_labels(row["labels"])),
                rung=rung_of(row["labels"]),
                surface=row["name"],
                node_status=row["node_status"],
            )
            for row in rows
        ]

    def _from_anchors(
        self,
        session,
        question: str,
        anchors: list[Anchor],
        limit: int,
        *,
        ambiguous: tuple[str, ...] = (),
        loose: bool = False,
        carried: bool = False,
    ) -> Retrieval:
        """Everything downstream of having anchors, whatever produced them.

        Shared by the two ways a question gets them -- resolving a name in the
        question, or inheriting the conversation's subjects -- so the ranking,
        the text reservation and the edge rules cannot differ between them.
        """
        ids = sorted({a.entity_id for a in anchors})
        # The question's words MINUS the anchors' own. A question naming
        # Strahd already counts him through his occurrences; letting
        # `strahd` score again as a content word would count one signal
        # twice and re-favour exactly the broad sections this is meant to
        # demote.
        anchor_words = {word for a in anchors for word in a.surface.lower().split()}
        terms = [t for t in content_terms(question) if t not in anchor_words]
        passages = self._passages(session, ids, terms)

        # The text path runs even though a name resolved, and this is the
        # change that matters most. Anchoring is not the same as anchoring
        # WELL: `coffin` resolves to an extracted prop in Castle Ravenloft,
        # and while text ran only on a total anchoring failure, "who is
        # lying in the coffin in the burgomaster's mansion" had no way back.
        #
        # Searched on the question's OWN terms -- `content_terms(question)`,
        # not `terms` -- because the anchor words are removed only to stop
        # one signal being counted twice inside the graph's ranking. Lucene
        # is a separate ordering that never sees those occurrences, so
        # withholding `strahd` from it would just make it a worse search.
        text_terms = content_terms(question)
        text_passages = self._text_passages(session, text_terms, limit)
        kept = combine_passages(passages, text_passages, limit)

        edges = dedupe_edges(self._rows(session, EDGES, {"ids": ids}))
        accepted, proposed = split_by_status(edges)

        # Edges stay anchored on the RESOLVED names, and deliberately do not
        # follow the text passages the reservation added. The text path
        # gathers entities from the sections it scored because it has no
        # resolved name to work from; here there is one, and pulling in
        # relationships about entities the question never named -- chosen by
        # a Lucene score -- would put guesses under the heading that reads
        # as what the graph knows about what you asked.
        return Retrieval(
            question=question,
            anchors=tuple(anchors),
            passages=tuple(kept),
            accepted=tuple(accepted),
            proposed=tuple(proposed),
            # Graph candidates the budget cut, which is what this has always
            # counted. Text passages are not counted as dropped: the text
            # path is bounded by `limit` at the query, so it has no tail.
            dropped=max(0, len(passages) - sum(1 for p in kept if p.path == PATH_GRAPH)),
            ambiguous=ambiguous,
            loose=loose,
            carried=carried,
            path=PATH_GRAPH,
            terms=tuple(text_terms),
            miss_reason="" if kept else "anchored, but no section mentions the anchors",
        )

    def _text_passages(self, session, terms: list[str], limit: int) -> list[Passage]:
        """The prose search itself, with no opinion about why it was called.

        Split out of `_by_text` so the two callers cannot drift: the fallback
        that runs when nothing anchored, and the `TEXT_SLOTS` reservation that
        runs alongside a graph result. A second copy of "search the sections and
        build passages" would be free to disagree with this one about width,
        truncation or the score -- the same duplication `passage.py` exists to
        prevent for "the same sentence".

        The passage is anchored at offset 0, since Lucene scores a whole
        document and picking one matched term to centre on would imply the
        section is about that term. At `section` width that is the whole
        section anyway; at `sentence` width it is the section's opening, which
        is the book's own topic statement.
        """
        if not terms:
            return []
        rows = self._rows(
            session,
            SEARCH_SECTIONS,
            {"query": lucene_query(terms), "limit": limit},
        )
        return [
            Passage(
                section_id=row["section_id"],
                chapter=row["chapter"],
                chapter_index=row["chapter_index"],
                section=row["section"],
                section_index=row["section_index"],
                # Through `_render`, so `passage_width` applies here too. It
                # used to call `derive_passage` directly and always sent one
                # sentence, silently ignoring the setting -- which is how a
                # whole-section search returned 930 tokens of the wrong
                # sentence.
                text=self._render({"text": row["text"], "offset": 0}),
                truncated=self._truncated({"text": row["text"]}),
                occurrences=0,
                entity_ids=(),
                score=row["score"],
                path=PATH_TEXT,
            )
            for row in rows
        ]

    def _by_text(self, session, question: str, limit: int) -> Retrieval:
        """The last resort: search the prose for what the question describes.

        Reached only when the question names nothing. It reports `path='text'`
        and carries NO anchors, because no name resolved -- which sections to
        read is a Lucene score's opinion, and that has to stay visible.

        IT DOES CARRY THE GRAPH'S EDGES, from the entities those sections name.
        It used to carry none, on the reasoning that a text hit has no entity to
        hang a relationship off. That was wrong in a way a real question
        exposed: asked "who owns the tavern", it found section E2 -- exactly the
        right section -- and returned prose alone, so three `OWNS` edges a human
        had accepted about that very room never reached the model, which
        answered that the canon did not cover it. Retrieving a section and
        discarding what the graph knows about its occupants is using the book as
        a text file.

        The passage is anchored at offset 0, since Lucene scores a whole
        document and picking one matched term to centre on would imply the
        section is about that term. At `section` width that is the whole
        section anyway; at `sentence` width it is the section's opening, which
        is the book's own topic statement.
        """
        terms = content_terms(question)
        if not terms:
            return Retrieval(
                question=question,
                miss_reason=(
                    "the question names nothing and, once its question words are "
                    "removed, says nothing to search for"
                ),
            )
        passages = self._text_passages(session, terms, limit)
        section_ids = [p.section_id for p in passages]
        ids = sorted(
            row["id"]
            for row in self._rows(
                session, ENTITIES_IN_SECTIONS, {"section_ids": section_ids}
            )
        ) if section_ids else []
        accepted, proposed = split_by_status(
            dedupe_edges(self._rows(session, EDGES, {"ids": ids})) if ids else []
        )
        return Retrieval(
            question=question,
            accepted=tuple(accepted),
            proposed=tuple(proposed),
            passages=tuple(passages),
            path=PATH_TEXT if passages else PATH_NONE,
            terms=tuple(terms),
            miss_reason=(
                ""
                if passages
                else f"the question names nothing, and no section matches {terms}"
            ),
        )

    def _passages(self, session, ids: list[str], terms: list[str]) -> list[Passage]:
        """One passage per SECTION, ranked.

        Per section rather than per mention: two anchors named in one section is
        one thing for a DM to read, and emitting it twice would both waste the
        budget and let a single dense section crowd out every other. The
        occurrence counts add, which is what makes a section naming both anchors
        outrank one naming either.

        RANKING is `occurrences + TERM_WEIGHT * matched terms`, then the number
        of distinct anchors, then the book's own order. The last only breaks
        ties, so the ordering is total and a re-run cannot reshuffle it.

        THE TERM SIGNAL EXISTS BECAUSE OCCURRENCES ALONE ANSWER THE WRONG
        QUESTION. Counting how loudly a section names the anchors ranks the
        sections that talk about them MOST, which for `Strahd` and `Barovia` is
        the introduction's overview -- while every word of the question that is
        not a name goes unused. "Who are Strahd's undead enemies in Barovia"
        ranked its answer NINTH, and that answer contains the words `undead` and
        `enemies` almost verbatim.

        The candidate set is untouched by this. Every eligible section is one
        that mentions a resolved name; terms only reorder them. So the fact/guess
        line the text fallback respects is respected here too -- a term can move
        a passage up, never conjure one.

        Note what this does NOT fix, because ranking cannot: a section the scan
        never linked is not a candidate at any weight. "What happens at the
        cemetery at midnight" is the example -- the book writes `cemetery` in
        lower case in `March of the Dead`, and the single-word case rule (the
        rule keeping the LORE entity `Light` off every lit torch) means
        `Cemetery` has no mention there.

        That question now hits, and NOT because ranking improved: `TEXT_SLOTS`
        reaches the section through the index instead. The limit stated here is
        real and unchanged. It is worth being precise about which repair worked,
        because a sweep of nine occurrence-saturating and term-weighting
        variants moved this set by at most one question in either direction --
        ranking was measured, repeatedly, and is not where these misses live.
        """
        # The chapters the anchors THEMSELVES live in, read off their ids: a
        # chapter-scoped id spells its chapter as its middle segment, and a
        # book-global one (`kftgv:golden-vault`) has none and contributes
        # nothing -- which is right, since a global name is evidence about no
        # particular chapter.
        home_chapters = {
            entity_id.split(":")[1] for entity_id in ids if entity_id.count(":") >= 2
        }

        merged: dict[str, dict] = {}
        for row in self._rows(session, MENTIONS, {"ids": ids}):
            section_id = f"{row['chapter']}#{row['section_index']}"
            slot = merged.setdefault(
                section_id,
                {
                    "chapter": row["chapter"],
                    "chapter_index": row["chapter_index"],
                    "section": row["section"],
                    "section_index": row["section_index"],
                    "text": row["section_text"],
                    "offset": row["offset"],
                    "occurrences": 0,
                    "entity_ids": [],
                    "aliases": [],
                },
            )
            slot["occurrences"] += row["occurrences"] or 0
            slot["entity_ids"].append(row["entity_id"])
            slot["aliases"].extend(row["aliases"] or [])
            # The passage anchors on the EARLIEST mention in the section, so a
            # section naming two anchors quotes wherever the book first raises
            # either of them rather than whichever row the driver returned last.
            slot["offset"] = min(slot["offset"], row["offset"])

        passages = [
            Passage(
                section_id=self._section_id(slot),
                chapter=slot["chapter"],
                chapter_index=slot["chapter_index"],
                section=slot["section"],
                section_index=slot["section_index"],
                text=self._render(slot),
                truncated=self._truncated(slot),
                occurrences=slot["occurrences"],
                entity_ids=tuple(sorted(set(slot["entity_ids"]))),
                aliases=tuple(sorted(set(slot["aliases"]))),
                term_hits=terms_present(slot["text"], terms),
                home_chapter=slot["chapter"] in home_chapters,
            )
            for slot in merged.values()
        ]
        passages.sort(
            key=lambda p: (
                -(
                    p.occurrences
                    + TERM_WEIGHT * p.term_hits
                    + CHAPTER_WEIGHT * p.home_chapter
                ),
                -len(p.entity_ids),
                p.chapter_index,
                p.section_index,
            )
        )
        return passages

    def _render(self, slot: dict) -> str:
        """The passage text at the configured width."""
        if self.passage_width == WIDTH_SECTION:
            return derive_section(slot["text"], SECTION_MAX)[0]
        return derive_passage(slot["text"], slot["offset"])

    def _truncated(self, slot: dict) -> bool:
        if self.passage_width != WIDTH_SECTION:
            return False
        return derive_section(slot["text"], SECTION_MAX)[1]

    def _section_id(self, slot: dict) -> str:
        """The id the write path minted, rebuilt from its parts.

        `MENTIONS` returns the section's heading and index but not its id, and
        widening that shared query for this module's benefit would change what
        `lookup` reads. The format is the write path's and is pinned by a test
        that reads a real section id out of the graph.

        THE BOOK WAS HARDCODED `cos` HERE while one book was the whole world,
        and a second book made it a lie: every passage the graph path returned
        was labelled Curse of Strahd whatever book it came from, so a citation
        pointed a reader at the wrong adventure. It also hid cross-book leakage
        from the only measurement looking for it -- a foreign passage arrived
        wearing the local book's prefix.
        """
        return f"{self.book}:{slot['chapter']}#{slot['section_index']}"

    def _session(self):
        from backend.core.database import neo4j_session

        return neo4j_session()

    def _rows(self, session, query: str, params: dict | None = None) -> list[dict]:
        # `book` beside `plane` because they are the same kind of fact: which
        # slice of the graph this reader is allowed to see. Injected once, so a
        # query cannot forget it.
        merged = {
            "plane": CANON_PLANE,
            "book": f"{self.book}:",
            "book_slug": self.book,
            # None when no campaign is selected, which is the DEFAULT and makes
            # every campaign clause below a no-op. The evaluation harnesses
            # construct retrievers without one, so contamination is impossible
            # by construction rather than by remembering.
            "campaign": self.campaign,
            "campaign_prefix": f"hb:{self.campaign}:" if self.campaign else None,
            **(params or {}),
        }
        return [dict(record) for record in session.run(query, merged)]
