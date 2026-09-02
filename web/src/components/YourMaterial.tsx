'use client'

import { useCallback, useEffect, useState } from 'react'
import type { CampaignElement, GeneratedReply } from '@/lib/api'
import { labAPI } from '@/lib/api'
import { Card } from './ui'

/**
 * Everything this table has made, and which of it is still only a name.
 *
 * THE FRESH-SESSION ENTRY POINT. A conversation opened tomorrow holds no
 * subgraph and no history. The graph remembers, but a DM has no way to ask it
 * "what was I building" -- so this is that question, answered from the graph
 * rather than from anything the session carries.
 *
 * A cluster mints STUBS: a scene arrives with four names attached, each with a
 * role and no prose. Fleshing them out is work spread over sittings, so what
 * is still unwritten is the useful thing to show first.
 */
export function YourMaterial({
  campaign,
  refreshKey,
  onDraft,
  onRead,
}: {
  campaign: string | null
  refreshKey: number
  onDraft: (card: GeneratedReply) => void
  onRead: (sectionId: string) => void
}) {
  const [elements, setElements] = useState<CampaignElement[]>([])
  const [busy, setBusy] = useState('')
  const [failed, setFailed] = useState('')

  const load = useCallback(async () => {
    if (!campaign) return
    try {
      setElements((await labAPI.elements(campaign)).elements)
      setFailed('')
    } catch (error) {
      setFailed(error instanceof Error ? error.message : String(error))
    }
  }, [campaign])

  useEffect(() => {
    if (!campaign) return
    let cancelled = false
    labAPI
      .elements(campaign)
      .then((r) => {
        if (!cancelled) setElements(r.elements)
      })
      .catch((error) => {
        if (!cancelled) setFailed(error instanceof Error ? error.message : String(error))
      })
    return () => {
      cancelled = true
    }
  }, [campaign, refreshKey])

  const draft = async (element: CampaignElement) => {
    if (busy) return
    setBusy(element.entity_id)
    setFailed('')
    try {
      onDraft(await labAPI.draftExpansion(campaign!, element.entity_id))
      await load()
    } catch (error) {
      setFailed(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy('')
    }
  }

  if (!campaign) {
    return (
      <Card title="Your material">
        <p className="p-3 text-meta leading-relaxed text-ink-dim">
          Pick a table to see what it has made.
        </p>
      </Card>
    )
  }

  const stubs = elements.filter((e) => !e.own_section)
  const written = elements.filter((e) => e.own_section)

  return (
    <Card title="Your material">
      <p className="border-b border-line px-3 py-2 text-meta text-ink-dim">
        {elements.length} made · {stubs.length} still just a name
      </p>
      {failed && <p className="px-3 py-2 text-meta text-red-400">{failed}</p>}
      <div className="max-h-[22rem] overflow-y-auto p-1">
        {/* UNWRITTEN FIRST, because that is the work. A name with a role and
            no prose is a thing the DM meant to come back to. */}
        {stubs.map((element) => (
          <Row
            key={element.entity_id}
            element={element}
            busy={busy === element.entity_id}
            onDraft={() => draft(element)}
            onRead={onRead}
            campaign={campaign}
            onChanged={load}
          />
        ))}
        {written.length > 0 && (
          <p className="mt-2 border-t border-line px-2 pt-2 text-label uppercase tracking-wide text-ink-faint">
            written up
          </p>
        )}
        {written.map((element) => (
          <Row
            key={element.entity_id}
            element={element}
            busy={false}
            onRead={onRead}
            campaign={campaign}
            onChanged={load}
          />
        ))}
      </div>
    </Card>
  )
}

function Row({
  element,
  busy,
  onDraft,
  onRead,
  campaign,
  onChanged,
}: {
  element: CampaignElement
  busy: boolean
  onDraft?: () => void
  onRead: (sectionId: string) => void
  campaign: string
  onChanged: () => void
}) {
  //: The role, while it is being rewritten. `null` is reading, which is what
  //  this panel is for -- the edit is the occasional thing.
  const [draft, setDraft] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const save = async () => {
    if (draft === null || saving) return
    setSaving(true)
    try {
      await labAPI.setRole(campaign, element.entity_id, draft)
      setDraft(null)
      onChanged()
    } finally {
      setSaving(false)
    }
  }

  // Only something WITH prose opens. A stub has nothing to show, and a door
  // onto an empty room is worse than no door -- the "flesh out" beside it is
  // the action that stub actually offers.
  const readable = element.own_section
  return (
    <div className="group flex items-baseline gap-2 rounded-md px-2 py-1 hover:bg-overlay/40">
      {draft !== null ? (
        <input
          autoFocus
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onBlur={save}
          onKeyDown={(event) => {
            if (event.key === 'Enter') save()
            // ESCAPE ABANDONS, and it has to: this input sits over the only
            // description a stub has, and a reflex keystroke must not be able
            // to commit half a rewrite.
            if (event.key === 'Escape') setDraft(null)
          }}
          className="min-w-0 flex-1 rounded-md border border-line bg-surface px-1 text-meta text-ink"
        />
      ) : (
      <button
        disabled={!readable}
        onClick={() => readable && onRead(readable)}
        className={`min-w-0 flex-1 truncate text-left text-meta ${
          readable
            ? 'text-ink-dim hover:underline'
            : 'cursor-default text-amber-300'
        }`}
        title={element.role || element.entity_id}
      >
        {element.name}
        {element.role && (
          <span className="text-ink-faint"> · {element.role}</span>
        )}
      </button>
      )}
      <span className="shrink-0 text-label uppercase tracking-wide text-ink-faint">
        {element.kind}
      </span>
      {draft === null && (
        <button
          onClick={() => setDraft(element.role || '')}
          className="shrink-0 text-label text-ink-faint opacity-0 transition-opacity group-hover:opacity-100 hover:text-amber-300"
        >
          role
        </button>
      )}
      {onDraft && draft === null && (
        <button
          onClick={onDraft}
          disabled={busy}
          className="shrink-0 text-label text-ink-faint opacity-0 transition-opacity group-hover:opacity-100 hover:text-amber-300 disabled:opacity-100"
        >
          {busy ? 'drafting…' : 'flesh out'}
        </button>
      )}
    </div>
  )
}
