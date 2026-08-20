'use client'

import { useMemo } from 'react'
import type { SubgraphView } from '@/lib/api'
import { Explain } from './ui'

/**
 * What the conversation is holding, as a ledger rather than a picture.
 *
 * Not the whole graph -- the working set, which is the MEMORY now that the
 * transcript is bounded to the current question. Seeing it is the only way to
 * tell "the agent forgot" apart from "the agent never knew".
 *
 * This replaced a force layout, which could not do that job for two measured
 * reasons. First, the working set is mostly DISCONNECTED -- a typical turn
 * holds ~9 entities with ~3 edges between them -- so the simulation scattered
 * unrelated components and autofit zoomed out until every node was sub-pixel.
 * Second, and worse: most held edges point at a name that is NOT a held node
 * (76 edges against 3 nodes on a real turn), and a node-and-edge drawing can
 * only show the node-to-node minority. It drew 4 of those 76 and counted the
 * rest as "not drawn" -- which is to say it hid most of the memory.
 *
 * What the model actually reads each turn is `Subgraph.render()`: the held
 * entities, then every relationship line, split derived/guessed. This panel
 * mirrors that rendering one-to-one, so what the developer sees IS what the
 * model was shown, not a projection of it.
 */

/** How a thing got here. The colours carry the same distinction `how` does. */
const HOW_COLOUR: Record<string, string> = {
  seeded: '#34d399',
  named: '#fbbf24',
  expanded: '#60a5fa',
}

const HOW_LABEL: Record<string, string> = {
  seeded: 'resolved from a question',
  named: 'named in an answer',
  expanded: 'fetched by a tool',
}

/** A name the agent knows OF but is not holding: it appears only inside a
 *  relationship line, has no id here, and a follow-up cannot resolve through
 *  it. Grey is that claim. */
const NOT_HELD = '#737373'

type Edge = SubgraphView['edges'][number]

/** One rendered relationship line: every far end an entity shares a direction,
 *  type and status with, on one line. Grouping is what keeps a hub readable --
 *  Strahd alone carried ~40 edges on a real turn, which grouped to ~20 lines
 *  and would otherwise have been 40. */
type Group = {
  dir: 'out' | 'in'
  rel: string
  status: string
  others: string[]
}

function groupEdges(name: string, edges: Edge[]): Group[] {
  const groups = new Map<string, Group>()
  for (const edge of edges) {
    const dir = edge.source === name ? 'out' : 'in'
    const other = dir === 'out' ? edge.target : edge.source
    // `::` rather than a NUL separator. NUL cannot appear in the data either,
    // but two of them made git treat this SOURCE FILE as binary -- no diff,
    // no review. `dir` is in/out, `rel_type` is SCREAMING_SNAKE and `status`
    // is accepted/proposed, so no colon can collide.
    const key = `${dir}::${edge.rel_type}::${edge.status}`
    const group = groups.get(key)
    if (group) group.others.push(other)
    else groups.set(key, { dir, rel: edge.rel_type, status: edge.status, others: [other] })
  }
  // Derived before guessed, mirroring the two headings `Subgraph.render()`
  // puts in front of the model; alphabetical within, so re-asking a question
  // does not reshuffle the panel.
  return [...groups.values()].sort(
    (a, b) =>
      Number(a.status !== 'accepted') - Number(b.status !== 'accepted') ||
      a.rel.localeCompare(b.rel) ||
      a.dir.localeCompare(b.dir),
  )
}

function EndpointName({ name, held }: { name: string; held: Map<string, SubgraphView['nodes'][number]> }) {
  const node = held.get(name)
  return (
    <span style={{ color: node ? (HOW_COLOUR[node.how] ?? '#d4d4d4') : NOT_HELD }}>
      {name}
    </span>
  )
}

function GroupLine({ group, held }: { group: Group; held: Map<string, SubgraphView['nodes'][number]> }) {
  const guessed = group.status !== 'accepted'
  return (
    <li className="pl-4 leading-relaxed">
      {/* No per-line Explain: forty dotted underlines drowned the panel. The
          bright/dim encoding is explained once, on the footer's counts. Kept
          hue-free deliberately -- colour already means how a NODE got here,
          and a green rel label would read as "seeded". */}
      <span className={guessed ? 'text-neutral-500' : 'font-medium text-neutral-200'}>
        {group.dir === 'out' ? `${group.rel} →` : `← ${group.rel}`}
      </span>{' '}
      {group.others.map((other, i) => (
        <span key={`${other}-${i}`} className={guessed ? 'opacity-80' : ''}>
          {i > 0 && <span className="text-neutral-700"> · </span>}
          <EndpointName name={other} held={held} />
        </span>
      ))}
    </li>
  )
}

