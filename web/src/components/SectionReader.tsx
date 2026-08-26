'use client'

import { useEffect, useState } from 'react'
import type { SectionRead } from '@/lib/api'
import { labAPI } from '@/lib/api'

/**
 * The prose behind a heading, for a person to read at a table.
 *
 * THE THING A DM ACTUALLY DOES. The running order listed 547 headings and the
 * material panel listed a cast, and clicking either did nothing -- so "show me
 * the scene I wrote" meant asking the chat and hoping retrieval surfaced it,
 * for text sitting one query away.
 *
 * A DRAWER RATHER THAN A ROUTE. Reading a section is a glance mid-conversation,
 * not a place to navigate to and come back from, and the chat it interrupts is
 * still on screen behind it.
 */
export function SectionReader({
  sectionId,
  campaign,
  onClose,
  onEdited,
}: {
  sectionId: string | null
  campaign: string | null
  onClose: () => void
  onEdited?: () => void
}) {
  const [section, setSection] = useState<SectionRead | null>(null)
  const [failed, setFailed] = useState('')
  //: What `section` is ABOUT. Compared against the requested id rather than
  //  clearing state synchronously in the effect, which cascades renders --
  //  and which would flash the previous section's prose under the new
  //  heading for a frame, the one thing a provenance-first panel must not do.
  const [loadedFor, setLoadedFor] = useState<string | null>(null)
  //: The draft, while a DM is rewriting. `null` means they are reading --
  //  which is the state to be in by default, because this drawer is opened
  //  mid-session to look something up far more often than to change it.
  const [draft, setDraft] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!sectionId) return
    let cancelled = false
    labAPI
      .section(sectionId, campaign)
      .then((found) => {
        if (cancelled) return
        setSection(found)
        setLoadedFor(sectionId)
        setDraft(null)
        setFailed('')
      })
      .catch((error) => {
        if (!cancelled) setFailed(error instanceof Error ? error.message : String(error))
      })
    return () => {
      cancelled = true
    }
  }, [sectionId, campaign])

  // Escape closes it, because a drawer that traps you is worse than no
  // drawer. It backs out of EDITING first rather than out of the drawer: a
  // reflex keystroke should not throw away a paragraph somebody just typed.
  useEffect(() => {
    if (!sectionId) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      if (draft !== null) setDraft(null)
      else onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [sectionId, onClose, draft])

  const save = async () => {
    if (draft === null || !campaign || !sectionId || saving) return
    setSaving(true)
    setFailed('')
    try {
      await labAPI.editSection(campaign, sectionId, draft)
      // Re-read rather than patching state locally: `edited` is DERIVED on the
      // server from whether the text still matches what the model wrote, and
      // guessing at it here is how the two come to disagree.
      setSection(await labAPI.section(sectionId, campaign))
      setDraft(null)
      onEdited?.()
    } catch (error) {
      setFailed(error instanceof Error ? error.message : String(error))
    } finally {
      setSaving(false)
    }
  }

  if (!sectionId) return null
  // Only shown once it is the CURRENT section's content.
  const shown = loadedFor === sectionId ? section : null
  const yours = shown?.plane === 'campaign'

  return (
    <div
      className="fixed inset-0 z-40 flex justify-end bg-black/50"
      // A click on the backdrop does not discard a rewrite either, for the
      // reason Escape does not.
      onClick={() => draft === null && onClose()}
    >
      <div
        className="h-full w-full max-w-2xl overflow-y-auto border-l border-neutral-800 bg-neutral-950 p-5"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="mb-3 flex items-baseline justify-between gap-4">
          <h2
            className={`text-base font-medium ${
              yours ? 'text-amber-200' : 'text-neutral-200'
            }`}
          >
            {shown?.heading ?? 'Loading…'}
          </h2>
          <div className="flex shrink-0 items-baseline gap-3 text-xs">
            {/* ONLY YOUR OWN. The book is not editable and the server refuses
                it either way; offering the button would be a lie the backend
                then has to tell you about. */}
            {yours && draft === null && (
              <button
                onClick={() => setDraft(shown?.text ?? '')}
                className="text-neutral-500 hover:text-amber-300"
              >
                edit
              </button>
            )}
            <button
              onClick={onClose}
              className="text-neutral-500 hover:text-neutral-300"
            >
              close (esc)
            </button>
          </div>
        </div>

        {/* WHOSE WORD IT IS, said before the prose rather than after it. The
            whole project rests on a DM being able to tell, and a drawer that
            showed the book and their own invention in the same typeface would
            undo that at the moment it matters most. */}
        <p className="mb-4 text-xs text-neutral-500">
          {yours ? (
            <>
              <span className="text-amber-400">Yours.</span> Written for this
              campaign — the published book does not say this.
            </>
          ) : (
            <>
              <span className="text-emerald-400/80">The book.</span>{' '}
              {shown?.chapter}
            </>
          )}
        </p>

        {failed && <p className="text-sm text-red-400">{failed}</p>}

        {shown && (
          <>
            {draft === null ? (
              <div className="whitespace-pre-wrap text-sm leading-relaxed text-neutral-200">
                {forReading(shown.text, shown.heading) || (
                  <span className="text-neutral-600">No prose.</span>
                )}
              </div>
            ) : (
              <div>
                {/* THE RAW STORED TEXT, not what `forReading` renders. Editing
                    a tidied copy would save the tidying over the original and
                    quietly lose whatever it dropped. */}
                <textarea
                  value={draft}
                  onChange={(event) => setDraft(event.target.value)}
                  rows={16}
                  className="w-full rounded border border-neutral-800 bg-neutral-900/60 p-2 text-sm leading-relaxed outline-none focus:border-amber-600/60"
                />
                <div className="mt-2 flex items-center gap-3 text-xs">
                  <button
                    onClick={save}
                    disabled={saving}
                    className="rounded-md bg-amber-600/90 px-3 py-1.5 font-medium text-neutral-950 hover:bg-amber-500 disabled:opacity-40"
                  >
                    {saving ? 'Saving…' : 'Save'}
                  </button>
                  <button
                    onClick={() => setDraft(null)}
                    className="text-neutral-500 hover:text-neutral-300"
                  >
                    cancel (esc)
                  </button>
                  <span className="text-neutral-600">
                    The citations below were made about the original and are
                    not re-checked.
                  </span>
                </div>
              </div>
            )}

            {shown.edited && (
              <p className="mt-3 text-xs text-amber-500/80">
                You edited this after it was drafted. The provenance below
                describes the original text and was not re-checked.
              </p>
            )}

            {(shown.from_canon.length > 0 ||
              shown.from_yours.length > 0 ||
              shown.from_context.length > 0 ||
              shown.invented.length > 0) && (
              <div className="mt-5 space-y-3 border-t border-neutral-800 pt-4 text-xs">
                <Split
                  label="From the book"
                  items={shown.from_canon.map((c) => `${c.claim} ${c.cite}`)}
                  tone="text-emerald-300/80"
                />
                {/* BETWEEN the book and the conversation, because that is
                    where it sits: sourced, checkable, and not canon. A model
                    shown one numbered list of passages files a campaign
                    passage under the book, so this is derived from the cite's
                    plane rather than taken from what the model called it. */}
                <Split
                  label="From your own material"
                  items={shown.from_yours.map((c) => `${c.claim} ${c.cite}`)}
                  tone="text-amber-200/80"
                />
                <Split
                  label="From the table"
                  items={shown.from_context}
                  tone="text-sky-300/80"
                />
                <Split
                  label="Invented"
                  items={shown.invented}
                  tone="text-amber-300/80"
                />
              </div>
            )}

            {shown.cites.length > 0 && (
              <p className="mt-4 border-t border-neutral-800 pt-3 text-xs text-neutral-600">
                Built on: {shown.cites.join(', ')}
              </p>
            )}
          </>
        )}
      </div>
    </div>
  )
}

