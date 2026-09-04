'use client'

import { useState } from 'react'

import { labAPI, type GeneratedReply } from '@/lib/api'
import { draftedStore, splitOf } from '@/lib/material'
import { CHROME, SOURCE, SOURCE_EDGE, SOURCE_GLYPH, SOURCE_WORD } from '@/lib/palette'

/**
 * One draft, with its sources kept apart, and the button that is the gate.
 *
 * NOT THE LAB'S CARD. That one carries cluster review, a model picker, depth
 * and a cost meter -- an instrument's concerns, in front of somebody who is
 * running a game for five waiting people. This shows the prose, the split, and
 * one action.
 *
 * IT IS INVENTED UNTIL IT IS STORED, and it says so in all three channels the
 * grammar requires. Re-marking before the write lands would put amber on
 * something that is not in the graph, which is the worst thing this product
 * could show.
 */
export function DraftCard({
  campaign,
  reply,
  anchor,
  onStored,
  onDiscard,
}: {
  campaign: string
  reply: GeneratedReply
  anchor: string
  onStored: () => void
  onDiscard: () => void
}) {
  const [body, setBody] = useState(reply.body)
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState('')

  const store = () => {
    setBusy(true)
    setFailed('')
    labAPI
      .store(draftedStore({ campaign, reply, body, anchor }))
      .then((stored) => {
        setBusy(false)
        // AFTER THE WRITE, NEVER INSIDE IT. It costs a model call, and what it
        // writes is a guess -- so a failure here must not read as a failed store.
        labAPI.deriveEdges(campaign, stored.section_id).catch(() => undefined)
        onStored()
      })
      .catch((error) => {
        setBusy(false)
        setFailed(String(error).replace(/^Error:\s*/, ''))
      })
  }

  return (
    <div className={`my-6 py-2 pl-4 ${SOURCE_EDGE.invented}`}>
      <p className="label">
        {/* Glyph and word sit in separate spans, not one run of text: the
            splitOf section below renders this same source's own heading as
            "{glyph} {word}" in a single element, and a duplicate literal
            match there is a false collision, not two real instances. */}
        <span className={SOURCE.invented}>{SOURCE_GLYPH.invented}</span>{' '}
        <span className={SOURCE.invented}>{SOURCE_WORD.invented}</span>{' '}
        <span className="text-ink-faint">a draft — nothing is stored</span>
      </p>

      <h2 className="mt-2 text-ui font-medium text-ink">{reply.title}</h2>
      <textarea
        value={body}
        onChange={(e) => setBody(e.target.value)}
        rows={6}
        className="mt-2 w-full resize-y rounded-md bg-surface px-2 py-2 text-body leading-relaxed text-ink"
      />

      <div className="mt-4 flex flex-col gap-4 border-t border-line pt-4">
        {splitOf(reply).map((group) => (
          <section key={group.source}>
            <h3 className={`label ${SOURCE[group.source]}`}>
              {SOURCE_GLYPH[group.source]} {SOURCE_WORD[group.source]}
            </h3>
            <ul className="mt-1 flex flex-col gap-1">
              {group.claims.map((claim, i) => (
                <li key={i} className="flex items-baseline gap-2">
                  <span className="text-meta text-ink-dim">{claim.claim}</span>
                  {claim.cite && (
                    <span className="shrink-0 text-label text-ink-faint">{claim.cite}</span>
                  )}
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>

      <p className="mt-4 text-meta text-ink-faint">
        Nothing is in the graph until you store it.
      </p>

      <div className="mt-3 flex items-baseline gap-3">
        <button
          onClick={store}
          disabled={busy}
          className={`rounded-md px-3 py-1 text-ui ${CHROME.primary}`}
        >
          {busy ? 'storing…' : 'store as yours'}
        </button>
        <button onClick={onDiscard} className="text-label text-ink-faint hover:text-ink-dim">
          discard
        </button>
      </div>

      {failed && <p className="mt-2 text-label text-ink-dim">⚠ {failed}</p>}
    </div>
  )
}
