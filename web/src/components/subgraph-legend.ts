/**
 * The colour vocabulary the working set is read in, shared by the ledger and
 * the graph so the two views cannot drift apart. A node that is amber in one
 * must be amber in the other -- they are the same claim shown two ways.
 *
 * IT BORROWED THE SOURCE HUES AND MEANT SOMETHING ELSE BY THEM. `palette.ts`
 * states the rule -- a hue names a SOURCE and nothing else may borrow it --
 * and this painted emerald for "resolved from a question", amber for "named in
 * an answer", blue for "fetched by a tool". So in the one panel showing what
 * the model actually read, an amber dot did not mean "yours": a canon entity
 * the model happened to name wore the campaign's colour, on the axis where
 * confusing those two matters most.
 *
 * HOW A THING ARRIVED IS A SECOND AXIS, and the palette already says what to do
 * with one: caution is not a source either, and it is carried by a GLYPH and
 * muted text rather than by a hue. So the shape says how a node got here and
 * the neutrals carry contrast, which leaves the four hues saying the only
 * thing they say.
 */

/** How a thing got here, by SHAPE. Weakest evidence gets the emptiest mark. */
export const HOW_GLYPH: Record<string, string> = {
  seeded: '●', // filled: a name the question itself resolved
  named: '◐', // half: the answer happened to say it
  expanded: '○', // hollow: a tool reached for it
}

/** Contrast, not hue. Brighter is stronger evidence. */
export const HOW_COLOUR: Record<string, string> = {
  seeded: '#e5e5e5',
  named: '#a3a3a3',
  expanded: '#737373',
}

export const HOW_LABEL: Record<string, string> = {
  seeded: 'resolved from a question',
  named: 'named in an answer',
  expanded: 'fetched by a tool',
}

/** A name the agent knows OF but is not holding: it appears only inside a
 *  relationship line, has no id here, and a follow-up cannot resolve through
 *  it. Dimmest of all, and hollow. */
export const NOT_HELD = '#525252'
export const NOT_HELD_GLYPH = '○'
