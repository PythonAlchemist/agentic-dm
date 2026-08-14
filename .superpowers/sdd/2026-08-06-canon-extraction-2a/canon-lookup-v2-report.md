# A read path into canon, rebuilt against the schema that exists

Branch `feat/canon-lookup-v2`, off `main` (`d823c0f`).

## Why this was rebuilt rather than rebased

`feat/canon-lookup` (`73d49bd`, unmerged) built the same three tools and had a
green suite. It was green because its fixtures wrote `section_heading` onto
entity nodes — a property the writer had already deleted by the time that branch
was written. Against the real graph its `section` came back `None` on every
answer. It was a test suite passing on a schema that no longer existed, so its
three signatures and its query log survive here and none of its Cypher does.

The queries it wrote read `n.entity_type`, `n.chapter_slug` and
`n.section_heading` off `:Entity`. An entity node today carries
`{id, name, plane, status, votes}` and nothing else: its type is a **label**, its
rung is a **label**, and where it appears is a set of `:Mention` nodes hanging off
`:Section` nodes hanging off `:Chapter`. Three of the four things the old
queries selected do not exist.

## What was built

`backend/canon/lookup.py` — one class, `CanonLookup`, three methods:

```python
CanonLookup.where_is(name: str) -> dict     # placements + the passages that discuss it
CanonLookup.whats_here(place: str) -> dict  # occupants + the section describing the place
CanonLookup.lookup(name: str) -> dict       # labels, rung, mentions with evidence, edges
```

`DMTools` (`backend/agents/tools.py`) gains `where_is`, `whats_here` and
`lookup_canon`, each a one-line delegation, plus a `canon` constructor argument.
Constructing `DMTools` opens no connection; a session is taken per question and
dropped again. No cache, no fourth tool, no Cypher passthrough.

### Names resolve through `aliases.resolve_name` and through nothing else

One traversal — `(:Alias {normalized})-[:ALIAS_OF]->(:Entity)` — and no fallback
tier behind it. The previous version had two tiers (exact, then a
`toLower(n.name)` pass) plus a slug-equality near-match consulted on the miss
path. All three are gone, because they are all now redundant: an entity's
canonical name is itself an `:Alias`, `normalized` already folds case and U+2019,
and the authored seed carries the short forms. Keeping a second tier would be
maintaining a second answer to the same question, free to disagree with the
first.

`normalized` is lowercase, trimmed, apostrophe-folded and **nothing else**. A
mutation that added a single `CONTAINS` fallback to the resolver was run against
the suite: four tests fail, including `Ismar` and `ZzLightbearer`.

### `accepted` and `proposed` are separate lists, never merged

Every result carries both as distinct keys, and every row keeps its own `status`,
so a `conflicted` edge — a proposed edge demoted for contradicting an accepted
one — is still identifiable inside `proposed`. A row that somehow carries no
status lands in `proposed` too: trust is earned from evidence and must never be
the default. Collapsing the split fails seven tests.

The passages and sections are neither. They come from the document's own
structure, which cannot hallucinate the way an edge can, so they are returned
under their own keys rather than laundered into `accepted`.

### A rung is `None` when there is no rung

`rung_of` returns `None` rather than a default. The writer gives a rung only
where the book's key convention or the hand-authored seed supplies one, so a
place without one is *unclassified*, and that is a real state the answer has to
preserve. `Old Bonegrinder` and `Castle Ravenloft` are both `:LOCATION` with no
rung today; guessing `SITE` from the absence would manufacture a claim the
extraction deliberately declined to make.

Type labels are returned as a **list** for the same reason. A disputed type wears
two — `Barovia` is `:LOCATION:SETTING` — and no single string says that.

## The log

Every call appends one JSON line to `data/query-log.jsonl` (gitignored):
timestamp, tool, arguments, `found`, how many names resolved, the
accepted/proposed counts, and a structural count (`passages`, `sections` or
`mentions`) that travels on hits as well as misses. That last one matters more
than it looks: "placed nowhere, but discussed in one section" and "placed nowhere
and never mentioned" are different findings, and the log has to tell them apart.

An empty answer additionally carries `miss_reason`, a human-readable
`miss_detail`, and `chapters_in_graph`:

