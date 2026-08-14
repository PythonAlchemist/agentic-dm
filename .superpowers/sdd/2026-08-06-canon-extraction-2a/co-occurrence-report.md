# Co-occurrence: which entities the book names in the same sentence

**Branch:** `feat/co-occurrence` off `main` (`53e8f2c`)
**Spec:** `docs/superpowers/specs/2026-08-14-mention-weight-design.md` §2 only.
§1 is the `53e8f2c` this branches from; §3 was read and is untouched.

## The headline number

**100 `CO_OCCURS_WITH` edges over 153 mentions — 0.65 per mention.**

It did not explode. The design asked for this figure because a sentence naming
*n* entities is *n(n-1)* edges, so the total is quadratic in the widest span the
boundary rule admits. The widest sentence in the three loaded chapters names
**three** entities, which is six edges, and there is no second tier: no mention
in the corpus co-occurs with more than two others.

```
out-degree      mentions
   0              83        54%  — the mention's sentence names nothing else
   1              40
   2              30
   3+              0
```

100 edges resolve to **41 distinct unordered entity pairs**, split
`the-village-of-barovia` 76 / `introduction` 24 / `foreword` 0. The foreword's
four mentions are in four different sentences, which is the honest answer for a
chapter of Tracy Hickman writing about 1983.

The verdict the design wanted: **the sentence rule is tight enough to keep.** A
section-granular version of the same query over the same graph returns edges for
every pair in a room description; the sentence cuts that to 0.65 per mention
without any filtering, thresholding or model.

## The worst single sentence

Two sentences tie at three entities. Chapter 3's:

> They include the barkeep, three Vistani sitting together, and a man named
> Ismark Kolyanovich—who happens to be the son of the village burgomaster,
> Kolyan Indirovich.

— `Vistani`, `Ismark Kolyanovich`, `Kolyan Indirovich`, 6 edges. And the
introduction's:

> Adventurers from a foreign land find themselves in Barovia, a mysterious realm
> surrounded by deadly fog and ruled by Strahd von Zarovich, a vampire and
> wizard.

— `Barovia`, `Strahd von Zarovich`, `vampire`, 6 edges. Both are genuinely one
sentence and both genuinely name three things. There is no case in this corpus
where the span rule swallowed a paragraph and called it a sentence.

## The most-connected entities, and what that says

| by incoming edges | | by distinct partner entity | |
|---|---|---|---|
| Strahd von Zarovich | 10 | Castle Ravenloft | 7 |
| Barovia | 8 | Barovia | 6 |
| **vampire** | 8 | Strahd von Zarovich | 6 |
| Castle Ravenloft | 7 | Vallaki | 5 |
| Vallaki | 6 | **vampire** | 4 |
| Mad Mary's Townhouse | 4 | Donavich | 3 |

**`vampire` is third, and that is a finding about `vampire`, not about
co-occurrence.** It is the node §3 exists to delete: a category the book uses as
a common noun, tied for second by incoming edges purely because the sentence
introducing Strahd also says "a vampire and wizard". Every one of its eight
edges is the same claim restated — that Strahd is a vampire — which §3 will
record as a `:Undead` label on Strahd and then remove the node. This is the
clearest measurement of that node's junkiness the project has yet produced, and
it came free.

`light` does **not** appear. It has mentions but never shares a sentence with
another entity, which is what a common noun scattered through prose looks like
under a sentence-granular rule and is a mild point in the rule's favour.

Otherwise the ranking is exactly the campaign's spine: Strahd, Barovia, Castle
Ravenloft, Vallaki. Nothing absurd surfaced.

## What was built

`backend/canon/cooccurrence.py`, new, depending on `passage` and `spine`:

- `plan_co_occurrences(sections, mentions) -> list[CoOccurrence]` — the pairs.
- `co_occurrence_counts(planned, names_by_id)` — the ranking above, printed on
  every write beside the mention census.
- `widest_sentence(...) -> WidestSentence | None` — the number to watch, with
  the prose, so a boundary rule coming loose in chapter 12 is visible in that
  chapter's own output rather than in a slow query six months later.

The span rule is **imported, not restated**. `passage.sentence_bounds` decides
what one sentence is, here and in `lookup`, and nothing in this module looks at
punctuation. Five tests exercise the shared rule from this side —
`St. Andral's Church`, `area K42.`, `appendix D.`, a table row, a heading over
prose — and each one asserts that two entities either side of a *doubtful*
period do co-occur, which is only true because the rule refuses to split there.

In the graph: `(:Mention)-[:CO_OCCURS_WITH]->(:Entity)`, MERGEd on the pair, no
properties. It carries no `status`: the `accepted`/`proposed` split exists
because a model guessed a typed relationship and a hand read found a third of
the guesses wrong, and there is nothing here for a reviewer to accept. It sits
with `MENTIONED_IN` and `DESCRIBES` on the deterministic side, as a bare string
in `schema.py` rather than a `RelationshipType` member.

**No relationship is inferred from it, and nothing in the module could.** There
is no type, no weight, no score.

## Deviation: the pair is mutual, not one-directional

**One deviation from the literal spec, and it is worth one edge.**

The spec says "the other entities whose own mention offsets fall inside the same
derived sentence span". Implemented literally — B pairs with A iff B's offset is
inside A's span — the corpus produces **99** edges, one of which has no partner
in the other direction:

> Inside are a tinderbox, a few wooden boxes full of candles, and two well-used
> books: *Hymns to the Dawn* … and *The Blade of Truth: The Uses of Logic in the
> War Against Diabolist Heresies, as Fought by the Ulmist Inquisition*, …

