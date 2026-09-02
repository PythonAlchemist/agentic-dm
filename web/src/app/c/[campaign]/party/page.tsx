'use client'

import Link from 'next/link'
import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'next/navigation'

import { Shell } from '@/components/product/Shell'
import { tableAPI, type Found, type Held, type HeldBefore } from '@/lib/api'
import { CHROME, SOURCE, SOURCE_EDGE, SOURCE_GLYPH } from '@/lib/palette'

/**
 * What the table is carrying, and what it was carrying before.
 *
 * GROUPED BY HOLDER, BECAUSE THAT IS THE QUESTION. "What has Ireena got" comes
 * up at a table roughly a hundred times more often than "where is the
 * Sunsword" -- and the second is one click away on any row, which is the right
 * ratio.
 *
 * HANDING OVER IS ONE ACTION, NOT TWO. The graph closes the old holding and
 * opens the new one in a single transaction; a screen offering "take away"
 * and then "give" would let a DM stop halfway and leave the item nowhere.
 *
 * HISTORY IS NEVER DELETED. Dropping an item closes the holding -- that the
 * party carried the Sunsword for six sessions is true whether or not they
 * still do, and it is the only interesting question about an item.
 */
export default function PartyPage() {
  const params = useParams<{ campaign: string }>()
  const campaign = decodeURIComponent(params.campaign)

  const [held, setHeld] = useState<Held[]>([])
  const [past, setPast] = useState<{ item: string; rows: HeldBefore[] } | null>(null)
  const [giving, setGiving] = useState<Held | null>(null)
  const [adding, setAdding] = useState(false)
  const [failed, setFailed] = useState('')

  const load = useCallback(() => {
    tableAPI
      .inventory(campaign)
      .then((r) => setHeld(r.held))
      .catch((error) => setFailed(String(error)))
  }, [campaign])

  useEffect(load, [load])

  const byHolder = new Map<string, Held[]>()
  for (const one of held) {
    const key = one.holder ?? 'somebody'
    byHolder.set(key, [...(byHolder.get(key) ?? []), one])
  }

  const hand = (item: string, holder: string) => {
    tableAPI
      .give(campaign, item, holder)
      .then(() => {
        setGiving(null)
        setAdding(false)
        load()
      })
      .catch((error) => setFailed(String(error).replace(/^Error:\s*/, '')))
  }

  return (
    <Shell campaign={campaign} section="party">
      <div className="mx-auto max-w-3xl px-6 py-12">
        <div className="flex items-baseline gap-3">
          <h1 className="text-title font-medium text-ink">Carried</h1>
          <button
            onClick={() => setAdding((was) => !was)}
            className="text-label text-ink-dim hover:text-ink"
          >
            {adding ? 'cancel' : 'give the party something'}
          </button>
        </div>

        {adding && (
          <Picker
            campaign={campaign}
            label="which item?"
            kind="ITEM"
            onPick={(item) => hand(item.entity_id, tableAPI.partyId(campaign))}
          />
        )}

        {failed && <p className="mt-3 text-meta text-ink-dim">⚠ {failed}</p>}

        {[...byHolder.entries()].map(([holder, items]) => (
          <section key={holder} className="mt-8">
            <h2 className="label text-ink-faint">
              {holder}
            </h2>
            <ul className="mt-2 flex flex-col">
              {items.map((one) => (
                <li
                  key={one.item_id}
                  className={`flex h-11 items-center gap-3 rounded-md px-2 ${CHROME.row} ${
                    one.plane === 'campaign' ? SOURCE_EDGE.yours : ''
                  }`}
                >
                  <Link
                    href={`/c/${campaign}/e/${encodeURIComponent(one.item_id)}`}
                    className="text-ui text-ink hover:underline"
                  >
                    {one.name}
                  </Link>
                  {one.plane === 'campaign' && (
                    <span className={`shrink-0 text-label ${SOURCE.yours}`}>
                      {SOURCE_GLYPH.yours}
                    </span>
                  )}
                  {one.since_session && (
                    <span className="text-label text-ink-faint">
                      since session {one.since_session}
                    </span>
                  )}
                  <span className="ml-auto flex shrink-0 gap-3">
                    <button
                      onClick={() =>
                        tableAPI
                          .provenance(campaign, one.item_id)
                          .then((r) => setPast({ item: one.name, rows: r.held_by }))
                          .catch(() => undefined)
                      }
                      className="text-label text-ink-faint hover:text-ink-dim"
                    >
                      before this
                    </button>
                    <button
                      onClick={() => setGiving(one)}
                      className="text-label text-ink-dim hover:text-ink"
                    >
                      hand over
                    </button>
                    <button
                      onClick={() =>
                        tableAPI
                          .drop(campaign, one.item_id, one.holder_id ?? '')
                          .then(load)
                          .catch(() => undefined)
                      }
                      className="text-label text-ink-faint hover:text-ink-dim"
                    >
                      drop
                    </button>
                  </span>
                </li>
              ))}
            </ul>
          </section>
        ))}

        {held.length === 0 && (
          <p className="mt-6 text-ui text-ink-faint">Nobody is carrying anything.</p>
        )}

        {giving && (
          <div className="mt-6">
            <p className="text-ui text-ink-dim">
              Hand {giving.name} to&hellip;{' '}
              <button
                onClick={() => setGiving(null)}
                className="text-label text-ink-faint hover:text-ink-dim"
              >
                cancel
              </button>
            </p>
            <Picker
              campaign={campaign}
              label="who takes it?"
              kind=""
              onPick={(who) => hand(giving.item_id, who.entity_id)}
              extra={{
                entity_id: tableAPI.partyId(campaign),
                name: 'The party',
                plane: 'campaign',
                labels: ['FACTION'],
                named_by_book: false,
              }}
            />
          </div>
        )}

        {past && (
          <section className="mt-8 rounded-md border border-line bg-surface/40 p-3">
            <h2 className="label text-ink-faint">
              {past.item} — every hand it passed through
            </h2>
            <ul className="mt-2 flex flex-col gap-1">
              {past.rows.map((row, i) => (
                <li key={i} className="text-ui text-ink-dim">
                  {row.holder}
                  <span className="ml-2 text-label text-ink-faint">
                    {row.until_session === null
                      ? 'has it now'
                      : row.until_session === ''
                        ? 'gave it up — nobody wrote down when'
                        : `until session ${row.until_session}`}
                  </span>
                </li>
              ))}
            </ul>
            <button
              onClick={() => setPast(null)}
              className="mt-2 text-label text-ink-faint hover:text-ink-dim"
            >
              close
            </button>
          </section>
        )}
      </div>
    </Shell>
  )
}

