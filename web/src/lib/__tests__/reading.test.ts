/**
 * Splitting a section into what a reader sees.
 *
 * The book shipped 286 illustrations inside its own prose and the app replaced
 * every one with the string "[illustration]". Restoring them is the first half
 * of image support, and it is a discard to stop rather than a pipeline to
 * build — so the rules for where a figure sits deserve the same care as the
 * text around it.
 */
import { describe, expect, it } from 'vitest'

import { readingBlocks } from '@/lib/reading'

describe('the book’s own figures', () => {
  it('becomes an illustration block, not a placeholder', () => {
    const blocks = readingBlocks('![image](https://x.test/a.png)', 'H')
    expect(blocks).toEqual([
      { kind: 'illustration', src: 'https://x.test/a.png', alt: '' },
    ])
  })

  it('keeps the prose either side of it, in order', () => {
    const blocks = readingBlocks(
      'Before.\n\n![image](a.png)\n\nAfter.',
      'H',
    )
    expect(blocks.map((b) => b.kind)).toEqual(['prose', 'illustration', 'prose'])
    expect(blocks[0]).toMatchObject({ text: 'Before.' })
    expect(blocks[2]).toMatchObject({ text: 'After.' })
  })

  it('drops the harvester’s useless alt text', () => {
    // Every harvested figure says "image", which tells a screen reader nothing.
    const [block] = readingBlocks('![image](a.png)', 'H')
    expect(block).toMatchObject({ alt: '' })
  })

  it('keeps real alt text when the book gave any', () => {
    const [block] = readingBlocks('![Strahd von Zarovich](a.png)', 'H')
    expect(block).toMatchObject({ alt: 'Strahd von Zarovich' })
  })

  it('leaves an image inside a sentence alone', () => {
    // Only a figure on its own line is the book placing a plate; anything
    // inline is part of the sentence and splitting there would break it.
    const text = 'The sign reads ![image](a.png) and nothing else.'
    expect(readingBlocks(text, 'H')).toEqual([{ kind: 'prose', text }])
  })

  it('handles several in a row without merging them', () => {
    const blocks = readingBlocks('![image](1.png)\n![image](2.png)', 'H')
    expect(blocks.map((b) => b.kind)).toEqual(['illustration', 'illustration'])
  })
})

describe('the heading the drawer already shows', () => {
  it('is dropped when the section repeats it first', () => {
    const blocks = readingBlocks('# Vallaki\n\nA town.', 'Vallaki')
    expect(blocks).toEqual([{ kind: 'prose', text: 'A town.' }])
  })

  it('is kept when it says something else', () => {
    const blocks = readingBlocks('# Somewhere Else\n\nA town.', 'Vallaki')
    expect(blocks[0]).toMatchObject({ text: '# Somewhere Else\n\nA town.' })
  })

  it('is kept when it comes later, because that is structure', () => {
    const blocks = readingBlocks('A town.\n\n# Vallaki\n\nInside.', 'Vallaki')
    expect(blocks[0]).toMatchObject({ text: 'A town.\n\n# Vallaki\n\nInside.' })
  })
})

describe('what it never does', () => {
  it('emits no empty prose blocks', () => {
    const blocks = readingBlocks('\n\n![image](a.png)\n\n', 'H')
    expect(blocks).toHaveLength(1)
  })

  it('survives an empty section', () => {
    expect(readingBlocks('', 'H')).toEqual([])
  })
})
