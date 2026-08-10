# Canon Extraction 2a: Sections, Layer Passes, and Grading

**Date**: 2026-08-06
**Status**: Approved, not yet implemented
**Parent**: [2026-08-05-canon-campaign-graph-design.md](2026-08-05-canon-campaign-graph-design.md)
**Depends on**: [2026-08-06-canon-ontology-resolver-design.md](2026-08-06-canon-ontology-resolver-design.md) (stage 1, merged)

## Context

Stage 1 built the ontology and the two-plane resolver. This is the first third of stage 2:
turning the transcribed Curse of Strahd corpus into *candidate* entities and relationships,
and measuring how good they are.

**Stage 2 is decomposed into three specs.** 2a is where all the iteration and all the risk
live, and it is the only part with ground truth:

| | Contents | Done when |
|---|---|---|
| **2a** (this) | Section splitting, three layer passes, grading harness | Chapter 3 clears the bar below |
| 2b | Cross-chapter resolution and id minting | Duplicate collapse verified across chapters |
| 2c | Review gate and writing canon to Neo4j | Canon lands in the graph |

2b and 2c cannot be designed properly until we have seen what 2a produces.

### Corpus, as measured

A duplicate-page defect was found and fixed while designing this (commit `9e225f7`): the
source PDF is a flipbook export containing every page twice. Numbers below are post-fix.

| | |
|---|---|
| Pages | 258 (was 509) |
| Corpus | 209,902 tokens |
| Chapters | 25 |
| Chapter 3 — the graded one | 4,853 tokens, 8 H2 sections |
| Chapter 4 — the largest | 35,879 tokens, ~60 H2 sections |
| ChromaDB chunks | 269 |

Three layer passes over the whole corpus is ~630k input tokens: roughly **$0.15 with
`gpt-4o-mini`**. A single chapter-3 tuning iteration is ~15k input tokens — a fraction of a
cent, which is what makes an iterate-against-ground-truth loop practical.

## Design Decisions

### 1. The extraction unit is a section, packed to a token budget

Chapters are too big (chapter 4 is 35,879 tokens, and a single response enumerating its
entities would be enormous). Chunks are too arbitrary — they split mid-topic, so an entity
introduced in one and located in the next becomes two partial extractions that the
least-certain part of the pipeline has to merge.

Sections split on `##` headings, which are the seams the *author* chose, so related facts
mostly stay together. Section sizes vary a lot, so contiguous sections are **packed** into
units up to a token budget (1,500 tokens): tiny sections ride along with their neighbours
rather than wasting a call, and an oversized section stands alone.

### 2. Three passes per unit, one per layer

Each pass sees only its own layer's vocabulary. A spatial pass that knows only about
`CONTAINS` / `CONNECTED_TO` / `LOCATED_IN` produces markedly cleaner output than a general
"find entities and relationships" prompt, and it makes a bad layer diagnosable in isolation.

Layer vocabularies come from `LAYER_MAP` (stage 1) rather than being re-listed in prompts,
so adding a relationship type cannot silently leave the extractor unaware of it.

### 3. Candidates carry names, not ids

2a emits *candidates*: proposed nodes and edges identified by name, with provenance
(chapter slug, section heading, layer). Minting deterministic ids and collapsing
`Strahd von Zarovich` across twelve chapters is resolution's job, in 2b. Keeping 2a
id-free means the grading loop is not entangled with the dedup logic it would otherwise
have to be correct about first.

### 4. Recall is measured; precision is spot-checked

**Recall is computable.** The golden set's chapter-3 subset (18 nodes, 25 edges) is the
denominator: for each entry, did extraction produce a matching candidate?

**Precision is not computable against this key, and pretending otherwise would be worse
than not measuring it.** The golden set is *not exhaustive* — chapter 3 contains far more
nameable things than 18. A candidate with no golden match is usually a legitimate entity
the key simply doesn't list, not a fabrication. Scoring precision against a non-exhaustive
key would punish an extractor for being thorough and reward one for being timid.

So the harness reports:
- **recall**, as a number, against the chapter-3 subset
- **misses** — golden entries with no candidate, listed individually
- **unmatched candidates** — listed individually for human spot-check, explicitly *not*
  scored

