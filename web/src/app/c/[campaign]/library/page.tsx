'use client'

import Link from 'next/link'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams } from 'next/navigation'

import { Shell } from '@/components/product/Shell'
import {
  labAPI,
  tableAPI,
  type Found,
  type MapRow,
  type OrderRow,
} from '@/lib/api'
import { CHROME, SOURCE, SOURCE_EDGE, SOURCE_GLYPH, SOURCE_WORD } from '@/lib/palette'

/**
 * Everything this table has: the book's running order, and its maps.
 *
 * A MAP IS A PROPERTY OF A PLACE, so making one is picking a place and giving
 * it a picture. There is no map library to file things into, no folders, no
 * names to keep in sync -- the graph is the index, and Castle Ravenloft's map
 * is reachable from Castle Ravenloft because that is where it belongs.
 *
 * THE PLACE PICKER IS NARROWED TO LOCATIONS, matching the range `MAP_OF` keeps
 * in the graph. Offering an NPC and then refusing the write would be a rule
 * enforced twice and explained nowhere.
 *
 * 547 HAIRLINES IS GREY FOG. Every row carried a bottom border, which at this
 * length stops separating anything and just lowers the contrast of the whole
 * screen. Rows are separated by rhythm -- fixed height and whitespace -- and a
 * rule is spent only where the book itself changes chapter.
 *
 * THE CHAPTER STAYS A COLUMN, and that is a finding rather than a preference.
 * Sticky chapter headings were the plan until the data said otherwise: this
 * table's running order ALTERNATES between the introduction and the first
 * adventure row by row, so grouping by chapter produced a heading above every
 * single row -- louder than the repetition it replaced. The order is what the
 * table plays and must not be re-sorted to suit a layout, so the chapter goes
 * back to a quiet right-hand label and the rhythm does the separating.
 */
export default function LibraryPage() {
  const params = useParams<{ campaign: string }>()
  const campaign = decodeURIComponent(params.campaign)

  const [order, setOrder] = useState<OrderRow[]>([])
  const [maps, setMaps] = useState<MapRow[]>([])
  const [making, setMaking] = useState(false)

  const loadMaps = useCallback(() => {
    tableAPI.maps(campaign).then((r) => setMaps(r.maps)).catch(() => undefined)
  }, [campaign])

  useEffect(loadMaps, [loadMaps])

  useEffect(() => {
    labAPI.runningOrder(campaign).then((r) => setOrder(r.sections)).catch(() => undefined)
  }, [campaign])

  return (
    <Shell campaign={campaign} section="library">
      <div className="mx-auto max-w-3xl px-6 py-12">
        <div>
          <h1 className="text-title font-medium text-ink">The whole book</h1>
          <p className="mt-1 text-ui text-ink-dim">
            In the order it runs, with your scenes where you put them.
          </p>

          <ol className="mt-6 flex flex-col">
            {order.map((row, i) => (
              <li key={row.section_id}>
                <Link
                  href={`/c/${campaign}/s/${encodeURIComponent(row.section_id)}`}
                  className={`flex h-8 items-center gap-3 rounded-md px-2 ${CHROME.row} ${
                    row.skipped ? 'opacity-40' : ''
                  } ${row.origin === 'campaign' ? SOURCE_EDGE.yours : ''}`}
                >
                  {/* ROW TEXT STAYS INK. The edge carries the hue and the
                      label carries the glyph; tinting the sentence as well is
                      the same claim a third time. */}
                  <span className="truncate text-ui text-ink">{row.heading}</span>
                  {row.origin === 'campaign' && (
                    <span className={`shrink-0 text-label ${SOURCE.yours}`}>
                      {SOURCE_GLYPH.yours} {SOURCE_WORD.yours}
                    </span>
                  )}
                  {/* SAID ONCE PER RUN. Where the order stays in one chapter
                      the label appears on the first row and then stops, so a
                      long chapter reads as a block rather than as 40 copies of
                      its own name. */}
                  <span className="ml-auto shrink-0 text-meta text-ink-faint">
                    {row.skipped
                      ? 'skipped'
                      : row.chapter && row.chapter !== order[i - 1]?.chapter
                        ? row.chapter
                        : ''}
                  </span>
                </Link>
              </li>
            ))}
            {order.length === 0 && (
              <li className="py-2 text-ui text-ink-faint">Nothing here yet.</li>
            )}
          </ol>
        </div>

        <section className="mt-12 border-t border-line pt-6">
          <div className="flex items-baseline justify-between">
            <h2 className="label text-ink-faint">
              Maps
            </h2>
            <button
              onClick={() => setMaking((was) => !was)}
              className="text-label text-ink-dim hover:text-ink"
            >
              {making ? 'cancel' : 'add one'}
            </button>
          </div>

          {making && (
            <NewMap
              campaign={campaign}
              onMade={() => {
                setMaking(false)
                loadMaps()
              }}
            />
          )}

          <ul className="mt-3 flex flex-col gap-1">
            {maps.map((m) => (
              <li key={m.id}>
                <Link
                  href={`/c/${campaign}/m/${encodeURIComponent(m.id)}`}
                  className="text-ui text-ink-dim hover:underline"
                >
                  {m.name}
                </Link>
                <span className="ml-2 text-label text-ink-faint">{m.place}</span>
              </li>
            ))}
            {maps.length === 0 && !making && (
              <li className="text-ui text-ink-faint">No maps yet.</li>
            )}
          </ul>
        </section>
      </div>
    </Shell>
  )
}

