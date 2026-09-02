'use client'

import Link from 'next/link'
import { useEffect, useState, type ReactNode } from 'react'

import { Door } from '@/components/Door'
import { auth, tableAPI } from '@/lib/api'
import { CHROME } from '@/lib/palette'

/**
 * The frame every product screen sits in.
 *
 * NOT THE LAB'S FRAME. The lab is an instrument -- three resizable panes, a
 * cost meter in the masthead, a model picker -- and it stays exactly as it is
 * at `/lab`, because a DM should no more choose an inference model than choose
 * a database index. This is the other audience: somebody running a game.
 *
 * ONE NAV, ALWAYS THE SAME PLACE. A DM mid-session is not exploring; they are
 * looking something up while five people wait. The bar does not collapse, move
 * or animate, and the campaign it belongs to is named in it so a DM with two
 * tables open in two tabs can tell them apart at a glance.
 *
 * AND IT KNOWS WHICH CHAIR YOU ARE IN. Every tab used to show for everybody,
 * and three of them refuse a player outright -- the running order is the plot
 * of what they have not reached, the cast names NPCs they have never met, and
 * Setup is the DM's own controls. Five tabs where three are locked doors is
 * worse than two that work: it reads as broken rather than as gated.
 *
 * THE ROLE IS ASKED FOR, NOT PASSED IN. Every screen would otherwise have to
 * fetch it and hand it down, and the one that forgot would quietly show a
 * player the DM's nav.
 *
 * AND THE TOKEN IS LOADED HERE, which is the only place every product screen
 * passes through. `auth.load()` was called on the home page alone, so on a
 * gated deployment every OTHER page ran unauthenticated: a person opening a
 * bookmarked scene got a wall of failed requests and a page that looked empty
 * rather than locked. An empty screen and a locked one are the two states a
 * reader must never confuse, because only one of them is worth waiting for.
 */
export function Shell({
  campaign,
  section,
  children,
  aside,
}: {
  campaign?: string
  section?: 'prep' | 'library' | 'play' | 'party' | 'settings' | 'log' | 'told'
  children: ReactNode
  aside?: ReactNode
}) {
  const [role, setRole] = useState<string | null>(null)
  const [locked, setLocked] = useState(false)

  useEffect(() => {
    auth.onRefused(() => setLocked(true))
    auth.load()
  }, [])

  useEffect(() => {
    if (!campaign || locked) return
    tableAPI
      .whoami(campaign)
      // AN UNIDENTIFIED READER RUNS THE TABLE, the same ruling the backend
      // makes: `ACCESS_TOKENS` unset is one person at their own machine. A
      // failed call falls the other way, so a broken gate closes doors rather
      // than opening them.
      .then((who) => setRole(who.identified ? who.role || 'player' : 'dm'))
      .catch(() => setRole('player'))
  }, [campaign, locked])

  const runs = role === 'dm'

  // A REFUSAL IS A DOOR, NOT A BLANK PAGE. Rendered before the frame so a
  // locked reader is asked for a token rather than shown an outline of a
  // product they cannot see.
  //
  // AND OPENING IT RELOADS. Every screen fetches what it needs in an effect
  // keyed on the campaign, so the requests that failed while locked are not
  // retried when the token arrives -- clearing the flag alone leaves a person
  // looking at the empty page their refusals produced. One reload, once, puts
  // every loader back in a good state.
  if (locked) {
    return <Door onOpened={() => window.location.reload()} />
  }

  return (
    <div className="flex h-full flex-col bg-ground text-ink">
      <header className="flex h-11 shrink-0 items-center gap-1 border-b border-line px-4">
        <Link
          href="/"
          className="mr-3 text-ui font-medium text-ink hover:text-chrome"
        >
          Table
        </Link>

        {campaign && role !== null && (
          <>
            <span className="mr-3 truncate text-meta text-ink-faint">{campaign}</span>
            <Tab href={`/c/${campaign}`} on={section === 'prep'}>
              {runs ? 'Prep' : 'Your table'}
            </Tab>
            <Tab href={`/c/${campaign}/log`} on={section === 'log'}>
              Log
            </Tab>
            <Tab href={`/c/${campaign}/party`} on={section === 'party'}>
              Party
            </Tab>
            {runs && (
              <>
                <Tab href={`/c/${campaign}/library`} on={section === 'library'}>
                  Library
                </Tab>
                <Tab href={`/c/${campaign}/play`} on={section === 'play'}>
                  Play
                </Tab>
                <Tab href={`/c/${campaign}/told`} on={section === 'told'}>
                  Told
                </Tab>
                <Tab href={`/c/${campaign}/settings`} on={section === 'settings'}>
                  Setup
                </Tab>
              </>
            )}
          </>
        )}

        <div className="ml-auto flex items-center gap-3">
          {aside}
          {/* THE LAB IS NOT GONE, it is just not here. Kept reachable because
              the retrieval report and the subgraph ledger are how a DM audits
              an answer that smells wrong -- that is a trust feature, not
              clutter, and burying it would delete it. */}
          {/* THE LAB IS THE DM'S INSTRUMENT and its chat reads the whole
              book, so the link is not offered to a player -- the endpoint
              refuses them anyway, and a link that always fails is a worse
              answer than no link. */}
          {runs && (
            <Link
              href="/lab"
              className="text-meta text-ink-faint hover:text-ink-dim"
              title="The research instrument: retrieval, subgraph, cost"
            >
              Lab
            </Link>
          )}
        </div>
      </header>

      <main className="min-h-0 flex-1 overflow-y-auto">{children}</main>
    </div>
  )
}

function Tab({ href, on, children }: { href: string; on: boolean; children: ReactNode }) {
  return (
    <Link
      href={href}
      // CONTRAST, NEVER HUE. `palette.ts` reserves every hue for a source, so
      // a selected tab may not borrow one -- a brighter neutral against a dark
      // ground is legible without competing for meaning.
      // THE CHROME LADDER, not a hand-picked pair. Rest is dim; hover lifts
      // one step; selected lifts further AND gains weight, so the current tab
      // is legible in a screenshot with the colour removed.
      className={`rounded-md px-2 py-1 text-ui ${CHROME.row} ${
        on ? CHROME.selected : 'text-ink-dim'
      }`}
    >
      {children}
    </Link>
  )
}
