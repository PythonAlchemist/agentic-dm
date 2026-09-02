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
  //: Backwards edges the DM has turned round. Keyed exactly as
  //  `cluster.edge_key` folds them, so the server agrees about which one.
  const [turned, setTurned] = useState<Set<string>>(new Set())
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
      accept_reversed: [...turned],
    }),
    [campaign, card, anchor, elements, rejected, renames, resolutions, turned],
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
    <div className="mt-3 rounded-md border border-line bg-surface/40 p-3">
      <div className="mb-2 flex items-baseline justify-between">
        <h4 className="text-meta font-medium uppercase tracking-wide text-ink-dim">
          What this contains
        </h4>
        <span className="text-meta tabular-nums text-ink-faint">
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
              className={`rounded-md border px-2 py-1.5 ${
                collision
                  ? 'border-line bg-overlay/60'
                  : 'border-line/80'
              }`}
            >
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  className="accent-neutral-400"
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
                  className={`min-w-0 flex-1 rounded-md border border-transparent bg-transparent px-1 text-meta focus:border-line focus:${
                    out ? 'text-ink-faint line-through' : 'text-ink'
                  }`}
                />
                <span className="shrink-0 text-label uppercase tracking-wide text-ink-faint">
                  {element.kind}
                </span>
              </div>
              {element.role && (
                <p className="ml-6 mt-0.5 text-label text-ink-dim">{element.role}</p>
              )}
              {/* A COLLISION BLOCKS THE WRITE. `hb:` and the book's prefix are
                  different namespaces, so this would otherwise mint quietly and
                  leave two things answering to one name. */}
              {collision && (
                <div className="ml-6 mt-1 text-label">
                  <span className="text-ink">
                    {collision.canon_id} already has this name.
                  </span>
                  <div className="mt-1 flex gap-2">
                    <button
                      onClick={() =>
                        setResolutions((p) => ({ ...p, [name]: 'link' }))
                      }
                      className="rounded-md border border-line px-2 py-0.5 hover:bg-overlay"
                    >
                      use the book&apos;s
                    </button>
                    <span className="text-ink-faint">or rename it above</span>
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
        <ul className="mt-2 space-y-0.5 border-t border-line pt-2 text-label text-ink-dim">
          {Object.entries(plan.dropped).map(([reason, n]) => (
            <li key={reason}>
              {n} × {reason}
            </li>
          ))}
        </ul>
      )}
      {/* THE RELATIONSHIPS, shown because the DM is the gate on them. Two
          runs of this model propose different edges (0.64 agreement), which is
          fatal where nothing reviews the output and merely a different
          suggestion where somebody ticks each one. What is listed here has
          already passed the book's own domain/range check. */}
      {plan && plan.edges.length > 0 && (
        <div className="mt-2 border-t border-line pt-2">
          <div className="text-label font-medium uppercase tracking-wide text-ink-dim">
            How they relate ({plan.edges.length})
          </div>
          <ul className="mt-1 space-y-0.5 text-label text-ink-dim">
            {plan.edges.map((edge) => (
              <li key={`${edge.source}-${edge.rel_type}-${edge.target}`}>
                {edge.source}{' '}
                <span className="text-yours/70">{edge.rel_type}</span>{' '}
                {edge.target}
              </li>
            ))}
          </ul>
        </div>
      )}
      {/* A REAL RELATIONSHIP POINTING THE WRONG WAY. Dropping it lost the
          relationship along with the mistake; flipping it silently would be
          inventing a fact, since `Strahd SEEKS Ireena` and its reverse are
          different claims. So it is offered, and a person decides -- the same
          shape as the name collisions above. */}
      {plan && plan.edges_reversible.length > 0 && (
        <div className="mt-2 border-t border-line pt-2">
          <div className="text-label font-medium uppercase tracking-wide text-ink-dim">
            Written backwards ({plan.edges_reversible.length})
          </div>
          <ul className="mt-1 space-y-1 text-label text-ink-dim">
            {plan.edges_reversible.map((edge) => {
              const key = edge.key
              return (
                <li key={key} className="flex items-baseline gap-2">
                  <span className="min-w-0 flex-1">
                    <span className="text-ink-faint line-through">
                      {edge.target} {edge.rel_type} {edge.source}
                    </span>
                    {' → '}
                    {edge.source}{' '}
                    <span className="text-yours/70">{edge.rel_type}</span>{' '}
                    {edge.target}
                  </span>
                  <button
                    onClick={() =>
                      setTurned((prior) => {
                        const next = new Set(prior)
                        next.add(key)
                        return next
                      })
                    }
                    className="shrink-0 rounded-md border border-line px-2 py-0.5 hover:bg-overlay"
                  >
                    turn it round
                  </button>
                </li>
              )
            })}
          </ul>
        </div>
      )}
      {plan && Object.keys(plan.edges_dropped).length > 0 && (
        <ul className="mt-2 space-y-0.5 text-label text-ink-dim">
          {Object.entries(plan.edges_dropped).map(([reason, n]) => (
            <li key={reason}>
              {n} × relationship dropped — {reason}
            </li>
          ))}
        </ul>
      )}
      {Object.keys(card.manifest_dropped ?? {}).length > 0 && (
        <p className="mt-1 text-label text-ink-faint">
          {Object.entries(card.manifest_dropped ?? {})
            .map(([reason, n]) => `${n} × ${reason}`)
            .join(' · ')}
        </p>
      )}
      {failed && <p className="mt-2 text-label text-ink-dim">{failed}</p>}
    </div>
  )
}
