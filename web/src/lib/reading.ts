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
  | { kind: 'illustration'; src: string; alt: string }

/** An image on a line of its own -- the book's own figure placement. */
const FIGURE = /^!\[([^\]]*)\]\(([^)\s]+)\)\s*$/

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

  const flush = () => {
    const prose = run.join('\n').trim()
    if (prose) blocks.push({ kind: 'prose', text: prose })
    run = []
  }

  for (const line of lines) {
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
  return blocks
}
