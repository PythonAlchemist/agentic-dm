# Aliases, and the eight

**Branch:** `feat/canon-aliases`, off `main` at `e1b1ab1`
**Commit:** `0bb8f80`
**Spec:** `docs/superpowers/specs/2026-08-14-narrative-spine-design.md`, the alias half

---

## The number

**Strahd von Zarovich has 8 mentions in chapter 3**, one per section that names
him: 0, 2, 5, 7, 14, 15, 20, 21. Before this work he had 1.

The distance between 1 and 8 is one line of YAML. The matcher is byte-for-byte
the one `e1b1ab1` shipped -- still whole-word, still case-sensitive for a
single-word name, still folding U+2019 and nothing else. Nothing infers that
`Strahd` and `Strahd von Zarovich` name one man; a human wrote it down.

The preamble is the section the design predicted it would be:

| § | heading | occ | spellings the book used |
| ---: | --- | ---: | --- |
| 0 | Chapter 3: The Village of Barovia | 6 | `Strahd von Zarovich` ×1, `Strahd` ×5 |
| 2 | House Occupants | 4 | `Strahd` ×4 |
| 5 | E2. Blood of the Vine Tavern | 5 | `Strahd` ×5 |
| 7 | E4. Burgomaster's Mansion | 4 | `Strahd` ×4 |
| 14 | E5f. Chapel | 1 | `Strahd` ×1 |
| 15 | E5g. Undercroft | 1 | `Strahd` ×1 |
| 20 | March of the Dead | 1 | `Strahd` ×1 |
| 21 | Dream Pastries | 3 | `Strahd` ×3 |

That table is `USES_ALIAS`, and it is the story information the design asked
for: the book introduces him in full once, in the preamble, and calls him
`Strahd` for the rest of the chapter.

The before is kept beside the after.
`test_without_the_alias_the_same_scan_finds_one` runs the identical scan over
the identical sections with the alias removed and asserts **1**. If that ever
also returns 8, the matcher has been loosened and the alias node is doing
nothing.

---

## What was built

```
(:Entity) <-[:ALIAS_OF]- (:Alias {name, normalized})
(:Mention) -[:USES_ALIAS {occurrences}]-> (:Alias)
```

### `:Alias` is keyed on the surface form, and is global

One node per distinct spelling, shared across entities. Two things answering to
`Barovia` would be one `:Alias` with two `ALIAS_OF` edges -- the graph saying
the name is ambiguous rather than quietly picking one. That is also why
`resolve_name` returns a **list** and never a best guess.

Keyed on `name` rather than on `normalized`, so `Bildrath's Mercantile` and
`Bildrath's Mercantile` (U+2019) are two nodes. They normalize alike and both
resolve to the same shop; keeping them separate is the only way a mention can
record which of the two the section actually set.

### The canonical name is itself an `:Alias`, for every canon entity in the plane

`_BACKFILL_ALIASES` runs inside every chapter's transaction, after the delete
and before the scan, and gives **every** canon entity its own name as an
`:Alias` -- not only the ones the chapter wrote.

This is the one place a chapter's write deliberately reaches beyond its own
chapter, and the exception is narrow: it asserts nothing a chapter could
disagree with, because the name is already on the entity. What it buys is that
"resolve a name through `:Alias`" is TOTAL rather than a rule with a migration
hole in it. Without it, an entity written before aliases existed -- or by
`seed_loader.load_seed`, which writes canon nodes and knows nothing about any of
this -- would be unreachable by name and invisible to the scan. A silent zero,
which is the failure the whole narrative-spine design exists to remove.

`_known_entities` therefore reads names through `ALIAS_OF` **and nowhere else**,
and **raises** if a canon entity reaches it with no alias.
`test_resolving_a_name_never_reads_the_entitys_own_name_property` deletes an
entity's `ALIAS_OF` edge, asserts `e.name` still says what it is called, and
asserts the lookup finds nothing -- which is what proves the read path has one
source rather than two that could drift.

### `normalized` is three operations and it is checkable that it is only three

Lowercase, trim, U+2019 → `'`. `test_aliases.py` spends more assertions on what
normalization does NOT do than on what it does:

- it does not strip punctuation (a slug would; `The Blade of Truth: …` keeps its
  colon, so two titles differing only by punctuation stay two names)
- it does not collapse internal whitespace
- it does not strip a leading article (`The Village of Barovia` ≠
  `Village of Barovia`; both are recorded, neither is inferred)
- a prefix is not the same name
- a token subset is not the same name -- the specific match that let a candidate
  `Ireena` credit the quest `Escort Ireena to Vallaki`