- `no_such_relationship` — the graph holds the entity and has no edge of the kind
  asked for. Diagnosed **first**, and nothing may mask it: this is the miss worth
  acting on, because both ends already exist and only the edge is absent.
- `name_not_in_graph` — no `:Alias` in the canon plane answers to the name, and
  the book's index does not know it either.
- `chapter_not_extracted` — the book's index knows the name and the graph does
  not hold it. Nothing to hand-author yet.

The gazetteer is optional; its absence costs only the ability to tell the third
reason from the second.

## Twenty questions

Run against the live graph: 58 entities, 3 of 25 chapters, the gazetteer loaded.

| # | Question | Call | Result |
|---|---|---|---|
| 1 | who's in the burgomaster's mansion | `whats_here("Burgomaster's Mansion")` | HIT 3 accepted, 2 proposed, 1 section |
| 2 | where do I read about Ismark | `lookup("Ismark")` | HIT 1 accepted, 4 proposed, 2 mentions |
| 3 | what's in the church | `whats_here("Church")` | HIT 8 accepted, 0 proposed, 1 section |
| 4 | who is Ireena related to | `lookup("Ireena")` | HIT 3 accepted, 12 proposed, 5 mentions |
| 5 | where is the Tome of Strahd | `where_is("Tome of Strahd")` | MISS `no_such_relationship` — node present (`:ITEM:Artifact`), no placement |
| 6 | who's in the tavern | `whats_here("Blood on the Vine")` | HIT 8 accepted, 0 proposed, 1 section |
| 7 | where is Doru | `where_is("Doru")` | HIT 3 accepted, 2 proposed, 3 passages |
| 8 | what do we know about Strahd | `lookup("Strahd")` | HIT 0 accepted, 4 proposed, 14 mentions |
| 9 | what's in the village of Barovia | `whats_here("Village of Barovia")` | HIT 7 accepted, 0 proposed |
| 10 | where do I find Madam Eva | `where_is("Madam Eva")` | HIT 1 accepted, 0 proposed, 2 passages |
| 11 | who is Morgantha | `lookup("Morgantha")` | HIT 0 accepted, 1 proposed, 1 mention |
| 12 | what's at Old Bonegrinder | `whats_here("Old Bonegrinder")` | MISS `no_such_relationship` — node present (`:LOCATION`, no rung), nothing inside |
| 13 | where's the Sunsword | `where_is("Sunsword")` | MISS `no_such_relationship` — node present (`:ITEM:Artifact`), no placement |
| 14 | who is Donavich | `lookup("Donavich")` | HIT 7 accepted, 8 proposed, 8 mentions |
| 15 | what's in the undercroft | `whats_here("Undercroft")` | HIT 2 accepted, 1 proposed, 1 section |
| 16 | where's Gertruda | `where_is("Gertruda")` | HIT 1 accepted, 1 proposed, 1 passage |
| 17 | who are the Vistani | `lookup("Vistani")` | HIT 1 accepted, 1 proposed, 5 mentions |
| 18 | what's in the cemetery | `whats_here("Cemetery")` | HIT 1 accepted, 0 proposed, 1 section |
| 19 | who is Rictavio | `lookup("Rictavio")` | MISS `name_not_in_graph` — absent from graph and from the book's index |
| 20 | where is Bildrath's Mercantile | `where_is("Bildrath's Mercantile")` | HIT 1 accepted, 0 proposed, 1 passage |

**16 hits, 4 misses.** The previous run of the same questions was 12 and 8.

## The name mismatches are gone

All three of the previous run's name-mismatch misses are now hits, and all three
for the same reason — the alias layer landed between the two runs:

- **`Burgomaster's Mansion`** (Q1). The book sets U+2019, a DM types `'`.
  `normalized` folds them, and both spellings are `:Alias` nodes on the same
  entity. Previously `name_not_in_graph`.
- **`Village of Barovia`** (Q9). An authored alias on `cos:the-village-of-barovia`.
  Previously `name_not_in_graph` — and note the old report's diagnosis ("the
  graph calls it `Barovia`") was itself wrong: `Barovia` is the *region*, a
  different node. The old fuzzy diagnostic pointed at the wrong entity.
- **`Ismark`** (Q2, Q18 in the old table). Resolves to
  `cos:ismark-kolyanovich` through the authored short form, exactly as
  `Ismark Kolyanovich` does. Asserted directly, against the real book's canon
  rather than a fixture, in `TestTheRealBook`.

