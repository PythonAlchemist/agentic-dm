# The narrative spine and the mention scan

**Branch:** `feat/narrative-spine`, off `main` at `177ca01`
**Spec:** `docs/superpowers/specs/2026-08-14-narrative-spine-design.md`, everything except aliases

---

## The headline number is 1, not 8, and the scan is not what is wrong

Strahd is named in **8 of chapter 3's 22 sections**. After this work he has **1
mention there**. That is not a rounding, and it is not a bug in the matcher.

The scan matches whole words against an entity's **canonical name**. The only
Strahd node in the graph is named `Strahd von Zarovich`, and that exact string
occurs in exactly one of chapter 3's sections — the preamble, quoting his own
line about Tatyana. The other seven sections write **`Strahd`**, and nothing in
this scope connects those two strings.

The design says so itself: matching is "against the entity's canonical name **and
every recorded alias**". Aliases were carved out of this task. The eight is the
alias task's number, not this one's, and the two halves cannot be separated the
way the split assumed.

There is no second node to carry the seven, either. The extractor did emit a bare
`Strahd` candidate for chapter 3 — but `gazetteer.is_known("Strahd")` is False,
so it is dropped before the write, and the harvested wiki entry for `Strahd von
Zarovich` does not record `Strahd` among its aliases. Measured directly:

```
candidate names containing "strahd" in ch3:  ['Strahd', 'Strahd von Zarovich', 'Strahd zombies']
gazetteer.is_known('Strahd')               -> False
gazetteer.is_known('Strahd von Zarovich')  -> True
\bStrahd\b over the 22 sections            -> 8
'Strahd von Zarovich' over the 22 sections -> 1
```

Reaching 8 from here needs exactly one thing: an authored alias `Strahd` →
`cos:strahd-von-zarovich`, and a re-migration. It must **not** be reached by
loosening the matcher — prefix matching, token subsets, or "first token of a
multi-word name" would each give 8 here and would each be the loose matching that
has damaged this codebase twice. `tests/test_canon/test_spine.py` pins the 1 with
a docstring saying why, so anyone who makes it 8 has to do it through `:Alias`.

I did not stop and wait, because the rest of the work is correct and needed
regardless: the spine, the sections, `DESCRIBES`, the `:Mention` node, the scan
and the removal of `description` are all independent of aliases, and the alias
task lands on top of them additively.

---

## What was built

### The spine

```
(:Book {slug, title})
  -[:HAS_CHAPTER {index}]-> (:Chapter {slug, title, index})
  -[:HAS_SECTION {index}]-> (:Section {id, heading, index, depth, parent_index, text, key})
```

`backend/canon/spine.py` is new and holds all of it, plus the scan. `:Section`
carries its own `text`, which is the whole reason a mention can quote rather than
assert.

Section ids are `cos:<chapter>#<index>` — keyed on the index, not the heading,
because `(chapter, heading)` is not unique (chapter 4 has four sections headed
"Treasure").

### `(:Section)-[:DESCRIBES]->(:LOCATION)`

Reused, not re-derived: `structure.place_of_section` decides whether a heading
names a place at all, and `writer.mint_id` turns `(key, name)` into the id. The
target must actually carry `:LOCATION` — chapter 3's `E5d. Trapdoor` is a keyed
heading the extractor typed an ITEM, and it correctly describes nothing. 13 of
chapter 3's 22 sections describe a place; 14 are keyed and Trapdoor is the one
that drops out.

`_write_spine` **MATCHes** both endpoints and raises on a miss. A `MERGE` on the
target would have quietly created a bare place node no extraction proposed.

### `:Mention`, and how aliases stay additive

```
(:Entity) <-[:REFERS_TO]- (:Mention {id, evidence, occurrences, offset, plane, chapter_slug})
                          -[:IN_SECTION]-> (:Section)
```

One node per **(entity, section)** pair — `<entity_id>@<section_id>` — so a
re-scan MERGEs onto the same node rather than doubling it, and two sentences
about Ireena in one section are one mention with `occurrences: 2`.