export function SubgraphPanel({ view }: { view: SubgraphView | null }) {
  const shaped = useMemo(() => {
    if (!view) return null
    const held = new Map(view.nodes.map((n) => [n.name, n]))
    // Every edge is shown under exactly ONE held endpoint -- the source when
    // it is held, else the target. Under both, each node-to-node edge would
    // appear twice and the counts in the footer would stop matching the list.
    const byOwner = new Map<string, Edge[]>()
    const orphans: Edge[] = []
    for (const edge of view.edges) {
      const owner = held.has(edge.source)
        ? edge.source
        : held.has(edge.target)
          ? edge.target
          : null
      if (owner === null) {
        orphans.push(edge)
      } else {
        const list = byOwner.get(owner)
        if (list) list.push(edge)
        else byOwner.set(owner, [edge])
      }
    }
    const notHeld = new Set<string>()
    for (const edge of view.edges) {
      if (!held.has(edge.source)) notHeld.add(edge.source)
      if (!held.has(edge.target)) notHeld.add(edge.target)
    }
    return {
      held,
      byOwner,
      orphans,
      notHeld: notHeld.size,
      guessed: view.edges.filter((e) => e.status !== 'accepted').length,
    }
  }, [view])

  const empty = !view || view.nodes.length === 0

  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 items-baseline justify-between border-b border-neutral-800 px-3 py-2">
        <span className="text-[11px] font-medium uppercase tracking-wider text-neutral-500">
          In this conversation
        </span>
        {view && <span className="text-xs text-neutral-600">turn {view.turn}</span>}
      </div>

      {empty && (
        <p className="p-3 text-xs leading-relaxed text-neutral-600">
          Nothing held yet. Ask something and what the conversation is about
          will appear here.
        </p>
      )}

      {!empty && shaped && (
        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-3 py-2 text-xs">
          {/* API order is kept: most recently touched first, which is also
              reverse eviction order -- the list reads top-to-bottom as
              "safest to next out the door". */}
          {view.nodes.map((n) => {
            const groups = groupEdges(n.name, shaped.byOwner.get(n.name) ?? [])
            const stale = n.turn < view.turn
            return (
              <div key={n.id}>
                <div className="flex items-baseline gap-2">
                  <Explain text={HOW_LABEL[n.how] ?? n.how}>
                    <span style={{ color: HOW_COLOUR[n.how] ?? '#a3a3a3' }}>●</span>
                  </Explain>
                  <span className="font-medium text-neutral-200">{n.name}</span>
                  <span className="truncate text-neutral-600">{n.labels.join('/')}</span>
                  <span className="ml-auto shrink-0">
                    <Explain
                      text={
                        stale
                          ? `Last touched on turn ${n.turn}; the current turn is ${view.turn}. Eviction drops the oldest-touched first, so this is aging out.`
                          : 'Touched this turn, so pinned: the current subject cannot be evicted to make room for itself.'
                      }
                    >
                      <span className={stale ? 'text-amber-600/80' : 'text-neutral-600'}>
                        t{n.turn}
                      </span>
                    </Explain>
                  </span>
                </div>
                {groups.length === 0 ? (
                  <p className="pl-4 text-neutral-600">no relationships held</p>
                ) : (
                  <ul>
                    {groups.map((g, i) => (
                      <GroupLine key={i} group={g} held={shaped.held} />
                    ))}
                  </ul>
                )}
              </div>
            )
          })}

          {/* Eviction deletes a node's edges with it, so this should stay
              empty -- but an edge both of whose ends are unheld would
              otherwise vanish, and silently showing fewer relationships than
              the model reads is the old panel's sin. */}
          {shaped.orphans.length > 0 && (
            <div>
              <p className="text-neutral-600">between names not held:</p>
              <ul>
                {shaped.orphans.map((e, i) => (
                  <li key={i} className="pl-4 leading-relaxed">
                    <EndpointName name={e.source} held={shaped.held} />{' '}
                    <span className={e.status === 'accepted' ? 'font-medium text-neutral-200' : 'text-neutral-500'}>
                      {e.rel_type} →
                    </span>{' '}
                    <EndpointName name={e.target} held={shaped.held} />
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      <p className={empty ? 'hidden' : 'shrink-0 border-t border-neutral-800 px-3 py-2 text-xs text-neutral-600'}>
        <Explain text="Derived relationships (the bright lines) come from the book's own structure and are reliable. Guessed ones (the dim lines) come from an extractor and roughly a third are wrong — leads to check, never facts.">
          {(view?.edges.length ?? 0) - (shaped?.guessed ?? 0)} derived ·{' '}
          {shaped?.guessed ?? 0} guessed
        </Explain>
        {' · '}
        <Explain text="Names the agent knows only through a relationship line. It is not holding them: no id, and a follow-up cannot resolve through one. If an answer needed one of these, the agent never knew it -- as opposed to held-then-evicted, which is forgetting.">
          {shaped?.notHeld ?? 0} named, not held
        </Explain>
        {' · '}
        {view?.passages ?? 0} section{view?.passages === 1 ? '' : 's'} read
      </p>
    </div>
  )
}
