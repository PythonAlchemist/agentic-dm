# The conversational subgraph: two agents, one working set, read-only Cypher

**Date:** 2026-08-19
**Status:** Design agreed in conversation, not yet implemented
**Depends on:** `33a08dc` — the labelled union of the graph and text paths, and
the per-passage provenance that makes a mixed result readable

## Why

Two questions, asked in sequence, in the lab:

> **who is rictavio**
> Anchors `Rictavio → Rictavio`. Eight passages, seven by name and one by
> keyword. A correct answer.
>
> **what about him makes him special**
> Anchors **nothing**. Searches Lucene for `him, makes, special` and returns
> the section headed `Special Events` **eight times**, from eight different
> chapters, along with **93 relationships** — 59 derived and 34 guessed —
> harvested from those eight junk sections.

The second turn threw away everything the first turn established and rebuilt
its context from a pronoun. Three separate faults produce that:

1. **Retrieval never sees the conversation.** `_retrieve_canon(user_input)`
   receives the raw message and nothing else.
2. **`him` is a content word.** `_QUESTION_WORDS` holds `it its they them
   their` and omits `he she him her his hers`, so the Lucene query is literally
   `him, makes, special` — and `special` matches a structural heading that
   exists in eight chapters.
3. **Junk sections contribute edges.** The text path gathers entities from
   whatever Lucene returned. When Lucene returns garbage, so do the edges.

Fixing those three in place was the obvious move and is the wrong one. It
patches a stateless design: every turn resolves names from scratch, fetches
everything about them, and rebuilds the context. That is also why a question
naming Strahd ships **43 proposed relationships and zero derived ones** whether
or not it asked about relationships, and why a turn costs **6,160 input
tokens** against 184 out — **89% of the spend is context**, most of it re-sent.

The conversation already knows who "he" is. The system throws that away.

## The shape

A conversation owns a **working subgraph** — its accumulating view of the
canon graph — and two agents with different jobs sit either side of it.

```
DM agent            owns the conversation and the subgraph.
                    Decides what it needs. Writes the answer.
                    Never sees the ontology. Never emits Cypher.

        asks in words  ↓         ↑  labelled rows

Graph agent         owns the ontology. Writes Cypher, runs it read-only,
                    returns structured rows. Never writes prose to a user.
                    Never sees the campaign conversation.
```

The boundary is what makes "do not send the whole graph" true by construction
rather than by discipline: the DM agent **cannot** see the graph, only what it
asked for.

It also maps onto the line this project already defends. The graph agent
returns data carrying its own `status`; the DM agent must not launder a guess
into a fact. Same rule as `canon_context`'s two headings, one layer further
out.

## The subgraph

```
Subgraph
  nodes       entity id -> name, labels, how it entered
  edges       (source, type, target, status, how it entered)
  passages    section id -> text already read
  turn        the turn each item entered on
```

`how it entered` is `seeded` (deterministic retrieval), `expanded` (the graph
agent fetched it), or `named` (the answer used it). Provenance per item, for
the same reason every other object here carries it: a reader has to be able to
say why something is in front of them.

**It grows, and it is the reason "he" needs no resolver.** Rictavio is already
a node in the subgraph with an id. The DM agent does not resolve a pronoun; it
already knows which node the conversation is about, and says so when it asks
the graph agent for more.

**It is what gets rendered, not the retrieval** -- a compact node and edge
summary, plus prose for sections newly read this turn.

*Corrected 2026-08-19, after measuring rather than assuming.* An earlier draft
of this section claimed that was where the 6,160 tokens go. It is not. Counted
on a real turn:

    system prompt              734
    canon block              5,501
      passage prose          5,078    82% of the whole turn
      relationship lines       162     3%
      headings + preamble      261

Fetching edges on demand instead of dumping twelve saves about 3%. THE MODEL
HAS NO MEMORY BETWEEN CALLS, so a subgraph tracked on this side does not
reduce what has to sit in front of it: if a later turn needs those sections,
they are re-sent whether or not we recorded having fetched them. And the
current design does not accumulate -- the canon block is inserted fresh each
turn and never enters history -- so there is no stacking to remove.

Sending summaries of already-read sections instead of prose WOULD cut it, and
trades grounding fidelity: a model cannot quote or cite accurately from a
summary, and citation reliability is already the weakest measured behaviour
(one answer-eval question cites its section on three runs in five).

So this is a correctness and continuity design, not a cost one. Per-turn
tokens are roughly flat and TOTAL tokens likely rise, because the graph agent
carries the ontology in its own context on every call and a turn becomes two
calls instead of one.

## What must survive contact with a generated query

