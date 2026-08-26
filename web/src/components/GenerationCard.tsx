'use client'

import { useState } from 'react'
import type { ClusterPlan, GeneratedReply, OrderRow } from '@/lib/api'
import { labAPI } from '@/lib/api'
import { ClusterReview } from './ClusterReview'

/**
 * One draft, with its three sources kept apart, and the button that is the gate.
 *
 * THE SPLIT IS SHOWN, NOT SUMMARISED. A DM acting on this at a table cannot
 * afford to mistake an invented detail for the book's text, so what came from
 * canon, what came from the conversation and what the model supplied are three
 * lists a person reads before approving -- never one blended paragraph.
 *
 * NOTHING HERE IS IN THE GRAPH until Store is pressed. That is the whole shape
 * of the flow: a model proposes, a human reads, one step applies.
 */
export function GenerationCard({
  card,
  campaign,
  order,
  onStored,
}: {
  card: GeneratedReply
  campaign: string | null
  order: OrderRow[]
  onStored?: () => void
}) {
  const [body, setBody] = useState(card.body)
  const [anchor, setAnchor] = useState(card.anchor ?? '')
  const [busy, setBusy] = useState(false)
  const [stored, setStored] = useState('')
  const [failed, setFailed] = useState('')
  const [plan, setPlan] = useState<ClusterPlan | null>(null)
  const [clusterBody, setClusterBody] = useState<Record<string, unknown> | null>(null)

  const isCluster = (card.elements?.length ?? 0) > 0
  // A collision is a question only a person can answer, so it BLOCKS the
  // write rather than resolving itself in either direction.
  const blocked = isCluster && plan !== null && !plan.storable

  const edited = body.trim() !== card.body.trim()

  const store = async () => {
    if (!campaign || busy) return
    setBusy(true)
    setFailed('')
    try {
      // A cluster posts the payload the REVIEW built, with the edited body
      // laid over it -- so what is written is what was planned and shown, not
      // a second guess assembled here.
      const result = isCluster
        ? await labAPI.storeCluster({ ...(clusterBody ?? {}), body })
        : await labAPI.store({
            campaign,
            kind: card.kind,
            title: card.title,
            body,
            generated_body: card.body,
            from_canon: card.from_canon,
            invented: card.invented,
            from_context: card.from_context ?? [],
            sources: card.sources,
            anchor: anchor || null,
            model: card.model,
          })
      setStored(result.entity_id)
      onStored?.()
    } catch (error) {
      setFailed(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(false)
    }
  }

  if (card.error) {
    return (
      <div className="rounded-md border border-red-900/60 bg-red-950/20 p-3 text-sm">
        <p className="text-red-400">
          The {card.kind} draft failed: {card.error}
        </p>
      </div>
    )
  }

  return (
    <div className="rounded-md border border-amber-900/50 bg-amber-500/[0.03] p-3">
      <div className="mb-2 flex items-baseline justify-between gap-3">
        <h3 className="text-sm font-medium text-amber-200">{card.title}</h3>
        <span className="shrink-0 text-xs uppercase tracking-wide text-neutral-600">
          draft {card.kind}
        </span>
      </div>

      <textarea
        value={body}
        onChange={(e) => setBody(e.target.value)}
        rows={7}
        className="w-full rounded border border-neutral-800 bg-neutral-900/60 p-2 text-sm leading-relaxed outline-none focus:border-amber-600/60"
      />
      {/* Said plainly, because nothing re-checks a body after a person edits
          it -- the citations below still claim what the model claimed. */}
      {edited && (
        <p className="mt-1 text-xs text-amber-500/80">
          Edited. The citations below were made about the original text and are
          not re-checked.
        </p>
      )}

      <div className="mt-3 space-y-2 text-xs">
        <Provenance
          label="From the book"
          hint="Each cites a passage. A pointer for you to check, not a proof."
          items={card.from_canon.map((c) => `${c.claim} ${c.cite}`)}
          tone="text-emerald-300/80"
        />
        {(card.from_context?.length ?? 0) > 0 && (
          <Provenance
            label="From this conversation"
            hint="Taken from what you said at the table, not from the book."
            items={card.from_context ?? []}
            tone="text-sky-300/80"
          />
        )}
        <Provenance
          label="Invented"
          hint="The model supplied these. Nothing in the book says them."
          items={card.invented}
          tone="text-amber-300/80"
        />
      </div>

      {campaign && isCluster && (
        <ClusterReview
          card={card}
          campaign={campaign}
          anchor={anchor}
          onPlan={(next, body) => {
            setPlan(next)
            setClusterBody(body)
          }}
        />
      )}

      {campaign ? (
        <div className="mt-3 border-t border-neutral-800 pt-3">
          <label className="block text-xs text-neutral-400">
            Where it goes in your running order
            <select
              value={anchor}
              onChange={(e) => setAnchor(e.target.value)}
              className="mt-1 w-full rounded border border-neutral-800 bg-neutral-900 px-2 py-1.5 text-xs text-neutral-200"
            >
              <option value="">Nowhere in particular</option>
              {order
                .filter((row) => row.origin === 'canon' && !row.skipped)
                .map((row) => (
                  <option key={row.section_id} value={row.section_id}>
                    after {row.heading}
                  </option>
                ))}
            </select>
          </label>

          <div className="mt-2 flex items-center gap-3">
            <button
              onClick={store}
              disabled={busy || !!stored || blocked}
              className="rounded-md bg-amber-600/90 px-3 py-1.5 text-xs font-medium text-neutral-950 transition-colors hover:bg-amber-500 disabled:opacity-40"
            >
              {stored ? 'Stored' : busy ? 'Storing…' : 'Store in my campaign'}
            </button>
            {stored && (
              <span className="text-xs text-neutral-500">
                Written as <code className="text-neutral-400">{stored}</code>
              </span>
            )}
            {/* Named, not merely disabled: a greyed button with no reason
                beside it is a dead end rather than a decision. */}
            {blocked && (
              <span className="text-xs text-amber-500/90">
                Resolve the name{plan!.collisions.length === 1 ? '' : 's'} above first.
              </span>
            )}
          </div>
          {failed && <p className="mt-2 text-xs text-red-400">{failed}</p>}
        </div>
      ) : (
        <p className="mt-3 border-t border-neutral-800 pt-3 text-xs text-neutral-500">
          Pick a table on the left to store this. Canon-only sessions have
          nowhere to put it.
        </p>
      )}
    </div>
  )
}

function Provenance({
  label,
  hint,
  items,
  tone,
}: {
  label: string
  hint: string
  items: string[]
  tone: string
}) {
  return (
    <div>
      <div className={`font-medium ${tone}`}>
        {label} <span className="text-neutral-600">({items.length})</span>
      </div>
      <p className="text-neutral-600">{hint}</p>
      {items.length > 0 && (
        <ul className="mt-1 space-y-0.5 text-neutral-400">
          {items.map((item, index) => (
            <li key={index}>· {item}</li>
          ))}
        </ul>
      )}
    </div>
  )
}