"You missed Kolyan and invented a barkeep" is what makes the loop iterable; "precision
0.34" would be actively misleading.

### 5. The bar

**Recall ≥ 0.9 on the chapter-3 subset, and no fabrications in a hand-checked sample of
unmatched candidates.**

Precision matters more than recall in principle — under-extraction self-heals when a table
invents the missing entity as a campaign node, while a junk canon node pollutes every
campaign forever — but since precision cannot be automated here, the fabrication check is
a human gate rather than a threshold.

### 6. Matching is by normalized name

A candidate matches a golden node when their names normalize equal (lowercase, punctuation
and articles stripped) or when the candidate's name matches one of the golden entry's
`aliases`. An edge matches when its type is identical and both endpoint names match.

This is deliberately loose. Strict matching would fail on `Ismark` vs `Ismark the Lesser`
and turn recall into a measure of naming luck rather than extraction quality. Resolution
(2b) is where canonical naming gets decided; 2a should not pre-empt it.

### 7. Nothing writes to Neo4j

2a's output is a candidate set on disk plus a score. Keeping the graph out of the loop we
iterate on fastest means a tuning run cannot corrupt anything, and the expensive-to-verify
question (does the graph look right) is deferred to 2c where it belongs.

## Components

| File | Responsibility |
|---|---|
| `backend/canon/sections.py` | Chapter markdown → `Section`s on `##` headings; pack contiguous sections into `ExtractionUnit`s under a token budget. Pure text, no LLM. |
| `backend/canon/extract.py` | Three layer passes per unit. Returns `Candidate` records. Owns the prompts. |
| `backend/canon/grade.py` | Score a candidate set against a golden subset. Returns recall, misses, and unmatched candidates. Pure, no LLM. |
| `backend/canon/models.py` | Extend with `Section`, `ExtractionUnit`, `CandidateNode`, `CandidateEdge`, `GradeReport`. |
| `backend/scripts/extract_canon.py` | CLI: `--chapter`, `--layer`, `--grade`, `--limit`. |

Three of the five are pure functions with no external dependency, which is where the
testing leverage is.

## Data flow

```
chapter markdown
      │
      ▼
 sections.py ──► [Section] ──► pack ──► [ExtractionUnit]   (~1,500 tokens each)
                                             │
                                             ▼  × 3 layers
                                        extract.py ──► [Candidate]
                                             │
                                             ▼
                                         grade.py ◄── extractable_subset(seed, "ch3")
                                             │
                                             ▼
                             recall + misses + unmatched candidates
                                             │
                                             ▼
                                    tune prompts, repeat
```

## Testing

**Section splitting** gets real chapter markdown as fixtures, covering the three shapes the
corpus actually contains: chapter 3 (8 sections, normal), chapter 4 (~60 sections, many
small keyed rooms), and Appendix D (stat blocks, whose structure differs from prose).
Packing is tested on the boundaries — a section over budget stands alone, several tiny ones
combine, and no section is ever dropped or duplicated by packing.

**Extraction** is tested with a mocked client: prompt construction (does the spatial pass
carry only spatial vocabulary), response parsing, and malformed-response handling. No live
calls in tests.

**Grading** is tested against hand-built candidate sets where the score is known by
construction — a perfect set scores 1.0, a set missing one entry scores exactly
`(n-1)/n`, an alias-only match still counts, and a set containing a deliberately invented
entity surfaces it in `unmatched` rather than silently affecting the number.

## Out of scope

- Cross-chapter resolution and id minting (2b)
- The review gate and writing to Neo4j (2c)
- Extracting anything but chapter 3 at tuning time. Running the corpus is the *end* of 2a,
  after the bar is met, and even then only chapter 4 and Appendix D get hand-checked before
  a full run — spot-checks agreed during design, because chapter 3 is NPC-and-narrative
  heavy and says nothing about how ~60 keyed rooms or a stat-block appendix extract.

## Known risks

**Chapter 3 is unrepresentative.** It exercises the narrative layer hard — the
highest-value and highest-risk one, per the design consultation — but contains almost no
keyed-room structure and no stat blocks. Tuning to a high score there could leave us
confidently wrong about the other 60% of the corpus. Mitigation is the chapter-4 and
Appendix-D spot-checks before the full run, escalating to authoring a second golden slice
if either looks shaky.

