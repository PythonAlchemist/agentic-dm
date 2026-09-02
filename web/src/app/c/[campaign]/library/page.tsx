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
import { CHROME, SOURCE } from '@/lib/palette'

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
      <div className="mx-auto grid max-w-5xl gap-10 px-6 py-10 md:grid-cols-[1fr_18rem]">
        <div>
          <h1 className="text-xl font-medium text-neutral-100">The whole book</h1>
          <p className="mt-1 text-sm text-neutral-500">
            In the order it runs, with your scenes where you put them.
          </p>

          <ol className="mt-5 flex flex-col">
            {order.map((row) => (
              <li key={row.section_id}>
                <Link
                  href={`/c/${campaign}/s/${encodeURIComponent(row.section_id)}`}
                  className={`flex items-baseline gap-3 border-b border-neutral-900 py-2 hover:bg-neutral-900/40 ${
                    row.skipped ? 'opacity-40' : ''
                  }`}
                >
                  <span
                    className={`truncate text-sm ${
                      row.origin === 'campaign' ? SOURCE.yours : 'text-neutral-200'
                    }`}
                  >
                    {row.heading}
                  </span>
                  <span className="ml-auto shrink-0 text-[11px] text-neutral-600">
                    {row.skipped ? 'skipped' : row.chapter}
                  </span>
                </Link>
              </li>
            ))}
            {order.length === 0 && (
              <li className="py-2 text-sm text-neutral-600">Nothing here yet.</li>
            )}
          </ol>
        </div>

        <aside>
          <div className="flex items-baseline justify-between">
            <h2 className="text-[11px] uppercase tracking-widest text-neutral-600">
              Maps
            </h2>
            <button
              onClick={() => setMaking((was) => !was)}
              className="text-[11px] text-neutral-500 hover:text-neutral-300"
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
                  className="text-sm text-neutral-300 hover:underline"
                >
                  {m.name}
                </Link>
                <span className="ml-2 text-[11px] text-neutral-600">{m.place}</span>
              </li>
            ))}
            {maps.length === 0 && !making && (
              <li className="text-sm text-neutral-600">No maps yet.</li>
            )}
          </ul>
        </aside>
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
    <div className="mt-3 rounded border border-neutral-800 bg-neutral-900/50 p-2">
      {place ? (
        <p className="text-sm text-neutral-300">
          {place.name}{' '}
          <button
            onClick={() => setPlace(null)}
            className="ml-1 text-[11px] text-neutral-500 hover:text-neutral-300"
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
          className={`w-full rounded border border-neutral-800 bg-neutral-950 px-2 py-1 text-sm text-neutral-200 outline-none ${CHROME.focus}`}
        />
      )}

      <ul className="mt-1 flex max-h-40 flex-col overflow-y-auto">
        {shown.map((entity) => (
          <li key={entity.entity_id}>
            <button
              onClick={() => setPlace(entity)}
              className="w-full rounded px-1.5 py-1 text-left text-sm text-neutral-300 hover:bg-neutral-800"
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
            className={`mt-2 w-full rounded px-2 py-1 text-[11px] ${CHROME.primary}`}
          >
            {busy ? 'storing…' : 'choose the image'}
          </button>
        </>
      )}

      {failed && <p className="mt-2 text-[11px] text-neutral-400">⚠ {failed}</p>}
    </div>
  )
}
