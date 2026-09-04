import type { GeneratedReply } from '@/lib/api'
import type { Source } from '@/lib/palette'

export interface SourceClaim {
  claim: string
  cite: string
}

export interface SourceGroup {
  source: Source
  claims: SourceClaim[]
}

/**
 * THE ONE PLACE THE API'S NAMES MEET THE PALETTE'S.
 *
 * The API says `from_canon` and `from_context`; the design system says BOOK and
 * TABLE. Translating in a second place is how `from_context` ends up labelled
 * "context" on one screen and "table" on another, which is the drift
 * `palette.ts` exists to stop. Every consumer reads the split from here.
 *
 * ORDER IS THE PALETTE'S ORDER, not the interface's: book, yours, table,
 * invented. A reader learns one sequence and meets it everywhere.
 *
 * AN EMPTY SOURCE IS OMITTED, not rendered blank. "Nothing came from the book"
 * is a claim worth making by absence; a headed empty list makes it look like
 * something failed to load.
 */
export function splitOf(reply: GeneratedReply): SourceGroup[] {
  const bare = (claims: string[] | undefined): SourceClaim[] =>
    (claims ?? []).map((claim) => ({ claim, cite: '' }))

  const groups: SourceGroup[] = [
    { source: 'book', claims: reply.from_canon ?? [] },
    { source: 'yours', claims: reply.from_yours ?? [] },
    { source: 'table', claims: bare(reply.from_context) },
    { source: 'invented', claims: bare(reply.invented) },
  ]
  return groups.filter((g) => g.claims.length > 0)
}