**One duplication, and it is pinned.** `_BACKFILL_ALIASES` is Cypher and cannot
call `normalize`, so the rule is written twice.
`test_the_backfills_cypher_normalisation_agrees_with_the_python_one` feeds a
name that is padded, mixed-case AND curly, so all three operations have to
agree; three mutants (drop the fold, drop the trim, drop the lowercase) are each
caught by it.

### Two new rules in the scan, neither a similarity judgment

**The longest match wins an overlap.** `Strahd` matches inside `Strahd von
Zarovich`, so a section that spells him out in full produces two exact
whole-word matches over one run of text -- and named him once. Counting both
would make `occurrences` a count of recorded aliases rather than of appearances,
and would put a `USES_ALIAS` edge on a spelling the book did not use. Ties go to
the earlier span, then to the alphabetically first form, so the output is fully
determined.

**A span attributes to the form that spells it best**, in three tiers, each an
exact string equality under a transformation named in full: identical; identical
once U+2019 is folded; identical once case is dropped. Both spellings of
`Bildrath's Mercantile` match the book's curly setting, and only one of them is
what the section says.

Both rules are no-ops for an entity with a single recorded name, which is what
lets every pre-existing scan test pass unchanged.

### Where the aliases live

A third block in `backend/canon/seeds/location-subtypes.yaml`, beside the
location rungs and the artifact list -- one hand-authored file, one loader, one
matching rule (the slug of `name` or of any spelling under it, so a single entry
covers a straight and a curly apostrophe and does not need to know which the
provenance tiebreak minted the node under).

`validate_aliases` refuses three things, each silent in the graph otherwise: an
entry with no spellings, a spelling that slugifies to nothing, and two entries
reaching one slug with different sets of spellings. Two entries that AGREE are
fine -- the same claim written twice is not a contradiction.

---

## The aliases, and why each one

**13 authored spellings; 71 `:Alias` nodes** = 58 canonical names + 13.

| entity | alias | why |
| --- | --- | --- |
| Strahd von Zarovich | `Strahd` | 8 of chapter 3's 22 sections; the measurement this design was built on |
| Ismark Kolyanovich | `Ismark` | the chapter's prose never spells his patronymic; only his NPC block does |
| Ismark Kolyanovich | `Ismark the Lesser` | the book's own epithet, in the tavern section |
| Ireena Kolyana | `Ireena` | 5 sections across the three chapters; the extractor emits both as separate candidates |
| The Village of Barovia | `Village of Barovia` | the settlement, written both ways |
| Krezk | `Village of Krezk` | ditto, in the introduction |
| Blood of the Vine Tavern | `Blood on the Vine Tavern`, `Blood on the Vine` | the book names it differently **on purpose**: the sign outside is defaced so an "n" is scratched over the "f", and §5 uses both spellings in adjacent paragraphs |
| Bildrath's / Burgomaster's / Mad Mary's / Donavich's / Doru's | the ASCII twin of each curly possessive | the graph minted these with U+2019; recording both is what lets `USES_ALIAS` state which typography a section set, rather than leaving it inferred from the fold |

### What was measured and deliberately rejected

- **`Barovia` for the village.** The region and the settlement share a word and
  are different places. The alias would fold thirteen mentions of the valley
  into the village. Pinned by a test.
- **`Mary` for Mad Mary.** It matches -- in the foreword, where the Mary is Mary
  Shelley. The alias would have credited Mad Mary with *Frankenstein*. This is
  the bar an entry has to clear and it is one line away in every direction.
  Pinned by a test.
- **`Count Strahd`** (introduction §0): real, but `Strahd` already covers it and
  a title is not a name.
- **`Church of Barovia`**: zero occurrences in the loaded corpus.
- **`Bildrath` alone**: it is the shopkeeper's name, and the shop is a different
  entity. An alias would have merged a person into a building.

---

## Counts

| | before | after |
| --- | ---: | ---: |
| canon entities | 58 | 58 |
| `:Alias` nodes | 0 | **71** |
| `ALIAS_OF` edges | 0 | **71** |
| `:Mention` nodes | 135 | **149** |
| `USES_ALIAS` edges | 0 | **160** |
| `:Section` / `:Chapter` / `:Book` | 36 / 3 / 1 | 36 / 3 / 1 |
| `DESCRIBES` edges | 13 | 13 |
| canon ontology edges | 86 | 86 |
| entities with no `:Alias` | 58 | **0** |
| mentions with no `USES_ALIAS` | 135 | **0** |
| mentions with an empty evidence span | 0 | **0** |

