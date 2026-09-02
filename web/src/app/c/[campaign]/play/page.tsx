'use client'

import Link from 'next/link'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams } from 'next/navigation'

import { Shell } from '@/components/product/Shell'
import {
  labAPI,
  tableAPI,
  type OrderRow,
  type SessionDiff,
  type SessionRow,
} from '@/lib/api'
import { CHROME, SOURCE, SOURCE_GLYPH } from '@/lib/palette'

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
  const [touched, setTouched] = useState<
    { section_id: string; heading: string; names: string[] }[]
  >([])
  const [note, setNote] = useState('')
  const [failed, setFailed] = useState('')
  const file = useRef<HTMLInputElement>(null)

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

  const upload = (chosen: File | undefined) => {
    if (!chosen || !open) return
    setFailed('')
    chosen
      .text()
      .then((content) => tableAPI.transcript(campaign, open, content))
      .then((stored) => {
        setNote(
          `${stored.turns} turns became ${stored.sections} section` +
            `${stored.sections === 1 ? '' : 's'} and ${stored.mentions} mention` +
            `${stored.mentions === 1 ? '' : 's'}.`,
        )
        return tableAPI.touched(campaign, open)
      })
      .then((r) => setTouched(r.touched))
      .catch((error) => setFailed(String(error).replace(/^Error:\s*/, '')))
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
      {/* FULL WIDTH, WITH THE CONTENT KEPT TO A MEASURE. Play is operated
          rather than read, so it takes the width -- but the scene list is
          still a list of sentences and stretching it to 1440px would make
          every row a tracking exercise. */}
      <div className="mx-auto grid max-w-7xl gap-8 px-6 py-12 md:grid-cols-[15rem_minmax(0,1fr)]">
        <aside>
          <div className="flex items-baseline justify-between">
            <h2 className="label text-ink-faint">
              Sessions
            </h2>
            <button
              onClick={start}
              className="label text-ink-dim hover:text-ink"
            >
              new
            </button>
          </div>

          <ul className="mt-3 flex flex-col">
            {sessions.map((s) => (
              <li key={s.id}>
                <button
                  onClick={() => setOpen(s.id)}
                  className={`flex w-full items-baseline gap-2 rounded-md px-2 py-1 text-left text-ui ${
                    s.id === open ? CHROME.selected : 'text-ink-dim hover:text-ink'
                  }`}
                >
                  <span className="tabular-nums">#{s.number}</span>
                  <span className="truncate">{s.title || 'untitled'}</span>
                  <span className="ml-auto shrink-0 text-label tabular-nums text-ink-faint">
                    {s.covered}/{s.planned}
                  </span>
                </button>
              </li>
            ))}
            {sessions.length === 0 && (
              <li className="px-2 py-1 text-ui text-ink-faint">
                Nothing yet.
              </li>
            )}
          </ul>

          {failed && (
            <p className="mt-4 text-label leading-relaxed text-ink-dim">⚠ {failed}</p>
          )}
        </aside>

        <div>
          <h1 className="text-title font-medium text-ink">Tonight</h1>
          <p className="mt-1 text-ui text-ink-dim">
            Plan a scene before you run it; mark it played when you have.
          </p>

          {/* ONE EMPTY STATE, NOT TWO. The sidebar said "No sessions yet" and
              this said "Start a session to plan against it" -- the same fact,
              twice, on one screen. The sidebar keeps the quiet version; this
              is where the answer to it lives. */}
          {!open && (
            <div className="mt-10 max-w-md">
              <p className="text-body text-ink-dim">
                A session is the night you play. Open one and this becomes
                tonight&rsquo;s running order: plan the scenes you mean to
                reach, mark what you actually ran, and upload the transcript
                afterwards.
              </p>
              <button
                onClick={start}
                className={`mt-4 rounded-md px-3 py-1 text-ui ${CHROME.primary}`}
              >
                Start the first session
              </button>
            </div>
          )}

          {open && (
            <>
              {/* WHAT ACTUALLY HAPPENED. A recording is the one document here
                  that may not assert: it becomes prose and mentions, and every
                  claim it seems to make stays a suggestion below. */}
              <div className="mt-6 flex items-baseline gap-3">
                <input
                  ref={file}
                  type="file"
                  accept=".txt,.json,.md,text/plain,application/json"
                  className="hidden"
                  onChange={(event) => upload(event.target.files?.[0])}
                />
                <button
                  onClick={() => file.current?.click()}
                  className={`rounded-md px-2 py-1 text-label ${CHROME.primary}`}
                >
                  upload the transcript
                </button>
                {note && <span className="text-label text-ink-dim">{note}</span>}
              </div>

              {touched.length > 0 && (
                <div className="mt-4 rounded-md border border-line bg-surface/40 p-3">
                  <h2 className="label text-ink-faint">
                    The recording names these
                  </h2>
                  <p className="mt-1 text-label text-ink-faint">
                    Evidence, not a verdict. Mark what you actually ran.
                  </p>
                  <ul className="mt-2 flex flex-col gap-1">
                    {touched.map((t) => (
                      <li key={t.section_id} className="flex items-baseline gap-2 text-ui">
                        <span className="text-ink-dim">{t.heading}</span>
                        <span className="text-label text-ink-faint">
                          {t.names.slice(0, 4).join(', ')}
                        </span>
                        <button
                          onClick={() => mark(t.section_id, 'covered')}
                          className="ml-auto text-label text-ink-dim hover:text-ink"
                        >
                          mark played
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

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
                        className="flex items-baseline gap-3 border-b border-line py-2"
                      >
                        <Link
                          href={`/c/${campaign}/s/${encodeURIComponent(row.section_id)}`}
                          className="truncate text-ui text-ink hover:underline"
                        >
                          {row.heading}
                        </Link>
                        {row.origin === 'campaign' && (
                          <span className={`shrink-0 text-label ${SOURCE.yours}`}>
                            {SOURCE_GLYPH.yours}
                          </span>
                        )}
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
      className={`rounded-md px-1.5 py-0.5 text-label transition-colors ${
        on ? CHROME.selected : 'text-ink-faint hover:text-ink-dim'
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
      <h2 className="label text-ink-faint">{title}</h2>
      <ul className="mt-2 flex flex-col gap-1">
        {scenes.map((s) => (
          <li key={s.id}>
            <Link
              href={`/c/${campaign}/s/${encodeURIComponent(s.id)}`}
              className="text-ui text-ink-dim hover:underline"
            >
              {s.heading || s.id}
            </Link>
          </li>
        ))}
        {scenes.length === 0 && <li className="text-ui text-ink-faint">{empty}</li>}
      </ul>
    </section>
  )
}
