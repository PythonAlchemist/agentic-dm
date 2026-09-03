/**
 * Colour is a trust carrier in this product, so it may not also be decoration.
 *
 * IT WAS BOTH. Amber meant, simultaneously: the selected tab, the primary
 * button, a focus ring, the DM's question text, a keyword-match caveat, an
 * unverified price, YOUR material, and INVENTED material — the last two one
 * shade apart in the same hue, which are the two a DM must never confuse.
 *
 * THE RULE: a hue names a SOURCE, and nothing else may borrow it.
 *
 *   book      the published book
 *   yours     written for this campaign
 *   table     said in conversation, in no book
 *   invented  the model supplied it, nothing stands behind it
 *
 * Chrome gets no hue at all. Selection, focus and the primary action are
 * carried by CONTRAST — see `CHROME` below and `DESIGN.md` §3.
 *
 * CAUTION IS NOT A SOURCE and does not get a hue either. "This rate is
 * unverified" is a claim about RELIABILITY, on a different axis from where a
 * sentence came from. It carries a ⚠ and muted text: the glyph is the signal.
 *
 * THE HUES WERE RETUNED, AFTER A MEASUREMENT ERROR WAS FOUND. Three designers
 * independently moved one "for colour blindness" and all three were overruled
 * on a simulation that had been run against the wrong colours — emerald-500 and
 * amber-400, while the product was painted in emerald-300 and amber-200.
 *
 * Measured properly, what shipped had a worst pair of dE 8.8 under
 * deuteranopia: YOURS against INVENTED. Amber and rose collapsed into each
 * other — the DM's own material and a model's invention, which are the two
 * this file exists to keep apart, and one shade apart in the same hue was
 * exactly the defect its opening paragraph describes.
 *
 * The values now are searched, not picked: each source keeps its family, and
 * lightness and chroma are tuned for the ground under both common colour
 * blindnesses. Worst pair dE 36.2; every pair clears 36.
 *
 * WHICH IS WHY HUE NEVER WORKS ALONE. Every source is marked by hue AND a
 * redundant channel, and book and table differ in KIND: the book's words are
 * set in a serif and carry `§` with a citation; table talk carries `❝` with a
 * speaker. A reader who sees no colour at all still reads the provenance.
 *
 * The values live in `globals.css` as tokens; this file names their jobs.
 */

/** The four sources. Nothing else may use these. */
export const SOURCE = {
  book: 'text-book',
  yours: 'text-yours',
  table: 'text-table',
  invented: 'text-invented',
} as const

/** The left edge that marks a row or a block. Dashed for invented: nothing
 *  stands behind it, and the broken line says so without colour. */
export const SOURCE_EDGE = {
  book: 'border-l-2 border-book',
  yours: 'border-l-2 border-yours',
  table: 'border-l-2 border-table',
  invented: 'border-l-2 border-dashed border-invented',
} as const

/** The mandatory non-colour channel. An inline mention in a hue with no glyph
 *  is a bug, not a style choice. */
export const SOURCE_GLYPH = {
  book: '§',
  yours: '✎',
  table: '❝',
  invented: '◇',
} as const

/** What a reader is told the source IS, in words. Kept beside the hue so the
 *  label and the colour cannot drift apart. */
export const SOURCE_WORD = {
  book: 'BOOK',
  yours: 'YOURS',
  table: 'TABLE',
  invented: 'INVENTED',
} as const

export type Source = keyof typeof SOURCE

/** Chrome: contrast, never hue.
 *
 *  THE LADDER IS THE WHOLE ANSWER to why a product with no accent colour looks
 *  unfinished. Interactivity is lightness over the ground ladder, applied
 *  consistently: hover lifts, selection lifts further and adds weight, focus
 *  rings in `chrome`, and exactly one primary action per screen is filled.
 */
export const CHROME = {
  /** A row or tab that responds to the pointer. */
  row: 'chrome-row transition-colors',
  /** The chosen row, tab or option. Fill plus weight — never colour. */
  selected: 'chrome-selected',
  /** The one action a screen is for. Once per screen. */
  primary:
    'bg-chrome text-ground font-medium hover:bg-[#fffdf8] transition-colors disabled:opacity-40',
  /** A panel that catches the light from above, instead of a shadow. */
  lit: 'bg-surface lit',
  /** A draggable divider under the cursor. */
  grip: 'bg-line hover:bg-ink-faint transition-colors',
} as const

/** Reliability, on its own axis. The glyph carries it, not the colour. */
export const CAUTION = 'text-ink-dim'
