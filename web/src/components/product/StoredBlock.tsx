import { SOURCE, SOURCE_EDGE, SOURCE_GLYPH, SOURCE_WORD } from '@/lib/palette'

/**
 * What a draft becomes. Rendered in the SLOT THE DRAFT OCCUPIED, so accepting
 * a thing does not move it: the edge goes solid, the glyph changes, and the
 * prose stays where the DM was reading it. The transition is the product's
 * whole point, and it is only visible if nothing jumps.
 */
export function StoredBlock({ title, body }: { title: string; body: string }) {
  return (
    <div className={`my-6 py-2 pl-4 ${SOURCE_EDGE.yours}`}>
      <p className="label">
        <span className={SOURCE.yours}>
          {SOURCE_GLYPH.yours} {SOURCE_WORD.yours}
        </span>{' '}
        <span className="text-ink-faint">written for this campaign</span>
      </p>
      <h2 className="mt-2 text-ui font-medium text-ink">{title}</h2>
      <p className="mt-2 whitespace-pre-wrap text-body text-ink">{body}</p>
    </div>
  )
}
