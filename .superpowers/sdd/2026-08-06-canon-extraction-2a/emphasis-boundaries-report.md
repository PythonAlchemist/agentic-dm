# Emphasis is a boundary, not a letter

Branch `feat/emphasis-boundaries`, off `main` at `d823c0f`.

## The defect

`mention_pattern` bounded a name with `(?<!\w)` / `(?!\w)`. `_` is a word
character to Python, so a name the book sets in markdown italics was invisible
to the scan: the lookaround saw `_` as *more of the same word* and refused the
match. `_Tome of Strahd_` is how this corpus writes the item, and the entity
scanned to zero mentions.

## The fix

One constant and one substitution.

```python
WORD_CHAR = r"[^\W_]"
return re.compile(rf"(?<!{WORD_CHAR}){re.escape(folded)}(?!{WORD_CHAR})", flags)
```

`[^\W_]` is `\w` minus the underscore — every letter and digit Unicode knows,
and nothing else. This changes **which characters bound a name**, not **how
strict the bound is**. The lookarounds are still lookarounds; the case rule is
untouched; `Ismar` still does not find `Ismark` and `Strah` still does not find
`Strahd`, italicised or not.

`*` needed nothing: it was never a `\w` character, so bold and star-italic
always delimited correctly. Only `_` was ever broken. The character class keeps
`*` delimiting, and a test pins that so a future edit to the class cannot
quietly drop it.

The deliberate cost, recorded at the constant: an underscore now bounds a name
*wherever* it appears, so a `snake_case` token would split into names. This
corpus is the book's prose in markdown, where an underscore is always emphasis
and never an identifier.

## Tests

11 added in `TestEmphasisIsABoundary`. **6 failed before the fix and pass
after** — the emphasised multi-word name, the emphasised single-word name, the
match span excluding its delimiters, one-sided emphasis, and two end-to-end
scan tests.

**5 passed both before and after, and are labelled `PINNED` in their own
docstrings** rather than presented as evidence of the fix:

- the `*` cases, which never broke;
- the four strictness guards (case rule, whole-word at each end, plural).

Those four exist to fail if someone "fixes" this by reaching for `\b`,
`re.IGNORECASE`, or by dropping a lookaround — the failure mode the task
explicitly forbade. They guard the wrong fix, not this one, and calling them
behaviour tests would be the eleven-tests problem this project keeps catching.

Suite: **1015 passing in `tests/test_canon`**, of which **116 are
`@pytest.mark.neo4j`** and run against the live database — including the
atomicity pins, which still hold. 12 failures elsewhere in `tests/` (`test_ner`,
`test_rag`) are **pre-existing**: verified failing identically on `d823c0f` with
the change stashed. `ruff check` clean. `ruff format` reports drift on both
files, also verified pre-existing on the base commit, so nothing was reformatted.

## Measurement

The three loaded chapters were re-migrated from `data/canon/runs/*.json` with
`--replace`. Nothing was re-extracted.

**The diff was controlled.** Re-running the migration changes which entities are
in the graph when each chapter is scanned, which would confound a naive
before/after. So all three chapters were first re-migrated **with the old
matcher**, and that snapshot reproduced the original graph exactly — 149
mentions, 309 occurrences, 58 entities, and **zero per-entity drift**. The
numbers below therefore isolate the regex.

| entity | mentions before | after | occurrences before | after |
|---|---|---|---|---|
| Tome of Strahd | 0 | **1** | 0 | 1 |
| Hymns to the Dawn | 0 | **1** | 0 | 1 |
| The Blade of Truth: The Uses of Logic… | 0 | **1** | 0 | 1 |
| Strahd von Zarovich | 13 | **14** | 56 | 58 |

Four entities changed; **no entity's count fell**, and no other entity moved.

Totals: `:Mention` nodes **149 → 153**; occurrences **309 → 314**; `USES_ALIAS`
edges **160 → 164**. Entities (58) and aliases (71) unchanged, as they must be —
this touches the scan, not the write plan.

Per chapter: foreword 4 → 4, introduction 44 → 46, village 101 → 103.

### Every new span, audited

Five spans in total across the loaded corpus. Each was pulled with 70 characters
of context on both sides and read:

1. `_Tome of Strahd_` (introduction) — the artifact. Correct.
2. `_Hymns to the Dawn_` (village) — an italicised book title. Correct.
3. `_The Blade of Truth: …_` (village) — the companion volume in the same
   sentence, italicised. Correct despite the alarming length.
4. `_Tome of Strahd_` again, matching the alias `Strahd` inside it. Defensible:
   cross-entity overlap is not resolved by design, and the Tome does name him.
5. `_Curse of Strahd_` (introduction), matching the alias `Strahd`. **This is
   the false positive.**

### The implausible riser, stated plainly

`Strahd von Zarovich` gains a mention from `_Curse of Strahd_` — the **title of
the adventure**, not the vampire. The sentence is "*Curse of Strahd* is a story
of gothic horror", which is about the product.

Honest scoping:

- The **class** is pre-existing, not introduced here. A bare `Strahd` already
  matched inside any longer name containing it; `Curse of Strahd` simply never
  appears unitalicised in these three chapters, so the fix surfaced the first
  instance rather than creating the class.
- It is **bounded and small**: `_Curse of Strahd_` occurs **twice book-wide**,
  and both are italic.
- The real remedy is an entity for the adventure title so the longest-match rule
  can claim the span, or cross-entity overlap resolution. Both are out of scope
  for a boundary fix and neither should be smuggled in under one.

### A correction to the premise

The task described all three Tarokka artifacts as hidden by emphasis. Only one
was. Projected book-wide:

| artifact | spans, old matcher | new matcher | gain |
|---|---|---|---|
| Tome of Strahd | 9 | 17 | **+8** |
| Sunsword | 12 | 12 | 0 |
| Holy Symbol of Ravenkind | 11 | 11 | 0 |

`Sunsword` and `Holy Symbol of Ravenkind` are **never italicised anywhere in
this corpus**. They sit at 1 mention each because the two loaded content
chapters name them once, in the same sentence as the Tome — not because the
matcher was dropping them. This fix cannot raise them and does not. Their counts
will rise when the chapters that discuss them are loaded, and that is an
extraction-coverage question, not a matcher one.

The eight-span gain for the Tome is the fix's real yield, and seven of those
eight are in chapters not yet migrated.

## Verifier

`~/.claude/skills/canon-to-neo4j/verifier.sh` was not modified. Run against all
three chapters after the re-migration: **8/8 PASS each**, node and edge counts
identical to before (4/0, 22/2, 53/84). Verified rather than assumed, as asked —
it counts nodes and edges, and this change moves only mentions.
