/**
 * The colour vocabulary the working set is read in, shared by the ledger and
 * the graph so the two views cannot drift apart. A node that is amber in one
 * must be amber in the other -- they are the same claim shown two ways.
 */

/** How a thing got here. */
export const HOW_COLOUR: Record<string, string> = {
  seeded: '#34d399',
  named: '#fbbf24',
  expanded: '#60a5fa',
}

export const HOW_LABEL: Record<string, string> = {
  seeded: 'resolved from a question',
  named: 'named in an answer',
  expanded: 'fetched by a tool',
}

/** A name the agent knows OF but is not holding: it appears only inside a
 *  relationship line, has no id here, and a follow-up cannot resolve through
 *  it. Grey is that claim. */
export const NOT_HELD = '#737373'