Four invariants, none of which is a prompt instruction:

1. **Read-only, enforced by Neo4j.** `neo4j_session()` currently hands out one
   full-write session that everything shares; there is no read-only path in the
   codebase at all. A model composing queries needs a role with `MATCH` and no
   write privilege. `default_access_mode=READ` is not enough — on a single
   instance it routes, it does not forbid.
2. **`status` on every edge returned, always.** Free-form Cypher can trivially
   return a proposed edge without saying it is a guess. This is the invariant
   defended hardest across this project's history and the easiest to lose here.
3. **`plane` filtered, always.** Canon and campaign must never blur; that is
   the entire two-plane design.
4. **A row cap and a timeout.** A generated query can cartesian-product 900
   entities without meaning to.

2 and 3 are enforced by **wrapping, not trusting**: the graph agent proposes a
`MATCH`, the runner appends the projection and the plane predicate, and a query
that cannot be wrapped is rejected rather than run.

**The query is shown in the panel.** A generated Cypher that returns rows looks
exactly like a correct one — the same objection this project makes to
embeddings, that *a vector miss points at a number*. The mitigation is not
cleverness; it is that a DM who sees `MATCH (e)-[:OWNS]->(:Location {name:
'Blood of the Vine'})` can tell it asked the wrong question, and a DM who sees
only an answer cannot.

## What this costs the measurement, and the answer

`eval_retrieval` scores a **deterministic function**: 96 questions in, sections
out, currently 85% recall and 90% among anchored. Once a model composes the
queries, it stops describing the system. A miss stops meaning "an alias is
missing" and may mean "the model did not ask". This is not hypothetical — the
answer eval already shows this model citing its source on **three runs in
five** for one question.

**So the deterministic path stays, as the floor.** Turn one seeds the subgraph
with today's retrieval, unchanged. `eval_retrieval` keeps measuring that seed
and keeps meaning what it means. Everything the graph agent adds is expansion
on top of a known-good floor, measured separately.

**Multi-turn needs its own cases, because nothing measures it today.** All 96
retrieval questions and all 10 answer questions are single-turn — the answer
harness builds a fresh agent per question specifically so history cannot bleed.
The Rictavio pair above is the first case to add: ask who he is, then ask what
makes him special, and assert the second turn resolves to `cos:rictavio` rather
than to eight copies of `Special Events`.

## Increments

Each one is useful alone and verifiable before the next.

1. **A read-only role and `read_only_session()`.** No model involved. Testable
   immediately, and required before anything else here is safe.
2. **The `Subgraph` object, seeded from existing retrieval.** The increment
   that risks least, because it changes what is TRACKED rather than what is
   retrieved, so the existing eval still applies unchanged. It does not save
   tokens -- see the measurement above -- and its value is that increment 3
   has somewhere to put what it fetches.
3. **The graph agent with named tools** — `resolve`, `expand`, `passages` — a
   floor that cannot emit a bad query, plus the multi-turn eval cases. The
   pronoun problem is solved here, without a pronoun rule.
4. **Generated Cypher**, once there is a harness that can catch it being wrong.

The three faults in "Why" are fixed by increments 2 and 3 without being
addressed individually — except the missing pronouns in `_QUESTION_WORDS`,
which is a plain omission and should be corrected on its own.

## What this deliberately does not do

- **It does not make retrieval smarter.** The seed is unchanged. If the right
  section is not reachable today, it is not reachable after this.
- **It does not fix edge precision.** Roughly a third of proposed edges are
  false. The subgraph means a model is handed fewer of them, not better ones.
- **It does not reduce the token budget.** The two levers that do are
  `passages` and `passage_width`, both existing knobs with measured
  trade-offs: 8 -> 5 saves about 1,900 tokens a turn and costs 7 points of
  recall at unchanged MRR; sentence width saves far more and is measurably
  worse, since the tavern's owners are named 3,300 characters after the first
  mention of it. For scale, a 2,000-turn campaign costs $2.07 in total.
- **It does not remove the deterministic path.** Anything that cannot be
  answered from the seed plus expansion is still a countable hole.

## Open questions

- **Eviction.** Monotonic growth is simple and unbounded; a forty-turn session
  accumulates. Evict by token budget, by recency, or not at all until it
  measurably hurts?
- **Retries.** If the graph agent's query returns nothing, does it get to try
  again, and how many times before the turn gives up? Each retry is another
  call and another chance to be inconsistent.
- **Where the subgraph lives.** Per `DMAgent` instance today, which means it
  dies with the process, exactly as lab sessions already do. A campaign that
  should remember across restarts needs it persisted, and that is a different
  design.
