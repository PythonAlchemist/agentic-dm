'use client'

import { useState } from 'react'
import { auth } from '@/lib/api'

/**
 * The login wall.
 *
 * WHY IT EXISTS: the graph holds the prose of two published books. This
 * deployment is shared with people the DM has confirmed own them, and each of
 * those people was handed a token of their own -- not a shared password, so
 * one can be revoked without disturbing the rest. `backend/api/auth.py` is
 * where the rule is actually enforced; this is only the door.
 *
 * IT SAYS WHAT IT IS. A bare password box on an unexplained page reads as
 * something to get past. Naming the reason -- these are books you have to own
 * -- makes the gate legible to the person meeting it, who is a friend at the
 * table rather than an intruder.
 */
export function Door({ onOpened }: { onOpened: () => void }) {
  const [token, setToken] = useState('')
  const [checking, setChecking] = useState(false)
  const [refused, setRefused] = useState(false)

  async function tryIt(event: React.FormEvent) {
    event.preventDefault()
    if (!token.trim() || checking) return
    setChecking(true)
    setRefused(false)
    auth.set(token)
    // ASKED OF THE API, NOT CHECKED HERE. The frontend has no list of who is
    // allowed and must not: a gate the client decides is a gate anyone can
    // walk through with the devtools open.
    const ok = await auth.check()
    setChecking(false)
    if (ok) {
      onOpened()
      return
    }
    auth.clear()
    setRefused(true)
  }

  return (
    <div className="flex h-full items-center justify-center p-8">
      <form onSubmit={tryIt} className="w-full max-w-sm">
        <h1 className="text-base font-medium text-neutral-200">Agent Lab</h1>
        <p className="mt-2 text-sm leading-relaxed text-neutral-500">
          This lab reads from the text of <em>Curse of Strahd</em> and{' '}
          <em>Keys from the Golden Vault</em>, so it is shared only with people
          who own them. Ask the DM for a reader token.
        </p>

        <input
          type="password"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          placeholder="reader token"
          autoFocus
          autoComplete="current-password"
          spellCheck={false}
          className="mt-5 w-full rounded border border-neutral-800 bg-neutral-900 px-3 py-2 font-mono text-sm text-neutral-200 placeholder:text-neutral-700 focus:border-neutral-600 focus:outline-none"
        />

        <button
          type="submit"
          disabled={!token.trim() || checking}
          className="mt-3 w-full rounded bg-neutral-800 px-3 py-2 text-sm text-neutral-200 hover:bg-neutral-700 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {checking ? 'checking…' : 'Open'}
        </button>

        {refused && (
          <p className="mt-3 text-sm text-red-400">
            That token was refused. If it used to work, it may have been
            revoked -- ask the DM for a new one.
          </p>
        )}
      </form>
    </div>
  )
}
