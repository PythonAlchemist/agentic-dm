'use client'

import Link from 'next/link'
import type { ReactNode } from 'react'

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
 */
export function Shell({
  campaign,
  section,
  children,
  aside,
}: {
  campaign?: string
  section?: 'prep' | 'library' | 'play'
  children: ReactNode
  aside?: ReactNode
}) {
  return (
    <div className="flex h-full flex-col bg-neutral-950 text-neutral-200">
      <header className="flex shrink-0 items-center gap-1 border-b border-neutral-800 px-4 py-2">
        <Link
          href="/"
          className="mr-3 text-sm font-medium text-neutral-300 hover:text-neutral-100"
        >
          Table
        </Link>

        {campaign && (
          <>
            <span className="mr-3 truncate text-xs text-neutral-500">{campaign}</span>
            <Tab href={`/c/${campaign}`} on={section === 'prep'}>
              Prep
            </Tab>
            <Tab href={`/c/${campaign}/library`} on={section === 'library'}>
              Library
            </Tab>
            <Tab href={`/c/${campaign}/play`} on={section === 'play'}>
              Play
            </Tab>
          </>
        )}

        <div className="ml-auto flex items-center gap-3">
          {aside}
          {/* THE LAB IS NOT GONE, it is just not here. Kept reachable because
              the retrieval report and the subgraph ledger are how a DM audits
              an answer that smells wrong -- that is a trust feature, not
              clutter, and burying it would delete it. */}
          <Link
            href="/lab"
            className="text-xs text-neutral-600 hover:text-neutral-400"
            title="The research instrument: retrieval, subgraph, cost"
          >
            Lab
          </Link>
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
      className={`rounded px-2.5 py-1 text-sm transition-colors ${
        on
          ? 'bg-neutral-800 text-neutral-100'
          : 'text-neutral-500 hover:text-neutral-300'
      }`}
    >
      {children}
    </Link>
  )
}
