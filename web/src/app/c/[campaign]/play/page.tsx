'use client'

import Link from 'next/link'
import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'next/navigation'

import { Shell } from '@/components/product/Shell'
import {
  labAPI,
  tableAPI,
  type OrderRow,
  type SessionDiff,
  type SessionRow,
} from '@/lib/api'
import { CHROME, SOURCE } from '@/lib/palette'

/**
 * A night of play: what you meant to run, and what you actually reached.
 *
 * TWO LISTS, NOT A STATUS. `sessions.py` keeps `PLANNED` and `COVERED` as
 * separate edges precisely so this screen can exist -- a single status per
 * scene would let one of the two claims overwrite the other, and the overwrite
 * would destroy the only interesting thing here.
 *
 * THE INTERESTING COLUMN IS "UNPLANNED". Every prep tool shows what you did
 * not get to. What a table did that nobody planned is where a campaign
 * actually leaves the book, and it is the raw material for the transcript
 * work: it is what a session was really about.
 *
 * COVERING IS ONE CLICK, MID-SESSION. A DM has five people waiting. Marking a
 * scene played may not be a form.
 */
export default function PlayPage() {
  const params = useParams<{ campaign: string }>()
  const campaign = decodeURIComponent(params.campaign)

  const [sessions, setSessions] = useState<SessionRow[]>([])
  const [open, setOpen] = useState<string>('')
  const [diff, setDiff] = useState<SessionDiff | null>(null)
  const [order, setOrder] = useState<OrderRow[]>([])
  const [failed, setFailed] = useState('')

  const loadSessions = useCallback(() => {
    tableAPI
      .sessions(campaign)
      .then((r) => {
        setSessions(r.sessions)
        // THE NEWEST IS THE ONE YOU ARE IN. `sessions` comes back newest
        // first, and a DM opening this screen mid-game wants tonight.
        setOpen((was) => was || r.sessions[0]?.id || '')
      })
      .catch((error) => setFailed(String(error)))
  }, [campaign])

  useEffect(loadSessions, [loadSessions])

  useEffect(() => {
    labAPI.runningOrder(campaign).then((r) => setOrder(r.sections)).catch(() => undefined)
  }, [campaign])

  const loadDiff = useCallback(() => {
    // NO SYNCHRONOUS CLEAR. Setting state in an effect body cascades a render;
    // the screen already gates every use of `diff` on `open`, so a stale diff
    // with no session selected is not reachable.
    if (!open) return
    tableAPI.diff(campaign, open).then(setDiff).catch(() => undefined)
  }, [campaign, open])

  useEffect(loadDiff, [loadDiff])

  const start = () => {
    tableAPI
      .openSession(campaign)
      .then((made) => {
        setOpen(made.id)
        loadSessions()
      })
      .catch((error) => setFailed(String(error)))
  }

  const planned = new Set((diff?.planned ?? []).map((s) => s.id))
  const covered = new Set((diff?.covered ?? []).map((s) => s.id))

  const mark = (sectionId: string, as: 'planned' | 'covered') => {
    const call =
      as === 'planned'
        ? tableAPI.plan(campaign, open, sectionId)
        : tableAPI.cover(campaign, open, sectionId)
    call.then(loadDiff).then(loadSessions).catch((error) => setFailed(String(error)))
  }

  return (
    <Shell campaign={campaign} section="play">
      <div className="mx-auto grid max-w-5xl gap-10 px-6 py-10 md:grid-cols-[16rem_1fr]">
        <aside>
          <div className="flex items-baseline justify-between">
            <h2 className="text-[11px] uppercase tracking-widest text-neutral-600">
              Sessions
            </h2>
            <button onClick={start} className={`rounded px-2 py-0.5 text-[11px] ${CHROME.primary}`}>
              start one
            </button>
          </div>

          <ul className="mt-3 flex flex-col">
            {sessions.map((s) => (
              <li key={s.id}>
                <button
                  onClick={() => setOpen(s.id)}
                  className={`flex w-full items-baseline gap-2 rounded px-2 py-1.5 text-left text-sm ${
                    s.id === open ? CHROME.selected : 'text-neutral-400 hover:text-neutral-200'
                  }`}
                >
                  <span className="tabular-nums">#{s.number}</span>
                  <span className="truncate">{s.title || 'untitled'}</span>
                  <span className="ml-auto shrink-0 text-[11px] tabular-nums text-neutral-600">
                    {s.covered}/{s.planned}
                  </span>
                </button>
              </li>
            ))}
            {sessions.length === 0 && (
              <li className="px-2 py-1 text-sm text-neutral-600">
                No sessions yet.
              </li>
            )}
          </ul>

          {failed && (
            <p className="mt-4 text-[11px] leading-relaxed text-neutral-400">⚠ {failed}</p>
          )}
        </aside>

        <div>
          <h1 className="text-xl font-medium text-neutral-100">Tonight</h1>
          <p className="mt-1 text-sm text-neutral-500">
            Plan a scene before you run it; mark it played when you have.
          </p>

          {!open && (
            <p className="mt-6 text-sm text-neutral-600">
              Start a session to plan against it.
            </p>
          )}

          {open && (
            <>
              <ol className="mt-6 flex flex-col">
                {order
                  .filter((row) => !row.skipped)
                  .slice(0, 24)
                  .map((row) => {
                    const isPlanned = planned.has(row.section_id)
                    const isCovered = covered.has(row.section_id)
                    return (
                      <li
                        key={row.section_id}
                        className="flex items-baseline gap-3 border-b border-neutral-900 py-2"
                      >
                        <Link
                          href={`/c/${campaign}/s/${encodeURIComponent(row.section_id)}`}
                          className={`truncate text-sm hover:underline ${
                            row.origin === 'campaign' ? SOURCE.yours : 'text-neutral-200'
                          }`}
                        >
                          {row.heading}
                        </Link>
                        <span className="ml-auto flex shrink-0 items-center gap-2">
                          <Toggle
                            on={isPlanned}
                            onClick={() => mark(row.section_id, 'planned')}
                            label="plan"
                          />
                          <Toggle
                            on={isCovered}
                            onClick={() => mark(row.section_id, 'covered')}
                            label="played"
                          />
                        </span>
                      </li>
                    )
                  })}
              </ol>

              {diff && (
                <div className="mt-8 grid gap-6 sm:grid-cols-2">
                  <Column
                    title="Did not get to"
                    empty="Everything you planned, you ran."
                    scenes={diff.missed}
                    campaign={campaign}
                  />
                  <Column
                    title="Played, never planned"
                    empty="Nothing off-book tonight."
                    scenes={diff.unplanned}
                    campaign={campaign}
                  />
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </Shell>
  )
}

function Toggle({
  on,
  onClick,
  label,
}: {
  on: boolean
  onClick: () => void
  label: string
}) {
  return (
    <button
      onClick={onClick}
      aria-pressed={on}
      // CONTRAST, NEVER HUE -- `palette.ts` keeps every hue for a source, and
      // "played" is not a source.
      className={`rounded px-1.5 py-0.5 text-[11px] transition-colors ${
        on ? CHROME.selected : 'text-neutral-600 hover:text-neutral-400'
      }`}
    >
      {label}
    </button>
  )
}

function Column({
  title,
  empty,
  scenes,
  campaign,
}: {
  title: string
  empty: string
  scenes: { id: string; heading: string }[]
  campaign: string
}) {
  return (
    <section>
      <h2 className="text-[11px] uppercase tracking-widest text-neutral-600">{title}</h2>
      <ul className="mt-2 flex flex-col gap-1">
        {scenes.map((s) => (
          <li key={s.id}>
            <Link
              href={`/c/${campaign}/s/${encodeURIComponent(s.id)}`}
              className="text-sm text-neutral-300 hover:underline"
            >
              {s.heading || s.id}
            </Link>
          </li>
        ))}
        {scenes.length === 0 && <li className="text-sm text-neutral-600">{empty}</li>}
      </ul>
    </section>
  )
}
