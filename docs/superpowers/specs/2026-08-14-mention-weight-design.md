# Lighter mentions, co-occurrence, and creature types

**Date:** 2026-08-14
**Status:** Approved in conversation, not yet implemented
**Depends on:** `5c5f894` — narrative spine, aliases, lookup

Three changes, prompted by opening a `:Mention` node in Neo4j Browser and finding
a 231-character paragraph in the details panel. Ordered by confidence: the first
is pure deletion, the last removes a node that should never have existed.

---

## 1. Evidence is a duplicated copy — derive it instead

Measured on the live graph:

```
153 mentions · avg evidence 231 chars · max 320 · total 35,383
:Section already carries `text`
several evidence strings stored 3x -- three entities in one paragraph
```

The Mention carries `offset`; the Section carries the full `text`. The stored
evidence is therefore a second copy of something the graph already has, and a
paragraph naming three entities is stored three times.

**Drop the `evidence` property.** Derive it on read: slice `section.text` around
`offset`, trimmed to the containing sentence. `backend/canon/lookup.py` is the
only consumer that surfaces it, and it already joins the Section.

**Sentence trimming rule:** expand from `offset` to the nearest sentence
boundary in each direction, capped at 300 characters so a run-on paragraph
cannot reintroduce the bulk. Prefer a simple boundary rule over a sentence
tokenizer — no new dependency, and a rough boundary is fine for a passage a
human reads.

**Keep `occurrences` and `offset`.** They are facts about the mention, not
copies. `offset` is the first occurrence; that is what the derivation anchors on.

**Success:** every `:Mention` loses `evidence`; `lookup` still returns a readable
passage for each; the graph sheds ~35k characters; the Browser details panel fits
on screen.

---

## 2. Co-occurrence at span granularity

Two mentions sharing a `:Section` is weak evidence — a section is often a whole
room description. Two entities named in the same *sentence* is strong, and the
offsets to compute it are already stored.

```
(:Mention)-[:CO_OCCURS_WITH]->(:Entity)
```

For each mention, the other entities whose own mention offsets fall inside the
same derived sentence span. Deterministic, no model, no cost.

**Why it earns its place:** this is the raw material for relationship inference
without asking a model to invent one. "Strahd, Barovia, Madam Eva and the tarokka
deck all appear in one sentence" is a fact. Whether that means `SEEKS` or
`THREATENS` is the judgment we have repeatedly failed to automate — so record the
fact and leave the judgment alone.

**Direction and duplication:** the relationship is symmetric in meaning but
should be written once per (mention, entity) pair, not twice. A mention never
co-occurs with its own entity.

**Watch the count.** If a dense paragraph names eight entities, that is 8x7
edges. Report the total and the worst section; if it explodes, the sentence rule
is too loose and that is worth knowing before it lands.

---

## 3. `vampire` is a category, not an individual

The `vampire` node has seven mentions and will gain one for every "a vampire" in
25 chapters, while never being a thing that exists in Barovia. Strahd *is* a
vampire — that is a fact about Strahd, not an edge between him and a node named
`vampire`.

This is the generic-noun problem in its clearest form, the same shape as `light`
matching nine sections.

**Creature type becomes a label**, from D&D's own canonical taxonomy — Undead,
Fiend, Fey, Humanoid, Monstrosity, Beast, Construct, Aberration, Celestial,
Dragon, Elemental, Giant, Ooze, Plant. It is genuinely canonical, stat blocks
state it verbatim, and it is set-like in the way type already is.

```
(:Entity:NPC:Undead {name:'Strahd von Zarovich'})
```

**Then `vampire` stops being an entity.** Concretely:

- add creature-type labels, hand-authored in the YAML that already carries
  location rungs, artifacts and aliases
- record `vampire` as an **alias** of Strahd where the prose means Strahd, if a
  span justifies it — and only where it does
- delete the standalone `vampire` node

**The judgment to be careful about:** "a vampire" does not always mean Strahd.
Doru is a vampire spawn; later chapters have others. Do **not** alias `vampire`
to Strahd globally. If a mention's span cannot be attributed, the honest outcome
is that the mention disappears with the node — a lost weak mention is better than
a wrong strong one.

**Success:** no `:MONSTER {name:'vampire'}` node; Strahd carries a creature-type
label; no mention that previously pointed at `vampire` now points at the wrong
entity.

---

## Sequencing, and why

**1 before 2**, because co-occurrence derives from the same sentence span that
evidence-trimming defines. Build the span rule once.

**3 last**, because it deletes a node and its mentions, and doing that before the
other two would make their before/after numbers unreadable.

## What does not change

Entity identity, type-as-label, the location hierarchy, `:Artifact`, aliases, the
spine, atomicity. The `accepted`/`proposed` split on typed relationships is
untouched — `CO_OCCURS_WITH` is deterministic and belongs with `MENTIONED_IN` and
`DESCRIBES` on the trustworthy side.

## Cost

Change 1 is a net deletion. Change 2 adds edges that could outnumber mentions
several-fold — that is the number to watch. Change 3 removes a node and however
many mentions were only ever pointing at a common noun.

## Open question

**Do other common nouns need the same treatment?** `light`, `Trapdoor`, `oil
lamp`, `tinderbox` are all in the graph on the same footing as Strahd. Creature
types fix `vampire` specifically because D&D supplies the taxonomy. The general
case — a common noun promoted to an entity — has no such external authority and
should not be solved speculatively. Fix `vampire`, count what remains, decide
then.
