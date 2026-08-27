'use client'

import { useEffect, useState } from 'react'

/**
 * One flip that decides whether the tool explains itself.
 *
 * THE DEBUG TIER ALREADY EXISTED AND WAS PERMANENTLY ON. Every chat turn
 * appended a token meter and a retrieval report, so after ten turns a third of
 * the transcript was instrumentation about questions the DM had moved past --
 * bench equipment stitched into the surface being played.
 *
 * WHERE THE LINE IS, and it is not "advanced vs basic". Anything that changes
 * whether a DM should BELIEVE a sentence is trust and is never hidden: the
 * provenance splits, the citations, the per-passage keyword-match flag, the
 * "Yours / The book" banner, an edited-so-not-re-checked warning, a collision,
 * a cost marked unverified, and `miss_reason` -- an answer that retrieved
 * nothing is a trust event, not a diagnostic. Anything that explains HOW the
 * sentence was produced is debug: token counts, anchors, search terms, dropped
 * counts, depth knobs, eviction ages.
 *
 * PERSISTED, because the two audiences are the same person on different days.
 * Flipped on for a dev afternoon it stays on; off at the table it stays off.
 */
const KEY = 'agent-lab:debug'

export function useDebug(): [boolean, (next: boolean) => void] {
  // LAZY INITIALISER, not an effect that sets state on mount. Reading storage
  // during render breaks hydration; reading it in an effect and calling
  // setState cascades a second render on every page load. `useState(fn)` runs
  // once, and the `window` guard is what makes it safe on the server.
  const [on, setOn] = useState(
    () => typeof window !== 'undefined' && window.localStorage.getItem(KEY) === '1',
  )

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      // A chord rather than only a switch: the whole value of this tier is
      // "one flip and everything explains itself", and reaching for a control
      // is already more friction than the question deserves.
      if (event.key === '.' && (event.metaKey || event.ctrlKey)) {
        event.preventDefault()
        setOn((prior) => {
          window.localStorage.setItem(KEY, prior ? '0' : '1')
          return !prior
        })
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  return [
    on,
    (next: boolean) => {
      window.localStorage.setItem(KEY, next ? '1' : '0')
      setOn(next)
    },
  ]
}