**Sections carry no page attribution.** Chapter markdown is a concatenation with no page
markers, so a candidate's provenance is `(chapter_slug, section_heading)` rather than a page
number. That is arguably better for finding the source text, but it means the
chunk-page-attribution weakness noted in the stage-0 review is not fixed here either.

**The narrative layer's failure mode is silent.** Vector search degrades visibly; a graph
query over 80%-recall narrative edges returns a confident, incomplete answer. This is why
recall is the number that gates the full run rather than a thing we check afterwards.

---

## Addendum (2026-08-07, task 10) — three things this document states that are no longer true

Recorded here rather than edited in above, so the reasoning that led to each original
decision stays readable.

**§1's packing was removed (commit `b7d405d`).** There is no token budget and no `pack`
step: an `ExtractionUnit` is exactly one `Section`, produced by `units_from_sections`.
Packing saved a few cents across the corpus and cost the ability to say which section a
candidate came from — which both structural derivation and stage 2b's resolution depend
on. At gpt-4o-mini prices that is a bad trade. The data-flow diagram's `──► pack ──►
[ExtractionUnit] (~1,500 tokens each)` should read `──► [ExtractionUnit] (one per
section)`. The cost valve that shipped instead is `--limit N`.

**§5's bar of 0.9 was unreachable as written, and by construction.** Feeding the golden set
to itself as a perfect-by-construction candidate set scored 0.78 node / 0.68 edge
unambiguous recall: four golden nodes and eight golden edges could never be credited,
because their own exact names are token-subsets of other golden entries (`Vallaki` inside
`Escort Ireena to Vallaki`). No extractor of any quality could have reached 0.9. Two
changes followed. Matching is now type-aware — a candidate credits a golden entry only when
the names match *and* the candidate's `entity_type` equals the type segment of the golden
id — which removes nearly every collision, since nearly every one was a type collision. And
`grade` now computes and reports that ceiling next to every score, so a bar can never again
be set above what the key admits without anyone noticing. Any future bar must be stated
relative to the ceiling, and a ceiling below 1.0 must be read as a defect in the key.

**A single run's edge set is a ~50% arbitrary draw.** At temperature 0 with the seed pinned,
unique-edge Jaccard between two runs of the same chapter is 0.49 while the reported recall
numbers are identical — recall is blind to the churn, because the edges that swap out are
mostly ones the golden set does not list either way. Stage 2b must therefore consume
multi-sample consensus (extract N times, keep what recurs) rather than one run's artifact.
Treating a single artifact as *the* extraction of a chapter would bake in half an arbitrary
draw, and no recall number computed here would show it.

**Recall alone cannot rank two extractors, and type-awareness did not change that.** The
type rule above raised the price of a name-only shotgun by roughly the type count and no
more. Measured: the same ~10-line regex, emitting each scraped name once per `EntityType`
(one extra loop, 18 copies) and stamping a matching `layer` so `anchor_quests` passes,
scores node 0.84 / 0.84 and edge 0.72 / 0.48 unambiguous — 0.74 / 0.74 and 0.60 / 0.60 after
`anchor_quests`. The three-pass pipeline's current numbers are node 0.74 / 0.74 and edge
0.44 / 0.44 (chapter 3, key-based sections, Task 11). The raw shotgun still wins on all four
with no LLM; its anchored variant now ties node recall instead of beating it. (The
0.79 / 0.74 and 0.32 / 0.28 previously quoted here are `55e250d`'s numbers, from a different
run of a pre-key-sections pipeline; with run-to-run edge Jaccard at 0.40–0.49 they were never
comparable in principle, and they are superseded.) The reason the shotgun wins is structural:
recall is monotone in candidate count, so an extra candidate can never revoke a credit
already earned, and no looseness setting or ambiguity filter changes that. Stage 2b inherits
this metric and must not use it to choose between two extractors. What would work is a
precision term, a candidate budget (score per N candidates), or §5's hand-checked fabrication
sample.

**§5's fabrication gate has now been checked, and it is FAILED — not pending.** 30 of 145 LLM
edges from a chapter-3 run were hand-read against their own quoted evidence, and roughly
**half are false as stated**. Nothing is hallucinated in the usual sense: the evidence spans
are genuine book prose. What is wrong is the relationship attached to them — unsupported or
inverted — `Castle Ravenloft -OWNS-> Strahd`, `Chapel -LOCATED_IN-> Donavich`,
`Doru -TRAVELED_TO-> Strahd` off "sent by Strahd". Also in the sample: 2 self-loops, 26 edges
with a bare generic-noun endpoint, 17 nodes that are bare generic nouns (`Chapel` ×4, `Hall`,
`Crypts` ×2, `Trapdoor` ×2), and 1 edge with no real evidence. Derived structural edges were
excluded from the sample; they carried one self-loop of their own
(`Trapdoor -LOCATED_IN-> Trapdoor`, from an ITEM-typed node naming its own section), fixed in
`structure.py` in Task 11.

Stage 2b must size its review gate for a **measured ~50% edge error rate**, not for an
unknown. Recall says the extractor finds the key's entities; it says nothing about whether
the edges it emits are true, and now there is a number for that.

---

## Addendum (2026-08-10, task 11) — the splitter, and the module §Components forgot

**§1's split rule is no longer `##`.** A heading at *any* level from H1 to H4 whose text
matches the keyed pattern (`E4. Burgomaster's Mansion`, `K18a. High Tower Shaft`) starts a
section; an unkeyed `##` still starts a prose section; an unkeyed H1 does not split, because
the assembler finds chapter boundaries there and running headers land there too. The vision
transcription assigns heading levels essentially at random — the same keyed room appears as
H1, H2, H3 and H4 within one chapter (chapter 3: 2/4/8; chapter 4: 39/40/23/1) — so the
H2-only rule lost roughly 60% of the book's keyed areas silently, as sections that were
never proposed. Section counts: chapter 3 **21** (was 11), chapter 4 **147** (was 84),
Appendix D **32** (unchanged). Appendix D is unchanged because **not one of its 88 headings
is keyed**, which also means appendices get no derived containment at all — a fact 2b should
not mistake for an extraction failure. The `sections.py` row in §Components should read
"Chapter markdown → `Section`s on keyed headings at any level and on unkeyed `##`".