/** Search this table's cast. `extra` prepends a row the graph has no id for
 *  yet -- the party, before anything has been given to it. */
function Picker({
  campaign,
  label,
  kind,
  onPick,
  extra,
}: {
  campaign: string
  label: string
  kind: string
  onPick: (entity: Found) => void
  extra?: Found
}) {
  const [q, setQ] = useState('')
  const [found, setFound] = useState<Found[]>([])

  useEffect(() => {
    if (!q.trim()) return
    let cancelled = false
    tableAPI
      .search(campaign, q, kind)
      .then((r) => !cancelled && setFound(r.found))
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [q, campaign, kind])

  const shown = q.trim() ? found : []
  const rows = extra ? [extra, ...shown] : shown

  return (
    <div className="mt-3 max-w-sm rounded-md border border-line bg-surface/50 p-2">
      <input
        autoFocus
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder={label}
        className={`w-full rounded-md bg-overlay px-2 py-1 text-ui text-ink`}
      />
      <ul className="mt-1 flex max-h-48 flex-col overflow-y-auto">
        {rows.map((entity) => (
          <li key={entity.entity_id}>
            <button
              onClick={() => onPick(entity)}
              className="flex w-full items-baseline gap-2 rounded-md px-1.5 py-1 text-left text-ui hover:bg-overlay"
            >
              <span className="text-ink">{entity.name}</span>
              {entity.plane === 'campaign' && (
                <span className={`text-label ${SOURCE.yours}`}>
                  {SOURCE_GLYPH.yours}
                </span>
              )}
              <span className="ml-auto label text-ink-faint">
                {entity.labels.join(' ').toLowerCase()}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
