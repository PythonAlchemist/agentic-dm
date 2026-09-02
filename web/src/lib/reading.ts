/**
 * A section's body, split into what a reader actually sees.
 *
 * THE BOOK'S ART WAS ALREADY THERE AND WAS BEING THROWN AWAY. 286 image URLs
 * across 229 canon sections came in with the harvest, and `forReading` replaces
 * every one of them with the literal string "[illustration]" before a DM sees
 * it. So the first half of "images for entities" is not a pipeline to build --
 * it is a discard to stop. The book placed these illustrations itself, on the
 * page they belong to, and that placement is as much the book's as its
 * sentences are.
 *
 * ALONGSIDE `forReading`, NOT INSTEAD OF IT. The lab keeps its plain-text
 * reader; this is the product's, and the two can differ because they serve
 * different people.
 */

export type ReadingBlock =
  | { kind: 'prose'; text: string }
  | { kind: 'aloud'; text: string }
  | { kind: 'illustration'; src: string; alt: string }

/**
 * The book's emphasis, which was reaching the reader as punctuation.
 *
 * `_An Adventure for 1st-Level Characters_` rendered with its underscores
 * showing. The transcription preserves the book's italics as Markdown -- it
 * was told to -- and nothing downstream turned them back into italics, so
 * every emphasised line in 1,378 sections carried two stray characters.
 *
 * ONLY EMPHASIS, and only where it wraps whole words. This is not a Markdown
 * renderer and must not become one: the prose is the book's and the fewer
 * transformations between the page and the reader, the better. Headings,
 * links and lists are left exactly as the book set them.
 */
const EMPHASIS = /(^|[\s(\["'])_([^_\n]+)_(?=[\s).,;:!?\]"']|$)/g

export function withEmphasis(text: string): string {
  return text.replace(EMPHASIS, (_all, before, inner) => `${before}\u2063${inner}\u2063`)
}

/** The marker `withEmphasis` leaves around an emphasised run. An invisible
 *  separator, so it cannot collide with anything the book actually prints. */
export const EMPHASIS_MARK = '\u2063' 

/** An image on a line of its own -- the book's own figure placement. */
const FIGURE = /^!\[([^\]]*)\]\(([^)\s]+)\)\s*$/

/**
 * READ-ALOUD TEXT, which was reaching the table as punctuation.
 *
 * The transcription preserves the book's boxed read-aloud passages as Markdown
 * blockquotes -- it was told to -- and nothing downstream turned them back, so
 * 825 canon sections rendered a literal `>` at the head of every line of the
 * one thing a DM reads out word for word.
 *
 * IT IS ALSO THE MISSING TYPE STEP. `text-aloud` exists in the token layer for
 * exactly this and had no way to be reached, because nothing produced a block
 * that deserved it.
 */
const QUOTED = /^>\s?/

export function readingBlocks(text: string, heading: string): ReadingBlock[] {
  const lines = text.split('\n')

  // The drawer already shows the heading; a first heading that repeats it is
  // the same words twice. A LATER heading is structure the reader wants.
  const first = lines.findIndex((line) => line.trim() !== '')
  if (first >= 0 && lines[first].replace(/^#+\s*/, '').trim() === heading.trim()) {
    lines.splice(0, first + 1)
  }

  const blocks: ReadingBlock[] = []
  let run: string[] = []
  let aloud: string[] = []

  const flush = () => {
    const prose = run.join('\n').trim()
    if (prose) blocks.push({ kind: 'prose', text: prose })
    run = []
  }

  // A RUN OF QUOTED LINES IS ONE PASSAGE. The book boxes them together and a
  // DM reads them as one, so splitting per line would break a sentence across
  // blocks.
  const flushAloud = () => {
    const said = aloud.join('\n').trim()
    if (said) blocks.push({ kind: 'aloud', text: said })
    aloud = []
  }

  for (const line of lines) {
    if (QUOTED.test(line)) {
      flush()
      aloud.push(line.replace(QUOTED, ''))
      continue
    }
    // A BLANK LINE INSIDE A QUOTE keeps the passage open; anything else ends it.
    if (aloud.length && line.trim() === '') {
      aloud.push('')
      continue
    }
    flushAloud()

    const figure = FIGURE.exec(line)
    if (figure) {
      flush()
      blocks.push({
        kind: 'illustration',
        src: figure[2],
        // The harvester's alt text is the literal word "image", which is worth
        // nothing to a screen reader. The book's caption is the next line of
        // prose, so the honest alt is what the figure IS, not what it says.
        alt: figure[1] && figure[1].toLowerCase() !== 'image' ? figure[1] : '',
      })
      continue
    }
    run.push(line)
  }
  flush()
  flushAloud()
  return blocks
}