**§Components and the data-flow diagram omit `backend/canon/structure.py` entirely**, and it
is not a minor omission: it now produces the *majority* of chapter 3's edges — **60 derived
against 120 from the LLM**, where before the splitter change it produced 28. It belongs in
the table as "Chapter/section hierarchy → `CONTAINS` and `LOCATED_IN` `CandidateEdge`s. Pure,
no LLM, cannot hallucinate", and in the diagram as a second arrow out of `[Section]` merging
into the candidate set ahead of `grade.py`. Containment is derived from the *key*, not from
heading depth: a suffixed key (`E5g`) is contained by its stem's section (`E5`) when one
exists, falling back to the chapter place.

**Two defects in that module, found by review and fixed (Task 11).** Derived edges were
deduplicated on `(source_name, target_name, rel_type)` — name text alone — so distinct rooms
sharing a name silently lost containment: chapter 4's 103 keyed places produced only 100
`CONTAINS` edges, dropping `K51. Closet`, `K74b. Forgotten Treasure` and `K74f. Empty Cell`,
and the loss was undetectable downstream because the surviving edge's `section_heading` named
the *other* room. The key now includes `section_index` (chapter 4: 103 of 103). Separately,
the `LOCATED_IN` self-loop guard tested only `entity_type == "LOCATION"`, so an ITEM-typed
`Trapdoor` out of section `E5d. Trapdoor` shipped `Trapdoor -LOCATED_IN-> Trapdoor`; a node
naming its own section's place is now skipped regardless of type, case-insensitively.

**Not fixed, recorded for 2b.** The splitter's `#{1,4}` upper bound is untested and
behaviourally inert — the corpus contains no H5/H6 heading. And a mistyped node still yields
one false derived containment per chapter-3 run (`Barovia` typed `SETTING`); finer sectioning
does not cause it, but it enlarges the surface as the corpus scales.
