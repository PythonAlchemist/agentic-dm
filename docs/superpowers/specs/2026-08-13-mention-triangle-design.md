# The mention triangle: aliases, mentions, and story progression

**Date:** 2026-08-13
**Status:** Approved in conversation, not yet implemented
**Depends on:** `feat/unique-entities` (globally unique entities, type-as-label)

## The problem

Two things the current graph cannot express, both found by pointing a DM's
questions at it.

**Names are not identity.** Of eight failed lookups in a 20-question probe, three
failed only because the DM's word differed from the graph's: `Ismark` where the
graph holds `Ismark Kolyanovich`, `Village of Barovia` where it holds `Barovia`,
and `Burgomaster's Mansion` where it holds `Burgomaster’s Mansion` — an ASCII
apostrophe against U+2019. A normalization table would paper over this and drift;
the book genuinely calls people several things.

**Facts have a location in the story, and the graph has nowhere to put it.** Both
of these are true of Ireena:

- she is the burgomaster's adopted daughter (chapter 3, stated plainly)
- she carries Tatyana's soul (chapter 3's preamble — DM-facing, not player-facing)

Attached to the entity, they are indistinguishable. A DM assistant that surfaces
the second when asked the first has spoiled the campaign's central reveal. This
is the problem the two-plane canon/campaign design was built for, but planes
track *a table's* progress; nothing tracks *the book's* order of revelation.

## The model

Reify the mention. Today an appearance is an edge; make it a node so things can
be said about it.

```
        (:Entity:NPC {id, name})
           ▲                  ▲
   REFERS_TO                   ALIAS_OF
           │                  │
   (:Mention {chapter_slug,    │
              chapter_index,   │
              section_heading, │
              section_index,   │
              evidence})       │
           └──── USES_ALIAS ──▶ (:Alias {name, normalized})
```

Three nodes, three edges. `REFERS_TO` and `ALIAS_OF` both point at the entity, so
the entity is reachable from either side; `USES_ALIAS` records which name the
book used *at that point*, which is itself story information — the party meets
"the devil Strahd" long before they meet Strahd von Zarovich.

### What each carries

**`:Entity`** — unchanged from `feat/unique-entities`. Globally unique for
people, items, factions, lore; chapter-and-key scoped for places. Type is a
label, not a property.

**`:Alias`** — one node per distinct surface form. `normalized` is
lowercase, trimmed, with U+2019 folded to `'`, and is the lookup key. The
entity's own canonical name is itself an `:Alias`, so lookup has one path
rather than two.

**`:Mention`** — one node per (entity, section) pair. Not per occurrence: two
sentences about Ireena in the same section are one mention. `chapter_index` and
`section_index` are the ordering key, and they are the whole reason this is a
node.

### Ordering is the point

`(chapter_index, section_index)` is the order the book reveals things. That makes
progression a range query rather than a bookkeeping problem:

```cypher
// What can be said about Strahd by the end of chapter 3?
MATCH (a:Alias)<-[:USES_ALIAS]-(m:Mention)-[:REFERS_TO]->(e:Entity {name:'Strahd von Zarovich'})
WHERE m.chapter_index <= 3
RETURN a.name, m.section_heading, m.evidence
ORDER BY m.chapter_index, m.section_index
```

## What this replaces

`feat/unique-entities` introduces `MENTIONED_IN` as an *edge* from entity to
chapter. This supersedes it: the edge becomes a `:Mention` node carrying the same
properties plus evidence, and gains the ability to be referred to. Reifying an
edge into a node is mechanical — do not rebuild the extraction to get there.

## What does NOT change

- Entity identity and the type-as-label work land first and stay as they are.
- Spatial containment (`CONTAINS` / `LOCATED_IN`) stays entity-to-entity. A room
  is inside another room regardless of who mentions it.
- The `accepted` / `proposed` split on relationship edges stays. It is orthogonal:
  mentions are deterministic, dramatic relationships are not.
- Atomicity: one transaction per chapter, still pinned by tests that fail if the
  writer commits per statement.

## Cost, stated plainly

Mentions will outnumber entities heavily — chapter 3 alone would produce a few
hundred. Across the book, thousands of nodes whose only job is to say "this thing
appears here". That is cheap for Neo4j and it is real weight in the model.

Queries get a hop longer. "What do we know about Strahd" stops being properties
on a node and becomes an aggregation over mentions. That is the trade being made
deliberately: the graph gets harder to read in exchange for being able to answer
*when* something is known.

This is more structure at a moment when the project is deliberately deleting
structure, and the distinction matters. The machinery being cut —
consensus voting, the gazetteer filter, the constraint table, the review queue —
exists to compensate for unreliable extraction. This exists to model something
true about the domain. A DM assistant that cannot tell what has been revealed is
broken in a way no extraction quality fixes.

## Open questions, to settle during implementation

**Do aliases come from extraction or by hand?** The extractor already produces
name variants as separate candidates — that is part of why `Ismark` and `Ismark
Kolyanovich` both exist. Folding those into aliases of one entity is exactly the
merge this design wants, but merging by string similarity is the loose matching
this project has been burned by twice. Start with aliases authored by hand or
taken from the seed file, and treat extractor-proposed aliases as `proposed`.

**Does a mention carry claims, or just evidence?** This spec says evidence — the
span of text. Attaching structured claims to mentions is the natural next step
and should not be built until something needs it.

## Success criteria

1. `where_is("Ismark")` and `where_is("Ismark Kolyanovich")` return the same
   entity, and so does the curly-apostrophe form of any name that has one.
2. The three name-mismatch misses from the 20-question probe become hits, with no
   fuzzy matching anywhere in the lookup path.
3. A range query over `chapter_index` returns strictly fewer facts than an
   unbounded one for at least one entity — demonstrating that revelation order is
   actually captured rather than merely modelled.
4. Node and edge counts for the three loaded chapters, before and after, with the
   mention count stated separately so the weight of the change is visible.
