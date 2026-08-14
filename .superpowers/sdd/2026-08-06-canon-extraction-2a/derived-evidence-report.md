# Derived evidence: a mention stops carrying a copy of its section

**Branch:** `feat/derived-evidence` off `main` (`5c5f894`)
**Commit:** `7626996`
**Spec:** `docs/superpowers/specs/2026-08-14-mention-weight-design.md` §1 only. §2
and §3 were read and are untouched.

## What was wrong

A `:Mention` stored `evidence`, a paragraph-sized quote of the section it
already points into. The section carries `text` and the mention carries
`offset`, so the prose was in the graph twice — and three times over wherever
one paragraph named three entities. Measured on the three loaded chapters before
the change:

```
153 mentions · avg evidence 231 chars · max 320 · total 35,383
9,894 of those characters were literal duplicates: 31 strings stored 2-3x
```

## What now happens

`backend/canon/passage.py` is new and depends on nothing but `re`. It exposes
two functions:

- `sentence_bounds(text, offset) -> (low, high)` — the containing sentence as
  **offsets** into the section's own text, capped at 300 characters.
- `derive_passage(text, offset) -> str` — that span, rendered.

The split exists because §2 needs the same span for a different reason. Deriving
a passage wants a string; computing co-occurrence wants to ask whether another
mention's offset falls inside the span. One rule, one implementation — two would
eventually disagree about one sentence, and the disagreement would surface as a
co-occurrence edge whose passage does not contain both names.

`spine.WriteMention` lost its `evidence` field and `spine.evidence_span` /
`EVIDENCE_MAX` are gone. `lookup.py` returns `s.text` and `m.offset` from the
`MENTIONS` query, derives the passage, and pops the section text before the row
reaches a caller — shipping it would have put the duplication back on the wire
instead of in the graph. The result key is still `evidence`: same answer to the
same question, only the storage changed.

`occurrences` and `offset` stay. They are what the scan learned, not copies of
anything, and `offset` is what the derivation anchors on.

## The boundary rule

A boundary is `.`, `?` or `!`, plus any closing quote/bracket/emphasis, followed
by whitespace or end of line. **Newlines are always boundaries.**

**The errors are not symmetric, and the rule is biased accordingly.** A span
that runs one sentence long costs a reader an extra clause. A span that splits
`St. Andral's` costs them the name. So a period is *rejected* as a boundary when
the word in front of it is:

| shape | example | corpus count |
|---|---|---|
| a single letter | `in appendix D.` | 3 lettered appendices |
| digits alone | `2.` opening a list item, `1978.` | — |
| a keyed area code | `### E5f. Chapel`, `beyond area K42.` | 578 |
| a recorded abbreviation | `St. Andral's`, `Avg. Level`, `TSR, Inc.` | `St.` ×18 |

The abbreviation set is 16 entries and deliberately small: each one costs a real
boundary somewhere, so nothing is in it that the corpus does not contain.
Currency is **not** in it — `A glass of wine costs 1 cp. Arik returns to
cleaning mugs.` is a real sentence end, and adding `cp` would merge two
sentences to prevent nothing.

**Newline as a hard boundary** was checked before it was adopted: across all 25
chapters of `data/ddb/cos/*.md`, a single newline mid-sentence occurs exactly
once, in an image caption. Prose is never hard-wrapped. The payoff is that a
mention inside a markdown table now quotes its own row rather than 300
characters of pipes.

Over the cap the span falls back to a window with the offset about a third of
the way in, snapped outward-in to whitespace. Truncating from the left would cut
off the very name the passage exists to show.

## Markdown markers: stripped, always

`_` and `*` come out of the rendered passage unconditionally — not only when a
span cuts one in half.

Stripping *only* unbalanced markers would render the same paragraph differently
depending on where it was cut, which is harder to explain than either consistent
choice, and a DM reads `Tome of Strahd`, not `_Tome of Strahd_`. The corpus
makes this concrete: `_**Vistani Owners. **_Three Vistani spies sit near the
door` is how the book sets a run-in header, and a span starting at `Three`
inherits exactly one delimiter.

