'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'
import { useParams } from 'next/navigation'

import { Shell } from '@/components/product/Shell'
import { Sittings } from '@/components/product/Sittings'
import { WhatWeKnow } from '@/components/product/WhatWeKnow'
import {
  labAPI,
  tableAPI,
  type CampaignElement,
  type OrderRow,
  type Whoami,
} from '@/lib/api'
import { SOURCE } from '@/lib/palette'

/**
 * The table's own page: what is coming, and who is in it.
 *
 * PREP IS THE DEFAULT POSTURE, not the lab's canon-only bench. A DM opening
 * this app is working on their game, so their own material leads and the book
 * is what it draws on.
 */
export default function CampaignHome() {
  const params = useParams<{ campaign: string }>()
  const campaign = decodeURIComponent(params.campaign)

  const [order, setOrder] = useState<OrderRow[]>([])
  const [cast, setCast] = useState<CampaignElement[]>([])
  const [who, setWho] = useState<Whoami | null>(null)

  useEffect(() => {
    labAPI.runningOrder(campaign).then((r) => setOrder(r.sections)).catch(() => undefined)
    labAPI.elements(campaign).then((r) => setCast(r.elements)).catch(() => undefined)
    tableAPI.whoami(campaign).then(setWho).catch(() => undefined)
  }, [campaign])

  const yours = order.filter((row) => row.origin === 'campaign')
  const next = order.filter((row) => !row.skipped).slice(0, 8)
  // A PLAYER GETS NO PREP COLUMN AT ALL. Both of its sources are refused to
  // them, so the honest rendering is to leave it out rather than to draw an
  // empty list that reads as "your DM has planned nothing".
  const runs = who === null || who.role === 'dm' || !who.identified

  return (
    <Shell campaign={campaign} section="prep">
      <div
        className={`mx-auto grid max-w-5xl gap-10 px-6 py-10 ${
          runs ? 'md:grid-cols-[1fr_18rem]' : ''
        }`}
      >
        {runs && (
        <div>
          <h1 className="text-xl font-medium text-neutral-100">What&rsquo;s next</h1>
          <p className="mt-1 text-sm text-neutral-500">
            The book&rsquo;s order, with your scenes where you put them.
          </p>

          <ol className="mt-5 flex flex-col">
            {next.map((row) => (
              <li key={row.section_id}>
                <Link
                  href={`/c/${campaign}/s/${encodeURIComponent(row.section_id)}`}
                  className="flex items-baseline gap-3 border-b border-neutral-900 py-2.5 hover:bg-neutral-900/40"
                >
                  <span
                    className={`text-sm ${
                      row.origin === 'campaign' ? SOURCE.yours : 'text-neutral-200'
                    }`}
                  >
                    {row.heading}
                  </span>
                  <span className="ml-auto shrink-0 text-[11px] text-neutral-600">
                    {row.chapter}
                  </span>
                </Link>
              </li>
            ))}
            {order.length === 0 && (
              <li className="py-2 text-sm text-neutral-600">
                Nothing in the running order yet.
              </li>
            )}
          </ol>
        </div>
        )}

        <aside>
          {runs && (
          <>
          <h2 className="text-[11px] uppercase tracking-widest text-neutral-600">
            Your cast
          </h2>
          <ul className="mt-3 flex flex-col gap-1">
            {cast.slice(0, 14).map((element) => (
              <li key={element.entity_id}>
                <Link
                  href={`/c/${campaign}/e/${encodeURIComponent(element.entity_id)}`}
                  className={`text-sm hover:underline ${SOURCE.yours}`}
                >
                  {element.name}
                </Link>
                {element.role && (
                  <span className="ml-2 text-[11px] text-neutral-600">
                    {element.role}
                  </span>
                )}
              </li>
            ))}
            {cast.length === 0 && (
              <li className="text-sm text-neutral-600">Nobody yet.</li>
            )}
          </ul>
          <p className="mt-4 text-[11px] text-neutral-700">
            {yours.length} of {order.length} scenes are yours
          </p>
          </>
          )}

          <div className="mt-8">
            <Sittings campaign={campaign} who={who} />
          </div>

          {/* FOR EVERYONE, and for a player it is the ONLY part of this page
              that answers. The running order and the cast are refused to them
              outright -- a running order is the plot of everything they have
              not reached, listed in order -- so those panels come back empty
              and this is what is theirs. */}
          <div className="mt-8">
            <WhatWeKnow campaign={campaign} />
          </div>
        </aside>
      </div>
    </Shell>
  )
}
