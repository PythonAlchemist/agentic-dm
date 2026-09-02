'use client'

import { useCallback, useEffect, useState } from 'react'

import { tableAPI, type Sitting, type Whoami } from '@/lib/api'
import { CHROME } from '@/lib/palette'

/**
 * When the table can actually sit down.
 *
 * SILENCE IS DRAWN, NOT SUMMED AWAY. Every other scheduling tool shows one
 * availability number, which makes "two said no" and "two have not looked at
 * their phone" the same picture -- and those lead to opposite decisions. The
 * bar has three segments and an unfilled remainder, and the remainder is the
 * point.
 *
 * NO HUES. `palette.ts` reserves every one of them for a SOURCE, and a
 * scheduling answer is not a source. Yes, no and maybe are three steps of
 * contrast, which is legible without borrowing a meaning.
 *
 * A PLAYER ANSWERS FOR THEMSELVES. The buttons post no name; the server reads
 * the seat. A DM looking at this screen sees the answers and can propose or
 * withdraw an evening, which is the asymmetry that actually exists at a table.
 */
export function Sittings({ campaign, who }: { campaign: string; who: Whoami | null }) {
  const [sittings, setSittings] = useState<Sitting[]>([])
  const [on, setOn] = useState('')
  const [failed, setFailed] = useState('')

  const load = useCallback(() => {
    tableAPI
      .sittings(campaign)
      .then((r) => setSittings(r.sittings))
      .catch(() => undefined)
  }, [campaign])

  useEffect(load, [load])

  // AN UNIDENTIFIED READER IS THE DM HERE, matching `player.audience` and
  // `roles.role_of`: `ACCESS_TOKENS` unset is the documented local case -- one
  // person at the machine, running their own game. Reading only `role === 'dm'`
  // left the local DM with no way to propose an evening at their own table.
  const isDM = who !== null && (who.role === 'dm' || !who.identified)

  const propose = () => {
    if (!on.trim()) return
    tableAPI
      .propose(campaign, on.trim())
      .then(() => {
        setOn('')
        load()
      })
      .catch((error) => setFailed(String(error).replace(/^Error:\s*/, '')))
  }

  const say = (sitting: string, answer: 'yes' | 'no' | 'maybe') => {
    tableAPI
      .answerSitting(campaign, sitting, answer)
      .then(load)
      .catch((error) => setFailed(String(error).replace(/^Error:\s*/, '')))
  }

  return (
    <section>
      <h2 className="text-[11px] uppercase tracking-widest text-neutral-600">
        When we can play
      </h2>

      {isDM && (
        <div className="mt-2 flex gap-2">
          <input
            value={on}
            onChange={(e) => setOn(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && propose()}
            // NOT A DATE PICKER. "Thursday after next" means something to the
            // six people in the group, and a picker would refuse the shorthand
            // they actually use while adding no correctness anybody wanted.
            placeholder="another evening"
            className={`min-w-0 flex-1 rounded border border-neutral-800 bg-neutral-950 px-2 py-1 text-sm text-neutral-200 outline-none ${CHROME.focus}`}
          />
          <button
            onClick={propose}
            className={`shrink-0 rounded px-2 py-1 text-[11px] ${CHROME.primary}`}
          >
            propose
          </button>
        </div>
      )}

      <ul className="mt-3 flex flex-col gap-3">
        {sittings.map((sitting) => (
          <li key={sitting.id}>
            <div className="flex items-baseline gap-2">
              <span className="text-sm text-neutral-200">{sitting.on}</span>
              <span className="text-[11px] tabular-nums text-neutral-600">
                {sitting.yes.length} of {sitting.seated}
              </span>
              {isDM && (
                <button
                  onClick={() => tableAPI.withdraw(campaign, sitting.id).then(load)}
                  className="ml-auto text-[11px] text-neutral-700 hover:text-neutral-500"
                >
                  withdraw
                </button>
              )}
            </div>

            <Bar sitting={sitting} />

            {sitting.unanswered > 0 && (
              <p className="mt-1 text-[11px] text-neutral-600">
                {sitting.unanswered} {sitting.unanswered === 1 ? 'has' : 'have'} not
                said either way
              </p>
            )}

            {/* SOMEBODY HAS TO BE IDENTIFIED TO ANSWER, because an answer is a claim
          by a person. On an open deployment there is nobody to record it
          against, so the buttons are absent rather than anonymous. */}
      {who?.identified && (
              <div className="mt-1 flex gap-1">
                {(['yes', 'maybe', 'no'] as const).map((answer) => (
                  <button
                    key={answer}
                    onClick={() => say(sitting.id, answer)}
                    aria-pressed={sitting[answer].includes(who.reader)}
                    className={`rounded px-1.5 py-0.5 text-[11px] ${
                      sitting[answer].includes(who.reader)
                        ? CHROME.selected
                        : 'text-neutral-600 hover:text-neutral-400'
                    }`}
                  >
                    {answer}
                  </button>
                ))}
              </div>
            )}
          </li>
        ))}
        {sittings.length === 0 && (
          <li className="text-sm text-neutral-600">No evenings on the table.</li>
        )}
      </ul>

      {failed && <p className="mt-2 text-[11px] text-neutral-400">⚠ {failed}</p>}
    </section>
  )
}

/** Three segments and an unfilled remainder. The remainder is nobody's answer,
 *  and it stays visible. */
function Bar({ sitting }: { sitting: Sitting }) {
  const total = Math.max(sitting.seated, 1)
  const width = (n: number) => `${(n / total) * 100}%`
  return (
    <div className="mt-1 flex h-1.5 w-full overflow-hidden rounded bg-neutral-900">
      <span style={{ width: width(sitting.yes.length) }} className="bg-neutral-200" />
      <span style={{ width: width(sitting.maybe.length) }} className="bg-neutral-500" />
      <span style={{ width: width(sitting.no.length) }} className="bg-neutral-700" />
    </div>
  )
}
