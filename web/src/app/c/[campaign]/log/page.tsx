'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'
import { useParams } from 'next/navigation'

import { Shell } from '@/components/product/Shell'
import { tableAPI, type LogNight } from '@/lib/api'
import { SOURCE } from '@/lib/palette'

/**
 * The adventure so far, by the night it happened.
 *
 * DERIVED, NEVER WRITTEN. Every row here already exists -- the sessions, and
 * the grants stamped with the session they were made in -- so the log is a
 * read. A stored log would be the copy that disagrees with the graph, and this
 * codebase has paid for that shape more than once.
 *
 * IT USES THE TABLE'S WORDS. A person revealed as "the coachman" is the
 * coachman here for as long as that is who they are; the log is what the
 * PLAYERS remember, not what the DM knows.
 *
 * NOTHING GENERATED. A model could write a nicer recap and it would be a recap
 * nobody could check, on the screen whose whole job is being the record.
 */
export default function LogPage() {
  const params = useParams<{ campaign: string }>()
  const campaign = decodeURIComponent(params.campaign)

  const [nights, setNights] = useState<LogNight[]>([])
  const [ready, setReady] = useState(false)

  useEffect(() => {
    tableAPI
      .log(campaign)
      .then((r) => {
        setNights(r.log)
        setReady(true)
      })
      .catch(() => setReady(true))
  }, [campaign])

  return (
    <Shell campaign={campaign} section="log">
      <div className="mx-auto max-w-2xl px-6 py-10">
        <h1 className="text-xl font-medium text-neutral-100">The adventure so far</h1>
        <p className="mt-1 text-sm text-neutral-500">
          What your table has been told, and the night you were told it.
        </p>

        <ol className="mt-8 flex flex-col gap-8">
          {nights.map((night) => (
            <li key={night.number}>
              <div className="flex items-baseline gap-3">
                <h2 className="text-sm font-medium text-neutral-200">
                  {night.number === 0
                    ? 'Before the first session'
                    : `Session ${night.number}`}
                </h2>
                {night.title && (
                  <span className="text-sm text-neutral-400">{night.title}</span>
                )}
                {night.held_on && (
                  <span className="ml-auto text-[11px] tabular-nums text-neutral-600">
                    {night.held_on.slice(0, 10)}
                  </span>
                )}
              </div>

              <ul className="mt-2 flex flex-col gap-1 border-l border-neutral-800 pl-3">
                {night.learned.map((one) => (
                  <li key={one.id} className="flex items-baseline gap-2">
                    <Link
                      href={
                        one.kind === 'scene'
                          ? `/c/${campaign}/s/${encodeURIComponent(one.id)}`
                          : `/c/${campaign}/e/${encodeURIComponent(one.id)}`
                      }
                      className="text-sm text-neutral-300 hover:underline"
                    >
                      {one.name}
                    </Link>
                    <span className="text-[10px] uppercase tracking-wide text-neutral-700">
                      {one.kind === 'scene' ? 'read' : 'met'}
                    </span>
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ol>

        {ready && nights.length === 0 && (
          <p className="mt-8 text-sm text-neutral-600">
            Nothing yet. Your DM has not shown the table anything.
          </p>
        )}

        <p className={`mt-10 text-[11px] ${SOURCE.book}`}>
          Everything here is quoted from the book or written by your DM. None of
          it was made up by a machine.
        </p>
      </div>
    </Shell>
  )
}
