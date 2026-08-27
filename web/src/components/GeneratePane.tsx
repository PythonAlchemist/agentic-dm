'use client'

import { useEffect, useState } from 'react'
import { labAPI, type Depth, type GeneratedReply, type OrderRow } from '@/lib/api'
import { GenerationCard } from './GenerationCard'
import { CallMeter, RetrievalPanel } from './Meters'

// Labels only. The PLACEHOLDERS come from the selected book's seed, because
// they name things -- and three Barovia examples stayed put when the lab
// switched to a heist anthology.
const KINDS = [
  { id: 'quest', label: 'Quest' },
  { id: 'npc', label: 'NPC' },
  { id: 'monster', label: 'Monster' },
]

/** A quest, NPC or monster, with what came from the book kept apart from what
 *  was made up. */
export function GeneratePane({
  examples,
  book,
  campaign,
  onChainChanged,
  model,
  depth,
  onSpend,
}: {
  /** The selected book's starter subjects, keyed by kind. */
  examples: Record<string, string>
  book: string
  campaign: string | null
  onChainChanged: () => void
  model: string
  depth: Depth
  onSpend: (reply: GeneratedReply) => void
}) {
  const [kind, setKind] = useState('npc')
  const [subject, setSubject] = useState('')
  const [result, setResult] = useState<GeneratedReply | null>(null)
  //: Bumped per draft, and used as the card's `key`. A REVISION returns a new
  //  card to the same mounted component, and `GenerationCard` holds the
  //  editable body in `useState(card.body)` -- which initialises once and
  //  never again. So "make him honest" came back with the smuggling gone from
  //  the provenance lists and still there in the prose: a DM reading a card
  //  whose two halves disagreed. Remounting is the right answer rather than
  //  syncing one field, because everything else the card holds -- the anchor,
  //  whether it was stored, a half-resolved cluster plan -- belongs to the
  //  draft that is being replaced.
  const [draftNumber, setDraftNumber] = useState(0)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [order, setOrder] = useState<OrderRow[]>([])

  useEffect(() => {
    if (!campaign) return
    let cancelled = false
    labAPI
      .runningOrder(campaign)
      .then((r) => {
        if (!cancelled) setOrder(r.sections)
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [campaign])

  const placeholder = examples[kind] ?? ''

  const run = async (revision?: { previous: string; note: string }) => {
    if (!subject.trim() || busy) return
    setBusy(true)
    setError('')
    // THE OLD CARD STAYS ON SCREEN during a revision. Clearing it would take
    // away the thing the DM is comparing against at the moment they asked for
    // a comparison, and a blank pane reads as "your draft is gone".
    if (!revision) setResult(null)
    try {
      const reply = await labAPI.generate(
        kind, subject.trim(), model, depth, book, campaign, revision,
      )
      setResult(reply)
      setDraftNumber((n) => n + 1)
      onSpend(reply)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="mb-3 flex shrink-0 gap-1 rounded-lg border border-neutral-800 bg-neutral-900/60 p-1 self-start">
        {KINDS.map((k) => (
          <button
            key={k.id}
            onClick={() => setKind(k.id)}
            className={`rounded-md px-3 py-1.5 text-sm transition-colors ${
              kind === k.id
                ? 'bg-neutral-800 text-neutral-100'
                : 'text-neutral-400 hover:bg-neutral-800/60'
            }`}
          >
            {k.label}
          </button>
        ))}
      </div>

      <div className="mb-4 flex shrink-0 gap-2">
        <input
          value={subject}
          onChange={(e) => setSubject(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') return void run()
            // Fill only into an empty field, so Tab goes on moving focus.
            if (e.key === 'Tab' && !subject) {
              e.preventDefault()
              setSubject(placeholder)
            }
          }}
          placeholder={placeholder}
          className="flex-1 rounded-md border border-neutral-800 bg-neutral-900/60 px-3 py-2 text-sm outline-none placeholder:text-neutral-600 focus:border-neutral-500"
        />
        <button
          onClick={() => run()}
          disabled={busy || !subject.trim()}
          className="rounded-md bg-neutral-200 px-4 py-2 text-sm font-medium text-neutral-950 hover:bg-white disabled:opacity-30"
        >
          {busy ? '…' : 'Generate'}
        </button>
      </div>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto pr-1">
        {error && (
          <p className="rounded-md border border-red-900/60 bg-red-950/30 p-3 text-sm text-red-400">
            {error}
          </p>
        )}

        {result?.error && (
          <div className="space-y-2 rounded-md border border-red-900/60 p-3 text-sm">
            <p className="text-red-400">{result.error}</p>
            {/* The raw text travels on failure: a malformed response is
                evidence about the prompt, and hiding it leaves nothing to
                debug from. */}
            <pre className="whitespace-pre-wrap text-xs text-neutral-500">{result.raw}</pre>
          </div>
        )}

        {result && !result.error && (
          <>
            {/* THE SAME CARD THE CHAT TAB SHOWS, deliberately. One generator,
                two callers, and one approval path -- a second store flow here
                would be free to drift into being the good one, or the one that
                forgot a provenance list. The split rendering lives in the card
                so both entry points cannot disagree about it. */}
            <GenerationCard
              key={draftNumber}
              card={result}
              campaign={campaign}
              order={order}
              onStored={onChainChanged}
              busy={busy}
              onRevise={(note) => run({ previous: result.body, note })}
            />

            {result.sources.length > 0 && (
              <ul className="space-y-0.5 text-xs text-neutral-600">
                {result.sources.map((s, i) => (
                  <li key={i}>
                    {s.citation} {s.section ?? s.source}
                    {s.path === 'text' && (
                      <span className="text-neutral-500"> · keyword match</span>
                    )}
                  </li>
                ))}
              </ul>
            )}

            <CallMeter usage={result.usage} cost={result.cost} />
            <RetrievalPanel report={result.retrieval} />
          </>
        )}
      </div>
    </div>
  )
}
