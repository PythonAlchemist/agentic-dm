# DM material authoring in the product — design

**Status:** proposed. Mockups in Figma, page `DM material flow`, boards 0–8.
**Scope of this spec:** boards 2, 3 and 6 — write in place, draft with the
provenance split, and the one step that applies. Boards 4, 5, 7 and 8 are
designed but deferred; see *Out of scope*.

---

## 1. The gap

A DM can read the book in the product and can decide what the table knows.
They cannot make anything. Every authoring surface this project has — drafting,
the four-source split, storing, editing prose — lives in `/lab`, which
`Shell.tsx` correctly calls the research instrument and which `DESIGN.md` §8
puts out of scope for the product's visual language.

That split is defensible for retrieval reports and cost meters. It is not
defensible for writing a scene. The result today is that the DM's own material
can only be created in the instrument, then read in the product.

**Almost none of this is a backend gap.** `labAPI` already has every call:

| Need | Existing call |
|---|---|
| ask for a draft | `labAPI.generate(kind, subject, model, depth, book, campaign, revision?)` |
| approve it into the graph | `labAPI.store({...})` — *"The card is the gate; this is the write."* |
| rewrite stored prose | `labAPI.editSection(campaign, sectionId, body)` |
| propose relationships after a write | `labAPI.deriveEdges(campaign, sectionId)` |

The work is a product-side surface over calls that exist.

---

## 2. Where it lives, and why that decides the shape

Authoring joins **the provenance rail** on `s/[id]`, beneath `Reveal`. The rail
is already the apparatus around the text; adding a second job to it costs no new
concept, and a DM mid-session finds it in the place they already look.

The writing itself happens **in the reading column, never in a modal**. This is
load-bearing rather than cosmetic. §6 assigns Literata to the book and Geist to
the DM's material, so a draft rendered directly beneath the book's prose shows
the difference between the two *in the type* while it is being written. A modal
would cover the one thing worth seeing.

**The anchor is free.** `store` takes `anchor` — "the canon section it goes
after". Because the flow begins inside a section, the anchor is that section.
Placement (board 5) becomes an optional refinement rather than a required step,
which is what lets this spec cover three boards instead of five.

---

## 3. Components

Three new components under `web/src/components/product/`, plus one rail change.

### `MaterialRail`
Renders inside the existing `s/[id]` rail below `Reveal`. Three actions —
*write a scene here*, *add someone*, *draft it for me* — over a `line` rule.
Owns which action is open; renders nothing else. `add someone` is present but
disabled in this scope.

**Gated exactly as `Reveal` is**: `useRuns(campaign)`, returning `null` for
anyone who is not the DM. A player must never see an authoring affordance, and
the reason is not tidiness — this screen is the one where a player is asked to
trust that what they are reading is the book's. An edit control in that frame
undermines the claim the screen exists to make, even if the endpoint would
refuse the write. Shell already withholds the DM's tabs; the rail must withhold
this for the same reason.

### `WriteBlock` — board 2
An empty `yours` block in the column: solid amber left edge, `✎ YOURS`, a title
input, a body textarea, and one primary action. Geist `text-body` throughout, so
it reads as the DM's voice against the book's serif above it.

### `DraftCard` — board 3
The product's rendering of a `GeneratedReply`. **Not a port of the lab's
`GenerationCard`**, which carries cluster review, a model picker, depth and a
cost meter — instrument concerns. The product card shows the prose and the four
source lists, unblended, each labelled in its own hue with its citation:

| List | Field | Label | Hue |
|---|---|---|---|
| the published book | `from_canon` | `§ from the book` | `source/book` |
| written for this campaign | `from_yours` | `✎ from yours` | `source/yours` |
| said at the table | `from_context` | `❝ from the table` | `source/table` |
| the model supplied it | `invented` | `◇ invented` | `source/invented` |

