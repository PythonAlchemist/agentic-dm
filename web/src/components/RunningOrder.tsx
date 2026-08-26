'use client'

import { useCallback, useEffect, useState } from 'react'
import type { OrderRow } from '@/lib/api'
import { labAPI } from '@/lib/api'
import { Card } from './ui'

/**
 * What this table actually plays, in order: the book with your cuts and
 * insertions in it.
 *
 * SKIPPED SECTIONS ARE SHOWN WHERE THEY WOULD SIT, struck through, rather than
 * removed from the list. A section that vanished entirely would read as one
 * that never existed, and a DM would have no way to put it back.
 *
 * The order is DERIVED from the chain each time it is asked for, never cached
 * here. A running order held in two places is two running orders.
 */
export function RunningOrder({
  campaign,
  refreshKey,
  onRead,
}: {
  campaign: string | null
  refreshKey: number
  onRead: (sectionId: string) => void
}) {
  const [rows, setRows] = useState<OrderRow[]>([])
  const [failed, setFailed] = useState('')
  const [busy, setBusy] = useState('')

  const load = useCallback(async () => {
    if (!campaign) return
    try {
      setRows((await labAPI.runningOrder(campaign)).sections)
      setFailed('')
    } catch (error) {
      setFailed(error instanceof Error ? error.message : String(error))
    }
  }, [campaign])

  useEffect(() => {
    if (!campaign) return
    // Guarded rather than cleared synchronously: a table switch mid-fetch
    // would otherwise paint the previous table's order under the new name.
    let cancelled = false
    labAPI
      .runningOrder(campaign)
      .then((r) => {
        if (!cancelled) setRows(r.sections)
      })
      .catch((error) => {
        if (!cancelled) setFailed(error instanceof Error ? error.message : String(error))
      })
    return () => {
      cancelled = true
    }
  }, [campaign, refreshKey])

  const toggle = async (row: OrderRow) => {
    if (!campaign || busy) return
    setBusy(row.section_id)
    try {
      if (row.skipped) await labAPI.unskip(campaign, row.section_id)
      else await labAPI.skip(campaign, row.section_id)
      await load()
    } catch (error) {
      setFailed(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy('')
    }
  }

  if (!campaign) {
    return (
      <Card title="Running order">
        <p className="p-3 text-xs leading-relaxed text-neutral-500">
          Pick a table to see what it plays. A canon-only session has no running
          order — it is just the book.
        </p>
      </Card>
    )
  }

  const mine = rows.filter((r) => r.origin === 'campaign').length
  const cut = rows.filter((r) => r.skipped).length

  return (
    <Card title="Running order">
      <p className="border-b border-neutral-800 px-3 py-2 text-xs text-neutral-500">
        {rows.length - cut} in play · {mine} yours · {cut} cut
      </p>
      {failed && <p className="px-3 py-2 text-xs text-red-400">{failed}</p>}
      <ol className="max-h-[26rem] overflow-y-auto p-1">
        {rows.map((row) => (
          <li
            key={row.section_id}
            className="group flex items-baseline gap-2 rounded px-2 py-1 hover:bg-neutral-800/40"
          >
            {/* THE HEADING IS THE DOOR. It listed 547 of these and clicking
                one did nothing, so reading your own scene meant asking the
                chat about text sitting one query away. */}
            <button
              onClick={() => onRead(row.section_id)}
              className={`min-w-0 flex-1 truncate text-left text-xs hover:underline ${
                row.skipped
                  ? 'text-neutral-600 line-through'
                  : row.origin === 'campaign'
                    ? 'text-amber-300'
                    : 'text-neutral-300'
              }`}
              title={row.section_id}
            >
              {row.heading}
            </button>
            {row.origin === 'campaign' && (
              <span className="shrink-0 text-[10px] uppercase tracking-wide text-amber-600/80">
                yours
              </span>
            )}
            {row.origin === 'canon' && (
              <button
                onClick={() => toggle(row)}
                disabled={busy === row.section_id}
                className="shrink-0 text-[10px] text-neutral-600 opacity-0 transition-opacity group-hover:opacity-100 hover:text-neutral-300"
              >
                {row.skipped ? 'restore' : 'cut'}
              </button>
            )}
          </li>
        ))}
      </ol>
    </Card>
  )
}
