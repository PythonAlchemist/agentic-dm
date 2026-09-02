'use client'

import Link from 'next/link'
import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'next/navigation'

import { Shell } from '@/components/product/Shell'
import { tableAPI, type Found, type Grant } from '@/lib/api'
import { SOURCE } from '@/lib/palette'

/**
 * Everything the table knows, in one place, with the switch beside it.
 *
 * A LIST OF WHAT THEY KNOW, NOT OF WHAT THEY DO NOT. That is the readable
 * direction and the reason grants are positive: this screen fits on a page,
 * while "everything they have not been told" is the whole graph minus a set
 * nobody can hold in their head.
 *
 * THE PER-ENTITY CONTROL STAYS WHERE THE READING HAPPENS. A DM decides what
 * the players know while reading the scene it comes up in, so `Reveal` lives
 * on the profile and on the section. This is the other question -- "wait, what
 * DO they know?" -- which the profile cannot answer because it only ever shows
 * one thing.
 *
 * TAKING SOMETHING BACK IS NOT UNDO, and the screen says so once, plainly,
 * rather than on every row.
 */
export default function ToldPage() {
  const params = useParams<{ campaign: string }>()
  const campaign = decodeURIComponent(params.campaign)

  const [grants, setGrants] = useState<Grant[]>([])
  const [q, setQ] = useState('')
  const [found, setFound] = useState<Found[]>([])
  const [failed, setFailed] = useState('')

  const load = useCallback(() => {
    tableAPI
      .revealed(campaign)
      .then((r) => setGrants(r.revealed))
      .catch((error) => setFailed(String(error).replace(/^Error:\s*/, '')))
  }, [campaign])

  useEffect(load, [load])

  useEffect(() => {
    if (!q.trim()) return
    let cancelled = false
    tableAPI
      .search(campaign, q)
      .then((r) => !cancelled && setFound(r.found))
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [q, campaign])

  const told = new Set(grants.map((g) => g.id))
  const shown = q.trim() ? found.filter((f) => !told.has(f.entity_id)) : []

  const act = (call: Promise<unknown>) =>
    call.then(load).catch((error) => setFailed(String(error).replace(/^Error:\s*/, '')))

  return (
    <Shell campaign={campaign} section="told">
      <div className="mx-auto max-w-3xl px-6 py-10">
        <h1 className="text-title font-medium text-ink">What your table knows</h1>
        <p className="mt-1 text-ui text-ink-dim">
          Everything else is hidden from them until you say otherwise.
        </p>

        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="tell them about someone…"
          className={`mt-5 w-full rounded-md border border-line bg-ground px-2 py-1.5 text-ui text-ink`}
        />

        {shown.length > 0 && (
          <ul className="mt-2 flex max-h-56 flex-col overflow-y-auto rounded-md border border-line bg-surface/50">
            {shown.map((one) => (
              <li key={one.entity_id}>
                <button
                  onClick={() => act(tableAPI.tellTable(campaign, one.entity_id))}
                  className="flex w-full items-baseline gap-2 px-2 py-1.5 text-left text-ui hover:bg-overlay"
                >
                  <span
                    className={
                      one.plane === 'campaign' ? SOURCE.yours : 'text-ink'
                    }
                  >
                    {one.name}
                  </span>
                  <span className="ml-auto text-label uppercase tracking-wide text-ink-faint">
                    tell them
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}

        {/* NO HAIRLINE PER ROW. Rhythm separates them; a rule per row at any
            length beyond a handful stops dividing and starts fogging. */}
        <ul className="mt-7 flex flex-col">
          {grants.map((grant) => (
            <li
              key={grant.id}
              className="flex h-11 items-center gap-3 rounded-md pl-3 pr-2 chrome-row"
            >
              <Link
                href={
                  grant.labels.includes('Section')
                    ? `/c/${campaign}/s/${encodeURIComponent(grant.id)}`
                    : `/c/${campaign}/e/${encodeURIComponent(grant.id)}`
                }
                className="truncate text-ui text-ink hover:underline"
              >
                {grant.name}
              </Link>
              {grant.as_name && (
                <span className="shrink-0 text-label text-ink-dim">
                  they call them &ldquo;{grant.as_name}&rdquo;
                </span>
              )}
              {grant.at_session && (
                <span className="shrink-0 text-label text-ink-faint">
                  {/* A BARE NUMBER IS NOT A DATE. The id ends in the session
                      number, and "1" on its own reads as a count of
                      something. */}
                  session {grant.at_session.split('-').pop()}
                </span>
              )}
              <button
                onClick={() => act(tableAPI.conceal(campaign, grant.id))}
                className="ml-auto shrink-0 text-label text-ink-dim hover:text-ink"
              >
                take it back
              </button>
            </li>
          ))}
        </ul>

        {grants.length === 0 && (
          <p className="mt-4 text-ui text-ink-faint">
            You have told them nothing yet.
          </p>
        )}

        <p className="mt-8 text-label leading-relaxed text-ink-faint">
          Taking something back hides it from here on. It does not unsay it
          &mdash; which is why nothing is shown to your table until you show it.
        </p>

        {failed && <p className="mt-2 text-label text-ink-dim">⚠ {failed}</p>}
      </div>
    </Shell>
  )
}