Per chapter: foreword 4, introduction 44, chapter 3 101.

Aliases add **14 mentions**, not hundreds. That is the honest shape of the
change: they matter enormously for a handful of entities the book refuses to
name in full, and not at all for the rest.

**Re-migrated from `data/canon/runs/*.json` with `--replace`. No re-extraction;
no model was called.**

### The migration needs two passes, and that is the documented limitation biting

`plan_aliases` is fed the nodes **this chapter writes**, so the alias `Village of
Barovia` is authored when chapter 3 writes that node. The introduction, written
first, therefore scanned without it and came back with 43 mentions; on the
second pass, with chapter 3 already in the graph, it found 44.

This is exactly the cross-chapter limitation `e1b1ab1` stated -- writing chapter
4 does not re-scan chapter 3 -- now visible for aliases as well as for entities.
The remedy is the same and costs nothing: write every chapter again. Two passes
reached a fixed point at **4 / 44 / 101 = 149**, confirmed by a third pass
returning identical figures. A loop writing chapters in book order should expect
to converge on its second lap rather than its first.

---

## The verifier: unchanged, 8/8, and the counts checked rather than assumed

`~/.claude/skills/canon-to-neo4j/verifier.sh` was **not edited**.

```
foreword-ravenloft-revisited   PASS 1..8   (4 nodes, 0 edges)    VERIFIER PASSED
introduction                   PASS 1..8   (21 nodes, 2 edges)   VERIFIER PASSED
the-village-of-barovia         PASS 1..8   (51 nodes, 84 edges)  VERIFIER PASSED
```

The brief asked me to verify rather than assume that more mentions per entity
changes no count it makes. Measured directly, by computing check 1's node set
twice -- once as it is, once restricted to mentions whose `USES_ALIAS` names the
entity's own canonical spelling, which is exactly the pre-alias set:

| chapter | check-1 nodes without aliases | with | delta |
| --- | ---: | ---: | --- |
| foreword | 4 | 4 | — |
| introduction | 21 | 21 | — |
| the-village-of-barovia | 50 | **51** | **+`Ismark Kolyanovich`** |

**One count moves, and it moves up.** Check 1 walks `Mention → Section →
Chapter` with `DISTINCT`, so its node set is "entities this chapter NAMES".
More occurrences of an entity cannot change it; a new entity CAN, and chapter 3
gains exactly the one whose full name its prose never writes. That is the
feature, arriving in the number that measures it.

Nothing else can move, and each for a structural reason rather than a lucky one:

- **Checks 2, 3, 4, 8** read `MATCH (a:Entity)-[r]->(b:Entity) WHERE
  r.chapter_slug = $slug`. An `:Alias` is not an `:Entity`, so `ALIAS_OF` and
  `USES_ALIAS` cannot match that pattern at all; and neither carries a
  `chapter_slug`, so they would fail the predicate even if it could. Edge counts
  are unchanged at 0 / 2 / 84.
- **Check 5** reads node ids. `Ismark Kolyanovich` is `cos:ismark-kolyanovich`
  -- global, one colon -- so it passes the scoping rule.
- **Check 7** reads the run artifact's filter counts, and `plan_write` is
  untouched by this work.

Two checks the previous report proposed (a non-empty evidence span, and a
chapter having a spine at all) are still the owner's call and still unwritten.
Both now read 0 and 36 respectively.

---

## Lookup: the alias path is reachable, and `feat/canon-lookup` is worth
rebasing as its own piece of work

`backend/canon/aliases.resolve_name(session, name)` is the read path and the
only one there should be. It normalizes, hits `:Alias.normalized`, follows
`ALIAS_OF`, returns every entity id that answers, sorted. It never reads
`e.name`.

Against the migrated graph, every requested pair resolves to one entity, with
nothing fuzzy anywhere in the path:

```
Ismark              / Ismark Kolyanovich      -> cos:ismark-kolyanovich
Strahd              / Strahd von Zarovich     -> cos:strahd-von-zarovich
Village of Barovia  / The Village of Barovia  -> cos:the-village-of-barovia
Bildrath's Merc.    / Bildrath’s Merc.        -> cos:…:e1-bildrath-s-mercantile
Burgomaster's M.    / Burgomaster’s M.        -> cos:…:e4-burgomaster-s-mansion
Mad Mary's T.       / Mad Mary’s T.           -> cos:…:e3-mad-mary-s-townhouse
Donavich's Bedroom  / Donavich’s Bedroom      -> cos:…:e5c-donavich-s-bedroom
Doru's Bedroom      / Doru’s Bedroom          -> cos:…:e5b-doru-s-bedroom
Blood on the Vine   / Blood of the Vine Tav.  -> cos:…:e2-blood-of-the-vine-tavern
Ireena              / Ireena Kolyana          -> cos:ireena-kolyana
```

