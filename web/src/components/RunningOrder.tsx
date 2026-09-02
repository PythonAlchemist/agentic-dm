'use client'

import { useCallback, useEffect, useState } from 'react'
import type { OrderRow } from '@/lib/api'
import { labAPI } from '@/lib/api'
import { Card } from './ui'

//: Every campaign's "we are here", in one key.
const PINS = 'agent-lab:playing'

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
  //: WHERE THE TABLE ACTUALLY IS. Everything else in this panel describes the
  //  book; this is the only thing that describes tonight. Kept in the browser
  //  rather than the graph deliberately -- it is a fact about a session in
  //  progress, not about the campaign, and writing it to Neo4j would make
  //  "where are we" something two DMs at one table could disagree about.
  //
  //  ONE LAZY READ of every campaign's pin, rather than an effect that reloads
  //  when `campaign` changes: an effect setting state on mount cascades a
  //  second render on every switch, and reading storage during render breaks
  //  hydration. A map read once and indexed is neither.
  //: What is being dragged, and where it would land. `where` is the two axes
  //  made visible: dropping ON a row puts the dragged thing INSIDE it, dropping
  //  on the line BETWEEN rows puts it AFTER. A tree view has to offer both or
  //  it can only express one of them, which is the whole defect this repairs.
  const [dragging, setDragging] = useState<string | null>(null)
  const [over, setOver] = useState<{ id: string; where: 'inside' | 'after' } | null>(null)

  const drop = async (target: OrderRow, where: 'inside' | 'after') => {
    if (!campaign || !dragging || dragging === target.section_id) return
    setDragging(null)
    setOver(null)
    try {
      if (where === 'inside') await labAPI.nest(campaign, dragging, target.section_id)
      else await labAPI.move(campaign, dragging, target.section_id)
      await load()
    } catch (error) {
      // THE ONTOLOGY'S REFUSAL, SHOWN AS WRITTEN. "an encounter goes inside a
      // scene, not inside an encounter" is the whole explanation and needs no
      // rewording here.
      setFailed(error instanceof Error ? error.message : String(error))
    }
  }

  const [pins, setPins] = useState<Record<string, string>>(() => {
    if (typeof window === 'undefined') return {}
    try {
      return JSON.parse(window.localStorage.getItem(PINS) || '{}')
    } catch {
      return {}
    }
  })
  const playing = campaign ? (pins[campaign] ?? null) : null

  const markPlaying = (sectionId: string) => {
    if (!campaign) return
    const next = { ...pins }
    if (playing === sectionId) delete next[campaign]
    else next[campaign] = sectionId
    window.localStorage.setItem(PINS, JSON.stringify(next))
    setPins(next)
  }
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
        <p className="p-3 text-meta leading-relaxed text-ink-dim">
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
  // HOW DEEP EACH ROW SITS, walked from its parent chain. The book recorded
  // this all along -- `Prisoner 13` holds `Varrin's Proposition` holds `The
  // Breaker's Map` -- and a flat list threw it away, which is why an encounter
  // that happens DURING a scene could only be drawn as its sibling.
  const depthOf = new Map<string, number>()
  const byId = new Map(rows.map((r) => [r.section_id, r]))
  const walk = (row: OrderRow): number => {
    const cached = depthOf.get(row.section_id)
    if (cached !== undefined) return cached
    depthOf.set(row.section_id, 0) // breaks a cycle rather than hanging on one
    const parent = row.parent ? byId.get(row.parent) : undefined
    const deep = parent ? walk(parent) + 1 : 0
    depthOf.set(row.section_id, deep)
    return deep
  }
  rows.forEach(walk)
  // A chapter holding the DM's own material opens by default -- it is the part
  // of the book this table has actually touched, and the one they came for.
  const isOpen = (chapter: string) =>
    openChapters.has(chapter) ||
    (openChapters.size === 0 &&
      groups.find((g) => g.chapter === chapter)?.mine !== 0)

  return (
    <Card title="Running order">
      <div className="flex items-baseline gap-2 border-b border-line px-3 py-2">
        <input
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          placeholder="find a scene…"
          className="min-w-0 flex-1 rounded-md border border-line bg-surface/60 px-2 py-1 text-meta focus:border-line"
        />
        <span className="shrink-0 text-meta tabular-nums text-ink-faint">
          {shown.length === rows.length
            ? `${rows.length - cut} · ${mine} yours`
            : `${shown.length} found`}
        </span>
      </div>
      {failed && <p className="px-3 py-2 text-meta text-ink-dim">{failed}</p>}
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
                className="flex w-full items-baseline gap-1 rounded-md px-2 py-1 text-left label text-ink-dim hover:bg-overlay/40"
              >
                <span className="text-ink-faint">
                  {isOpen(group.chapter) ? '▾' : '▸'}
                </span>
                <span className="min-w-0 flex-1 truncate">
                  {prettyChapter(group.chapter)}
                </span>
                <span className="tabular-nums text-ink-faint">
                  {group.rows.length}
                  {group.mine > 0 && (
                    <span className="text-yours/70"> ·{group.mine}</span>
                  )}
                </span>
              </button>
            )}
            {(filter !== '' || isOpen(group.chapter)) && (
              <ol>
                {group.rows.map((row) => (
                  <li
                    key={row.section_id}
                    // ONLY YOUR OWN MOVES. The book's sections stay where the
                    // book put them, so they are drop targets but never
                    // draggable.
                    draggable={row.origin === 'campaign'}
                    onDragStart={() => setDragging(row.section_id)}
                    onDragEnd={() => { setDragging(null); setOver(null) }}
                    onDragOver={(event) => {
                      if (!dragging || dragging === row.section_id) return
                      event.preventDefault()
                      const box = event.currentTarget.getBoundingClientRect()
                      // The lower quarter is the seam BETWEEN rows; anywhere
                      // else means into the row itself.
                      const where =
                        event.clientY > box.bottom - box.height / 4 ? 'after' : 'inside'
                      setOver({ id: row.section_id, where })
                    }}
                    onDragLeave={() => setOver((o) => (o?.id === row.section_id ? null : o))}
                    onDrop={(event) => {
                      event.preventDefault()
                      drop(row, over?.where ?? 'inside')
                    }}
                    className={`group flex items-baseline gap-2 rounded-md px-2 py-1 hover:bg-overlay/40 ${
                      row.section_id === playing ? 'bg-overlay' : ''
                    } ${dragging === row.section_id ? 'opacity-40' : ''} ${
                      over?.id === row.section_id && over.where === 'inside'
                        ? 'bg-overlay/60'
                        : ''
                    } ${
                      over?.id === row.section_id && over.where === 'after'
                        ? 'border-b border-ink-dim'
                        : ''
                    }`}
                  >
                    <button
                      onClick={() => markPlaying(row.section_id)}
                      title={row.section_id === playing ? 'not here any more' : 'we are here'}
                      className={`w-2 shrink-0 text-label ${
                        row.section_id === playing
                          ? 'text-ink'
                          : 'text-transparent group-hover:text-ink-faint'
                      }`}
                    >
                      ▶
                    </button>
            {/* THE HEADING IS THE DOOR. It listed 547 of these and clicking
                one did nothing, so reading your own scene meant asking the
                chat about text sitting one query away. */}
            <button
              onClick={() => onRead(row.section_id)}
              style={{ paddingLeft: `${(depthOf.get(row.section_id) ?? 1) - 1}rem` }}
              className={`min-w-0 flex-1 truncate text-left text-meta hover:underline ${
                row.skipped
                  ? 'text-ink-faint line-through'
                  : row.origin === 'campaign'
                    ? 'text-yours'
                    : 'text-ink-dim'
              }`}
              title={row.section_id}
            >
              {row.heading}
            </button>
            {row.origin === 'campaign' && (
              <span className="shrink-0 label text-yours/80">
                yours
              </span>
            )}
            {row.origin === 'canon' && (
              <button
                onClick={() => toggle(row)}
                disabled={busy === row.section_id}
                className="shrink-0 text-label text-ink-faint opacity-0 transition-opacity group-hover:opacity-100 hover:text-ink-dim"
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
