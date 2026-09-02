'use client'

import { useMemo, useState } from 'react'
import type { SubgraphView } from '@/lib/api'
import { SubgraphGraph } from './SubgraphGraph'
import { SOURCE } from '@/lib/palette'

import {
  HOW_COLOUR,
  HOW_GLYPH,
  HOW_LABEL,
  NOT_HELD,
  NOT_HELD_GLYPH,
} from './subgraph-legend'
import { Explain } from './ui'

/**
 * What the conversation is holding, two ways.
 *
 * Not the whole graph -- the working set, which is the MEMORY now that the
 * transcript is bounded to the current question. Seeing it is the only way to
 * tell "the agent forgot" apart from "the agent never knew".
 *
 * The LEDGER (this file) mirrors `Subgraph.render()` one-to-one: held
 * entities, then every relationship line, split derived/guessed. What the
 * developer reads IS what the model was shown, not a projection of it. That
 * exactness is why it is the default.
 *
 * The GRAPH (`SubgraphGraph`) shows what the ledger's reading order buries:
 * which names keep recurring across otherwise unrelated relationships. Its
 * node set deliberately includes far ends that are NOT held -- see the note
 * in that file for the measurement that forced it.
 */

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
      <span className={guessed ? 'text-ink-dim' : 'font-medium text-ink'}>
        {group.dir === 'out' ? `${group.rel} →` : `← ${group.rel}`}
      </span>{' '}
      {group.others.map((other, i) => (
        <span key={`${other}-${i}`} className={guessed ? 'opacity-80' : ''}>
          {i > 0 && <span className="text-ink-faint"> · </span>}
          <EndpointName name={other} held={held} />
        </span>
      ))}
    </li>
  )
}

export function SubgraphPanel({ view }: { view: SubgraphView | null }) {
  const [mode, setMode] = useState<'ledger' | 'graph'>('ledger')
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
      <div className="flex shrink-0 items-center justify-between gap-2 border-b border-line px-3 py-2">
        <span className="text-label font-medium uppercase tracking-wider text-ink-dim">
          In this conversation
        </span>
        <div className="flex items-center gap-2">
          {/* Both views read the same working set, so switching is free and
              never costs a call -- worth making obvious by keeping the toggle
              beside the turn counter rather than in the page's tab bar. */}
          <div className="flex rounded-md border border-line">
            {(['ledger', 'graph'] as const).map((id) => (
              <button
                key={id}
                onClick={() => setMode(id)}
                className={`px-2 py-0.5 text-label first:rounded-l-md last:rounded-r-md ${
                  mode === id
                    ? 'bg-overlay text-ink'
                    : 'text-ink-dim hover:bg-overlay/60'
                }`}
              >
                {id}
              </button>
            ))}
          </div>
          {view && <span className="text-meta text-ink-faint">turn {view.turn}</span>}
        </div>
      </div>

      {empty && (
        <p className="p-3 text-meta leading-relaxed text-ink-faint">
          Nothing held yet. Ask something and what the conversation is about
          will appear here.
        </p>
      )}

      {/* Both stay MOUNTED. The graph keeps each name's position across turns
          so the picture does not reshuffle under the reader, and that memory
          lives in the component -- unmounting it on every toggle would throw
          the layout away and defeat the point. */}
      {!empty && (
        <div className={mode === 'graph' ? 'min-h-0 flex-1' : 'hidden'}>
          <SubgraphGraph view={view} />
        </div>
      )}

      {!empty && shaped && (
        <div
          className={
            mode === 'ledger'
              ? 'min-h-0 flex-1 space-y-3 overflow-y-auto px-3 py-2 text-meta'
              : 'hidden'
          }
        >
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
                    {/* THE SHAPE SAYS HOW IT ARRIVED, the brightness how
                        strongly. The hues belong to `palette.SOURCE` and say
                        where a sentence CAME FROM, which is a different axis. */}
                    <span style={{ color: HOW_COLOUR[n.how] ?? '#a3a3a3' }}>
                      {HOW_GLYPH[n.how] ?? NOT_HELD_GLYPH}
                    </span>
                  </Explain>
                  <span className="font-medium text-ink">{n.name}</span>
                  <span className="truncate text-ink-faint">{n.labels.join('/')}</span>
                  {/* NOT NAMED BY THE BOOK. Explicitly false only: a node the
                      lookup could not find is left unmarked rather than
                      described either way. */}
                  {n.named_by_book === false && (
                    <Explain text="No section of the book names this. It came from the extraction — a common noun title-cased into a name, or a name written for something the book only describes — so there is no sentence to quote about it. What it connects to may still be right.">
                      {/* INVENTED, which is what the palette calls a name the
                          model supplied with nothing behind it. This borrowed
                          `sky`, which names THE TABLE -- something said in
                          conversation -- and these were never said by anyone. */}
                      <span
                        className={`shrink-0 rounded-md border border-line px-1 text-label ${SOURCE.invented}`}
                      >
                        unnamed
                      </span>
                    </Explain>
                  )}
                  <span className="ml-auto shrink-0">
                    <Explain
                      text={
                        stale
                          ? `Last touched on turn ${n.turn}; the current turn is ${view.turn}. Eviction drops the oldest-touched first, so this is aging out.`
                          : 'Touched this turn, so pinned: the current subject cannot be evicted to make room for itself.'
                      }
                    >
                      <span className={stale ? 'text-ink-dim' : 'text-ink-faint'}>
                        t{n.turn}
                      </span>
                    </Explain>
                  </span>
                </div>
                {groups.length === 0 ? (
                  <p className="pl-4 text-ink-faint">no relationships held</p>
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
              <p className="text-ink-faint">between names not held:</p>
              <ul>
                {shaped.orphans.map((e, i) => (
                  <li key={i} className="pl-4 leading-relaxed">
                    <EndpointName name={e.source} held={shaped.held} />{' '}
                    <span className={e.status === 'accepted' ? 'font-medium text-ink' : 'text-ink-dim'}>
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

      <p className={empty ? 'hidden' : 'shrink-0 border-t border-line px-3 py-2 text-meta text-ink-faint'}>
        <Explain text="Derived relationships (the bright lines) come from the book's own structure and are reliable. Guessed ones (the dim lines) come from an extractor and roughly a third are wrong — leads to check, never facts.">
          {(view?.edges.length ?? 0) - (shaped?.guessed ?? 0)} derived ·{' '}
          {shaped?.guessed ?? 0} guessed
        </Explain>
        {' · '}
        <Explain text="Names the agent knows only through a relationship line. It is not holding them: no id, and a follow-up cannot resolve through one. If an answer needed one of these, the agent never knew it -- as opposed to held-then-evicted, which is forgetting.">
          {shaped?.notHeld ?? 0} named, not held
        </Explain>
        {(view?.together?.length ?? 0) > 0 && (
          <>
            {' · '}
            <Explain text="Pairs of held entities the book names in ONE SENTENCE. Not a relationship — the graph records that they were named together and nothing about what it means. Shown as dashed lines in the graph view, and never sent to the model, which would read a relationship into it.">
              {view?.together?.length} named together
            </Explain>
          </>
        )}
        {' · '}
        {view?.passages ?? 0} section{view?.passages === 1 ? '' : 's'} read
      </p>
    </div>
  )
}
