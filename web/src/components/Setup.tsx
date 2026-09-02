'use client'

import { useEffect } from 'react'
import type { BookInfo, CampaignInfo, Depth, ModelInfo } from '@/lib/api'
import { Controls } from './Controls'

/**
 * Which world, whose table, which model — one click away instead of on screen.
 *
 * THESE WERE THE TOP 1,512px OF A 288px RAIL, in a viewport 1,141px tall. The
 * consequence was not clutter but arithmetic: the campaign picker and the
 * running order could never be visible at the same time, so the panels a DM
 * works in during a session sat permanently below the fold behind the ones they
 * touch once.
 *
 * GATING THEM COSTS NOTHING because switching a book or a table already RESETS
 * the conversation — the rail was offering constant access to an action nobody
 * takes mid-session, and the warning saying so was standing text rather than
 * something said at the moment it applies.
 */
export function Setup({
  open,
  onClose,
  ...controls
}: {
  open: boolean
  onClose: () => void
  campaigns: CampaignInfo[]
  campaign: string | null
  onCampaign: (c: string | null) => void
  books: BookInfo[]
  book: string
  onBook: (b: string) => void
  models: ModelInfo[]
  model: string
  onModel: (m: string) => void
  depth: Depth
  onDepth: (d: Depth) => void
  debug: boolean
}) {
  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-40 flex justify-start bg-black/50" onClick={onClose}>
      <div
        className="h-full w-full max-w-sm overflow-y-auto border-r border-line bg-ground p-5"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="mb-4 flex items-baseline justify-between">
          <h2 className="text-body font-medium text-ink">Setup</h2>
          <button
            onClick={onClose}
            className="text-meta text-ink-dim hover:text-ink"
          >
            close (esc)
          </button>
        </div>
        {/* SAID HERE, at the moment it applies, rather than standing in the
            rail forever where it was read once and then cost space. */}
        <p className="mb-4 text-meta leading-relaxed text-ink-dim">
          Changing the book or the table starts a new conversation — a session
          reads one book, so what the agent is holding onto has to go with it.
        </p>
        <Controls {...controls} />
      </div>
    </div>
  )
}