That sentence is over 300 characters, so `sentence_bounds` falls back to a
**window** placed around the offset it was asked about. `tinderbox`'s window
reaches the 87-character book title; the title's window, anchored 137 characters
later, does not reach back to the tinderbox. The graph would have said the
tinderbox co-occurs with the book and the book with nothing.

The 300-character cap exists so a rendered passage stays readable. **A rendering
budget may not decide the direction of a symmetric fact.** So two offsets pair
when *either* falls inside the other's span. Below the cap this is one test
written twice — both offsets in one sentence derive the identical span — so it
changes exactly this one pair, and the total is 100 rather than 99. It is not a
second span rule: `sentence_bounds` is still the only thing that decides where a
sentence ends.

A test pins it (`test_a_sentence_over_the_passage_cap_is_still_symmetric`) and
dies under the one-directional implementation.

## The limitation, stated rather than papered over

**83 of 153 mentions co-occur with nothing, and roughly half of that is the
`offset` field, not the prose.** A `:Mention` stores one offset — where the
section *first* says the name. An entity named in sentences 1 and 5 is anchored
in sentence 1, so a pairing it makes only in sentence 5 is invisible.
`test_a_shared_later_sentence_is_not_seen` pins this as a known consequence.

Widening it means storing every span rather than the first, which is a change to
what a `:Mention` *is* and would multiply the edge count by an unmeasured
factor. It was not made here. The figure to carry forward is that **100 is a
floor, not the true count**, and the true count is bounded by whatever
per-occurrence anchoring would cost — which should be measured before it is
built, on the same three chapters.

## Tests

**44 new tests.** 25 pure (`tests/test_canon/test_cooccurrence.py`), 19 against
a live Neo4j or the CLI formatter (`test_write_canon_neo4j.py`,
`test_write_canon_cli.py`). Whole repo: **1389 pass**, with 12 pre-existing
failures in `test_ner` / `test_rag` (pyahocorasick, untouched by this branch and
failing identically on `53e8f2c` — confirmed by stashing the diff and re-running).

**Every behaviour test was watched failing, and then mutation-tested.** Seven
mutations of the planner and seven of the writer were applied one at a time; the
tests that died under each are recorded below. Two tests survived every mutation
and were **deleted or replaced** rather than shipped:

- `assert len(planned) == len(set(planned))` — the duplicate guard. It could not
  fail: a `:Mention` carries one offset, so no offset-based planner can emit a
  row twice. The guard that *can* fail is live — the graph's edge count compared
  against `len(plan)`. The write MERGEs, so a plan emitting a row twice would
  land one edge and the two numbers would part. That is the exact failure mode
  the brief warned about (a `set` absorbing duplicate rows), and it is now the
  only place it can be caught.
- `test_a_replace_is_not_refused_by_the_campaign_data_check` — passed before and
  after. `_delete_chapter`'s campaign-data check excludes `CO_OCCURS_WITH` by
  Cypher null semantics whether or not the type is listed, exactly as the
  existing comment records for `ALIAS_OF`. The constant is listed anyway as a
  statement of intent, the no-op is documented in the docstring, and the test was
  replaced by one that *can* fail: `deleted_edges` must not count
  co-occurrences, which would break the moment anyone put a `chapter_slug` on
  the edge.

| mutation | tests that died |
|---|---|
| pair at section granularity | 6 |
| no self-entity guard | 18 |
| one-directional (drop the mutual rule) | 1 |
| skip a missing section instead of raising | 1 |
| unordered output | 1 |
| span leaks 40 chars past the sentence | 6 |
| pair once per unordered pair (half the rows) | 11 |
| nothing written to the graph | 7 |
| only half the directions written | 6 |
| edge carries `chapter_slug` and `plane` | 1 |
| missing endpoint skipped, not raised | 1 |
| written *before* the mentions | 14 |
| summary reports a count other than the plan's | 1 |

## Atomicity

Unchanged. `plan_co_occurrences` runs inside `_write_tx`, planned from the
mentions that transaction just wrote, and every edge is written before the
transaction returns. `test_they_share_the_chapters_one_transaction` raises on an
edge whose endpoint no node creates — *after* nodes, sections, mentions and
co-occurrences have all been written inside the transaction — and asserts the
graph holds none of them. The mutation that reorders co-occurrence before the
mention writes kills 14 tests.

Co-occurrences are removed by the existing `DETACH DELETE` of a chapter's
mentions. They are deliberately **not** given a `chapter_slug`: `deleted_edges`
is the figure a human compares against `written_edges`, and sweeping the
co-occurrence graph into it would make that comparison unreadable.

## Verifier

**8/8 on all three chapters, unchanged.** Not assumed — run and read:

```
foreword-ravenloft-revisited   4 nodes,  0 edges   PASSED
introduction                  22 nodes,  2 edges   PASSED
the-village-of-barovia        53 nodes, 84 edges   PASSED
```

The edge counts are identical to before the change. The verifier's edge query is
`MATCH (a:Entity)-[r]->(b:Entity) WHERE r.chapter_slug = $slug`;
`CO_OCCURS_WITH` runs `Mention → Entity` and carries no `chapter_slug`, so it is
invisible to that query on both counts. `verifier.sh` was not modified.

## Re-migration

All three loaded chapters re-migrated from `data/canon/runs/*.json` with
`--replace`. **Nothing was re-extracted; no model was called and no money spent.**
Mentions 153 → 153, entities 58 → 58, and every pre-existing relationship type
holds its previous count exactly. The only change to the graph is 100 new edges
of a new type.
