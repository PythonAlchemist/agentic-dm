'use client'

import Link from 'next/link'
import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'next/navigation'

import { Shell } from '@/components/product/Shell'
import { tableAPI, type Found, type Grant } from '@/lib/api'
import { CHROME, SOURCE } from '@/lib/palette'

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
    <Shell campaign={campaign} section="settings">
      <div className="mx-auto max-w-2xl px-6 py-10">
        <h1 className="text-xl font-medium text-neutral-100">What your table knows</h1>
        <p className="mt-1 text-sm text-neutral-500">
          Everything else is hidden from them until you say otherwise.
        </p>

        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="tell them about someone…"
          className={`mt-5 w-full rounded border border-neutral-800 bg-neutral-950 px-2 py-1.5 text-sm text-neutral-200 outline-none ${CHROME.focus}`}
        />

        {shown.length > 0 && (
          <ul className="mt-2 flex max-h-56 flex-col overflow-y-auto rounded border border-neutral-800 bg-neutral-900/50">
            {shown.map((one) => (
              <li key={one.entity_id}>
                <button
                  onClick={() => act(tableAPI.tellTable(campaign, one.entity_id))}
                  className="flex w-full items-baseline gap-2 px-2 py-1.5 text-left text-sm hover:bg-neutral-800"
                >
                  <span
                    className={
                      one.plane === 'campaign' ? SOURCE.yours : 'text-neutral-200'
                    }
                  >
                    {one.name}
                  </span>
                  <span className="ml-auto text-[10px] uppercase tracking-wide text-neutral-600">
                    tell them
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}

        <ul className="mt-7 flex flex-col">
          {grants.map((grant) => (
            <li
              key={grant.id}
              className="flex items-baseline gap-3 border-b border-neutral-900 py-2"
            >
              <Link
                href={
                  grant.labels.includes('Section')
                    ? `/c/${campaign}/s/${encodeURIComponent(grant.id)}`
                    : `/c/${campaign}/e/${encodeURIComponent(grant.id)}`
                }
                className="truncate text-sm text-neutral-200 hover:underline"
              >
                {grant.name}
              </Link>
              {grant.as_name && (
                <span className="shrink-0 text-[11px] text-neutral-500">
                  they call them &ldquo;{grant.as_name}&rdquo;
                </span>
              )}
              {grant.at_session && (
                <span className="shrink-0 text-[11px] text-neutral-700">
                  {/* A BARE NUMBER IS NOT A DATE. The id ends in the session
                      number, and "1" on its own reads as a count of
                      something. */}
                  session {grant.at_session.split('-').pop()}
                </span>
              )}
              <button
                onClick={() => act(tableAPI.conceal(campaign, grant.id))}
                className="ml-auto shrink-0 text-[11px] text-neutral-500 hover:text-neutral-300"
              >
                take it back
              </button>
            </li>
          ))}
        </ul>

        {grants.length === 0 && (
          <p className="mt-4 text-sm text-neutral-600">
            You have told them nothing yet.
          </p>
        )}

        <p className="mt-8 text-[11px] leading-relaxed text-neutral-600">
          Taking something back hides it from here on. It does not unsay it
          &mdash; which is why nothing is shown to your table until you show it.
        </p>

        {failed && <p className="mt-2 text-[11px] text-neutral-400">⚠ {failed}</p>}
      </div>
    </Shell>
  )
}
