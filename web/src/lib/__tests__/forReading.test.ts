/**
 * The one client code that ALTERS the book's text before a DM reads it.
 *
 * Everything else on this screen renders what the API sent. `forReading` drops
 * a heading and rewrites image lines, so a bug here changes what the book
 * appears to say -- and it had no test at all, in a project whose whole claim
 * is that a DM can tell the book from everything else.
 */
import { describe, expect, it } from 'vitest'

import { forReading } from '@/components/SectionReader'

describe('dropping the heading the drawer already shows', () => {
  it('removes a first heading that repeats it', () => {
    expect(forReading('# The Old Bonegrinder\n\nA windmill.', 'The Old Bonegrinder'))
      .toBe('A windmill.')
  })

  it('keeps a first heading that says something else', () => {
    const text = '# Something Else\n\nA windmill.'
    expect(forReading(text, 'The Old Bonegrinder')).toBe(text)
  })

  it('keeps a LATER heading, which is structure the reader wants', () => {
    const text = 'A windmill.\n\n# The Old Bonegrinder\n\nInside.'
    expect(forReading(text, 'The Old Bonegrinder')).toBe(text)
  })

  it('ignores blank lines before the heading', () => {
    expect(forReading('\n\n## Vallaki\n\nA town.', 'Vallaki')).toBe('A town.')
  })

  it('matches regardless of heading depth', () => {
    expect(forReading('#### N2. Blue Water Inn\n\nBeer.', 'N2. Blue Water Inn'))
      .toBe('Beer.')
  })

  it('tolerates surrounding whitespace in the drawer heading', () => {
    expect(forReading('# Vallaki\n\nA town.', '  Vallaki  ')).toBe('A town.')
  })
})

describe('image lines', () => {
  it('replaces one with a marker, because the alt text is the word "image"', () => {
    expect(forReading('![image](https://example.test/x.png)\n\nA caption.', 'H'))
      .toBe('[illustration]\n\nA caption.')
  })

  it('leaves an image that sits inside a sentence alone', () => {
    const text = 'The sign reads ![image](x.png) and nothing else.'
    expect(forReading(text, 'H')).toBe(text)
  })

  it('handles several', () => {
    expect(forReading('![a](1.png)\n![b](2.png)', 'H'))
      .toBe('[illustration]\n[illustration]')
  })
})

describe('what it never does', () => {
  it('leaves ordinary prose untouched', () => {
    const text = 'Strahd watches from the castle.\n\nThe fog closes in.'
    expect(forReading(text, 'Nothing Like This')).toBe(text)
  })

  it('does not lose the body when the heading is all there is', () => {
    expect(forReading('# Vallaki', 'Vallaki')).toBe('')
  })

  it('survives an empty section', () => {
    expect(forReading('', 'Vallaki')).toBe('')
  })
})
