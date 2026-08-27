'use client'

import { useEffect, useState } from 'react'
import type { EntityRead, SectionRead } from '@/lib/api'
import { labAPI } from '@/lib/api'
import { PaneHeader } from './ui'

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
  onJump,
  onFocus,
}: {
  sectionId: string | null
  campaign: string | null
  onClose: () => void
  onEdited?: () => void
  /** Follow a name to another section, without closing the drawer. */
  onJump: (sectionId: string) => void
  /** What the DM is now looking at, so the chat can lean on it. FOLLOWS THE
   *  ENTITY: clicking a name in the prose moves the focus onto that name,
   *  because "give me a crew for this" then means his crew. */
  onFocus: (focus: { id: string; label: string }) => void
}) {
  const [section, setSection] = useState<SectionRead | null>(null)
  const [failed, setFailed] = useState('')
  //: What `section` is ABOUT. Compared against the requested id rather than
  //  clearing state synchronously in the effect, which cascades renders --
  //  and which would flash the previous section's prose under the new
  //  heading for a frame, the one thing a provenance-first panel must not do.
  const [loadedFor, setLoadedFor] = useState<string | null>(null)
  //: An entity the reader clicked a NAME to reach. Shown over the section
  //  rather than instead of it: they were reading something, and a name is a
  //  glance away from it and back — so the section stays underneath and the
  //  back arrow returns to exactly where they were.
  const [entity, setEntity] = useState<EntityRead | null>(null)

  const openEntity = async (entityId: string) => {
    try {
      const found = await labAPI.entity(entityId, campaign)
      setEntity(found)
      onFocus({ id: found.entity_id, label: found.name })
    } catch (error) {
      setFailed(error instanceof Error ? error.message : String(error))
    }
  }
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
        setEntity(null)
        onFocus({ id: found.section_id, label: found.heading })
        setFailed('')
      })
      .catch((error) => {
        if (!cancelled) setFailed(error instanceof Error ? error.message : String(error))
      })
    return () => {
      cancelled = true
    }
  }, [sectionId, campaign, onFocus])

  // Escape closes it, because a drawer that traps you is worse than no
  // drawer. It backs out of EDITING first rather than out of the drawer: a
  // reflex keystroke should not throw away a paragraph somebody just typed.
  useEffect(() => {
    if (!sectionId) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      if (draft !== null) setDraft(null)
      else if (entity) setEntity(null)
      else onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [sectionId, onClose, draft, entity])

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

  // Only shown once it is the CURRENT section's content.
  const shown = loadedFor === sectionId ? section : null
  const yours = shown?.plane === 'campaign'

  // A PANE NOW, NOT A DRAWER. It was an overlay because the screen had one
  // column to spare; with three it is the middle one, and reading no longer
  // covers up the list you found it in or the conversation about it.
  if (!sectionId) {
    return (
      <div className="flex h-full items-center justify-center rounded-lg border border-neutral-800/60 bg-neutral-900/20">
        <p className="max-w-xs px-6 text-center text-xs leading-relaxed text-neutral-600">
          Pick a section or something you have made. It opens here, and the
          chat leans on whatever is open.
        </p>
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-lg border border-neutral-800 bg-neutral-900/20">
      <PaneHeader title="Viewer" subtitle={shown?.heading ?? 'Loading…'}>
            {/* ONLY YOUR OWN. The book is not editable and the server refuses
                it either way; offering the button would be a lie the backend
                then has to tell you about. */}
            {yours && draft === null && (
              <button
                onClick={() => setDraft(shown?.text ?? '')}
                className="text-neutral-500 hover:text-neutral-200"
              >
                edit
              </button>
            )}
        <button
          onClick={onClose}
          className="text-neutral-600 hover:text-neutral-300"
        >
          close
        </button>
      </PaneHeader>

      <div className="min-h-0 flex-1 overflow-y-auto p-5">
        <h2
          className={`mb-2 text-base font-medium ${
            yours ? 'text-amber-200' : 'text-neutral-200'
          }`}
        >
          {shown?.heading ?? 'Loading…'}
        </h2>

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

        {entity && (
          <EntityCard
            entity={entity}
            onBack={() => setEntity(null)}
            onRead={(sectionId) => {
              setEntity(null)
              onJump(sectionId)
            }}
          />
        )}

        {shown && (
          <>
            {draft === null ? (
              <div className="whitespace-pre-wrap text-sm leading-relaxed text-neutral-200">
                <Named
                  text={forReading(shown.text, shown.heading)}
                  mentions={shown.mentions}
                  onOpen={openEntity}
                />
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
                  className="w-full rounded border border-neutral-800 bg-neutral-900/60 p-2 text-sm leading-relaxed outline-none focus:border-neutral-500"
                />
                <div className="mt-2 flex items-center gap-3 text-xs">
                  <button
                    onClick={save}
                    disabled={saving}
                    className="rounded-md bg-neutral-200 px-3 py-1.5 font-medium text-neutral-950 transition-colors hover:bg-white disabled:opacity-40"
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
              <p className="mt-3 text-xs text-neutral-400">
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
                  tone="text-rose-300/80"
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

/**
 * The prose, with the names the GRAPH says are in it made clickable.
 *
 * WHICH names is not decided here. The mention triangle already records that
 * this section refers to this entity, so the surfaces arrive with the section
 * and this only has to locate them; a reader scanning for names of its own
 * would disagree with retrieval the first time two things shared a spelling,
 * and would light up every "guard" in the book.
 *
 * MATCHED IN THE RENDERED TEXT, not by stored offset. `forReading` drops the
 * H1 and rewrites image lines, so an offset into the raw body points somewhere
 * else by the time a person sees it. Searching for a surface the graph has
 * already vouched for is exact enough: the only thing being guessed is WHERE a
 * confirmed name sits, and a surface that fell inside a dropped line simply
 * is not found, which is the right answer.
 *
 * LONGEST FIRST, so `Captain Saltmarrow` wins over `Saltmarrow` and the短
 * match cannot eat the start of the long one.
 */
function Named({
  text,
  mentions,
  onOpen,
}: {
  text: string
  mentions: SectionRead['mentions']
  onOpen: (entityId: string) => void
}) {
  if (!text) return <span className="text-neutral-600">No prose.</span>
  const surfaces = [...mentions]
    .filter((m) => m.surface)
    .sort((a, b) => b.surface.length - a.surface.length)
  if (surfaces.length === 0) return <>{text}</>

  const pattern = new RegExp(
    `(${surfaces.map((m) => escapeRegExp(m.surface)).join('|')})`,
    'g',
  )
  const bySurface = new Map(surfaces.map((m) => [m.surface, m]))

  return (
    <>
      {text.split(pattern).map((piece, index) => {
        const hit = bySurface.get(piece)
        if (!hit) return <span key={index}>{piece}</span>
        return (
          <button
            key={index}
            onClick={() => onOpen(hit.entity_id)}
            title={`${hit.name}${hit.kind ? ` · ${hit.kind}` : ''}`}
            className={`underline decoration-dotted underline-offset-2 hover:decoration-solid ${
              hit.plane === 'campaign' ? 'text-amber-200/90' : 'text-neutral-100'
            }`}
          >
            {piece}
          </button>
        )
      })}
    </>
  )
}

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
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

/**
 * What the graph holds about a name somebody clicked.
 *
 * NOT PROSE, and it says so. Most entities have no write-up — a canon place
 * exists because the book named it, and the honest answer is the record: what
 * it is, whose it is, and every section that names it. That last list is the
 * useful half: a name on its own is a dictionary entry, and the sections are
 * what let a DM follow a thread through the book and their own material at
 * once.
 */
function EntityCard({
  entity,
  onBack,
  onRead,
}: {
  entity: EntityRead
  onBack: () => void
  onRead: (sectionId: string) => void
}) {
  const yours = entity.plane === 'campaign'
  return (
    <div className="mb-5 rounded-md border border-neutral-800 bg-neutral-900/60 p-4">
      <div className="mb-2 flex items-baseline justify-between gap-4">
        <h3
          className={`text-sm font-medium ${
            yours ? 'text-amber-200' : 'text-neutral-100'
          }`}
        >
          {entity.name}
          {entity.kind && (
            <span className="ml-2 text-[10px] uppercase tracking-wide text-neutral-600">
              {entity.kind}
            </span>
          )}
        </h3>
        <button
          onClick={onBack}
          className="shrink-0 text-xs text-neutral-500 hover:text-neutral-300"
        >
          back (esc)
        </button>
      </div>

      <p className="text-xs text-neutral-500">
        {yours ? (
          <>
            <span className="text-amber-400">Yours.</span> Written for this
            campaign.
          </>
        ) : (
          <>
            <span className="text-emerald-400/80">The book.</span>{' '}
            {entity.labels.join(' · ').toLowerCase() || 'named in the text'}
          </>
        )}
        {entity.role && <> — {entity.role}</>}
      </p>

      {entity.invented.length > 0 && (
        <ul className="mt-2 space-y-0.5 text-xs text-rose-300/80">
          {entity.invented.map((line, index) => (
            <li key={index}>· {line}</li>
          ))}
        </ul>
      )}

      {entity.own_section && (
        <button
          onClick={() => onRead(entity.own_section!)}
          className="mt-3 text-xs text-neutral-400 underline hover:text-neutral-200"
        >
          read its write-up
        </button>
      )}

      {/* WHAT EACH PLACE SAYS, not just that it says something. A list of
          headings tells a DM where to go looking; the sentences tell them what
          the thing IS, and they were one hop away the whole time.

          THE BOOK FIRST. Canon is the part they cannot change, and a DM
          checking what is established wants that before what they invented on
          top of it. */}
      {entity.named_in.length > 0 && (
        <div className="mt-3 space-y-3 border-t border-neutral-800 pt-2">
          {[...entity.named_in]
            .sort((a, b) => Number(a.plane === 'campaign') - Number(b.plane === 'campaign'))
            .map((where) => (
              <div key={where.section_id}>
                <button
                  onClick={() => onRead(where.section_id)}
                  className={`text-[11px] uppercase tracking-wide hover:underline ${
                    where.plane === 'campaign'
                      ? 'text-amber-300/70'
                      : 'text-emerald-300/60'
                  }`}
                >
                  {where.heading}
                </button>
                <ul className="mt-0.5 space-y-0.5">
                  {where.says.map((line, index) => (
                    <li key={index} className="text-xs leading-relaxed text-neutral-300">
                      {line}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
        </div>
      )}
    </div>
  )
}
