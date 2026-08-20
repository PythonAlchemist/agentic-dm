import { useMemo } from 'react'
import ForceGraph2D from 'react-force-graph-2d'
import type { SubgraphView } from './api'

/**
 * What the conversation is holding, as a picture.
 *
 * Not the whole graph -- this is the working set, which is why it is small
 * enough to draw. It is also the memory now that the transcript is gone, so
 * seeing it is the only way to tell "the agent forgot" apart from "the agent
 * never knew".
 */

/** How a thing got here. The colours carry the same distinction `how` does. */
const HOW_COLOUR: Record<string, string> = {
  seeded: '#34d399', // a question resolved this name
  named: '#fbbf24', // an answer used it
  expanded: '#60a5fa', // a tool went and fetched it
}

const HOW_LABEL: Record<string, string> = {
  seeded: 'resolved from a question',
  named: 'named in an answer',
  expanded: 'fetched by a tool',
}

export function SubgraphPanel({ view }: { view: SubgraphView | null }) {
  // Keyed on the node ids so the layout is not thrown away and re-simulated on
  // every turn -- a graph that jumps each time you speak is unreadable.
  const data = useMemo(() => {
    if (!view) return { nodes: [], links: [] }
    const byName = new Map(view.nodes.map((n) => [n.name, n.id]))
    return {
      nodes: view.nodes.map((n) => ({
        id: n.id,
        name: n.name,
        how: n.how,
        labels: n.labels.join('/'),
      })),
      // Edges name their endpoints, and only those whose BOTH ends are held
      // can be drawn -- an edge to an evicted node would otherwise render as a
      // line to nowhere.
      links: view.edges
        .map((e) => ({
          source: byName.get(e.source),
          target: byName.get(e.target),
          status: e.status,
          rel: e.rel_type,
        }))
        .filter((l) => l.source && l.target),
    }
  }, [view])

  if (!view || view.nodes.length === 0) {
    return (
      <div className="text-xs text-neutral-500 p-3">
        Nothing held yet. Ask something and what the conversation is about will
        appear here.
      </div>
    )
  }

  const undrawn = view.edges.length - data.links.length

  return (
    <div className="text-xs">
      <div className="flex justify-between items-baseline px-3 pt-3">
        <span className="uppercase tracking-wide text-neutral-400">
          In this conversation
        </span>
        <span className="text-neutral-500">turn {view.turn}</span>
      </div>

      <div className="h-56">
        <ForceGraph2D
          graphData={data}
          width={300}
          height={224}
          backgroundColor="transparent"
          nodeRelSize={5}
          nodeColor={(n: any) => HOW_COLOUR[n.how] ?? '#a3a3a3'}
          nodeLabel={(n: any) => `${n.name} (${n.labels}) — ${HOW_LABEL[n.how] ?? n.how}`}
          linkColor={(l: any) => (l.status === 'accepted' ? '#525252' : '#3f3f46')}
          linkLabel={(l: any) => `${l.rel} · ${l.status}`}
          linkWidth={(l: any) => (l.status === 'accepted' ? 1.5 : 0.5)}
          linkDirectionalArrowLength={3}
          cooldownTicks={60}
        />
      </div>

      <ul className="px-3 pb-2 space-y-1">
        {view.nodes.slice(0, 8).map((n) => (
          <li key={n.id} className="flex gap-2 items-baseline">
            <span style={{ color: HOW_COLOUR[n.how] ?? '#a3a3a3' }}>●</span>
            <span className="text-neutral-300">{n.name}</span>
            <span className="text-neutral-600">{n.labels.join('/')}</span>
          </li>
        ))}
        {view.nodes.length > 8 && (
          <li className="text-neutral-600">…and {view.nodes.length - 8} more</li>
        )}
      </ul>

      <p className="px-3 pb-3 text-neutral-500">
        {view.edges.length} relationship{view.edges.length === 1 ? '' : 's'}
        {/* Counted rather than hidden: a line to an evicted node cannot be
            drawn, and silently drawing fewer would misreport what is held. */}
        {undrawn > 0 && `, ${undrawn} not drawn`} · {view.passages} section
        {view.passages === 1 ? '' : 's'} read
      </p>
    </div>
  )
}
