'use client'

import { useCallback, useEffect, useState } from 'react'

import { tableAPI, type Grant } from '@/lib/api'
import { useRuns } from '@/lib/role'
import { CHROME } from '@/lib/palette'

/**
 * Whether the table has been told about this.
 *
 * ON THE THING ITSELF, not in a permissions screen. A DM decides what the
 * players know while reading the scene where it comes up, and a separate list
 * of grants somewhere in settings would be filled in never.
 *
 * IT SAYS WHAT IT CANNOT DO. Concealing removes the grant; it does not remove
 * what anybody already read. That is not a defect to apologise for -- it is
 * the whole reason the default is "not shown", and the copy says so where the
 * decision is made rather than in a document nobody opens.
 *
 * NO HUE. `palette.ts` keeps every hue for a SOURCE, and "the table knows
 * this" is not a source -- it is a fact about an audience. Contrast carries it.
 */
export function Reveal({
  campaign,
  target,
  name,
}: {
  campaign: string
  target: string
  name: string
}) {
  const [grant, setGrant] = useState<Grant | null>(null)
  const [ready, setReady] = useState(false)
  const [alias, setAlias] = useState('')
  const [naming, setNaming] = useState(false)
  const [failed, setFailed] = useState('')
  // WHAT THE TABLE KNOWS IS THE DM'S DECISION, so it is the DM's control. A
  // player was being shown "your table knows about this — take it back", which
  // is the one sentence on the screen that is not addressed to them.
  const runs = useRuns(campaign)

  const load = useCallback(() => {
    tableAPI
      .revealed(campaign)
      .then((r) => {
        setGrant(r.revealed.find((g) => g.id === target) ?? null)
        setReady(true)
      })
      // A PLAYER GETS NO CONTROL AT ALL, and a failure here is how this
      // component learns that: the route is the DM's. Not an error banner --
      // just nothing, which is the correct amount of interface.
      .catch(() => setReady(false))
  }, [campaign, target])

  useEffect(load, [load])

  if (!ready || runs !== true) return null

  const act = (call: Promise<unknown>) =>
    call
      .then(() => {
        setNaming(false)
        setAlias('')
        load()
      })
      .catch((error) => setFailed(String(error).replace(/^Error:\s*/, '')))

  return (
    <div className="flex flex-col gap-1">
      {/* STACKED, NOT A ROW. This sits in the section reader's narrow rail as
          well as under a profile heading, and a horizontal row wrapped "tell
          them" onto two lines mid-phrase. */}
      <div className="flex flex-col items-start gap-2">
        <span className="text-meta text-ink-faint">
          {grant
            ? grant.as_name
              ? `Your table knows this as “${grant.as_name}”.`
              : 'Your table knows about this.'
            : 'Your table has not been told about this.'}
        </span>
        {grant ? (
          <button
            onClick={() => act(tableAPI.conceal(campaign, target))}
            className="label text-ink-dim hover:text-ink"
          >
            take it back
          </button>
        ) : (
          <div className="flex flex-col items-start gap-1">
            <button
              onClick={() => act(tableAPI.tellTable(campaign, target))}
              // AN ACTION, NOT A SELECTION. `CHROME.selected` is the grammar
              // for the row you are on; on an unpressed button it reads as a
              // toggle that is already on.
              className={`rounded-md px-3 py-1 text-ui ${CHROME.primary}`}
            >
              tell them
            </button>
            <button
              onClick={() => setNaming((was) => !was)}
              className="text-meta text-ink-faint hover:text-ink-dim"
            >
              under another name
            </button>
          </div>
        )}
      </div>

      {naming && (
        <div className="flex gap-2">
          <input
            autoFocus
            value={alias}
            onChange={(e) => setAlias(e.target.value)}
            onKeyDown={(e) =>
              e.key === 'Enter' &&
              alias.trim() &&
              act(tableAPI.tellTable(campaign, target, alias.trim()))
            }
            // How a party actually meets somebody: the coachman for three
            // sessions before Strahd.
            placeholder={`what they call ${name}`}
            className={`min-w-0 flex-1 rounded-md bg-surface px-2 py-0.5 text-label text-ink`}
          />
          <button
            onClick={() => alias.trim() && act(tableAPI.tellTable(campaign, target, alias.trim()))}
            className={`shrink-0 rounded-md px-2 py-1 text-ui ${CHROME.selected}`}
          >
            tell them that
          </button>
        </div>
      )}

      {grant && (
        <p className="text-meta leading-tight text-ink-faint">
          Taking it back hides it from here on. It does not unsay it.
        </p>
      )}

      {failed && <p className="text-label text-ink-dim">⚠ {failed}</p>}
    </div>
  )
}
