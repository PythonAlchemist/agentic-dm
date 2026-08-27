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
  //: FINDING TONIGHT'S SCENE WAS FREEHAND SCROLLING through 547 rows. A DM
  //  mid-session knows the name of what they want, so a filter beats any
  //  amount of grouping -- and grouping is offered too, because between
  //  sessions they are browsing rather than searching.
  const [filter, setFilter] = useState('')
  const [openChapters, setOpenChapters] = useState<Set<string>>(new Set())
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
  const needle = filter.trim().toLowerCase()
  const shown = needle
    ? rows.filter((r) => r.heading.toLowerCase().includes(needle))
    : rows
  const groups = byChapter(shown)
  // A chapter holding the DM's own material opens by default -- it is the part
  // of the book this table has actually touched, and the one they came for.
  const isOpen = (chapter: string) =>
    openChapters.has(chapter) ||
    (openChapters.size === 0 &&
      groups.find((g) => g.chapter === chapter)?.mine !== 0)

  return (
    <Card title="Running order">
      <div className="flex items-baseline gap-2 border-b border-neutral-800 px-3 py-2">
        <input
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          placeholder="find a scene…"
          className="min-w-0 flex-1 rounded border border-neutral-800 bg-neutral-900/60 px-2 py-1 text-xs outline-none focus:border-neutral-500"
        />
        <span className="shrink-0 text-xs tabular-nums text-neutral-600">
          {shown.length === rows.length
            ? `${rows.length - cut} · ${mine} yours`
            : `${shown.length} found`}
        </span>
      </div>
      {failed && <p className="px-3 py-2 text-xs text-red-400">{failed}</p>}
      <ol className="max-h-[26rem] overflow-y-auto p-1">
        {groups.map((group) => (
          <li key={group.chapter}>
            {/* CHAPTERS COLLAPSE, and while filtering they do not: a search
                result hidden inside a folded chapter is a search that failed.
                The DM's own scenes keep their chapter open by default, since
                that is the part of the book this table has actually touched. */}
            {!filter && (
              <button
                onClick={() =>
                  setOpenChapters((prior) => {
                    const next = new Set(prior)
                    if (next.has(group.chapter)) next.delete(group.chapter)
                    else next.add(group.chapter)
                    return next
                  })
                }
                className="flex w-full items-baseline gap-1 rounded px-2 py-1 text-left text-[11px] uppercase tracking-wide text-neutral-500 hover:bg-neutral-800/40"
              >
                <span className="text-neutral-700">
                  {isOpen(group.chapter) ? '▾' : '▸'}
                </span>
                <span className="min-w-0 flex-1 truncate">
                  {prettyChapter(group.chapter)}
                </span>
                <span className="tabular-nums text-neutral-700">
                  {group.rows.length}
                  {group.mine > 0 && (
                    <span className="text-amber-500/70"> ·{group.mine}</span>
                  )}
                </span>
              </button>
            )}
            {(filter !== '' || isOpen(group.chapter)) && (
              <ol>
                {group.rows.map((row) => (
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
            )}
          </li>
        ))}
      </ol>
    </Card>
  )
}

/** `prisoner-13` reads as `Prisoner 13` to somebody scanning for a scene. */
function prettyChapter(slug: string) {
  return slug
    .split('-')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
}

/**
 * The order as chapters, in the order the chain visits them.
 *
 * NOT SORTED, and that is the point: a running order is a sequence a DM
 * arranged, so the chapters come out in the order they are played rather than
 * alphabetically or by the book's own numbering.
 */
function byChapter(rows: OrderRow[]) {
  const groups: { chapter: string; rows: OrderRow[]; mine: number }[] = []
  const index = new Map<string, number>()
  // A CAMPAIGN ROW INHERITS THE CHAPTER IT WAS INSERTED INTO. It carries none
  // of its own -- it hangs off a `:Campaign`, not a `:Chapter` -- and bucketing
  // those into a "Yours" group at the end destroys the single thing this panel
  // exists to show: a scene sitting WHERE THE DM PUT IT, between the book's
  // sections. Same reasoning as showing a cut section struck through in place
  // rather than removing it.
  let carried = 'elsewhere'
  for (const row of rows) {
    const chapter = row.chapter || carried
    carried = chapter
    if (!index.has(chapter)) {
      index.set(chapter, groups.length)
      groups.push({ chapter, rows: [], mine: 0 })
    }
    const group = groups[index.get(chapter)!]
    group.rows.push(row)
    if (row.origin === 'campaign') group.mine += 1
  }
  return groups
}
