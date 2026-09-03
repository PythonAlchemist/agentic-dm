# Table — Design Specification

One promise: a reader can always tell what the published book says from what a model
invented. A hue names a SOURCE (`web/src/lib/palette.ts`); nothing else may borrow it;
chrome is carried by contrast alone. Everything below serves that.

Dark only, for now (see §7). All ratios are WCAG contrast against **ground `#131110`**
and **surface `#1c1917`**, computed, not estimated.

---

## 1. Verdict

**A wins.** The product is a table at night, not a terminal: A's warm ground, single
light source (radial wash + top-lit border, no shadows), and Literata for the book's
own voice are the identity we ship. A's neutrals were the only ones verified exact
(ink 15.1:1) and they survive re-measurement below.

Taken from **C**, wholesale: the chrome ladder (§3) — the concrete answer to why the
product looks unfinished — remapped onto A's warm neutrals; the disciplined type scale
with a role per step (§4); the 4px grid and fixed row heights (§5); the Library
treatment (sticky chapter headers, hairlines between chapters only, chapter-tick rail,
`/` to filter); "elevation is lightness, never shadow" (which A independently agrees
with). Taken from **B**: the 16px floor and ~65ch cap on book prose; the 42rem prose
column with the saved width becoming a provenance/sidenote rail; horizontal rules
instead of boxes.

**Overruled, and why:**

- ~~**All three designers on the source hues.**~~ **CORRECTED — this ruling was
  wrong.** The comparison was run against emerald-500 and amber-400 while the
  product was painted in emerald-300 and amber-200, so it measured a palette the
  app never had. Measured properly, what shipped had a worst pair of **dE 8.8**
  (`yours` vs `invented` under deuteranopia — amber and rose collapsing, the two
  the promise exists to keep apart). The designers were right that a problem
  existed; C's diagnosis, that `invented` needed to move toward magenta so its
  blue channel separates it, was the correct one. The hues are now searched
  values with a worst pair of **dE 36.2**, every pair above 36, contrast
  7.76–9.17 on surface, and `web/src/lib/__tests__/hues.test.ts` computes this
  from `globals.css` on every run so a number in a comment can no longer be the
  only thing holding it. Superseded text follows for the record:

  Each moved a hue "for colour blindness"
  and each made it worse. Measured worst-pair separation under deuteranopia/protanopia
  (CIELab dE): current emerald/amber/sky/rose **29.9 / 35.0**; A's teal set 16.6 / 22.2;
  B's magenta set 24.2 / **10.2** (book and invented near-identical under protanopia —
  the exact pair the promise exists to keep apart). C's set, measured to close the gap
  (Viénot 1999 simulation): worst pairs 24.7 / 17.8 — competitive, not better than the
  incumbent, and switching costs a re-teach of colours already deployed across 32 files.
  **The current four hues stay.** A and B also diagnosed the wrong at-risk pair: it is
  **book vs table** (green vs blue), not book vs invented — so the redundant non-colour
  channel (§6) is load-bearing precisely there: serif-vs-grotesk and §-vs-❝ separate
  book from table even where hue fails.
- **B on a mandatory light theme.** All four source hues fail 3:1 on B's cream
  (2.31 / 1.52 / 1.52 / 1.72). See §7: deferred, not rejected.
- **C on the cool ground** (`#0B0B0D` is the wrong character) and on Source Serif 4
  (one serif in the product: Literata, which carries optical sizing).
- **A on its type scale** (12/13/14/16/19/24 has no 11px label step and no read-aloud
  step; the merged scale in §4 replaces it) and on its teal (above).
- **B on Literata-for-everything.** The serif is a provenance channel: it marks the
  book's voice and nothing else. Setting app headings in it would spend the strongest
  non-colour signal on decoration.

---

## 2. Tokens

Replace the `:root`/`@theme` block in `src/app/globals.css` with:

