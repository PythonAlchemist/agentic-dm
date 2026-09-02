import { describe, expect, it } from 'vitest'

import { EMPHASIS_MARK, withEmphasis } from '@/lib/reading'

/**
 * The book's italics were reaching the reader as punctuation: every
 * `_emphasised_` line in 1,378 sections showed its underscores.
 */
describe('the book’s emphasis', () => {
  it('marks a whole-line emphasis', () => {
    const found = withEmphasis('_An Adventure for 1st-Level Characters_')
    expect(found).toBe(`${EMPHASIS_MARK}An Adventure for 1st-Level Characters${EMPHASIS_MARK}`)
  })

  it('marks emphasis inside a sentence', () => {
    expect(withEmphasis('the spell _fireball_ is loud')).toBe(
      `the spell ${EMPHASIS_MARK}fireball${EMPHASIS_MARK} is loud`,
    )
  })

  it('leaves an underscore inside a word alone', () => {
    // `section_id` and `named_by_book` appear in prose about the graph, and a
    // greedy rule would italicise the middle of them.
    expect(withEmphasis('the section_id column')).toBe('the section_id column')
  })

  it('leaves a lone underscore alone', () => {
    expect(withEmphasis('a _ b')).toBe('a _ b')
  })

  it('does not span a line break', () => {
    expect(withEmphasis('_open\nclose_')).toBe('_open\nclose_')
  })

  it('handles emphasis after an opening bracket', () => {
    expect(withEmphasis('(_see below_)')).toBe(
      `(${EMPHASIS_MARK}see below${EMPHASIS_MARK})`,
    )
  })
})