And the negative half, which is the half that matters:

```
'Ismar'  'Strah'  'Ismark Kol'  'Mary'  'Barovia Village'  'the Strahd'  ->  nothing
```

### On rebasing `feat/canon-lookup` (`73d49bd`)

I cherry-picked it to find out. **It applies to `main` with no textual conflict
and all 48 of its tests pass.** I reverted it anyway, and the reason is a
finding rather than a preference.

Its tests pass **only because they write `section_heading` and `section_index`
onto their own fixture nodes** -- two properties `e1b1ab1` deleted from
`WriteNode`. Run against the real graph, the branch answers:

```
where_is('Ismark Kolyanovich')  -> found, section=None, section_index=None
where_is('Ismark')              -> MISS: name_not_in_graph
where_is("Bildrath's Mercantile") -> MISS: "the graph spells it 'Bildrath’s Mercantile'"
```

So it is textually clean and semantically stale, and its test suite cannot see
the difference -- a suite that passes both before and after the defect it
guards, which is the eleventh-test pattern this project keeps paying for.

That makes the rebase **worth doing and a separate task**, with three items:

1. `_match` becomes `resolve_name` -- roughly ten lines, and it fixes the second
   and third misses above outright.
2. `section` / `section_index` must be re-derived from the spine (the first
   `:Mention` in `(chapter.index, section.index)` order) in `_NODE_FIELDS` and
   in the three tool queries. This is the real content of the rebase.
3. `tests/test_canon/test_lookup.py` must build its fixtures through a spine
   instead of setting the two dead properties by hand, or item 2 lands with the
   same blind spot it has now.

Bundling 900 lines of an unreviewed second feature into the alias branch would
have made both harder to review, and item 2 is not alias work.

---

## Testing

**1070 tests pass** across `tests/test_canon` + `tests/test_graph` (999 on
`main`, so +71), of which **114 are the live-Neo4j set** marked
`@pytest.mark.neo4j`. 1301 pass across the whole suite; the 12 failures in
`tests/test_ner` and `tests/test_rag` are **pre-existing** -- confirmed by
stashing this branch and re-running, identical 12, missing gazetteer data files.

Ruff clean (`E,F,I,UP`, line-length 100) on every file this branch touches.
`backend/graph/schema.py` carries 42 pre-existing findings, unchanged: `ruff
--fix` initially rewrote them along with unrelated churn in
`backend/graph/operations.py`, `backend/scripts/ingest_pdf.py` and
`tests/test_canon/test_depth_sections.py`, and all of that was reverted. The 19
lines this branch adds to `schema.py` are clean.

### Every rule was watched failing: 32 of 33 mutants caught

Not by writing a test and watching an ImportError. Each rule was broken one at a
time in the shipped code and the suite re-run.

**`spine.py` — 10/10.** Aliases ignored ¦ overlaps not suppressed ¦ shortest
match wins ¦ both spelling tiers collapsed (separately) ¦ `USES_ALIAS` never
recorded ¦ uses ordered by name not frequency ¦ evidence quotes the last
occurrence ¦ spans in match order not reading order ¦ an uncompilable form
matching everything.

**`aliases.py` — 8/8.** Each of the three normalization steps dropped ¦
normalization gaining a fourth step (punctuation stripping) ¦ the entity's own
name dropped from its aliases ¦ the seed matched on raw name instead of slug ¦
a blank surface form kept ¦ resolution falling back to reading `e.name`.

**`seed_loader.py` — 2/2.** Both validator refusals.

**`writer.py` — 12/13.** Aliases written after the scan ¦ the backfill dropped ¦
each of the three Cypher normalization steps ¦ a missing alias endpoint written
silently ¦ `USES_ALIAS` not written ¦ an aliasless entity skipped instead of
refused ¦ the scan reading `e.name` as well ¦ a replace leaving `ALIAS_OF`
behind ¦ the orphan sweep deleting non-orphans ¦ the orphan sweep unscoped.

**Four mutants survived the first pass** and were the reason for four new or
strengthened tests: the U+2019 spelling tier had no test; `occurrences` and
`offset` were pinned only by single-occurrence fixtures, so "the FIRST
occurrence" was unguarded in two ways; and the Cypher/Python normalization
duplication had nothing holding it together.

