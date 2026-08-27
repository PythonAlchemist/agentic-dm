"""Render a `Retrieval` into the block the model is asked to answer from.

A pure function of the retrieval -- no database, no model, no I/O -- so what the
agent grounds on can be tested exactly rather than inferred from an answer.

TWO THINGS THIS MUST GET RIGHT, and they are the same thing twice.

**The passages have to actually be here.** The pipeline this sits beside inserts
a list of source NAMES and tells the model "relevant context has been
retrieved", which grounds nothing: the model is informed that an answer exists
somewhere and then writes from memory. Whatever a DM sees has to be traceable to
prose the book contains, so the prose travels.

**Provenance has to survive the trip.** Retrieval knows things the model cannot
recover from the text alone -- whether a name resolved or a keyword merely
matched, whether a relationship was derived from the book's structure or guessed
by an extractor that is wrong roughly a third of the time. Flattening all of
that into "here is some context" hands the model unverified claims wearing the
same clothes as the book's own words. So each kind is labelled, in the plainest
language available, with what it is worth.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from backend.canon.retrieval import DEFAULT_LIMIT, PATH_GRAPH, PATH_TEXT, Retrieval


@dataclass(frozen=True)
class Depth:
    """How much canon reaches the model.

    Every field trades context against tokens, and the point of making them
    adjustable rather than tuned once is that the trade is not the same for
    every question -- a rules lookup needs one passage, a scene needs five.

    `include_proposed` is the one that is not a size knob. Proposed edges are
    extractor guesses, wrong about a third of the time, and excluding them asks
    a different question: not "how much context", but "how much UNVERIFIED
    context". Being able to turn them off and re-ask is how you find out whether
    a bad answer came from the model or from a false edge fed to it.
    """

    #: Defaulted from the retriever's own budget rather than restated, so the
    #: number the evaluation harness measures is the number the agent gets.
    #: These were both 5 and drifted apart the moment one of them moved.
    passages: int = DEFAULT_LIMIT
    max_edges: int = 12
    #: Tokens the working subgraph may occupy before the oldest-touched items
    #: are evicted. Chosen against the measured shape of a turn: passage prose
    #: is about 5,000 tokens and relationship lines about 160, so 400 leaves
    #: the summary an order of magnitude smaller than the book it describes --
    #: which is the right proportion for something that says what the
    #: conversation is ABOUT rather than what the book says.
    subgraph_budget: int = 400
    include_proposed: bool = True
    #: Withhold a guessed edge whose own cited sentence does not support it.
    #:
    #: Every proposed edge carries `evidence_check`, a verdict on whether the
    #: sentence the extractor read says what the edge claims -- 61% supported
    #: in Curse of Strahd, 51% in the heist anthology. This drops the rest.
    #:
    #: OFF BY DEFAULT until it is measured. The verdict is a model grading a
    #: model, and gating what a DM is shown on it is a larger claim than
    #: recording it, which is why the label was written first and used second.
    only_supported_edges: bool = False
    #: `section` sends each passage's whole section; `sentence` sends one
    #: sentence around the mention.
    #:
    #: SECTION IS THE DEFAULT because sentence width answers a narrower question
    #: than DMs ask. "Who owns the Blood of the Vine Tavern" is answered 3,331
    #: characters after the tavern's first mention, in the same section, under a
    #: sub-heading about roleplaying the other NPCs -- no sentence window
    #: anchored on the mention reaches it, however the anchor is chosen. Sections
    #: are cheap enough to send whole: the median is 842 characters, and five of
    #: them run about a thousand tokens.
    passage_width: str = "section"


def apply(retrieval: Retrieval, depth: Depth) -> Retrieval:
    """The retrieval as `depth` allows it to be seen.

    Passage count is applied by the retriever, which knows the ranking. What is
    applied HERE is `include_proposed`, because dropping the guesses is about
    what the model may read, not about what the graph holds -- the retrieval
    keeps reporting what it found either way.
    """
    kept = retrieval.proposed if depth.include_proposed else ()
    if kept and depth.only_supported_edges:
        # `unsupported` and `reversed` go; `unclear` and an UNJUDGED edge stay.
        # An edge nobody judged is not an edge that failed, and dropping it
        # here would make a missing verdict look like a verdict.
        kept = tuple(
            e for e in kept
            if e.get("evidence_check") not in {"unsupported", "reversed"}
        )
    return replace(retrieval, proposed=kept)

#: What the model is told about the whole block, before any of it.
#:
#: TAKES THE BOOK'S NAME rather than stating one. This said "Curse of Strahd"
#: unconditionally, and went on saying it after a second book was loaded -- so
#: every Golden Vault answer was prefaced to the model as Barovia. The same
#: stale-constant defect as the chapter count, except told to the model, where
#: no reader could see it. Counted, never written down, applies to prose too.
def _preamble(book_title: str) -> str:
    book = book_title or "the loaded canon"
    return (
        f"CANON — passages retrieved from {book} for this question.\n"
        "Answer from these passages, and CITE THE ONE YOU USED, like [1]. Cite "
        "every fact you take from them, however short the answer, and cite it "
        "even inside an answer that says the canon is thin — if you can state "
        "the fact, you can name where it came from. A DM checks your answer "
        "against the book, and an uncited claim is indistinguishable from one "
        "you remembered.\n"
        "If they do not cover what was asked, say so plainly rather than filling "
        "the gap from memory — a DM acting on an invented detail finds out at the "
        "table."
    )

#: Reached when no name in the question resolved. The model is told the answer
#: may simply not be here, because the fallback cannot say so itself: any
#: question sharing one word with any section returns that section.
_TEXT_WARNING = (
    "These sections were found by KEYWORD MATCH ONLY — nothing in the question "
    "named anything the canon graph knows. They share words with the question "
    "and may be about something else entirely. Use one only if it plainly "
    "answers what was asked, and say the canon does not cover it otherwise."
)

#: Appended to the heading of a single keyword-matched passage sitting among
#: resolved ones.
#:
#: A result that anchored on a name now also carries text passages, because
#: `TEXT_SLOTS` reserves room for them, and `_TEXT_WARNING` only fires when the
#: WHOLE retrieval was a keyword search. Without this the model would read a
#: Lucene guess under a block that says these passages were retrieved for the
#: question, with nothing to distinguish it from the section that resolved a
#: name -- which is the fact/guess line going quiet exactly where it is most
#: load-bearing.
_KEYWORD_MARK = "  (keyword match — may be about something else)"

#: What the model is told when retrieval came back empty.
#:
#: THE COUNT THAT USED TO BE HERE WENT STALE. This read "only 3 of its 25
#: chapters have been loaded" long after the whole book was written to the
#: graph, so the model was being told the corpus was 12% present when it was
#: complete. A number that describes the state of a database does not belong in
#: a string constant; the instruction that matters -- do not answer from memory
#: -- is true at every stage of loading, and is what this says now.
_NO_CANON = (
    "CANON — nothing retrieved for this question. Say plainly that the canon "
    "graph did not return anything on it. Do not answer from memory of the "
    "published adventure: retrieval missing something is not the same as the "
    "book not containing it, and a DM cannot tell an invented detail from a "
    "real one until it fails at the table."
)

#: Relationship trust, in words a model will act on rather than a status string.
_ACCEPTED_HEADING = (
    "Relationships DERIVED from the book's own structure. These are reliable:"
)
_PROPOSED_HEADING = (
    "Relationships GUESSED by an extractor. Roughly a third are wrong — treat "
    "each as a lead to check, never state one as fact:"
)

#: The third trust level, and the one the other two cannot express. Authored
#: material is not derived from the book's structure and is not an extractor's
#: guess -- it is a decision by the person running the game, which makes it
#: authoritative AT THIS TABLE and no claim at all about the published book.
_AUTHORED_HEADING = (
    "Relationships the DM AUTHORED for this campaign. True at this table; the "
    "published book does not say them:"
)

#: Marks on a passage, for what the DM's own decisions did to it.
_CAMPAIGN_MARK = "  ← YOUR CAMPAIGN, written by you. Not the published book."
_SKIPPED_MARK = "  ← SKIPPED in this campaign: not in play at this table."
#: A rider was not scored or matched -- it is here because of WHERE the DM put
#: it. A reader seeing it among ranked passages has to know that.
_RODE_MARK = "  ← in this campaign's running order beside [{}]. Positional, not a keyword match."


def _roster(entries: tuple[dict, ...]) -> str:
    """Everything this table has made, whether or not the question named it.

    THE MODEL HAS TO KNOW WHAT EXISTS BEFORE IT OFFERS TO INVENT IT. Asked to
    "revisit the homebrew content about the sea battle", it drafted a new
    scene -- because the only campaign material it ever saw was whatever a
    question happened to resolve, and that one did not. A DM opens a session to
    look over what they built; that is the main thing this list is for.

    NAMES AND ROLES, NOT PROSE, and it says so. A roster line is a fact about
    what is in the graph; the numbered passages are the only place the words
    themselves appear. Left unlabelled a model will happily paraphrase a role
    as though it had read the scene.
    """
    lines = [
        "EVERYTHING THIS TABLE HAS MADE — the DM's own, not the published "
        "book. This is an INDEX, not the text: a line here means the thing "
        "exists, never that you have read it. When they ask about one, use the "
        "numbered passages below if it is there, and say you have the name but "
        "not the words if it is not."
    ]
    for entry in entries:
        role = (entry.get("role") or "").strip()
        line = f"  {entry['name']} ({entry.get('kind') or 'thing'})"
        if role:
            line += f" — {role}"
        line += "" if entry.get("written") else "  [no prose written yet]"
        lines.append(line)
    return "\n".join(lines)


def _your_material(entities: tuple[dict, ...]) -> str:
    """What the DM has made, said as a record rather than as prose.

    STATES WHEN NOTHING HAS BEEN WRITTEN YET, because a stub and a gap look
    identical to a model otherwise, and the honest answers differ: "you made
    this and have not fleshed it out" is useful, "the book does not mention
    this" is wrong.
    """
    lines = [
        "YOUR CAMPAIGN — things this table has made. These are the DM's own, "
        "not the published book. Speak about them as established at this "
        "table, and never as canon."
    ]
    for entity in entities:
        described = [d for d in (entity.get("described_in") or ()) if d]
        role = (entity.get("role") or "").strip()
        line = f"  {entity['name']} ({entity.get('kind') or 'thing'})"
        if role:
            line += f" — {role}"
        if described:
            line += f". Appears in: {', '.join(described)}."
        else:
            line += ". Nothing has been written about it yet."
        lines.append(line)
    lines.append(
        "  If the DM asks for more about one of these and there is no prose "
        "above, say what is known and offer to flesh it out."
    )
    return "\n".join(lines)


def _authored(edge: dict) -> bool:
    """An edge the DM asserted, rather than one derived or guessed."""
    return edge.get("status") == "authored"


def render(retrieval: Retrieval, *, max_edges: int = 12, for_chat: bool = True) -> str:
    """The context block, or a statement that there is none.

    `max_edges` bounds each relationship list. A heavily-mentioned anchor such
    as Strahd carries dozens, and a wall of unverified edges buries the passages
    that are actually worth reading. What is cut is counted in the line above
    it, never dropped silently.
    """
    if not retrieval.passages:
        return _NO_CANON

    parts = [_preamble(retrieval.book_title)]
    if retrieval.path == PATH_TEXT:
        parts.append(_TEXT_WARNING)
        if retrieval.terms:
            parts.append(f"Words searched for: {', '.join(retrieval.terms)}.")

    # THE DM'S OWN RECORD, BEFORE THE PASSAGES. A thing they made is not a
    # passage and must not read as an absence: an element carries a kind, a
    # role and the scene that introduced it long before anyone writes prose
    # about it, and without this the model answered "the canon does not cover
    # any specific details about Captain Saltmarrow" about a character the DM
    # had invented an hour earlier.
    # WHAT THEY ARE LOOKING AT, ABOVE EVERYTHING. Whole, under its own
    # heading, and NOT among the numbered passages: it is not competing for a
    # retrieval slot, it is here because the DM has it open. Without this they
    # have to re-describe in a chat box the thing already on screen in front of
    # them, which is the complaint that started this.
    if retrieval.focus_prose and for_chat:
        open_now = retrieval.focus_prose
        mine = open_now.get("plane") == "campaign"
        parts.append(
            f"WHAT THE DM IS READING RIGHT NOW — {open_now.get('heading') or ''}"
            f"{'  ← their own, not the published book' if mine else '  ← the book'}\n"
            "Answer about this unless they clearly mean something else, and do "
            "not ask them to describe it back to you.\n"
            # THE RULE GOES WITH THE FACT. Told only in the tool descriptions,
            # "build out the sea battle, give me a cast of enemies" read as
            # make-me-something and minted a second scene beside the one on
            # screen. Here it sits next to the thing being talked about.
            # WHAT "THIS" MEANS, stated rather than left to be inferred.
            # Asked to "flesh out this character" with Captain Saltmarrow open,
            # the model drafted A Bent Turnkey -- a different NPC, picked from
            # the roster because it was marked as having no prose yet. "This",
            # "him", "her" and "it" are the thing named on this line and
            # nothing else.
            "WHEN THEY SAY this, it, him, her, this character, this scene -- "
            "they mean the thing named on the line above, not something else "
            "from the list below that seems to fit better.\n"
            "IF THEY ASK TO CHANGE, EXTEND, BUILD OUT, ADD TO, FLESH OUT OR "
            "SHORTEN THIS, "
            "that is `revise_my_material` and never `generate_homebrew` -- "
            "generating would leave them with two of it. Only reach for "
            "`generate_homebrew` when what they want is a SEPARATE thing that "
            "did not exist before.\n\n"
            f"{open_now.get('text') or ''}"
        )

    # THE ROSTER FIRST AND UNCONDITIONALLY, then the detail for whatever the
    # question actually named. One says what exists at this table, the other
    # says what the graph holds about the thing being discussed, and a model
    # that only ever got the second could not tell "you have not made that"
    # from "you did not mention it".
    # THE ROSTER IS A CHAT CONCERN AND NOT A GENERATOR'S. It exists so the
    # model knows what already EXISTS before it offers to invent it again --
    # a question only the chat is asked. Handed to a generator writing about a
    # named subject it is a menu of other names, and it behaved like one: told
    # to write up Captain Saltmarrow, it returned "A Bent Turnkey" in three
    # runs out of four, on both model tiers. The subject was right in the user
    # message the whole time; the system message was offering alternatives.
    if retrieval.campaign_roster and for_chat:
        parts.append(_roster(retrieval.campaign_roster))
    if retrieval.campaign_entities:
        parts.append(_your_material(retrieval.campaign_entities))

    numbers = {p.section_id: n for n, p in enumerate(retrieval.passages, start=1)}
    for number, passage in enumerate(retrieval.passages, start=1):
        heading = f"[{number}] {passage.chapter} › {passage.section}"
        # Only when the block has not already said it wholesale, so a pure text
        # retrieval does not repeat the warning on every line.
        if passage.path == PATH_TEXT and retrieval.path != PATH_TEXT:
            heading += _KEYWORD_MARK
        # WHOSE WORD IT IS, said on the line the model reads. The block above
        # promises "passages retrieved from <the book>", and a DM's own scene
        # arriving under that promise unlabelled would be the model telling a
        # table its own invention is published canon.
        if passage.origin == "campaign":
            heading += _CAMPAIGN_MARK
        elif passage.chain_status == "skipped":
            heading += _SKIPPED_MARK
        if passage.rode_with:
            heading += _RODE_MARK.format(numbers.get(passage.rode_with, "?"))
        parts.append(f"{heading}\n{passage.text}")

    for heading, edges in (
        (_ACCEPTED_HEADING, tuple(e for e in retrieval.accepted if not _authored(e))),
        (_PROPOSED_HEADING, retrieval.proposed),
        (
            _AUTHORED_HEADING,
            tuple(e for e in retrieval.accepted + retrieval.proposed if _authored(e)),
        ),
    ):
        if not edges:
            continue
        shown = edges[:max_edges]
        lines = [_edge_line(e) for e in shown]
        cut = len(edges) - len(shown)
        if cut:
            lines.append(f"  … and {cut} more, not shown")
        parts.append(heading + "\n" + "\n".join(lines))

    return "\n\n".join(parts)


def suggest_anchor(retrieval: Retrieval) -> tuple[str, tuple[str, ...]]:
    """Where a generation grounded in this retrieval belongs, and near what.

    Returns `(section_id, chapters)` -- the passage to put it after, and every
    chapter the retrieval touched, first-seen order.

    THE GENERATION ALREADY KNOWS THIS AND WAS THROWING IT AWAY. A scene about
    the voyage retrieves `Trek to the Prison`, `Approaching the Prison`,
    `Prison Features` -- six passages, all from one chapter -- and the card
    then asked the DM to find the right one among 546 sections spanning
    thirteen unconnected heists, offering `V13: Gemstone Wing` from a museum
    robbery with equal prominence.

    THE CHAPTER IS CHOSEN BEFORE THE PASSAGE, and by WEIGHT rather than by
    rank. A scene belongs to a chapter, not to a paragraph, so the chapter that
    most of the retrieval came from is a better answer than whichever single
    passage scored highest. Taking the top passage alone proposed the book's
    INTRODUCTION for a mutiny on a prison barge -- front matter outranked the
    voyage because one general passage about rival crews scored well, while
    four passages from the adventure itself sat below it.

    A GRAPH PASSAGE IS PREFERRED OVER A TEXT ONE -- when the CHAPTER is chosen
    as well as within it, which it was not, and that was the defect. A resolved
    name is a fact about what a generation is about; a keyword hit is a guess.
    Weighting them the same meant four keyword hits scattered across
    `prisoner-13` outvoted four names the question actually resolved, and
    "a cast of enemies for the sea battle" anchored after `Revel's End` --
    past the voyage the fight happens on. Chapters are ordered by whether they
    hold a resolved name FIRST and by weight second: a lexicographic rule
    rather than a multiplier, because the number would be a guess and this is
    not.

    AND IF THE QUESTION NAMED THE DM'S OWN MATERIAL, THAT IS THE ANSWER. They
    have already decided where that scene lives in the running order, and a
    thing generated ABOUT it belongs beside it -- "a cast of enemies for the
    sea battle" goes where The Sea Battle is, not wherever the book talks most
    about ships. This outranks everything below because it is the only signal
    here that reflects a decision a person actually made.

    IT ANSWERS "WHICH SECTION DOES THE SUBJECT NAME MOST", NOT "WHICH BEAT IS
    THIS", and those come apart on any scene about getting somewhere. A sea
    battle on the voyage to Revel's End scores `Revel's End` at seven mentions
    and `Trek to the Prison` -- the voyage itself -- at two, so the suggestion
    lands after they have arrived. Nothing available reorders that: `voyage`
    matches no heading, and taking the earliest retrieved passage instead
    proposes `Varrin's Proposition`, the job offer, which is early by as much
    as the other is late.

    So this stays a first guess and the CARD shows the shortlist beside it --
    the eight passages the generation was written against, which is where the
    scene plausibly goes and among which a DM knows the beat they mean.
    Measured on four subjects: two right, one a beat late, one preferring a
    LORE section over the road the ambush happens on.

    It always proposes something rather than nothing: a suggestion a DM can
    override beats a list of 546 they have to search.
    """
    shown = sources(retrieval)
    if not shown:
        return "", ()

    # THE DM'S OWN, RESOLVED BY NAME. Not "a campaign passage appeared" -- one
    # rides along positionally beside almost any canon hit -- but one the
    # question actually resolved, which means this generation is about it.
    mine = [
        s
        for s in shown
        if s.get("type") == "campaign" and s.get("path") == PATH_GRAPH
    ]

    weight: dict[str, int] = {}
    resolved: set[str] = set()
    for rank, source in enumerate(shown):
        chapter = source.get("chapter")
        if not chapter:
            continue
        # Rank still breaks ties, so a chapter contributing one very good
        # passage beats another contributing one mediocre one.
        weight[chapter] = weight.get(chapter, 0) + (len(shown) - rank)
        if source.get("path") == PATH_GRAPH:
            resolved.add(chapter)

    chapters = tuple(
        sorted(weight, key=lambda c: (c not in resolved, -weight[c]))
    )
    if mine:
        return str(mine[0].get("source") or ""), chapters
    home = chapters[0]
    within = [s for s in shown if s.get("chapter") == home]
    by_graph = [s for s in within if s.get("path") == PATH_GRAPH]
    best = (by_graph or within)[0]
    return str(best.get("source") or ""), chapters


def sources(retrieval: Retrieval) -> list[dict]:
    """Citations for the UI, one per passage, in the order the model saw them.

    `path` rides along so a caller can render a keyword match differently from a
    resolved one. A citation that looks equally authoritative either way would
    undo the labelling the block above works to preserve.

    Taken from the PASSAGE, not from the retrieval. One result now mixes both
    paths, and stamping the question's coarse label on every citation was how a
    Lucene guess came to be presented in the UI as a resolved name.

    `type` IS READ OFF THE PASSAGE for exactly that reason. It was the constant
    `"canon"` on every citation, which was true while canon was all there was
    and became a lie the moment a DM's own material could be cited beside it --
    the same defect as the coarse path label, one layer along.
    """
    return [
        {
            "source": passage.section_id,
            "type": passage.origin,
            "chapter": passage.chapter,
            "section": passage.section,
            "path": passage.path,
            "citation": f"[{number}]",
            # Empty when no campaign is selected. Says whether the DM has this
            # in play, cut it, or has not placed it -- never used to rank.
            "chain_status": passage.chain_status,
            "rode_with": passage.rode_with,
        }
        for number, passage in enumerate(retrieval.passages, start=1)
    ]


def _edge_line(edge: dict) -> str:
    """`A -RELATIONSHIP-> B`, in the direction the graph stores it.

    Direction is not cosmetic here. `Strahd SEEKS Ireena` and `Ireena SEEKS
    Strahd` are different claims about the same two nodes, and reversal is one
    of the extractor's four measured failure modes -- so the arrow is written
    out rather than left to a phrasing that might read either way.
    """
    entity = edge.get("entity", "?")
    other = edge.get("other", "?")
    relationship = edge.get("relationship", "?")
    if edge.get("direction") == "in":
        entity, other = other, entity
    return f"  {entity} -{relationship}-> {other}"