```css
@theme {
  /* Ground ladder — elevation is lightness, never shadow. */
  --color-ground:   #131110;  /* page */
  --color-surface:  #1c1917;  /* panel, card        1.08:1 vs ground */
  --color-overlay:  #262220;  /* popover, menu      1.19 / 1.11 */
  --color-line:     #2e2a24;  /* hairline rules     1.32 / 1.23 */

  /* Ink ladder — three text roles, assigned, not accidental. */
  --color-ink:       #eae6df; /* primary text      15.14 / 14.06 */
  --color-ink-dim:   #a89f93; /* secondary text     7.21 /  6.70 */
  --color-ink-faint: #8a8175; /* meta, timestamps   4.91 /  4.56 */
  --color-chrome:    #f4f0e8; /* focus ring, primary fill  16.57 / 15.39 */

  /* THE FOUR SOURCES. Nothing else may use these (palette.ts is the contract). */
  --color-book:     #6ee7b7;  /* the published book       12.35 / 11.47 */
  --color-yours:    #fde68a;  /* written for this campaign 15.12 / 14.04 */
  --color-table:    #7dd3fc;  /* said at the table         11.29 / 10.49 */
  --color-invented: #fda4af;  /* the model supplied it      9.96 /  9.25 */

  --radius-md: 6px;           /* the one radius (§5) */

  /* Type steps (size / line-height); roles in §4. */
  --text-label: 0.6875rem;  --text-label--line-height: 1rem;
  --text-meta:  0.75rem;    --text-meta--line-height:  1.125rem;
  --text-ui:    0.8125rem;  --text-ui--line-height:    1.25rem;
  --text-body:  0.875rem;   --text-body--line-height:  1.375rem;
  --text-canon: 1rem;       --text-canon--line-height: 1.625rem;
  --text-aloud: 1.125rem;   --text-aloud--line-height: 1.75rem;
  --text-title: 1.25rem;    --text-title--line-height: 1.75rem;
}

@theme inline {
  --font-sans:  var(--font-geist-sans);
  --font-mono:  var(--font-geist-mono);
  --font-serif: var(--font-literata);
}
```

`body` gets ground + ink + A's single light source:

```css
body {
  background:
    radial-gradient(80rem 40rem at 50% -10rem, rgb(234 230 223 / 0.04), transparent 70%),
    var(--color-ground);
  color: var(--color-ink);
  font-family: var(--font-geist-sans), ui-sans-serif, system-ui, sans-serif;
}
```

Surfaces carry the lit edge instead of a shadow — every `bg-surface` panel and
`bg-overlay` popover adds `border-t border-[rgb(244_240_232/0.08)]`. `box-shadow`
is banned product-wide (invisible on near-black; C is right).

Rules for the ladder: `line` is for hairlines only, never text. `ink-faint` is the
floor — nothing readable may be darker. Retire the accidental
`neutral-500`/`neutral-600` text everywhere; every text colour is one of ink /
ink-dim / ink-faint / a source hue, chosen on purpose. Source hues are used **solid**
— the `/80` opacity variants in `palette.ts` composite differently over every surface
and are dropped.

Update `palette.ts` to point its semantic names at these tokens
(`text-book`, `text-yours`, `text-table`, `text-invented`); the file and its comment
remain the audit trail.

---

## 3. The chrome ladder

Hueless chrome reads as interactive through **lightness steps of ink over the ground
ladder** — never a hue, never a shadow. Exact values:

| State | Treatment | Resolved on ground / surface |
|---|---|---|
| rest | transparent bg; text `ink-dim` (rows, nav) or `ink` (content) | — |
| hover | bg `rgb(234 230 223 / 0.05)`; text steps up one (dim→ink) | `#1e1c1a` / `#262321` |
| selected | bg `rgb(234 230 223 / 0.09)`; text `ink`; `font-weight: 500` | `#262423` / `#2f2b29` |
| focus-visible | `outline: 1.5px solid var(--color-chrome); outline-offset: 1px` | ring 16.57:1 vs ground |
| primary action | bg `chrome`, text `ground` (16.57:1), weight 500; hover bg `#fffdf8`; disabled opacity 40% | **once per screen** |
| grip / divider | rest `line`; hover `ink-faint` | — |

The hover and selected fills are ink-toned alpha so they warm both ground and surface
consistently — define them once as utilities (`.chrome-hover`, `.chrome-selected`) or
inline arbitrary values; do not hand-pick per-surface hexes. Selection is *always*
fill + weight, never colour. `CHROME` in `palette.ts` is rewritten to exactly these
five entries.

---

## 4. Type

Faces (`next/font/google` in `layout.tsx`):