`Ismar` resolves to nothing. So does `Donav`, and so does `ZzLightbearer` — a
token of a real multi-word name. Those are the three shapes of fuzzy match that
have damaged this codebase before, and each has a test.

Q7 (`where is Doru`) also flipped from miss to hit, which is not an alias win:
the mention and placement work since the last run actually attached him.

**Zero `name_not_in_graph` misses remain except the genuinely absent one.** In
the previous run that class was 3 of 8 misses; here it is 0 of 4, and the one
`name_not_in_graph` left is Rictavio, whom neither the graph nor the wiki index
knows because he is Van Richten under an alias the book withholds.

## What the four remaining misses have in common

**Three of four are the same thing: a node with no edge.** Tome of Strahd,
Sunsword, Old Bonegrinder. All three are *cross-references* — chapter 3 and the
introduction name them while describing something else, the extractor mints a
node per name, and nothing attaches. The log makes this visible without
re-running anything: Q5's line records `passages: 1`, so the Tome of Strahd is
discussed in exactly one section and placed nowhere.

Two of the three are the campaign's Tarokka artifacts. Their whole purpose is
that a card reading tells the party *where they are*, and the graph cannot answer
that for either — not because the chapter is missing, but because "where the
Sunsword is" is decided by a table in appendix E rather than stated in prose.
That is a hand-authoring job, and it is the same job for the Holy Symbol.

**One of four was genuinely absent.** Rictavio.

**`chapter_not_extracted` did not fire once in twenty questions**, though the path
works: `lookup("Vasilka")` and `lookup("Baba Lysaga")` both return it. The
project's assumption going in — that a graph holding 3 of 25 chapters would fail
by not having the content — is still wrong after a second run. It fails by
holding the nodes and not the edges.

So the hand-authoring list this exercise argues for has not changed shape since
the last run, but it has got shorter: the alias half is done, and what is left is
edges onto nodes that already exist.

## What the hits reveal

Unchanged from the previous run, and worth restating because the ratio is the
argument:

- `whats_here("Church")` — 8 accepted, 0 proposed
- `whats_here("Blood on the Vine")` — 8 accepted, 0 proposed
- `lookup("Strahd")` — 0 accepted, 4 proposed
- `lookup("Ireena")` — 3 accepted (all spatial), 12 proposed

The graph is trustworthy exactly where a DM needs least help — which room is
inside which building — and untrustworthy exactly where the question is
interesting. "Who is Ireena related to" returns twelve proposed edges, roughly a
third of them wrong, and `Ismark OPPOSES Ireena` is among them. Every
non-spatial relationship in this graph is unvetted model output, which is why the
two lists are never merged and why `DMTools` returns the dict rather than a
sentence.

One new observation the labels make available: `whats_here("Church")` returns
`Trapdoor` with `rung: None` beside six rooms with `rung: "AREA"`. The book keys
`E5d. Trapdoor` like a room and the extractor typed it `:ITEM`, so it correctly
gets no rung — the ladder it would be standing on is one it is not on. The read
path surfaces that rather than smoothing it over.

## One bug, found in review by calling the tools rather than reading the table

`lookup` fanned out through `USES_ALIAS`. Measured on Strahd before the fix:

```
:Mention nodes                        14
USES_ALIAS edges from those mentions  18
rows returned by lookup("Strahd")     18
distinct (chapter, section) in them   14
```

Four sections — `Foreword`, `Introduction`, `Story Overview` and chapter 3's
opener — write both `Strahd` and `Strahd von Zarovich`, so each of those mentions
carries two `USES_ALIAS` edges and the join emitted one row per edge instead of
one per mention. A DM asking where Strahd is discussed saw four passages twice,
and any count taken off the list ran 29% high. `Ireena` was worse: 10 rows for 5
mentions, because *every* section that names her uses both `Ireena` and `Ireena
Kolyana`. A 100% overcount.

The fix is a `WITH ... collect(DISTINCT a.name) AS aliases` — one row per
mention, carrying the spellings it used as a **list**. Deduplicating by dropping
the surface form would have been the cheaper fix and the wrong one: which name
the book used at a given point is real story information, since the party meets
`Strahd` long before `Strahd von Zarovich`. `collect` skips nulls, so a mention
with no alias edge yields `[]` and the field's shape never changes with the
number of spellings.