This is a rendering of the span, not an edit to it. `sentence_bounds` is
untouched, so the span remains a literal region of the section and §2 will still
reason about the book's own offsets.

## Before and after, one real mention

`cos:abbey-of-saint-markovia@cos:the-village-of-barovia#14`

**Before** — five properties, one of them 320 characters of prose that begins
mid-sentence:

```
{plane: 'canon', chapter_slug: 'the-village-of-barovia', occurrences: 1, offset: 2864,
 evidence: 'in the ground, Donavich suggests that Ireena be taken as far from Castle
 Ravenloft as possible. He proposes that the characters take her to the Abbey of Saint
 Markovia in Krezk (chapter 8) or, failing that, the fortified town of Vallaki (chapter
 5). Donavich is unaware that the abbey, once a bastion of good, has'}
```

**After** — four properties, no prose:

```
{plane: 'canon', chapter_slug: 'the-village-of-barovia', occurrences: 1, offset: 2864}
```

**Derived on read:**

> He proposes that the characters take her to the Abbey of Saint Markovia in
> Krezk (chapter 8) or, failing that, the fortified town of Vallaki (chapter 5).

The passage got *better*: it starts at a sentence rather than mid-clause.

## Three sample derived passages

**1. A sentence lifted out of a three-entity paragraph** — `Tatyana`, chapter 3.
This is the duplication case: the stored evidence for Tatyana, Ireena and Strahd
in this paragraph were three copies of one string.

> Few know that Ireena bears an uncanny resemblance to Tatyana, Strahd's dead
> beloved.

**2. A table row** — `Amber Temple`, introduction. Stored evidence was 300
characters of the Areas-by-Level table starting mid-row; newline-as-boundary
gives the row the entity is actually in.

> `| 9th | The Amber Temple | 13 |`

**3. The worst boundary the rule produces** — `tinderbox`, chapter 3, area E5e.
292 characters, the longest passage in the graph. The book writes a genuinely
~400-character sentence, so the cap fires and the window ends at a word boundary
mid-clause:

> Inside are a tinderbox, a few wooden boxes full of candles, and two well-used
> books: Hymns to the Dawn, a volume of chants to the Morninglord, and The Blade
> of Truth: The Uses of Logic in the War Against Diabolist Heresies, as Fought
> by the Ulmist Inquisition, **a strange book that mixes logic**

It stops after "logic", one word short of "exercises". It does not cut mid-word,
and the *stored* evidence for this same mention was also truncated mid-clause —
at `Inquisition_,`, with a stray underscore — so even the worst case is no worse
than what it replaces.

## Did deriving make passages worse?

No, and this was checked rather than assumed. All 153 mentions were compared
stored-against-derived. Every difference is an improvement: the derived passage
starts at a sentence boundary instead of mid-clause, and table rows go from 300
characters of pipes to the one row that matters.

The 40 passages shorter than 60 characters were read individually. Thirty-two
are section headings (`### E5. Church`), where the derived string is **byte-identical**
to the stored one — the key-code rule is what keeps `### E5f. Chapel` from
becoming `### E5f.`. Two are image-caption lines that go from a
media.dndbeyond.com URL plus a name down to just the name; thinner, but the URL
was never evidence of anything. The remaining six are table rows, all better.

No minimum-length rule was added, because nothing needed one.

Total derived: **17,046 characters over 153 mentions** (avg 111, median 106, max
292) against 35,383 stored — and the derived characters live in no node.

## Numbers

**Characters removed from the graph: 35,383.** `evidence` is now absent from all
153 mentions; `evidence_chars` reads 0.

The three loaded chapters were re-migrated from `data/canon/runs/*.json` with
`--replace`. **Nothing was re-extracted.** The census was taken before and after
and compared line by line, including per-entity mention and occurrence counts:

