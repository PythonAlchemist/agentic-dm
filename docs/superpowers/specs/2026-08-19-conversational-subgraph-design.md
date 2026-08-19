# The conversational subgraph: a working set, not a transcript

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

The second turn threw away everything the first established and rebuilt its
context from a pronoun. Three faults produce it:

1. **Retrieval never sees the conversation.** `_retrieve_canon(user_input)`
   receives the raw message and nothing else.
2. **`him` is a content word.** `_QUESTION_WORDS` holds `it its they them
   their` and omits `he she him her his hers`, so the query is literally
   `him, makes, special` — and `special` matches a structural heading present
   in eight chapters.
3. **Junk sections contribute edges.** The text path gathers entities from
   whatever Lucene returned. When Lucene returns garbage, so do the edges.

Patching those three in place keeps a stateless design in which every turn
resolves names from scratch, fetches everything about them and rebuilds the
context. That is also why a question naming Strahd ships **43 guessed
relationships and zero derived ones** whether or not it asked about
relationships.

The conversation already knows who "he" is. The system throws it away.

## What a long campaign actually needs

A DM runs one chat for a session, or a campaign. The naive answer is to carry
more transcript; `history_turns` exists for exactly that and is set to 6, which
`_generate_response` turns into `history_turns * 2 + 1` messages. It is both
too small to remember session 3 during session 7, and the wrong mechanism to
make bigger — raising it means re-sending old dialogue on every turn in the
hope the answer is somewhere in it.

**So the transcript stops being the memory, and `history_turns` goes away.**
Two things carry instead, and neither is a growing blob of prose:

```
subgraph          what THIS conversation is about, as graph nodes and edges.
                  Bounded by eviction. Rendered compactly every turn.

campaign plane    what the TABLE has established, in the graph already --
                  `revealed_in_session`, the truth/table split, `PlaneResolver`.
                  Queried when needed, never carried.
```

A long campaign then grows **the graph**, not the context.

### What dropping the transcript costs

Reference resolution is fine: "him" works because Rictavio is a node in the
subgraph with an id, not because the previous message is still in view.

What is lost is **conversational repair** — "no, the other one", "shorter",
"explain that again more simply". Those are about the dialogue rather than
about entities, and nothing in the subgraph holds them. This is a real cost and
it is accepted deliberately rather than overlooked; if it bites, the minimal
mitigation is to keep the single immediately-preceding exchange, which is a
constant rather than a knob.

## The shape

```
DM agent            owns the conversation and the subgraph.
                    Decides what it needs. Writes the answer.
                    Never sees the ontology. Never emits Cypher.

        asks in words  ↓         ↑  a short, labelled result

Graph agent         owns the ontology. Writes Cypher, runs it read-only,
                    returns structured rows. Never writes prose to a user.
                    Its transcript is DISCARDED.
```

**The split is about accumulation, not about token totals.** Total tokens go
up: the graph agent carries the ontology in its own context and a turn becomes
more than one call. What it buys is that exploration never becomes durable.

In a single agent with tools, a tool result is a message in the conversation.
`expand(cos:rictavio)` returning forty edges puts forty edges in the history,
and they are re-sent on the next turn, and the one after, long after the party
has left Vallaki. Five failed query attempts and two hundred rows of
intermediate results would ride along with them. A subagent explores in a
context that is thrown away and returns only what it found.

**The subgraph is durable; the transcript of how it was built is not.** That is
the whole reason for the boundary, and it is structural rather than a
discipline somebody has to remember.

## The subgraph

```
Subgraph
  nodes       entity id -> name, labels, how it entered, turn
  edges       (source, type, target, status, how it entered, turn)
  passages    section id -> text already read
```

`how it entered` is `seeded` (deterministic retrieval), `expanded` (the graph
agent fetched it), or `named` (an answer used it). Provenance per item, for the
same reason every other object here carries it.

**Eviction is required, not optional.** It is the only thing standing between a
long campaign and an unbounded working set, now that the transcript is gone.
Evict by token budget, oldest-touched first, with anything named in the last
answer pinned. A node evicted is not a node deleted — the graph still has it,
and the graph agent can fetch it again.

## The token accounting, measured

An earlier draft claimed this design cuts context. It does not, and the numbers
matter more than the intuition. Counted on a real turn:

    system prompt              734
    canon block              5,501
      passage prose          5,078    82% of the whole turn
      relationship lines       162     3%
      headings + preamble      261

