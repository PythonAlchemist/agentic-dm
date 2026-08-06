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
