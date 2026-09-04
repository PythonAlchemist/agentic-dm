import { SOURCE, SOURCE_EDGE, SOURCE_GLYPH, SOURCE_WORD } from '@/lib/palette'

/**
 * What the DM's material becomes once it is in the graph. Rendered in the SLOT
 * THE BLOCK BEFORE IT OCCUPIED, so accepting a thing does not move it: the
 * prose stays exactly where the DM was reading it.
 *
 * THE RE-MARKING IS THE DRAFT PATH'S. Coming from `DraftCard` the dashed rose
 * edge goes solid amber and ◇ becomes ✎ -- provenance changing in place, which
 * §8.4 calls the product's whole point made visible, and which is only visible
 * if nothing jumps. Coming from `WriteBlock` there is nothing to re-mark: it
 * already wore the solid `yours` edge and this same glyph, because a scene a
 * person typed was never invented. What changes on that path is the line
 * beneath the badge -- "not stored yet" becomes the citation.
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
