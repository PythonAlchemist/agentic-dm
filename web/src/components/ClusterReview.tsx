'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ClusterPlan, GeneratedReply } from '@/lib/api'
import { labAPI } from '@/lib/api'

/**
 * What a generation says it contains, and what storing it would actually do.
 *
 * RE-PLANNED ON THE SERVER AFTER EVERY EDIT. Rejecting an element or renaming
 * one changes which ids get minted and which names collide with the book, and
 * the browser is not the authority on either. The plan endpoint writes nothing;
 * it is the dry run, and Store is the apply.
 *
 * NOTHING HERE IS IN THE GRAPH until Store is pressed, and a name that already
 * exists in the campaign's book BLOCKS it until the DM says what the collision
 * means. Refusing to guess about identity is the whole reason the choice is
 * put in front of a person.
 */
export function ClusterReview({
  card,
  campaign,
  anchor,
  onPlan,
}: {
  card: GeneratedReply
  campaign: string
  anchor: string
  onPlan?: (plan: ClusterPlan | null, payload: Record<string, unknown>) => void
}) {
  // MEMOISED, and not for tidiness: `card.elements ?? []` builds a new array
  // every render, which changes `payload`'s dependencies every render, which
  // refires the effect, which re-plans, which renders. The plan endpoint would
  // have been called in a loop for as long as a card was on screen.
  const elements = useMemo(() => card.elements ?? [], [card.elements])
  const [rejected, setRejected] = useState<Set<string>>(new Set())
  const [renames, setRenames] = useState<Record<string, string>>({})
  const [resolutions, setResolutions] = useState<Record<string, string>>({})
  const [plan, setPlan] = useState<ClusterPlan | null>(null)
  const [failed, setFailed] = useState('')

  const payload = useCallback(
    () => ({
      campaign,
      kind: card.kind,
      title: card.title,
      body: card.body,
      generated_body: card.body,
      from_canon: card.from_canon,
      from_yours: card.from_yours ?? [],
      invented: card.invented,
      from_context: card.from_context ?? [],
      sources: card.sources,
      anchor: anchor || null,
      model: card.model,
      elements: elements.map((e) => ({ ...e, name: renames[e.name] ?? e.name })),
      edges: card.edges ?? [],
      approved: elements
        .filter((e) => !rejected.has(e.name))
        .map((e) => renames[e.name] ?? e.name),
      resolutions,
    }),
    [campaign, card, anchor, elements, rejected, renames, resolutions],
  )

  useEffect(() => {
    if (!campaign || elements.length === 0) return
    let cancelled = false
    labAPI
      .planCluster(payload())
      .then((next) => {
        if (cancelled) return
        setPlan(next)
        setFailed('')
        // The PAYLOAD travels with the plan, so the Store button cannot post
        // something other than what was planned and shown.
        onPlan?.(next, payload())
      })
      .catch((error) => {
        if (!cancelled) setFailed(error instanceof Error ? error.message : String(error))
      })
    return () => {
      cancelled = true
    }
  }, [campaign, elements.length, payload, onPlan])

  if (elements.length === 0) return null

  return (
    <div className="mt-3 rounded-md border border-neutral-800 bg-neutral-900/40 p-3">
      <div className="mb-2 flex items-baseline justify-between">
        <h4 className="text-xs font-medium uppercase tracking-wide text-neutral-400">
          What this contains
        </h4>
        <span className="text-xs tabular-nums text-neutral-600">
          {plan ? `${plan.elements.length} to store` : '…'}
        </span>
      </div>

      <ul className="space-y-1.5">
        {elements.map((element) => {
          const name = renames[element.name] ?? element.name
          const out = rejected.has(element.name)
          const collision = plan?.collisions.find((c) => c.name === name)
          return (
            <li
              key={element.name}
              className={`rounded border px-2 py-1.5 ${
                collision
                  ? 'border-amber-700/60 bg-amber-500/5'
                  : 'border-neutral-800/80'
              }`}
            >
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  className="accent-amber-500"
                  checked={!out}
                  onChange={() =>
                    setRejected((prior) => {
                      const next = new Set(prior)
                      if (next.has(element.name)) next.delete(element.name)
                      else next.add(element.name)
                      return next
                    })
                  }
                />
                <input
                  value={name}
                  onChange={(e) =>
                    setRenames((prior) => ({ ...prior, [element.name]: e.target.value }))
                  }
                  className={`min-w-0 flex-1 rounded border border-transparent bg-transparent px-1 text-xs focus:border-neutral-700 focus:outline-none ${
                    out ? 'text-neutral-600 line-through' : 'text-neutral-200'
                  }`}
                />
                <span className="shrink-0 text-[10px] uppercase tracking-wide text-neutral-600">
                  {element.kind}
                </span>
              </div>
              {element.role && (
                <p className="ml-6 mt-0.5 text-[11px] text-neutral-500">{element.role}</p>
              )}
              {/* A COLLISION BLOCKS THE WRITE. `hb:` and the book's prefix are
                  different namespaces, so this would otherwise mint quietly and
                  leave two things answering to one name. */}
              {collision && (
                <div className="ml-6 mt-1 text-[11px]">
                  <span className="text-amber-400">
                    {collision.canon_id} already has this name.
                  </span>
                  <div className="mt-1 flex gap-2">
                    <button
                      onClick={() =>
                        setResolutions((p) => ({ ...p, [name]: 'link' }))
                      }
                      className="rounded border border-neutral-700 px-2 py-0.5 hover:bg-neutral-800"
                    >
                      use the book&apos;s
                    </button>
                    <span className="text-neutral-600">or rename it above</span>
                  </div>
                </div>
              )}
            </li>
          )
        })}
      </ul>

      {/* THE DROP REPORT IS RENDERED, not summarised away. A generation that
          proposed six things and had two kept should say which two and why. */}
      {plan && Object.keys(plan.dropped).length > 0 && (
        <ul className="mt-2 space-y-0.5 border-t border-neutral-800 pt-2 text-[11px] text-neutral-500">
          {Object.entries(plan.dropped).map(([reason, n]) => (
            <li key={reason}>
              {n} × {reason}
            </li>
          ))}
        </ul>
      )}
      {plan && plan.edges_deferred > 0 && (
        <p className="mt-2 text-[11px] leading-relaxed text-neutral-600">
          {plan.edges_deferred} relationship
          {plan.edges_deferred === 1 ? '' : 's'} were proposed and are not stored.
          Measured at 27% type-impossible, so they are shown rather than written.
        </p>
      )}
      {Object.keys(card.manifest_dropped ?? {}).length > 0 && (
        <p className="mt-1 text-[11px] text-neutral-600">
          {Object.entries(card.manifest_dropped ?? {})
            .map(([reason, n]) => `${n} × ${reason}`)
            .join(' · ')}
        </p>
      )}
      {failed && <p className="mt-2 text-[11px] text-red-400">{failed}</p>}
    </div>
  )
}