/** Pick a place, give it a picture. That is the whole of making a map. */
function NewMap({
  campaign,
  onMade,
}: {
  campaign: string
  onMade: () => void
}) {
  const [q, setQ] = useState('')
  const [found, setFound] = useState<Found[]>([])
  const [place, setPlace] = useState<Found | null>(null)
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState('')
  const file = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!q.trim() || place) return
    let cancelled = false
    tableAPI
      .search(campaign, q, 'LOCATION')
      .then((r) => !cancelled && setFound(r.found))
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [q, campaign, place])

  const shown = q.trim() && !place ? found : []

  const onPick = (chosen: File | undefined) => {
    if (!chosen || !place) return
    setBusy(true)
    setFailed('')
    tableAPI
      .upload(campaign, chosen)
      .then((asset) =>
        tableAPI.createMap(campaign, place.name, place.entity_id, asset.id))
      .then(() => {
        setBusy(false)
        onMade()
      })
      .catch((error) => {
        setBusy(false)
        setFailed(String(error).replace(/^Error:\s*/, ''))
      })
  }

  return (
    <div className="mt-3 rounded-md border border-line bg-surface/50 p-2">
      {place ? (
        <p className="text-ui text-ink-dim">
          {place.name}{' '}
          <button
            onClick={() => setPlace(null)}
            className="ml-1 text-label text-ink-dim hover:text-ink"
          >
            change
          </button>
        </p>
      ) : (
        <input
          autoFocus
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="which place?"
          className={`w-full rounded-md bg-overlay px-2 py-1 text-ui text-ink`}
        />
      )}

      <ul className="mt-1 flex max-h-40 flex-col overflow-y-auto">
        {shown.map((entity) => (
          <li key={entity.entity_id}>
            <button
              onClick={() => setPlace(entity)}
              className="w-full rounded-md px-1.5 py-1 text-left text-ui text-ink-dim hover:bg-overlay"
            >
              {entity.name}
            </button>
          </li>
        ))}
      </ul>

      {place && (
        <>
          <input
            ref={file}
            type="file"
            accept="image/png,image/jpeg,image/webp"
            className="hidden"
            onChange={(event) => onPick(event.target.files?.[0])}
          />
          <button
            onClick={() => file.current?.click()}
            disabled={busy}
            className={`mt-2 w-full rounded-md px-3 py-1 text-ui ${CHROME.primary}`}
          >
            {busy ? 'storing…' : 'choose the image'}
          </button>
        </>
      )}

      {failed && <p className="mt-2 text-label text-ink-dim">⚠ {failed}</p>}
    </div>
  )
}
