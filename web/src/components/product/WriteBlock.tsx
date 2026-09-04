'use client'

import { useState } from 'react'

import { labAPI } from '@/lib/api'
import { handWrittenStore } from '@/lib/material'
import { CHROME, SOURCE, SOURCE_EDGE, SOURCE_GLYPH, SOURCE_WORD } from '@/lib/palette'

/**
 * A scene the DM writes, in the column, under the book's own words.
 *
 * NOT A MODAL, AND THAT IS THE POINT. §6 gives the book a serif and the DM's
 * material the app's face, so writing here shows the difference between the
 * two IN THE TYPE while it is being written. A dialog would cover the one
 * thing worth seeing.
 */
export function WriteBlock({
  campaign,
  anchor,
  onStored,
  onDiscard,
}: {
  campaign: string
  anchor: string
  onStored: (title: string, body: string) => void
  onDiscard: () => void
}) {
  const [title, setTitle] = useState('')
  const [body, setBody] = useState('')
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState('')

  const store = () => {
    setBusy(true)
    setFailed('')
    labAPI
      .store(handWrittenStore({ campaign, title, body, anchor }))
      .then((stored) => {
        setBusy(false)
        // AFTER THE WRITE, NEVER INSIDE IT, and on this path too -- a scene a
        // person typed names things just as a drafted one does. It costs a
        // model call and writes a guess, so a failure here must not read as a
        // failed store.
        labAPI.deriveEdges(campaign, stored.section_id).catch(() => undefined)
        onStored(title, body)
      })
      .catch((error) => {
        setBusy(false)
        setFailed(String(error).replace(/^Error:\s*/, ''))
      })
  }

  return (
    <div className={`my-6 py-2 pl-4 ${SOURCE_EDGE.yours}`}>
      <p className="label">
        <span className={SOURCE.yours}>
          {SOURCE_GLYPH.yours} {SOURCE_WORD.yours}
        </span>{' '}
        <span className="text-ink-faint">not stored yet</span>
      </p>

      <input
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="what happens here?"
        className="mt-3 w-full rounded-md bg-surface px-2 py-1.5 text-ui text-ink"
      />
      <textarea
        value={body}
        onChange={(e) => setBody(e.target.value)}
        rows={6}
        placeholder="your words"
        className="mt-2 w-full resize-y rounded-md bg-surface px-2 py-2 text-body leading-relaxed text-ink"
      />

      <div className="mt-3 flex items-baseline gap-3">
        <button
          onClick={store}
          disabled={busy || !body.trim()}
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
