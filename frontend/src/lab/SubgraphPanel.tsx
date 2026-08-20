import { useEffect, useMemo, useRef, useState } from 'react'
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

/**
 * The canvas is sized from its CONTAINER, not from a constant.
 *
 * It was `width={300}` against a 300px column, which left no room for the
 * canvas's own padding: nodes were clipped at the top edge and the panel grew a
 * horizontal scrollbar. A force layout also has no idea how big its viewport
 * is, so the fit has to be asked for once the simulation settles.
 */
function useMeasured() {
  const ref = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({ width: 0, height: 0 })

  useEffect(() => {
    const element = ref.current
    if (!element) return
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect
      setSize({ width, height })
    })
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  return { ref, ...size }
}

export function SubgraphPanel({ view }: { view: SubgraphView | null }) {
  const { ref, width, height } = useMeasured()
  const graph = useRef<any>(null)
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
    <div className="text-xs flex flex-col h-full">
      <div className="flex justify-between items-baseline px-3 pt-3">
        <span className="uppercase tracking-wide text-neutral-400">
          In this conversation
        </span>
        <span className="text-neutral-500">turn {view.turn}</span>
      </div>

      <div ref={ref} className="flex-1 min-h-[320px]">
        {width > 0 && (
        <ForceGraph2D
          ref={graph}
          graphData={data}
          width={width}
          height={height}
          // Asked for once the simulation settles, with a margin, so a node on
          // the edge of the layout is inside the viewport rather than clipped.
          onEngineStop={() => graph.current?.zoomToFit(400, 24)}
          backgroundColor="transparent"
          nodeRelSize={6}
          nodeColor={(n: any) => HOW_COLOUR[n.how] ?? '#a3a3a3'}
          nodeLabel={(n: any) => `${n.name} (${n.labels}) — ${HOW_LABEL[n.how] ?? n.how}`}
          // Names are DRAWN, not left to a hover. Unlabelled circles make the
          // reader hover each one to find out what the conversation is about,
          // which is the question this panel exists to answer at a glance.
          nodeCanvasObjectMode={() => 'after'}
          nodeCanvasObject={(n: any, ctx: CanvasRenderingContext2D, scale: number) => {
            const size = 11 / scale
            ctx.font = `${size}px ui-sans-serif, system-ui, sans-serif`
            ctx.textAlign = 'center'
            ctx.textBaseline = 'top'
            // Long names wrap rather than running off the canvas.
            const lines: string[] = []
            let line = ''
            for (const word of String(n.name).split(' ')) {
              const next = line ? `${line} ${word}` : word
              if (line && ctx.measureText(next).width > 90 / scale) {
                lines.push(line)
                line = word
              } else {
                line = next
              }
            }
            if (line) lines.push(line)

            lines.forEach((text, i) => {
              const y = n.y + 8 / scale + i * size * 1.15
              ctx.strokeStyle = 'rgba(10,10,10,0.9)'
              ctx.lineWidth = 3 / scale
              ctx.strokeText(text, n.x, y)
              ctx.fillStyle = '#d4d4d4'
              ctx.fillText(text, n.x, y)
            })
          }}
          linkColor={(l: any) => (l.status === 'accepted' ? '#525252' : '#3f3f46')}
          linkLabel={(l: any) => `${l.rel} · ${l.status}`}
          linkWidth={(l: any) => (l.status === 'accepted' ? 1.5 : 0.5)}
          linkDirectionalArrowLength={3}
          cooldownTicks={60}
        />
        )}
      </div>

      <ul className="px-3 pb-2 space-y-1 shrink-0 max-h-52 overflow-y-auto">
        {view.nodes.slice(0, 12).map((n) => (
          <li key={n.id} className="flex gap-2 items-baseline">
            <span style={{ color: HOW_COLOUR[n.how] ?? '#a3a3a3' }}>●</span>
            <span className="text-neutral-300">{n.name}</span>
            <span className="text-neutral-600">{n.labels.join('/')}</span>
          </li>
        ))}
        {view.nodes.length > 12 && (
          <li className="text-neutral-600">…and {view.nodes.length - 12} more</li>
        )}
      </ul>

      <p className="px-3 pb-3 text-neutral-500 shrink-0">
        {view.edges.length} relationship{view.edges.length === 1 ? '' : 's'}
        {/* Counted rather than hidden: a line to an evicted node cannot be
            drawn, and silently drawing fewer would misreport what is held. */}
        {undrawn > 0 && `, ${undrawn} not drawn`} · {view.passages} section
        {view.passages === 1 ? '' : 's'} read
      </p>
    </div>
  )
}
