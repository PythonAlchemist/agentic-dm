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
import { CAUTION, CHROME, SOURCE } from '@/lib/palette'

/** The four hue families the sources own. */
const SOURCE_HUES = ['emerald', 'amber', 'sky', 'rose']

/** Their hex forms, which an inline `style` uses instead of a class. */
const SOURCE_HEX = [
  '#34d399', '#10b981', '#6ee7b7', // emerald
  '#fbbf24', '#f59e0b', '#fcd34d', // amber
  '#38bdf8', '#0ea5e9', '#7dd3fc', // sky
  '#fb7185', '#f43f5e', '#fda4af', // rose
]

describe('a hue names a source and nothing else', () => {
  it('each source keeps its own hue', () => {
    expect(SOURCE.book).toContain('emerald')
    expect(SOURCE.yours).toContain('amber')
    expect(SOURCE.table).toContain('sky')
    expect(SOURCE.invented).toContain('rose')
  })

  it('no two sources share a hue', () => {
    const hues = Object.values(SOURCE).map(
      (c) => SOURCE_HUES.find((h) => c.includes(h)),
    )
    expect(new Set(hues).size).toBe(hues.length)
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
