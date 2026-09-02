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
  type LogNight,
  type OrderRow,
  type Whoami,
} from '@/lib/api'
import { CHROME, SOURCE, SOURCE_EDGE, SOURCE_GLYPH } from '@/lib/palette'

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
  const [recent, setRecent] = useState<LogNight[]>([])

  useEffect(() => {
    tableAPI.whoami(campaign).then(setWho).catch(() => undefined)
    tableAPI.log(campaign).then((r) => setRecent(r.log)).catch(() => undefined)
  }, [campaign])

  // ASKED FOR ONLY BY THE PERSON ALLOWED TO HAVE IT. Both of these are refused
  // to a player, and firing them anyway meant every player's first page load
  // spent two requests earning two 403s and printing them to the console.
  useEffect(() => {
    if (!who || (who.identified && who.role !== 'dm')) return
    labAPI.runningOrder(campaign).then((r) => setOrder(r.sections)).catch(() => undefined)
    labAPI.elements(campaign).then((r) => setCast(r.elements)).catch(() => undefined)
  }, [campaign, who])

  const yours = order.filter((row) => row.origin === 'campaign')
  const next = order.filter((row) => !row.skipped).slice(0, 8)
  // A PLAYER GETS NO PREP COLUMN AT ALL. Both of its sources are refused to
  // them, so the honest rendering is to leave it out rather than to draw an
  // empty list that reads as "your DM has planned nothing".
  //
  // UNKNOWN IS NOT THE DM. While `whoami` is in flight nobody is either
  // column, which costs a moment of blank space and avoids showing a player
  // the DM's headings before the answer arrives.
  const runs = who !== null && (who.role === 'dm' || !who.identified)
  const plays = who !== null && !runs

  return (
    <Shell campaign={campaign} section="prep">
      <div className="mx-auto grid max-w-5xl gap-8 px-6 py-12 md:grid-cols-[1fr_18rem]">
        {/* A PLAYER GETS THEIR OWN COLUMN, not the absence of the DM's. An
            empty page reads as a product that does not work; the last night's
            worth of what they were told is the thing they actually came back
            for. */}
        {plays && (
          <div>
            <h1 className="text-title font-medium text-ink">
              Where we got to
            </h1>
            <p className="mt-1 text-ui text-ink-dim">
              The last of what your DM has shown the table.
            </p>

            {recent.slice(0, 2).map((night) => (
              <section key={night.number} className="mt-6">
                <h2 className="label text-ink-faint">
                  {night.number === 0
                    ? 'Before the first session'
                    : `Session ${night.number}`}
                  {night.title ? ` — ${night.title}` : ''}
                </h2>
                <ul className="mt-2 flex flex-col gap-1">
                  {night.learned.map((one) => (
                    <li key={one.id}>
                      <Link
                        href={
                          one.kind === 'scene'
                            ? `/c/${campaign}/s/${encodeURIComponent(one.id)}`
                            : `/c/${campaign}/e/${encodeURIComponent(one.id)}`
                        }
                        className="text-ui text-ink-dim hover:underline"
                      >
                        {one.name}
                      </Link>
                    </li>
                  ))}
                </ul>
              </section>
            ))}

            {recent.length === 0 && (
              <p className="mt-6 text-ui text-ink-faint">
                Your DM has not shown the table anything yet.
              </p>
            )}

            {recent.length > 2 && (
              <Link
                href={`/c/${campaign}/log`}
                className="mt-6 inline-block text-meta text-ink-dim hover:text-ink"
              >
                the whole log →
              </Link>
            )}
          </div>
        )}

        {runs && (
        <div>
          <h1 className="text-title font-medium text-ink">What&rsquo;s next</h1>
          <p className="mt-1 text-ui text-ink-dim">
            The book&rsquo;s order, with your scenes where you put them.
          </p>

          <ol className="mt-6 flex flex-col">
            {next.map((row) => (
              <li key={row.section_id}>
                <Link
                  href={`/c/${campaign}/s/${encodeURIComponent(row.section_id)}`}
                  className={`flex h-9 items-center gap-3 rounded-md px-2 ${CHROME.row} ${
                    row.origin === 'campaign' ? SOURCE_EDGE.yours : ''
                  }`}
                >
                  {/* ROW TEXT STAYS INK; the edge carries the hue and this
                      carries the glyph. A tinted sentence says the same thing
                      a third time and turns a list into confetti. */}
                  <span className="text-ui text-ink">{row.heading}</span>
                  {row.origin === 'campaign' && (
                    <span className={`shrink-0 text-label ${SOURCE.yours}`}>
                      {SOURCE_GLYPH.yours}
                    </span>
                  )}
                  <span className="ml-auto shrink-0 text-meta text-ink-faint">
                    {row.chapter}
                  </span>
                </Link>
              </li>
            ))}
            {order.length === 0 && (
              <li className="py-2 text-ui text-ink-faint">
                Nothing in the running order yet.
              </li>
            )}
          </ol>
        </div>
        )}

        <aside>
          {runs && (
          <>
          {/* SAID ONCE, AT THE TOP. Every name in this list is the DM's own,
              so colouring all fourteen amber marked nothing and made the
              loudest thing on the screen the one carrying no information. A
              hue earns its place by distinguishing; where there is nothing to
              distinguish it is decoration, which is the one thing the rule
              forbids it from being. */}
          <h2 className={`label ${SOURCE.yours}`}>
            {SOURCE_GLYPH.yours} your cast
          </h2>
          <ul className="mt-3 flex flex-col gap-1">
            {cast.slice(0, 14).map((element) => (
              <li key={element.entity_id} className="leading-6">
                <Link
                  href={`/c/${campaign}/e/${encodeURIComponent(element.entity_id)}`}
                  className="text-ui text-ink hover:underline"
                >
                  {element.name}
                </Link>
                {element.role && (
                  <span className="ml-2 text-meta text-ink-faint">
                    {element.role}
                  </span>
                )}
              </li>
            ))}
            {cast.length === 0 && (
              <li className="text-ui text-ink-faint">Nobody yet.</li>
            )}
          </ul>
          <p className="mt-4 text-label text-ink-faint">
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