- `Geist` → `--font-geist-sans` — the apparatus: all UI, labels, app prose. (wired)
- `Geist_Mono` → `--font-geist-mono` — numbers, dice, timestamps, IDs, keys. (wired)
- `Literata` → `--font-literata` — **verbatim book text only**, loaded with
  `{ variable: '--font-literata', subsets: ['latin'], style: ['normal','italic'] }`
  (variable face; optical size axis comes free).

**The rule for the serif:** Literata appears exactly when the words are the published
book's words — section prose, read-aloud text, an inline quotation from the book.
Paraphrase, summary, your material, table talk, and model output are never serif.
The face itself is a provenance channel (§6) and this is why B's
serif-for-everything is overruled.

The scale — 7 steps replacing the current 9, each with one role:

| Step | Size/leading | Face, weight, tracking | Role |
|---|---|---|---|
| `text-label` | 11/16 | Geist Mono 500, uppercase, tracking `0.08em` | keys, column heads, source labels |
| `text-meta` | 12/18 | Geist 400 | timestamps, counts, captions, sidenotes |
| `text-ui` | 13/20 | Geist 400 (500 selected) | **the default**: rows, buttons, nav, inputs |
| `text-body` | 14/22 | Geist 400 | app prose: chat, descriptions, your notes |
| `text-canon` | 16/26 | Literata 400 | book prose. **The floor — book text never smaller.** |
| `text-aloud` | 18/28 | Literata 400, italic allowed | read-aloud / boxed text, presented at the table |
| `text-title` | 20/28 | Geist 600, tracking `-0.01em` | screen titles |

Migration: `text-sm` → `text-ui` or `text-body` by role; `text-[11px]` → `text-label`;
`text-xs` → `text-meta`. Numbers always Geist Mono at the surrounding step's size,
`tabular-nums`.

---

## 5. Space and composition

- **Grid:** 4px. Allowed spacing steps: 4 / 8 / 12 / 16 / 24 / 32 / 48 / 64
  (Tailwind 1–16; nothing off-scale, no 5s or 7s).
- **Page widths — exactly three,** replacing today's five:
  - **Reading** (`s/[id]` section reader, Told, What we know entries): a `42rem`
    prose column, left-set inside a `max-w-5xl` shell; the remaining right width is
    the **provenance rail** (sidenotes: citations, source labels, ⚠ reliability notes)
    at `text-meta`. Book prose never exceeds this column (~65ch).
  - **Panel** (`max-w-3xl`): Library, Party, Setup/Settings, Log, Your table, entity pages.
  - **Full**: Play, the map, `/lab`. Internal columns manage their own measure.
- **Row heights** (fixed, content centred): 28px dense meta rows · **32px default
  list row** (Library) · 44px touch rows (every player-facing list, Party roster).
- **Radius: `6px`, one value.** Codemod `rounded` (75×) and `rounded-lg` (8×) →
  `rounded-md`; `rounded-full` survives only for avatars, portrait thumbs, and pills.
- **Border policy:** hairline `line` rules **between groups, never around things**.
  Cards/panels are `bg-surface` + the lit top edge — no 1px full borders, no boxes
  around prose (B), no hairline under every row ("547 hairlines is grey fog" — C).
  Between-chapter rules only in the Library; whitespace separates rows.
- **Illustrations** (286): bleed to the prose column width, `rounded-md`, with a
  bottom scrim (`linear-gradient(transparent, rgb(19 17 16 / 0.5))`) so captions in
  `text-meta` sit legibly on them (A).

---

## 6. Provenance grammar

