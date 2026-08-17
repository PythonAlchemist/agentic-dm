# The narrative spine: sections, mentions, aliases, and where facts live

**Date:** 2026-08-14
**Status:** Approved in conversation, not yet implemented
**Supersedes:** `2026-08-13-mention-triangle-design.md` (the triangle is folded in here)
**Depends on:** `095a86e` — globally unique entities, type as a label, location hierarchy

## Why

Strahd is named in **8 of chapter 3's 22 sections**. The graph records **1**.

Everything the graph knows about him is one node with a `description` holding a
single sentence — *"A character defined as a selfish beast lurking behind a mask
of tragic romance"* — three `MENTIONED_IN` edges that carry no evidence, and four
typed relationships of which three are `proposed`.

Four distinct failures underneath that:

1. **Mentions record where an entity was *extracted*, not where it *appears*.**
   The extractor emitted Strahd as a candidate from the preamble; the tavern, the
   mansion, the chapel, the undercroft and the March of the Dead left no trace.
2. **`description` is single-valued and last-write-wins.** He will be described
   across 25 chapters; the node keeps whichever extraction ran most recently.
   Same defect class as the shared-edge `chapter_slug` overwrite.
3. **`MENTIONED_IN` carries no evidence** — it points at a section without saying
   what the section said.
4. **Descriptive facts have nowhere to live.** "Strahd is a vampire", "he has
   ruled Barovia for centuries" are not relationship-shaped, so nothing holds
   them.

## The model

### The spine — deterministic, no model judgment

```
(:Book {slug, title})
   -[:HAS_CHAPTER {index}]->    (:Chapter {slug, title, index})
   -[:HAS_SECTION {index}]->    (:Section {id, heading, index, depth, key})
```

`:Section` is the document unit the extractor already works in — one per heading,
exactly what `split_sections` produces. It carries its own text so a mention can
quote it.

**A section that describes a place links to it:**

```
(:Section)-[:DESCRIBES]->(:LOCATION)
```

That edge is derivable: a keyed section (`E5f. Chapel`) *is* the place it names,
and `structure.py` already computes that correspondence. It is the join that
makes party-exploration progression possible later — visited place → its section
→ what is knowable there.

### The triangle — what is said, where, and under what name

```
        (:Entity:NPC)
           ▲          ▲
    REFERS_TO          ALIAS_OF
           │          │
       (:Mention) ──USES_ALIAS──▶ (:Alias {name, normalized})
           │
      IN_SECTION
           ▼
       (:Section)
```

`:Mention` is one node per (entity, section) pair — not per occurrence; two
sentences about Ireena in one section are one mention. It carries the **evidence
span**, and it is where facts belong that are true *at that point in the book*.

`:Alias` is one node per distinct surface form. The entity's own canonical name is
itself an `:Alias`, so lookup has a single path. `normalized` is lowercase,
trimmed, U+2019 folded to `'` — and that is the *whole* normalization. Nothing
fuzzy, nothing token-subset. This project has twice been damaged by loose
matching; the alias node exists precisely so variants are **recorded rather than
guessed**.

`USES_ALIAS` records which name the book used at that point, which is itself story
information — the party meets "the devil Strahd" long before Strahd von Zarovich.

### Ordering is the point

`(chapter.index, section.index)` is the order the book reveals things, so
progression is a range query rather than bookkeeping:

```cypher
MATCH (m:Mention)-[:REFERS_TO]->(:Entity {name:'Strahd von Zarovich'}),
      (m)-[:IN_SECTION]->(s:Section)<-[:HAS_SECTION]-(c:Chapter)
WHERE c.index <= 3
RETURN c.slug, s.heading, m.evidence
ORDER BY c.index, s.index
```

## The mention scan

Mentions come from **scanning each section's text for known entity names** — not
from wherever the extractor happened to emit a candidate. Deterministic, no LLM,
no cost.

**Matching:** whole-word, against the entity's canonical name and every recorded
alias. Case-sensitive for single-word names, case-insensitive for multi-word ones
— `Light` the lore entity must not match every lit torch, while `blood of the
vine tavern` should match regardless of casing.

**Junk entities will produce junk mentions, and that is fine.** A `Trapdoor`
entity matching forty sections makes the junk *more* visible, not less — the same
argument that merging duplicate nodes made junk easier to spot. Report the top
twenty entities by mention count; anything absurd surfaces immediately.

**Expected outcome, and the check that it worked:** Strahd goes from 1 mention to
8 in chapter 3. If he does not, the scan is wrong.

## `:Scene` — defined now, populated later

A **scene** is something that *happens*, as against a section that *describes*.
The March of the Dead is a scene; `E5f. Chapel` is a place with a description.
Many sections are both.

`:Scene` is reserved with that meaning and **deliberately not populated in this
work.** What counts as a scene is a DM's judgment, not a document fact, and
inventing a derivation rule now would be exactly the speculative machinery this
project spent a day unwinding. When the progression system needs scenes, they get
hand-authored against sections that already exist.

## What progression will need, and why it is not built here

The eventual system tracks what a party has explored and derives what they could
know. That needs three things, and this design supplies two of them:

- **a place they visited** — `:LOCATION`, exists
- **what is knowable there** — `(:LOCATION)<-[:DESCRIBES]-(:Section)<-[:IN_SECTION]-(:Mention)`, this work
- **which party, and when** — campaign plane, not built, not designed here

The affordance is deliberate: with mentions anchored to sections and sections
joined to places, "what does this party know about Strahd" becomes a traversal
from visited places. No further canon-side structure is required, and none should
be added speculatively.

## What does not change

- Entity identity, type-as-label, the location hierarchy, `:Artifact`.
- Spatial containment stays entity-to-entity. A room is inside another room
  regardless of who mentions it.
- The `accepted` / `proposed` split on typed relationships. Orthogonal: mentions
  are deterministic, dramatic relationships are not.
- Atomicity — one transaction per chapter, pinned by tests that fail if the writer
  commits per statement.

## Cost, stated plainly

Mentions will heavily outnumber entities: chapter 3 alone goes from 72
`MENTIONED_IN` edges to several hundred `:Mention` nodes. Across the book,
thousands of nodes whose only job is to say "this thing appears here, and here is
what it said". Cheap for Neo4j; real weight in the model, and real noise in the
Browser unless the GRASS file keeps them small and pale.

"What do we know about X" stops being a property read and becomes an aggregation.
That is the trade being made on purpose: harder to read, able to answer *when*.

## Open questions, to settle in implementation

**Does `description` survive?** It is single-valued and last-write-wins, and
mentions make it redundant. Deleting it is the honest move, but check what reads
it first.

**Where do aliases come from?** The extractor already produces variants as
separate candidates (`Ismark`, `Ismark Kolyanovich`), and folding those together
is the merge this design wants — but by *string similarity* is the loose matching
that has burned this project twice. Start hand-authored, in the YAML that already
holds location rungs and artifacts. Extractor-proposed aliases land `proposed`.

## Success criteria

1. Strahd has 8 mentions in chapter 3, one per section that names him.
2. `where_is("Ismark")` and `where_is("Ismark Kolyanovich")` resolve to the same
   entity, and so does any curly-apostrophe variant — with no fuzzy matching
   anywhere in the path.
3. A range query bounded by `chapter.index` returns strictly fewer facts about
   some entity than an unbounded one. If not, revelation order is modelled but not
   captured.
4. Every `:Mention` carries a non-empty evidence span quoting its section.
5. Node and edge counts before and after, with `:Mention` stated separately so the
   weight of the change is visible.