| | before | after |
|---|---|---|
| `:Mention` nodes | 153 | 153 |
| occurrences | 314 | 314 |
| entities | 58 | 58 |
| aliases / `USES_ALIAS` | 71 / 164 | 71 / 164 |
| sections | 36 | 36 |
| mentions carrying `evidence` | 153 | **0** |
| characters of stored evidence | 35,383 | **0** |

Per chapter (foreword 4, introduction 46, village 103) and per entity across all
58: **identical**. This change touches which properties land, not the scan or
the write plan, so any drift would have been a defect.

## Tests

**1,113 in `tests/test_canon`, all passing**, of which **131 are
`@pytest.mark.neo4j`** against the live database — including all three atomicity
pins (`test_a_write_that_raises_partway_leaves_the_graph_unchanged`,
`test_a_failed_replace_leaves_the_previous_chapter_intact`,
`test_the_mention_scan_shares_the_chapters_one_transaction`). One transaction per
chapter, unchanged.

`tests/test_canon/test_passage.py` is new: **34 tests** over the span rule.

Full `tests/`: 1,345 passing, 12 failing. The 12 are in `test_ner`, `test_rag`
and `test_transcript` and are **pre-existing** — verified failing identically on
`5c5f894` with the change stashed. `ruff check` clean on every file touched.

### Every behaviour test was watched failing first

Not as an import error. The span rule was **first implemented naively** — a
plain `[.?!]\s` split with a left-truncating cap — and the suite run against it:

```
8 failed, 26 passed
  test_a_titles_period_does_not_split_a_name          -> 'Milivoj is digging a grave outside St.'
  test_a_keyed_area_code_does_not_end_a_sentence      -> 'The vault lies beyond area K42.'
  test_a_keyed_heading_keeps_the_name_it_keys         -> 'Church'   (from '### E5f. Chapel')
  test_a_lettered_appendix_does_not_end_a_sentence    -> split at 'appendix D.'
  test_a_numbered_list_marker_does_not_end_a_sentence -> split at '2.'
  test_the_capped_span_still_holds_the_name_it_is_evidence_for
  test_the_bounds_always_contain_the_offset
  test_a_heading_does_not_run_into_the_prose_beneath_it
```

Each failure is the exact defect its rule exists to prevent. The abbreviation
guard and the centred window turned all eight green.

The graph-shape assertions were checked for vacuity the same way. Because the
write-path change had already landed by the time they ran, `evidence` was
temporarily reinstated on `WriteMention.properties` and the tests re-run:
`test_a_mention_stores_an_offset_and_no_prose` and
`test_no_mention_in_the_graph_carries_evidence` both failed, then passed again
once it was removed. Neither normalizes before comparing, and both assert
`total > 0` first so an empty match set cannot pass them by having nothing to
judge.

`test_the_evidence_is_the_sentence_and_not_the_paragraph` required changing a
fixture: the `Rumours` section now opens with a decoy sentence naming nobody, so
"trimmed to the sentence" is falsifiable rather than incidentally true.

## Verifier

`~/.claude/skills/canon-to-neo4j/verifier.sh` was **not touched**. Its
indifference to this change was verified rather than assumed — run against the
re-migrated graph, from the main checkout, unmodified:

```
the-village-of-barovia        VERIFIER PASSED   8/8
introduction                  VERIFIER PASSED   8/8
foreword-ravenloft-revisited  VERIFIER PASSED   8/8
```

It reads `:Mention` only as a traversal hop from entity to section and never
touches `m.evidence`, which is why it is indifferent.

## Deviations

**One, and it is an addition to the spec rather than a departure from it.** §1
says "trimmed to the containing sentence" and names `.`, `?`, `!`. It does not
mention newlines. Newlines were made hard boundaries after checking that no
chapter hard-wraps prose, because without it every mention inside a markdown
table derived to a 300-character window of pipes — measurably worse than the
sentence rule delivers everywhere else. It also tightens the span §2 will
inherit, which is the direction that spec wants.

Nothing else. §2 and §3 are untouched.