Fetching edges on demand rather than dumping twelve saves about **3%**. The
floor is the **book**: to answer "who owns the tavern" the model needs the
tavern's section in front of it, and no architecture removes that. The model
has no memory between calls, so a subgraph tracked on this side does not reduce
what must sit in front of it.

The two levers that do move the budget are existing knobs with measured
trade-offs: `passages` 8 → 5 saves about 1,900 tokens a turn and costs 7 points
of recall at unchanged MRR; `passage_width` section → sentence saves far more
and is measurably worse, since the tavern's owners are named 3,300 characters
after the first mention of it. For scale, a 2,000-turn campaign costs **$2.07**.

**This is a correctness and continuity design.** Dropping the transcript saves
a little; the split costs a little more; neither is the point.

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
   the entire two-plane design, and it matters more once the campaign plane is
   carrying memory.
4. **A row cap and a timeout.** A generated query can cartesian-product 900
   entities without meaning to.

2 and 3 are enforced by **wrapping, not trusting**: the graph agent proposes a
`MATCH`, the runner appends the projection and the plane predicate, and a query
that cannot be wrapped is rejected rather than run.

**The query is shown in the panel.** Generated Cypher that returns rows looks
exactly like a correct one — the same objection this project makes to
embeddings, that *a vector miss points at a number*. The mitigation is not
cleverness; it is that a DM who sees `MATCH (e)-[:OWNS]->(:Location {name:
'Blood of the Vine'})` can tell it asked the wrong question, and a DM who sees
only an answer cannot.

## What this costs the measurement, and the answer

`eval_retrieval` scores a **deterministic function**: 96 questions in, sections
out, currently 85% recall and 90% among anchored. Once a model composes the
queries it stops describing the system, and a miss stops meaning "an alias is
missing" and may mean "the model did not ask". Not hypothetical — the answer
eval already shows this model citing its source on **three runs in five** for
one question.

**So the deterministic path stays, as the floor.** Turn one seeds the subgraph
with today's retrieval, unchanged, and `eval_retrieval` keeps measuring that
seed and keeps meaning what it means. Expansion sits on top of a known-good
floor and is measured separately.

**Multi-turn needs its own cases.** All 96 retrieval questions and all 10
answer questions are single-turn — the answer harness builds a fresh agent per
question specifically so history cannot bleed. The Rictavio pair is the first
case: ask who he is, then ask what makes him special, and assert the second
turn resolves to `cos:rictavio` rather than to eight copies of `Special
Events`. **Dropping the transcript makes these tests necessary rather than
merely nice**, since continuity now rests entirely on the subgraph.

## Increments

1. **A read-only role and `read_only_session()`.** No model involved. Testable
   immediately, and required before anything else here is safe.
2. **The `Subgraph` object, seeded from existing retrieval**, with eviction,
   rendered compactly each turn. `history_turns` is removed in the same change
   — the subgraph replaces it, and keeping both would be two mechanisms for
   one job. Risks least: it changes what is TRACKED, not what is retrieved, so
   the existing eval still applies unchanged.
3. **The graph agent with named tools** — `resolve`, `expand`, `passages` — a
   floor that cannot emit a bad query, plus the multi-turn eval cases. The
   pronoun problem is solved here, without a pronoun rule.
4. **Generated Cypher**, once a harness exists that can catch it being wrong.

The three faults in "Why" are fixed by 2 and 3 without being addressed
individually — except the missing pronouns in `_QUESTION_WORDS`, a plain
omission that should be corrected on its own.

## What this deliberately does not do

- **It does not make retrieval smarter.** The seed is unchanged. A section
  unreachable today is unreachable after this.
- **It does not fix edge precision.** Roughly a third of proposed edges are
  false. The model is handed fewer of them, not better ones.
- **It does not reduce the token budget.** See the accounting above.
- **It does not build campaign memory.** The campaign plane exists and is where
  durable table state belongs, but wiring the agent to read and write it is a
  design of its own and is not in scope here.

## Open questions

- **Retries.** If the graph agent's query returns nothing, does it try again,
  and how many times before the turn gives up? Each retry is another call and
  another chance to be inconsistent.
- **Where the subgraph lives.** Per `DMAgent` instance today, so it dies with
  the process exactly as lab sessions already do. A campaign that should
  survive a restart needs it persisted, which is the campaign-plane design
  above.
- **Whether one exchange of transcript comes back.** Deliberately dropped; the
  cost is conversational repair, and it should be measured before being
  reinstated on instinct.
