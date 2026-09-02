'use client'

import Link from 'next/link'
import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'next/navigation'

import { Shell } from '@/components/product/Shell'
import { tableAPI, type Found, type Held, type HeldBefore } from '@/lib/api'
import { CHROME, SOURCE } from '@/lib/palette'

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
      <div className="mx-auto max-w-3xl px-6 py-10">
        <div className="flex items-baseline gap-3">
          <h1 className="text-xl font-medium text-neutral-100">Carried</h1>
          <button
            onClick={() => setAdding((was) => !was)}
            className="text-[11px] text-neutral-500 hover:text-neutral-300"
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

        {failed && <p className="mt-3 text-xs text-neutral-400">⚠ {failed}</p>}

        {[...byHolder.entries()].map(([holder, items]) => (
          <section key={holder} className="mt-7">
            <h2 className="text-[11px] uppercase tracking-widest text-neutral-600">
              {holder}
            </h2>
            <ul className="mt-2 flex flex-col">
              {items.map((one) => (
                <li
                  key={one.item_id}
                  className="flex items-baseline gap-3 border-b border-neutral-900 py-2"
                >
                  <Link
                    href={`/c/${campaign}/e/${encodeURIComponent(one.item_id)}`}
                    className={`text-sm hover:underline ${
                      one.plane === 'campaign' ? SOURCE.yours : 'text-neutral-200'
                    }`}
                  >
                    {one.name}
                  </Link>
                  {one.since_session && (
                    <span className="text-[11px] text-neutral-600">
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
                      className="text-[11px] text-neutral-600 hover:text-neutral-400"
                    >
                      before this
                    </button>
                    <button
                      onClick={() => setGiving(one)}
                      className="text-[11px] text-neutral-500 hover:text-neutral-300"
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
                      className="text-[11px] text-neutral-600 hover:text-neutral-400"
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
          <p className="mt-6 text-sm text-neutral-600">Nobody is carrying anything.</p>
        )}

        {giving && (
          <div className="mt-6">
            <p className="text-sm text-neutral-400">
              Hand {giving.name} to&hellip;{' '}
              <button
                onClick={() => setGiving(null)}
                className="text-[11px] text-neutral-600 hover:text-neutral-400"
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
          <section className="mt-8 rounded border border-neutral-800 bg-neutral-900/40 p-3">
            <h2 className="text-[11px] uppercase tracking-widest text-neutral-600">
              {past.item} — every hand it passed through
            </h2>
            <ul className="mt-2 flex flex-col gap-1">
              {past.rows.map((row, i) => (
                <li key={i} className="text-sm text-neutral-400">
                  {row.holder}
                  <span className="ml-2 text-[11px] text-neutral-600">
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
              className="mt-2 text-[11px] text-neutral-600 hover:text-neutral-400"
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
    <div className="mt-3 max-w-sm rounded border border-neutral-800 bg-neutral-900/50 p-2">
      <input
        autoFocus
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder={label}
        className={`w-full rounded border border-neutral-800 bg-neutral-950 px-2 py-1 text-sm text-neutral-200 outline-none ${CHROME.focus}`}
      />
      <ul className="mt-1 flex max-h-48 flex-col overflow-y-auto">
        {rows.map((entity) => (
          <li key={entity.entity_id}>
            <button
              onClick={() => onPick(entity)}
              className="flex w-full items-baseline gap-2 rounded px-1.5 py-1 text-left text-sm hover:bg-neutral-800"
            >
              <span
                className={
                  entity.plane === 'campaign' ? SOURCE.yours : 'text-neutral-200'
                }
              >
                {entity.name}
              </span>
              <span className="ml-auto text-[10px] uppercase tracking-wide text-neutral-600">
                {entity.labels.join(' ').toLowerCase()}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