The card renders in **invented grammar** — dashed rose edge, `◇`, and the
closing line *"invented — nothing stands behind this."* — because until it is
stored, that is what it is.

### The transition — board 6
Not a component. Storing does **not** unmount the card and mount something else:
the same block re-marks in place, dashed rose to solid amber, `◇` to `✎`, and
the footer changes to the citation. The DM watches their material change
provenance without it moving. §8.4 calls this "the product's whole point made
visible"; it is only visible if nothing jumps.

---

## 4. Data flow

**Hand-written** (board 2):
`WriteBlock` → `labAPI.store({ campaign, kind: 'scene', title, body,
generated_body: '', from_canon: [], from_yours: [], invented: [],
from_context: [], sources: [], anchor: <the section being read>, model: '' })`.

`generated_body: ''` is the signal that no model was involved. Empty source
lists are correct and not a degenerate case: nothing was drawn from anywhere,
because a person wrote it.

**Model-drafted** (board 3):
`labAPI.generate(...)` → `GeneratedReply` held in component state, rendered as
`DraftCard`. **Nothing is persisted.** On store, the reply's fields pass through
unchanged except `body`, which carries the DM's edits while `generated_body`
keeps what the model produced — the pair is what lets a reader later tell an
accepted draft from an edited one.

**After the write**, both paths call `labAPI.deriveEdges`. It costs a model call
and writes `proposed` edges, so it runs after the write rather than inside it,
and its output is dimmed and labelled — a guess, never mixed with what the DM
asserted.

---

## 5. One vocabulary problem to settle

The API says `from_canon` and `from_context`. The design system says **book** and
**table**. `palette.ts` is explicit that a hue names a source and that the four
names are `book / yours / table / invented`.

Renaming the API is out of scope and would touch the backend mid-refactor. This
spec requires instead that **the mapping is declared once**, in `DraftCard`,
beside the palette import — never re-derived per call site. A second translation
elsewhere is how `from_context` eventually gets labelled "context" on one screen
and "table" on another, which is precisely the drift `palette.ts` exists to stop.

---

## 6. Error handling

- **Generate fails.** The card never appears; the rail action returns to rest
  with `⚠` and the message in `ink-dim`. Nothing was written, so there is
  nothing to roll back.
- **Store fails.** The block stays exactly as it was — still invented, still
  discardable — with `⚠` beneath the action. The block must not re-mark
  optimistically: showing amber for something that is not in the graph is the
  single worst failure this product can have.
- **`deriveEdges` fails.** Silent. The section is stored and correct; edge
  proposals are an enrichment, and a failure there must not read as a failed
  write.
- **Discard.** Always available while unstored, needs no confirmation, and
  leaves no trace — that is what makes inviting the model in safe.

---

## 7. Testing

- `DraftCard` maps all four lists to the right labels and hues, including the
  empty-list case (a list with no items is omitted, not rendered empty).
- A hand-written store sends `generated_body: ''` and four empty lists.
- An edited draft sends `body !== generated_body` with source lists unchanged.
- The store failure path leaves the block in invented grammar — asserted on the
  rendered edge and glyph, not on component state.
- `anchor` defaults to the section being read.

Existing suites stay green; `hues.test.ts` is untouched by this work.

---

## 8. Out of scope

Designed on boards 4, 5, 7 and 8, deliberately not specified here:

- **Revise** (board 4) — `generate`'s `revision: { previous, note }` already
  supports it; it is a second action on `DraftCard`, not new plumbing.
- **Placement picker** (board 5) — the anchor defaults correctly without it.
- **Add someone** (board 7) — needs an entity-creation call this spec has not
  audited; the rail action ships disabled.
- **Alias reveal** (board 8) — `tableAPI.tellTable` already takes an alias and
  the existing `Reveal` component already exposes it.

Also out of scope: material that belongs to no section — a faction, a house
rule, a rumour with no scene. The reader anchor cannot express it. That wants a
second entry point from Prep, and it is a real gap rather than an oversight.