**There is deliberately no `surface` property.** A mention can eventually be made
under several names at once, so "which names were used" is a *set*, and a set
belongs on `USES_ALIAS` edges rather than in a scalar that would have to pick
one. Adding aliases is therefore new edges from nodes that already exist, plus a
re-run of the scan — no reshaping.

`evidence` is always a **literal substring** of its section: the enclosing
paragraph when it fits in 320 characters, otherwise a window *centred on the
match*. No ellipsis is inserted, which is what makes `evidence in section.text`
a checkable invariant rather than an intention — and truncating from the left
would have produced spans that cut off the very name they are evidence for.

### The scan

`scan_mentions(sections, entities, chapter_slug)` — pure, deterministic, no model,
no cost. Whole-word via `(?<!\w)…(?!\w)` rather than `\b`, because names in this
book end in apostrophes (`Bildrath's Mercantile`, `Doru's Bedroom`).

- **Case-sensitive for a single-word name.** `Light` does not match a lit torch.
- **Case-insensitive for a multi-word name.** The run of words is itself the
  evidence, and the book's casing drifts (`Blood on the Vine tavern`).
- **One deviation, and it is in the design:** U+2019 is folded to `'` on both
  sides. The DDB corpus preserves the book's curly apostrophe while the extractor
  emits ASCII, so without it `Bildrath's Mercantile` scores **zero** against its
  own shop — a silent zero, which is the failure this work exists to remove. It
  is a one-for-one character substitution, so match offsets still index the
  original and the evidence quotes the book's own typography.

The scan runs **inside the chapter's transaction**, after the nodes land, against
every canon entity in the graph rather than only the chapter's own plan. An
entity is global to the book, so chapter 3 naming Castle Ravenloft is a fact
about chapter 3 whichever chapter minted the castle.

The converse does not hold and is a stated limitation: writing chapter 4 does not
re-scan chapter 3, so an entity chapter 4 introduces gets no chapter-3 mention
until chapter 3 is written again. Re-writing costs nothing, so the fix is a
re-migration rather than a cross-chapter write that would break the
one-transaction-per-chapter rule.

### `description` is gone

Deleted from `WriteNode` entirely, not merely stopped being written. Also gone
from `WriteNode`: `section_heading` and `section_index`, which existed only to
feed the `MENTIONED_IN` edge.

