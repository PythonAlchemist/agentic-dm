import type { GeneratedReply } from '@/lib/api'
import { labAPI } from '@/lib/api'
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

export type StoreBody = Parameters<typeof labAPI.store>[0]

/**
 * A SCENE A PERSON TYPED. Every source list is empty and that is the true
 * answer, not a degenerate one: nothing was drawn from anywhere, because
 * somebody wrote it. `generated_body: ''` is how a later reader tells this
 * apart from a draft that was accepted unchanged.
 */
export function handWrittenStore(a: {
  campaign: string
  title: string
  body: string
  anchor: string
}): StoreBody {
  return {
    campaign: a.campaign,
    kind: 'scene',
    title: a.title,
    body: a.body,
    generated_body: '',
    from_canon: [],
    from_yours: [],
    invented: [],
    from_context: [],
    sources: [],
    anchor: a.anchor,
    model: '',
  }
}

/**
 * A DRAFT THE DM KEPT. `body` carries their edits; `generated_body` keeps what
 * the model produced. The pair is the whole record of how much of this is
 * theirs, and it is why editing by hand does not erase the split.
 */
export function draftedStore(a: {
  campaign: string
  reply: GeneratedReply
  body: string
  anchor: string
}): StoreBody {
  return {
    campaign: a.campaign,
    kind: a.reply.kind,
    title: a.reply.title,
    body: a.body,
    generated_body: a.reply.body,
    from_canon: a.reply.from_canon ?? [],
    from_yours: a.reply.from_yours ?? [],
    invented: a.reply.invented ?? [],
    from_context: a.reply.from_context ?? [],
    sources: a.reply.sources ?? [],
    anchor: a.anchor,
    model: a.reply.model,
  }
}