Every source is marked by **hue + a redundant non-colour channel, always both** —
hue never works alone (A's refusal, kept). Because the measured at-risk pair is
book/table, their non-colour channels must differ in *kind*, and they do: face and
glyph.

| Source | Hue | Glyph | Extra channel |
|---|---|---|---|
| book | `--color-book` | `§` | **Literata**, plus a citation (chapter · section) |
| yours | `--color-yours` | `✎` | — |
| table | `--color-table` | `❝` | attribution (speaker · session) |
| invented | `--color-invented` | `◇` | **dashed** border in block form |

Three contexts, exactly:

1. **List row** — a `2px` left edge in the source hue spanning the row height
   (`border-l-2`, dashed for invented), plus the glyph + source word as a trailing
   `text-label` in the hue (`§ BOOK`, `◇ INVENTED`). Row text stays ink/ink-dim;
   never tint a whole row.
2. **Block of prose** — `border-l-2` in the hue (dashed for invented), `pl-4`; a
   header line above the text: glyph + source word in `text-label` in the hue, with
   the citation (book) or attribution (table) beside it in `text-meta` ink-faint.
   Book blocks are set `text-canon`/`text-aloud` Literata; all other blocks Geist
   `text-body`. Invented blocks additionally end with a `text-meta` ink-faint line:
   "invented — nothing stands behind this."
3. **Inline mention** — the span in the source hue with the glyph prefixed
   (`§ Strahd's brides`, `◇ the innkeeper's name`); `title`/popover names the source
   in full. The glyph is mandatory; a hue-only inline span is a bug.

Reliability stays off this axis (palette.ts): ⚠ + ink-dim, no hue, ever.

---

## 7. Light theme: not today

Deferred, with a defined gate — not rejected. The measurements decide it: all four
source hues fail 3:1 on cream (book 2.31, yours 1.52, table 1.52, invented 1.72), so
a light theme requires a **second full set of source hues**; B's darkened paper
variants (4.87–6.31:1) are the approved starting candidates, but they have not been
CVD-simulated, and every pitch that moved a hue un-measured made the promise weaker.
B's argument (players at noon on phones) is real and wins eventually. Gate to ship:
the light source set passes ≥4.5:1 on paper **and** worst-pair dE ≥ the incumbent's
29.9/35.0 under the same simulation, and every component reads tokens (no hardcoded
neutrals — which this spec's migration accomplishes as a side effect). Until then the
product is dark always, as `globals.css` already states.

---

## 8. Per-screen change list (work top to bottom)

**0. Foundation** — `globals.css` (§2 tokens, body, lit-edge utility, chrome-ladder
utilities), `layout.tsx` (add Literata), `palette.ts` (retarget SOURCE/CHROME to
tokens; keep the comment), codemod radii and type steps. Everything after is
per-screen application.

1. **Library** (548 sections; worst offender) — panel width; rows 32px `text-ui`;
   delete per-row hairlines, keep one `line` rule between chapters; sticky chapter
   headers (`bg-surface` + lit edge); chapter-tick scroll rail; `/` focuses filter;
   rows with DM/table/model annotations get the §6 row edge; selected row = chrome
   ladder, not a hue.
2. **Section reader** (`s/[id]`, shared by Library/Told links) — reading layout:
   42rem Literata `text-canon` column, provenance rail with citation + ⚠ sidenotes,
   read-aloud passages as §6 book blocks at `text-aloud`, illustrations per §5.
3. **Play** — full width; running order rows on the chrome ladder (selected = fill +
   weight); read-aloud in book grammar; every model contribution rendered in invented
   grammar before the DM can speak it; the screen's one primary action gets the
   chrome fill.
4. **Prep** — full-width working layout, internal columns on the 4px grid;
   `GenerationCard` output is invented-grammar blocks until accepted as yours
   (then re-marked ✎ yours — the transition is the product's whole point made
   visible); primary = Generate, once.
5. **Told** — reading layout; every told item is a §6 block with its source edge;
   timestamps `text-meta` mono in the rail.
6. **Party (DM)** — panel width; 44px roster rows; portraits `rounded-md`; stats in
   mono `tabular-nums`; no source hues anywhere on this screen unless a fact is
   being attributed.
7. **Map** (`m/[id]`) — full width; pins are chrome (ink on ground ladder), selection
   via ladder; a pin only takes a source hue when it *marks a source claim* (e.g. an
   invented location is `◇` + rose pin); labels `text-label`.
8. **Setup / Settings** — panel width; form labels `text-label` ink-dim; inputs
   `bg-surface` with focus ring per §3; destructive actions are ink + ⚠ confirmation,
   never red (red is nobody's hue, but a fifth hue is still a hue — contrast + ⚠).
9. **Player: Your table + Party** — panel width, 44px rows (phones); identical tokens,
   restricted content; the player's one primary action chrome-filled.
10. **Player: Log** — panel width; each entry in §6 row grammar (this is where the
    promise faces players); timestamps mono `text-meta`.
11. **Player: What we know** — the promise's proving ground: search input with §3
    focus ring; every result carries full §6 grammar; book-derived entries render
    their quoted text in Literata with citations; model-derived entries are
    unmissably ◇/dashed/rose.

`/lab` inherits tokens only; its dense layout is out of scope.