**The other two tools were checked for the same shape and are clean.**
`PASSAGES` already carried `RETURN DISTINCT` over the section tuple and never
touches `:Alias` (14 rows, 14 distinct). `DESCRIBING_SECTIONS` aggregates its
mentions with `collect(DISTINCT ...)`. `OCCUPANTS`, `PLACEMENTS`, `EDGES` and
`SUBJECTS` never join through `:Alias` at all, and `resolve_name` already returns
`DISTINCT` ids. Each of those five now carries a no-duplicate assertion anyway,
because the property is cheap to state and the cost of it silently ceasing to
hold is another inflated answer.

**Why 41 live tests passed with this present.** Every assertion about mentions
was written over a `set` — `{m["section"] for m in mentions}` — which is exactly
the operation that hides a duplicated row. The replacement asserts the property
directly (`len(seen) == len(set(seen))`) on a fixture section that deliberately
uses two surface forms, and count-free against the real book so the concurrent
mention-scan work cannot move it. Restoring the fan-out while keeping the field
name fails 5 tests; restoring the original query, whose field was a scalar
`alias`, fails 7. The conservative number for the defect itself is 5.

This is the third defect in this project's history that a green suite failed to
catch by asserting on a collapsed collection. It is worth saying plainly: a
`set()` in an assertion is a place where a cardinality bug can live.

## Tests

67 new: 62 in `tests/test_canon/test_lookup.py` (52 marked `neo4j`, 10 pure) and
5 in `tests/test_agents/test_tools.py` for the `DMTools` wiring. Full suite:
1294 passed, 12 failed — all 12 pre-existing spacy/NER failures present on
`d823c0f` before this branch, confirmed by stashing.

**The fixtures are not invented.** Every live test's graph is written by
`write_chapter` — the real writer, the real spine, the real mention scan, the
real alias backfill — so a test cannot pass by asserting a shape the pipeline
stopped producing. That is the precise failure mode of the previous attempt.
`TestTheSchemaTheseQueriesTarget` makes the guard explicit by asserting the
*absences*: no `entity_type` key, no `section_heading` key, no `chapter_slug` key
on an entity, type and rung carried as labels.

Every behavioural test was watched failing before the module existed (import
error, then red). Three mutations were additionally run to confirm the tests are
load-bearing rather than decorative:

| Mutation | Tests that fail |
|---|---|
| `split_by_status` returns one merged list | 7 |
| resolver falls back to `CONTAINS` on the alias name | 4 |
| `PASSAGES` selects `null` as the section heading — *the previous attempt's exact bug* | 1 |
| `MENTIONS` drops the `WITH` and fans out through `USES_ALIAS` — *the bug review caught* | 5 |

Two tests run against the real book's canon rather than a fixture
(`TestTheRealBook`), and both are deliberately count-free: a concurrent fix to
the mention scan is moving counts, so nothing here depends on one.

## Deviations

- **The module is at `backend/canon/lookup.py`, not `backend/agents/canon_tools.py`.**
  It reads the canon graph and shares the writer's status constants and the
  alias resolver, so it belongs beside them; `backend/agents/tools.py` holds only
  the three delegations. Flagged because the brief implied the other path.
- **The slug-equality miss diagnostic was dropped.** The previous version, on a
  miss, looked for a canon name that slugified to the same string and reported
  "the graph spells it X". Slug equality discards punctuation as well as case, so
  it is looser than `normalized` — and with the alias layer in place the case it
  existed for (a curly apostrophe) is now a hit rather than a miss. It is also
  what produced the old report's incorrect "the graph calls it `Barovia`". Gone.
- **`found` means different things per tool, on purpose.** For `where_is` and
  `whats_here` it tracks the relationship, so a thing discussed in four sections
  and placed nowhere still logs as `no_such_relationship` — which is the miss the
  exercise exists to count. For `lookup` it tracks the entity, because "tell me
  about X" is answered by the node existing.
- `backend/agents/tools.py` carries 14 pre-existing `UP045` ruff violations
  (`Optional[dict]` throughout). The lines added here use `X | None` and add
  none; the rest were left alone as out of scope.
