'use client'

import dynamic from 'next/dynamic'
import { useEffect, useMemo, useRef, useState } from 'react'
import type { SubgraphView } from '@/lib/api'
import { Explain } from './ui'

/**
 * What the conversation is holding, as a picture.
 *
 * Not the whole graph -- the working set, which is why it is small enough to
 * draw. It is also the MEMORY now that the transcript is bounded to the current
 * question, so seeing it is the only way to tell "the agent forgot" apart from
 * "the agent never knew".
 *
 * Loaded with `ssr: false` because the force layout wants a canvas and a
 * window, neither of which exists while Next renders on the server.
 */
const ForceGraph2D = dynamic(() => import('react-force-graph-2d'), { ssr: false })

/** How a thing got here. The colours carry the same distinction `how` does. */
const HOW_COLOUR: Record<string, string> = {
  seeded: '#34d399',
  named: '#fbbf24',
  expanded: '#60a5fa',
}

/**
 * What this component puts ON a node and a link.
 *
 * The library types its accessors against its own loose object -- everything
 * optional, `[others: string]: any` -- so these are cast at the boundary
 * rather than threaded through `dynamic()`, which erases generics anyway. The
 * cast is honest: `data` below is the only thing that ever builds these.
 */
type GraphNode = { id: string; name: string; how: string; labels: string; x: number; y: number }
type GraphLink = { status: string; rel: string }

const asNode = (n: unknown) => n as GraphNode
const asLink = (l: unknown) => l as GraphLink

const HOW_LABEL: Record<string, string> = {
  seeded: 'resolved from a question',
  named: 'named in an answer',
  expanded: 'fetched by a tool',
}

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
  const graph = useRef<{ zoomToFit: (ms: number, pad: number) => void; zoom: (k?: number, ms?: number) => number; d3Force: (name: string) => { strength: (v: number) => void } | undefined } | null>(null)

  // A gentler repulsion than the default, because this graph is mostly
  // UNCONNECTED: the entities a conversation holds usually have no edge between
  // them, and the default charge pushes those to the far corners.
  useEffect(() => {
    graph.current?.d3Force('charge')?.strength(-90)
  })

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
      // Only edges whose BOTH ends are held can be drawn: one to an evicted
      // node would render as a line to nowhere.
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

  const empty = !view || view.nodes.length === 0
  const undrawn = view ? view.edges.length - data.links.length : 0

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

      <div ref={ref} className={empty ? 'hidden' : 'min-h-0 flex-1'}>
        {width > 0 && (
          <ForceGraph2D
            ref={graph as never}
            graphData={data}
            width={width}
            height={height}
            onEngineStop={() => {
              const fg = graph.current
              if (!fg) return
              // Instant, so the zoom can be read back and clamped. Animated,
              // the getter still returns the old value.
              fg.zoomToFit(0, 24)
              // DISCONNECTED NODES FLY APART, and `zoomToFit` then zooms out
              // until every node is a sub-pixel dot. Most of what a
              // conversation holds has no edge to the rest of it, so this is
              // the normal case rather than an edge case.
              if (fg.zoom() < 0.7) fg.zoom(0.7, 200)
            }}
            backgroundColor="transparent"
            nodeRelSize={6}
            nodeColor={(n) => HOW_COLOUR[asNode(n).how] ?? '#a3a3a3'}
            nodeLabel={(n) => {
              const node = asNode(n)
              return `${node.name} (${node.labels}) — ${HOW_LABEL[node.how] ?? node.how}`
            }}
            // Names are DRAWN, not left to a hover: hovering each circle to
            // find out what the conversation is about defeats the panel.
            nodeCanvasObjectMode={() => 'after'}
            nodeCanvasObject={(n, ctx, scale) => {
              const node = asNode(n)
              const size = 11 / scale
              ctx.font = `${size}px ui-sans-serif, system-ui, sans-serif`
              ctx.textAlign = 'center'
              ctx.textBaseline = 'top'
              const lines: string[] = []
              let line = ''
              for (const word of String(node.name).split(' ')) {
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
                const y = node.y + 8 / scale + i * size * 1.15
                ctx.strokeStyle = 'rgba(10,10,10,0.9)'
                ctx.lineWidth = 3 / scale
                ctx.strokeText(text, node.x, y)
                ctx.fillStyle = '#d4d4d4'
                ctx.fillText(text, node.x, y)
              })
            }}
            linkColor={(l) => (asLink(l).status === 'accepted' ? '#525252' : '#3f3f46')}
            linkLabel={(l) => `${asLink(l).rel} · ${asLink(l).status}`}
            linkWidth={(l) => (asLink(l).status === 'accepted' ? 1.5 : 0.5)}
            linkDirectionalArrowLength={3}
            cooldownTicks={60}
          />
        )}
      </div>

      <ul className="max-h-56 shrink-0 space-y-1 overflow-y-auto px-3 py-2 text-xs">
        {(view?.nodes ?? []).map((n) => (
          <li key={n.id} className="flex items-baseline gap-2">
            <Explain text={HOW_LABEL[n.how] ?? n.how}>
              <span style={{ color: HOW_COLOUR[n.how] ?? '#a3a3a3' }}>●</span>
            </Explain>
            <span className="text-neutral-300">{n.name}</span>
            <span className="truncate text-neutral-600">{n.labels.join('/')}</span>
          </li>
        ))}
      </ul>

      <p className={empty ? 'hidden' : 'shrink-0 border-t border-neutral-800 px-3 py-2 text-xs text-neutral-600'}>
        {view?.edges.length ?? 0} relationship{view?.edges.length === 1 ? '' : 's'}
        {/* Counted rather than hidden: silently drawing fewer would misreport
            what the conversation is holding. */}
        {undrawn > 0 && `, ${undrawn} not drawn`} · {view?.passages ?? 0} section
        {view?.passages === 1 ? '' : 's'} read
      </p>
    </div>
  )
}