**The one deliberate survivor** is listing `ALIAS_OF` in `_delete_chapter`'s
campaign-data exemption. It is provably a no-op: `ALIAS_OF` carries no
`chapter_slug`, so `NOT (r.plane = $plane AND r.chapter_slug = $slug)` evaluates
to `NOT (true AND null)` = null, which a `WHERE` already excludes. It is kept
because those three types are exactly the ones that function deletes and a
reader should see the set in one place, and it is recorded here and in the
docstring rather than papered over with a test that would not fail.

### Atomicity

Unchanged and re-pinned for the new writes.
`test_a_failed_write_leaves_no_alias_behind` gives a write both an authored
alias and an edge whose endpoint no node creates; the alias, the backfill, the
sections and the mentions have all been written inside the transaction by the
time `_write_edge` raises, and none survives. A writer committing as it went
would leave a name index behind for a chapter that does not exist.

### One test-hygiene finding, and the code change it caused

**The mutation harness corrupted the live graph, and that exposed a real
over-broad delete.**

`_delete_chapter`'s orphan sweep was `MATCH (a:Alias) WHERE NOT
(a)-[:ALIAS_OF]->() DETACH DELETE a` -- correct, and unscoped. A mutant that
changed it to `WHERE true` ran against the shared local database (the live-Neo4j
tests share it with the real book, as `NAME_MARKER` already records) and deleted
**every `:Alias` node in the graph**, taking all 160 `USES_ALIAS` edges with
them. The backfill silently restored the 58 canonical names on the next write,
so the damage read as "the authored aliases are gone" rather than as anything
loud.

The sweep is now scoped to the alias names that delete just unpicked, collected
before the `ALIAS_OF` edges are removed. A delete should not be able to reach
what it never touched, and being one bad edit away from a chapter rewrite
emptying the book's whole name index is not an acceptable distance.
`test_a_replace_cannot_reach_an_alias_it_never_touched` creates a bystander
orphan and asserts a full replace leaves it standing; both the unscoped form and
the drop-the-emptiness-test form are caught.

The graph was re-migrated from the run artifacts afterwards and is at its fixed
point.

---

## Deviations, all deliberate

1. **`feat/canon-lookup` was not rebased.** Assessed, cherry-picked, measured,
   reverted -- see above. The alias path is reachable through `resolve_name`,
   which is the function that rebase should call.
2. **`_BACKFILL_ALIASES` writes outside the chapter.** The one place a chapter's
   write touches another chapter's nodes, justified above: it asserts only what
   the entity's own `name` property already says, and it is what removes the
   migration hole from the single-path rule.
3. **`_known_entities` raises** on a canon entity with no alias, rather than
   skipping it. A skipped entity contributes no mentions and is unreachable by
   name; the backfill makes the condition unreachable in practice, so the raise
   is a tripwire rather than a path.
4. **The migration converges on the second pass**, not the first. See above.
5. **`write_chapter` takes `aliases` as an optional positional.** Optional
   unlike `spine`, and not the same concession: it carries only the
   HAND-AUTHORED extras, a chapter with none is the ordinary case, and every
   entity gets its own name regardless from inside the transaction.
6. **`docs/neo4j-canon.grass` still not updated**, as at `e1b1ab1`. It now also
   wants entries for `:Alias`, `ALIAS_OF` and `USES_ALIAS`. `:Alias` should be
   small and pale for the same reason `:Mention` should: there are more of them
   than of the things they name.

---

## One finding out of scope, and it is worth someone's time

**Three entities have zero mentions anywhere, and it is not an alias problem.**
The previous report listed `Tome of Strahd`, `Hymns to the Dawn` and `The Blade
of Truth: …` as "alias-shaped -- canonical names the prose never spells in
full". Measured, that diagnosis is wrong. The prose *does* spell all three in
full. It sets them in markdown emphasis:

```
_Tome of Strahd_        _Hymns to the Dawn_        _The Blade of Truth: …_
```

`_` is a word character, so the matcher's `(?<!\w)` refuses the match one
character before the name begins. `Blade of Truth` matches in the same sentence
purely because a space precedes it.

No alias can fix this -- the canonical name is already correct and the failure is
in the lookaround meeting markup rather than prose. The fix is one character:
treat `_` as a boundary (`(?<![^\W_])`), which is exact and not a loosening,
since a markdown emphasis delimiter is not part of the word the book wrote. I
did not make it. It would move mention counts across every chapter, it is a
matcher change in a task whose entire premise is that the matcher does not move,
and it deserves its own before-and-after. Recording it here with the measurement
so the next person does not re-diagnose it as aliases.
