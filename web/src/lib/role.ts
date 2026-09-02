'use client'

import { useEffect, useState } from 'react'

import { tableAPI } from '@/lib/api'

/**
 * Which chair this browser is sitting in.
 *
 * ASKED ONCE PER COMPONENT THAT NEEDS IT, rather than threaded down through
 * props. The alternative is every screen fetching the role and handing it to
 * every control, and the one that forgot would show a player the DM's buttons
 * -- which is exactly the bug this exists to fix.
 *
 * `null` UNTIL KNOWN, AND THAT IS NOT "PLAYER". A control that renders while
 * the answer is in flight and disappears a moment later is worse than one that
 * arrives late, so callers gate on `runs === true` and get nothing until the
 * answer is in.
 *
 * IT DECIDES WHAT IS OFFERED, NEVER WHAT IS ALLOWED. Every write behind these
 * controls is refused server-side for a player regardless; this is about not
 * putting a button in front of somebody it will only ever say no to.
 */
export function useRuns(campaign: string): boolean | null {
  const [runs, setRuns] = useState<boolean | null>(null)

  useEffect(() => {
    if (!campaign) return
    tableAPI
      .whoami(campaign)
      // AN UNIDENTIFIED READER RUNS THE TABLE -- `ACCESS_TOKENS` unset is one
      // person at their own machine. A failed call falls the other way, so a
      // broken gate hides controls rather than offering them.
      .then((who) => setRuns(who.identified ? who.role === 'dm' : true))
      .catch(() => setRuns(false))
  }, [campaign])

  return runs
}