/**
 * The stored text as a person reads it, not as the harvester stored it.
 *
 * A section's body is the markdown the book was harvested from, and two parts
 * of it are noise HERE rather than in the graph: the H1 repeats the heading
 * printed two lines above it, and an image is a D&D Beyond URL this app does
 * not display. Both stay in the graph -- retrieval and citation want the text
 * exactly as harvested. This is a rendering decision, so it lives at the
 * rendering edge.
 */
function forReading(text: string, heading: string) {
  const lines = text.split('\n')
  // Only a FIRST heading, and only when it says what the drawer already says.
  // A mid-section H1 is structure the reader should keep.
  const first = lines.findIndex((line) => line.trim() !== '')
  if (first >= 0 && lines[first].replace(/^#+\s*/, '').trim() === heading.trim()) {
    lines.splice(0, first + 1)
  }
  return lines
    .map((line) => {
      // The alt text the harvester carries is the literal word "image", so
      // there is nothing to repeat -- the book's caption is the next line.
      return /^!\[.*?\]\(.*?\)\s*$/.test(line) ? '[illustration]' : line
    })
    .join('\n')
    .trim()
}

function Split({
  label,
  items,
  tone,
}: {
  label: string
  items: string[]
  tone: string
}) {
  if (items.length === 0) return null
  return (
    <div>
      <div className={`font-medium ${tone}`}>
        {label} <span className="text-neutral-600">({items.length})</span>
      </div>
      <ul className="mt-1 space-y-0.5 text-neutral-400">
        {items.map((item, index) => (
          <li key={index}>· {item}</li>
        ))}
      </ul>
    </div>
  )
}