`provenance_rank` in `plan_write` survives, with a narrowed job: it used to
decide which section to cite *and* which spelling to keep, and now decides only
the spelling. That matters more than it did — the name is what the scan looks for
in every section of the book, so a node carrying the extractor's
`burgomaster's mansion` instead of the book's `E4. Burgomaster's Mansion` finds
fewer of its own appearances.

### What read `description` before it was removed

Grepped first, as asked. Nothing in the canon pipeline read it; five things
outside it do, and **all five read `:Entity` generally rather than canon
specifically**, so they still work for campaign-plane entities (which
`graph.operations.create_entity` still writes a `description` onto) and now get
nothing for canon ones:

| Reader | What it does with it |
| --- | --- |
| `backend/rag/pipeline.py:63` | `f"[{type}] {name}: {description}"` into LLM context; falls back to `"No description"` |
| `backend/rag/enhanced_retriever.py:308` | appends `": {description}"` to an entity line, skipped when empty |
| `backend/rag/hybrid_pipeline.py:256` | same, guarded by `if entity.get("description")` |
| `backend/rag/reranker.py:102` | builds rerank text from `name - description` when a result has one |
| `frontend/src/components/EntityDetail.tsx:57` | renders a "Description" block, guarded by `entity.description &&` |
| `backend/graph/operations.py:375,386` | `search_entities` matches `toLower(e.description) CONTAINS …` |
| `backend/graph/schema.py` | `entity_search` fulltext index over `[e.name, e.description, e.aliases]` |

Every one of them is null-guarded already, so nothing breaks — canon entities
simply stop contributing a description to RAG context and to description-based
search. `operations.py` and the fulltext index were left alone on purpose:
campaign entities still have descriptions, and narrowing either would be a change
to the campaign plane that nobody asked for.

The natural replacement, when it is wanted, is an aggregate over
`(:Mention)-[:REFERS_TO]->(e)` ordered by `(chapter.index, section.index)` —
which is strictly more than the old property held, and can say *when*.

---

## Numbers

Migration: the canon plane was deleted and the three chapters rewritten from
`data/canon/runs/*.json`. **No re-extraction.** A plain `--replace` could not do
it — the replace path finds a chapter through `:Mention` and chapter-stamped
edges, and the graph on disk had neither shape — so a re-write would have MERGEd
onto the old nodes, left every `MENTIONED_IN` edge in place, and left
`description` on all 57 nodes carrying one (`SET n += $props` removes no key).
The wipe refused unless zero non-canon relationships touched a canon node; it
found zero.

| | before | after |
| --- | ---: | ---: |
| canon entities | 58 | 58 |
| `MENTIONED_IN` edges | 72 | **0** |
| `:Mention` nodes | 0 | **135** |
| `:Book` / `:Chapter` / `:Section` | 0 / 3 / 0 | 1 / 3 / **36** |
| `DESCRIBES` edges | 0 | **13** |
| canon ontology edges | 86 | 86 |
| canon nodes carrying `description` | 57 | **0** |
| mentions with an empty evidence span | — | **0** |

135 mentions against the 72 `MENTIONED_IN` edges they replace — 1.9×, at three
chapters. Per chapter: foreword 4, introduction 39, chapter 3 **92**.

**Strahd von Zarovich: 1 mention in chapter 3**, 4 across the three loaded
chapters (foreword §0, introduction §0, introduction §2, chapter 3 §0).

### Top 20 entities by mention count, whole graph

Junk is not filtered, and this list is why.

| n | entity | labels |
| ---: | --- | --- |
| 13 | Barovia | LOCATION, REGION, SETTING |
| 11 | Castle Ravenloft | LOCATION |
| **9** | **light** | **LORE** |
| 8 | Donavich | NPC |
| 8 | Vallaki | LOCATION, SETTLEMENT |
| **7** | **vampire** | **MONSTER** |
| 5 | Ireena Kolyana | NPC |
| 5 | Vistani | FACTION |
| 4 | Krezk | LOCATION, SETTLEMENT |
| 4 | Strahd von Zarovich | NPC |
| 3 | Doru | MONSTER, NPC |
| 3 | Kolyan Indirovich | NPC |
| 3 | Mad Mary | NPC |
| 3 | Mad Mary's Townhouse | LOCATION, SITE |
| 3 | Svalich Woods | LOCATION, WILD |
| 2 | Argynvostholt | LOCATION, LORE |
| 2 | Burgomaster's Mansion | LOCATION, SITE |
| 2 | Madam Eva | NPC |
| 2 | Old Bonegrinder | LOCATION |
| 2 | Tatyana | LORE, NPC |

Two entries are the visible junk the design predicted, and one of them is worth
looking at closely.

**`light` (LORE, 9) is the `Light` case, inverted.** The design's
case-sensitivity rule exists so that the LORE entity `Light` does not match every
lit torch. The entity the extractor actually produced is spelled **lowercase**,
so case-sensitive matching matches lowercase `light` — every lit torch and
nothing else. The rule is working exactly as specified; the defect is upstream,
in a bare common noun being admitted as a LORE entity at all. It is now the third
most-mentioned thing in the book, which is the argument for not filtering.

**`vampire` (MONSTER, 7)** is the same shape: a bare noun, not a creature the
book names.

Neither is worth a heuristic. A filter would hide them; the list surfaces them.

### The one absurdity that is *not* junk

`Barovia` at 13 is correct — it is the region, the village and the setting, and
it wears all three labels. Nothing needs doing.

### Entities with no mention anywhere (4 of 58)

`Ismark Kolyanovich`, `Tome of Strahd`, `Hymns to the Dawn`, and
`The Blade of Truth: The Uses of Logic in the War Against Diabolist Heresies, as
Fought by the Ulmist Inquisition`.

Three are alias-shaped: the book writes "Ismark", and the two book titles are
canonical names the prose never spells in full. The fourth (`Tome of Strahd`) is
the one that matters structurally — see the next section.

---

## What `MENTIONED_IN` was doing that mentions do not

`MENTIONED_IN` had three jobs. `:Mention` replaces one of them well and two of
them incompletely, and the gap is stated rather than papered over.

1. **Provenance for a reader** — "where do I read about Ireena". `:Mention`
   is strictly better: it says *where in the section* and quotes it.
2. **The loop's predicate** — "has this chapter been written".
3. **The replace scope** — "which nodes does this chapter own".

Jobs 2 and 3 are bookkeeping about the *write*, not facts about the book, and
they are now reconstructed from the two records that are: a `:Mention` this
chapter made, and an ontology edge this chapter asserted (`r.chapter_slug`).
`_CHAPTER_ENTITIES` unions them.

**Both arms are needed.** Chapter 3 writes `Ismark Kolyanovich`, whose full name
the chapter's prose never spells, so the mention arm misses him and the edge arm
catches him.

**The union is still not total**, and that is a real narrowing against
`MENTIONED_IN`, which covered every written node by construction. An entity with
neither a textual appearance nor a single edge is invisible to it: across the
three loaded chapters that is exactly one node, `Tome of Strahd`, written by the
introduction. The consequence is bounded — `--replace` leaves such a node behind
rather than deleting it, and the following write MERGEs onto it — and the
alternative would have been minting a mention with no evidence, which is the
fabrication the whole design refuses. `test_a_node_the_text_never_names_is_still
_this_chapters` pins the edge arm.

The counts move accordingly, and upward, because they now include entities
another chapter minted that this chapter genuinely names:

| chapter | `MENTIONED_IN` (before) | mention-or-edge (after) |
| --- | ---: | ---: |
| foreword | 4 | 4 |
| introduction | 18 | 19 |
| the-village-of-barovia | 50 | 53 |

---

## The verifier

`~/.claude/skills/canon-to-neo4j/verifier.sh` was **not edited**. Run against the
migrated graph, on all three chapters:

**Check 1 FAILS.** `1 nodes written -- 0 nodes, 84 edges`. Its node query
traverses `MENTIONED_IN`, which no longer exists.

**Checks 3 and 5 pass VACUOUSLY, which is worse than failing.** Both iterate the
same empty `nodes` list, so `check_edges` marks every edge unchecked and the
id-scoping loop examines nothing. This is precisely the failure mode the
verifier's own comments describe twice ("an empty node set makes checks 3, 4 and
5 pass by having nothing to judge"). Fixing check 1 fixes all three.

Checks 2, 4, 6, 7 and 8 are unaffected — they read edges or the run artifact.

**Proposed replacement** for the node query only (nothing else changes):

```cypher
CALL () {
    MATCH (:Mention {plane:'canon', chapter_slug:$slug})-[:REFERS_TO]->(e:Entity)
    WHERE e.plane = 'canon'
    RETURN e
  UNION
    MATCH (e:Entity {plane:'canon'})-[r]-(:Entity)
    WHERE r.plane = 'canon' AND r.chapter_slug = $slug
    RETURN e
}
RETURN DISTINCT e AS n, [l IN labels(e) WHERE l <> 'Entity'] AS labels
```

Verified against a *copy* of the verifier body, not the file itself:

```
foreword-ravenloft-revisited   PASS 1..8   (4 nodes, 0 edges)   VERIFIER PASSED
introduction                   PASS 1..8   (19 nodes, 2 edges)  VERIFIER PASSED
the-village-of-barovia         PASS 1..8   (53 nodes, 84 edges) VERIFIER PASSED
```

Two further checks are worth adding, and are the owner's call:

- **9 — every mention carries a non-empty evidence span.** Success criterion 4,
  currently unguarded outside the test suite:
  `MATCH (m:Mention {chapter_slug:$slug}) WHERE m.evidence IS NULL OR trim(m.evidence) = '' RETURN count(m)`
- **10 — the chapter has a spine at all.** A chapter with sections but no
  mentions and a chapter with neither are different failures, and check 1 cannot
  tell them apart: `MATCH (:Chapter {slug:$slug})-[:HAS_SECTION]->(s) RETURN count(s)`.

---

## Testing

**1046 tests pass** (999 in `tests/test_canon` + `tests/test_graph`, of which 47
are the live-Neo4j set marked `@pytest.mark.neo4j`; 1160 across the whole suite).
12 failures in `tests/test_ner` and `tests/test_rag` are **pre-existing** —
confirmed by stashing this branch's changes and re-running: missing gazetteer
data files, unrelated to canon.

Ruff clean on every file touched (`E,F,I,UP`, line-length 100).

### Every behaviour test was watched failing first

Not by writing the test and watching an ImportError — that proves nothing about
whether the test guards the behaviour. After the module was green, each rule was
**deliberately broken one at a time** and the suite re-run, to find tests that
pass both before and after the bug they guard. Two runs, 21 mutants, 21 caught:

**`backend/canon/spine.py` — 12/12 caught**

| mutation | caught by |
| --- | --- |
| single-word names matched case-insensitively | `test_a_single_word_name_is_case_sensitive` |
| word boundaries dropped (substring matching) | `test_matching_is_whole_word_at_the_end` |
| apostrophe folding removed | 4 tests |
| entity order left to the caller | `test_the_scan_is_deterministic_in_the_order_it_emits` |
| a prose heading treated as a place | `test_a_prose_heading_describes_nothing` |
| `DESCRIBES` written without the `:LOCATION` check | `test_a_keyed_section_naming_a_non_location_describes_nothing` |
| one mention per occurrence, not per pair | `test_two_sentences_..._are_ONE_mention` |
| evidence truncated from the left | `test_the_evidence_still_contains_the_name_when_the_paragraph_is_huge` |
| evidence assembled with an ellipsis | same |
| an unusable name compiled to match-everything | 2 tests |
| the section's text dropped from the node | 16 tests |
| mention identity keyed on the entity alone | 2 tests |

**`backend/canon/writer.py` — 11/11 caught** (the twelfth was not applicable; the
property it targets lives in `spine.py` and is covered above)

| mutation | caught by |
| --- | --- |
| the scan runs before this chapter's nodes land | 16 tests |
| mentions not written at all | 16 tests |
| the mention's missing-endpoint guard removed | `test_a_mention_of_an_entity_that_is_not_there_raises` |
| `DESCRIBES` MERGEs its target into existence | `test_a_section_describing_a_place_that_is_not_there_raises` |
| chapter index dropped from `HAS_CHAPTER` | `test_the_spine_hangs_together` |
| chapter index dropped from `:Chapter` | + `test_a_range_query_bounded_by_chapter_index_...` |
| replace leaves this chapter's mentions behind | 7 tests |
| replace leaves this chapter's sections behind | `test_a_replace_takes_this_chapters_mentions_and_sections_with_it` |
| chapter-entity traversal loses its edge arm | `test_a_node_the_text_never_names_is_still_this_chapters` |
| chapter-entity traversal loses its mention arm | 7 tests |
| `description` written back onto the node | `test_no_canon_node_carries_a_description` |

**Six of those mutants survived the first pass** — the mention endpoint guard,
the `DESCRIBES` MERGE, the replace-sections path, and both arms of the chapter
traversal had no test guarding them, exactly the class of test this project has
shipped eleven of. Four tests were added and one strengthened (rewriting a
3-section chapter as a 1-section chapter, so an un-deleted spine is visible)
before the second pass came back clean.

### Atomicity

Unchanged and re-pinned. `test_the_mention_scan_shares_the_chapters_one_transaction`
is the new one: the write raises on an edge whose endpoint no node creates,
*after* the nodes, the book, the sections and the mentions have all been written
inside the transaction. It asserts all four are absent afterwards. A writer that
committed as it went would leave a chapter full of sections and mentions behind,
and the loop's predicate reads exactly those — so the chapter would look **done**.

### One test-hygiene finding worth recording

The live-Neo4j tests share a database with the real book, and the scan matches on
**name**, globally. A test node called `Church` was therefore found by the real
book's `E5. Church`, and `count_canon_nodes` answered 2 for a chapter that wrote
one node. A name *suffix* is not enough either — matching is whole-word, so the
real `Church` still matches inside `Church of Pytest`. Test entities now carry a
marker glued to the front of **every token** (`ZzMadam ZzEva`), which puts a word
character immediately before every real name and makes the matcher's `(?<!\w)`
refuse. The id prefix protects the graph from the tests; this protects the tests
from the graph.

---

## Deviations from the spec, all deliberate

1. **Strahd is 1, not 8.** Unreachable without aliases; see the top of this
   report. Nothing was loosened to close the gap.
2. **The spine is split with the `depth` splitter, not the one each extraction
   ran under.** Chapter 3's paid extraction happened to use `key` (18 sections);
   `depth` gives the 22 the design measured. The spine is the *book's* structure,
   not a record of how one run was chunked, and `depth` is the splitter that
   knows nothing about Curse of Strahd. Consequence: a candidate's
   `section_index` no longer indexes the spine — which costs nothing, because
   mentions come from re-reading sections rather than from where a candidate was
   emitted. `--splitter` is exposed for parity; `DEFAULT_SPLITTER` documents why.
3. **Apostrophe folding is in the scan**, not held back with the aliases. It is
   named in the design as the whole of the normalisation, it is a one-for-one
   character substitution rather than a distance, and without it every
   `Bildrath's`-shaped name scores a silent zero.
4. **The spine relationship names are bare string constants** in
   `backend/graph/schema.py`, not `RelationshipType` members, following the
   precedent `ARTIFACT_LABEL` set. That enum is the vocabulary of relationships
   *between entities* — what `LAYER_MAP` partitions, what
   `RELATIONSHIP_DOMAIN_RANGE` type-checks, what the extraction prompt offers.
   None of these joins two entities or is proposed by a model.
   `RelationshipType.MENTIONED_IN` was removed with its `LAYER_MAP` entry.
5. **`write_chapter` now takes `spine` as a required positional argument.** Not
   optional: the mentions live there and the mentions are how the loop's
   predicate finds the chapter, so a write that skipped the spine would commit
   nodes into a chapter that then reads as unwritten.
6. **`docs/neo4j-canon.grass` was not updated.** The design asks for `:Mention`
   to be kept "small and pale" in the Browser, and the file exists only as an
   untracked edit in the shared checkout — it is not on `main` and not in this
   branch's history. It needs entries for `:Book`, `:Section`, `:Mention`,
   `HAS_CHAPTER`, `HAS_SECTION`, `DESCRIBES`, `REFERS_TO`, `IN_SECTION`, and its
   `relationship.MENTIONED_IN` line is now dead.

## One thing noticed in passing, out of scope

The introduction's run artifact records 5 written edges; the graph holds 2
carrying `chapter_slug='introduction'`. Three of them —
`Ireena IDENTITY_OF Tatyana` among them — are the same `(source, type, target)`
triples chapter 3 later asserted, and `MERGE … SET r += $props` re-stamped their
`chapter_slug`. This is the shared-edge `chapter_slug` overwrite the design names
as a known defect class, it predates this branch, and nothing here touches it.
It does mean the verifier's edge-scoped checks under-count for any chapter
written before one that repeats its edges.
