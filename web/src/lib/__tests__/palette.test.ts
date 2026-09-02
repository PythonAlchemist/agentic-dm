/**
 * The colour rule, checked rather than only stated.
 *
 * `palette.ts` says a hue names a SOURCE and nothing else may borrow it -- and
 * it existed as pure documentation, imported by nobody, while the subgraph
 * legend painted emerald, amber and blue for a completely different axis. So
 * in the one panel showing what the model read, an amber dot meant "named in
 * an answer" rather than "yours", on the axis where confusing those two
 * matters most.
 *
 * The file cannot stop the next violation on its own. This can.
 */
import { describe, expect, it } from 'vitest'

import { HOW_COLOUR, HOW_GLYPH, HOW_LABEL, NOT_HELD } from '@/components/subgraph-legend'
import {
  CAUTION,
  CHROME,
  SOURCE,
  SOURCE_EDGE,
  SOURCE_GLYPH,
  SOURCE_WORD,
} from '@/lib/palette'

/** The four token names the sources own. They were Tailwind hue families
 *  (`emerald`, `amber`, `sky`, `rose`) until the design pass moved every
 *  colour behind a semantic token in `globals.css`; the hues themselves are
 *  unchanged, which is the point of the token indirection. */
const SOURCE_HUES = ['book', 'yours', 'table', 'invented']

/** Their hex forms, which an inline `style` uses instead of a class. */
const SOURCE_HEX = [
  '#34d399', '#10b981', '#6ee7b7', // emerald
  '#fbbf24', '#f59e0b', '#fcd34d', // amber
  '#38bdf8', '#0ea5e9', '#7dd3fc', // sky
  '#fb7185', '#f43f5e', '#fda4af', // rose
]

describe('a hue names a source and nothing else', () => {
  it('each source keeps its own hue', () => {
    expect(SOURCE.book).toBe('text-book')
    expect(SOURCE.yours).toBe('text-yours')
    expect(SOURCE.table).toBe('text-table')
    expect(SOURCE.invented).toBe('text-invented')
  })

  it('no two sources share a hue', () => {
    expect(new Set(Object.values(SOURCE)).size).toBe(4)
  })

  it('every source carries a second channel that is not colour', () => {
    // MEASURED, NOT ASSUMED: three designers each proposed moving a hue for
    // colour blindness and each made the worst pair worse. The redundancy is
    // what actually carries the promise for a reader who sees no hue at all,
    // so a source with a colour and no glyph is a bug.
    for (const source of SOURCE_HUES) {
      expect(SOURCE_GLYPH[source as keyof typeof SOURCE_GLYPH]).toBeTruthy()
      expect(SOURCE_WORD[source as keyof typeof SOURCE_WORD]).toBeTruthy()
    }
  })

  it('no two sources share a glyph either', () => {
    expect(new Set(Object.values(SOURCE_GLYPH)).size).toBe(4)
    expect(new Set(Object.values(SOURCE_WORD)).size).toBe(4)
  })

  it('invented is the one marked by a broken line', () => {
    // Nothing stands behind it, and the dashes say so without colour.
    expect(SOURCE_EDGE.invented).toContain('dashed')
    for (const source of ['book', 'yours', 'table'] as const) {
      expect(SOURCE_EDGE[source]).not.toContain('dashed')
    }
  })

  it('chrome carries contrast, never a hue', () => {
    for (const value of Object.values(CHROME)) {
      for (const hue of SOURCE_HUES) expect(value).not.toContain(hue)
    }
  })

  it('caution is not a source and takes no hue', () => {
    for (const hue of SOURCE_HUES) expect(CAUTION).not.toContain(hue)
  })
})

describe('how a node arrived is a second axis', () => {
  it('it borrows no source hue', () => {
    // It used to be emerald / amber / blue -- the source vocabulary, meaning
    // something else entirely.
    for (const colour of [...Object.values(HOW_COLOUR), NOT_HELD]) {
      expect(SOURCE_HEX).not.toContain(colour.toLowerCase())
    }
  })

  it('it is carried by shape instead, which is what the palette prescribes', () => {
    expect(new Set(Object.values(HOW_GLYPH)).size).toBe(
      Object.keys(HOW_GLYPH).length,
    )
  })

  it('every state a node can be in has a glyph, a colour and a label', () => {
    for (const state of Object.keys(HOW_LABEL)) {
      expect(HOW_GLYPH[state], `glyph for ${state}`).toBeTruthy()
      expect(HOW_COLOUR[state], `colour for ${state}`).toBeTruthy()
    }
  })

  it('a name the agent is not holding is dimmer than any it is', () => {
    const held = Object.values(HOW_COLOUR).map((c) => parseInt(c.slice(1, 3), 16))
    expect(parseInt(NOT_HELD.slice(1, 3), 16)).toBeLessThan(Math.min(...held))
  })
})
