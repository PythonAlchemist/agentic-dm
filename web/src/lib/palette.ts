/**
 * Colour is a trust carrier in this product, so it may not also be decoration.
 *
 * IT WAS BOTH. Amber meant, simultaneously: the selected tab, the primary
 * button, a focus ring, the DM's question text, a keyword-match caveat, an
 * unverified price, YOUR material, and INVENTED material — the last two one
 * shade apart in the same hue, which are the two a DM must never confuse.
 * Twenty-one amber values across thirteen files, meaning at least four
 * different things.
 *
 * THE RULE: a hue names a SOURCE, and nothing else may borrow it.
 *
 *   emerald  the published book
 *   amber    yours — written for this campaign
 *   sky      the table — said in conversation, in no book
 *   rose     invented — the model supplied it, nothing stands behind it
 *
 * Chrome gets no hue at all. Selection, focus and the primary action are
 * carried by CONTRAST — a brighter neutral against a dark ground — which is
 * legible without competing for meaning, and leaves the four above to say the
 * only thing they say.
 *
 * CAUTION IS NOT A SOURCE and does not get a hue either. "This rate is
 * unverified" and "you edited this, the citations were not re-checked" are
 * claims about RELIABILITY, on a different axis from where a sentence came
 * from. They carry a ⚠ and muted text: the glyph is the signal.
 *
 * Kept as strings rather than a Tailwind theme extension because these are
 * read by a person auditing what a colour means, and one file they can open is
 * worth more than a config indirection.
 */

/** The four sources. Nothing else may use these. */
export const SOURCE = {
  book: 'text-emerald-300/80',
  yours: 'text-amber-200/80',
  table: 'text-sky-300/80',
  invented: 'text-rose-300/80',
} as const

/** Chrome: contrast, never hue. */
export const CHROME = {
  /** A selected tab, a chosen option. */
  selected: 'bg-neutral-800 text-neutral-100',
  /** The one action a screen is for: Ask, Store, Generate. */
  primary:
    'bg-neutral-200 text-neutral-950 hover:bg-white transition-colors disabled:opacity-30',
  /** A focused input. */
  focus: 'focus:border-neutral-500',
  /** A draggable divider under the cursor. */
  grip: 'hover:bg-neutral-600',
} as const

/** Reliability, on its own axis. The glyph carries it, not the colour. */
export const CAUTION = 'text-neutral-400'
