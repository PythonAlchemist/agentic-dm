'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { SubgraphView } from '@/lib/api'
import { HOW_COLOUR, NOT_HELD } from './subgraph-legend'

/**
 * The working set drawn as a graph.
 *
 * An earlier attempt at this failed and was replaced by the ledger, on the
 * finding that "most held edges point at a name that is NOT a held node, so a
 * node-and-edge drawing can only show the node-to-node minority". The finding
 * was right and the conclusion was wrong: it is only true if the HELD set is
 * the node set. Those far ends ARE nodes -- the neighbourhood -- and drawing
 * them is what gives the picture something to be about.
 *
 * Measured on a real turn ("tell me about Strahd"): 1 held node and 51 edges,
 * which the old panel rendered as an empty canvas. Adding the unheld far ends
 * makes it 24 nodes, and 16 of those far ends carry more than one edge --
 * Castle Ravenloft five, the Abbot four. That recurrence is the thing this
 * view shows and the ledger cannot: the ledger lists Strahd's relationships in
 * reading order, and you would have to hold twenty lines in your head to
 * notice that five of them land on the same castle.
 *
 * So the two views answer different questions and both are kept:
 *   ledger -- what exactly is the model reading, line by line
 *   graph  -- what is this conversation actually circling
 */

type Held = SubgraphView['nodes'][number]

type Node = {
  id: string
  label: string
  /** The held record, or null for a name known only through a relationship. */
  held: Held | null
  degree: number
  /** Written by the simulation. Kept because reusing a node object across
   *  turns is what stops the whole picture from re-scrambling (see `previous`). */
  x?: number
  y?: number
  vx?: number
  vy?: number
  /** Set only on edgeless nodes, which the simulation is not allowed to place
   *  (see `parkIsolated`). d3 treats fx/fy as a pin. */
  fx?: number
  fy?: number
}

type Link = {
  source: string
  target: string
  /** Every relationship between this pair, collapsed. Five parallel edges drawn
   *  on top of each other look like one line, so they are one line -- with the
   *  count in its width, and the detail on hover. EMPTY for a pair the book
   *  only names together. */
  rels: { type: string; status: string; from: string }[]
  accepted: number
  /** How many sentences name both. 0 when the graph never puts them in one.
   *
   *  A pair with typed relationships draws as a typed line even when it also
   *  co-occurs: the relationship is the stronger statement, and the sentence
   *  count joins it on hover. The dashed line is reserved for the case that
   *  carries information -- named together, and that is ALL that is known. */
  sentences: number
}

/** Unordered pair key: A→B and B→A are one line on the canvas, and splitting
 *  them would draw two edges the eye cannot tell apart anyway. Direction is
 *  kept per-relationship in `from`.
 *
 *  `::` and not a NUL separator, for the reason recorded in `SubgraphPanel`:
 *  a NUL in the source makes git treat the FILE as binary, so it ships with no
 *  diff and no review. Entity names carry no colons. */
function pairKey(a: string, b: string): string {
  return a < b ? `${a}::${b}` : `${b}::${a}`
}

/** Where a name sat last turn. */
type Seat = { x: number; y: number }

function build(
  view: SubgraphView,
  seats: Map<string, Seat>,
): { nodes: Node[]; links: Link[] } {
  const held = new Map(view.nodes.map((n) => [n.name, n]))
  const degree = new Map<string, number>()
  const bump = (name: string) => degree.set(name, (degree.get(name) ?? 0) + 1)

  const pairs = new Map<string, Link>()
  for (const edge of view.edges) {
    bump(edge.source)
    bump(edge.target)
    const key = pairKey(edge.source, edge.target)
    const rel = { type: edge.rel_type, status: edge.status, from: edge.source }
    const existing = pairs.get(key)
    if (existing) {
      existing.rels.push(rel)
      if (edge.status === 'accepted') existing.accepted += 1
    } else {
      pairs.set(key, {
        source: edge.source,
        target: edge.target,
        rels: [rel],
        accepted: edge.status === 'accepted' ? 1 : 0,
        sentences: 0,
      })
    }
  }

  // The sentence layer, folded onto the pairs that already exist and added as
  // new ones where they do not. Both ends are held by construction -- the query
  // requires it -- so this never introduces a node.
  for (const pair of view.together ?? []) {
    const key = pairKey(pair.source, pair.target)
    const existing = pairs.get(key)
    if (existing) {
      existing.sentences += pair.sentences
    } else {
      bump(pair.source)
      bump(pair.target)
      pairs.set(key, {
        source: pair.source,
        target: pair.target,
        rels: [],
        accepted: 0,
        sentences: pair.sentences,
      })
    }
  }

  // Held nodes first, then every far end that is not held. A held entity with
  // no edges still gets a dot -- "held and connected to nothing" is a real
  // state and the one worth seeing.
  const names = new Set<string>(view.nodes.map((n) => n.name))
  for (const edge of view.edges) {
    names.add(edge.source)
    names.add(edge.target)
  }

  const nodes: Node[] = [...names].map((name) => ({
    id: name,
    label: name,
    held: held.get(name) ?? null,
    degree: degree.get(name) ?? 0,
  }))

  parkIsolated(nodes)
  for (const node of nodes) {
    // A parked node already has its seat, and it is a deliberate one.
    if (node.fx !== undefined) continue
    const seat = seats.get(node.id)
    if (seat) {
      node.x = seat.x
      node.y = seat.y
    }
  }
  return { nodes, links: [...pairs.values()] }
}

/**
 * Pin every edgeless node to an outer ring, out of the simulation's hands.
 *
 * A held node with no edges this turn is a real and common state -- the
 * conversation moved on, its one connection was evicted, and it is still being
 * carried. Measured on turn 9 of a real session: five of them. Left to d3 they
 * are pure repulsion with nothing pulling back, so they fly to the corners,
 * and `zoomToFit` then has to frame the corners -- which squeezed a fifteen
 * node cluster into an illegible smudge in the middle. That single effect is
 * most of what "the graph is shitty" was.
 *
 * A ring says what is true: these are held, and they connect to nothing here.
 */
function parkIsolated(nodes: Node[]): void {
  const loose = nodes.filter((n) => n.degree === 0)
  // A node that was isolated last turn may be connected this turn; the pin has
  // to be cleared or it stays frozen where it was parked.
  for (const node of nodes) {
    node.fx = undefined
    node.fy = undefined
  }
  if (loose.length === 0) return

  // A first guess, so they are pinned before the first tick rather than
  // drifting during it. `ringIsolated` replaces this with a measured radius
  // once the cluster has actually settled.
  place(loose, 110 + Math.min(nodes.length - loose.length, 40) * 7, 0, 0)
}

function place(loose: Node[], radius: number, cx: number, cy: number): void {
  loose.forEach((node, i) => {
    const angle = (2 * Math.PI * i) / loose.length - Math.PI / 2
    node.fx = cx + radius * Math.cos(angle)
    node.fy = cy + radius * Math.sin(angle)
    node.x = node.fx
    node.y = node.fy
  })
}

/**
 * Re-seat the parked nodes just outside the settled cluster.
 *
 * The build-time radius is a guess about a layout that has not run yet, and
 * guessing it too wide is not harmless: the fit has to frame the ring, so
 * every extra unit of empty gap shrinks the cluster you are trying to read.
 * Measured at the guessed radius, the ring sat at roughly twice the cluster's
 * own, and the fifteen connected nodes used about a third of the pane.
 */
function ringIsolated(nodes: Node[]): void {
  const loose = nodes.filter((n) => n.degree === 0)
  const linked = nodes.filter((n) => n.degree > 0)
  if (loose.length === 0 || linked.length === 0) return

  let cx = 0
  let cy = 0
  for (const node of linked) {
    cx += node.x ?? 0
    cy += node.y ?? 0
  }
  cx /= linked.length
  cy /= linked.length

  let reach = 0
  for (const node of linked) {
    reach = Math.max(reach, Math.hypot((node.x ?? 0) - cx, (node.y ?? 0) - cy))
  }
  // Clear of the outermost node and its label, and no further.
  place(loose, reach + 34, cx, cy)
}

/** What one line says, in as few characters as fit on it.
 *
 *  UNLABELLED LINES ARE WHY THIS EXISTS. Asked to list the Vistani, a reader
 *  looked at Vistani's hub -- 25 lines to 25 names -- and reasonably read it as
 *  25 members. Four were `MEMBER_OF`. Rictavio and Rudolph van Richten are
 *  HOSTILE_TO and ENEMY_OF: the picture was drawing "enemy" and "member" as the
 *  same grey line and leaving the difference on hover, where nobody scanning a
 *  hub is looking. */
function linkLabel(link: Link): string {
  if (link.rels.length === 0) return 'together'
  const first = link.rels[0].type
  return link.rels.length === 1 ? first : `${first} +${link.rels.length - 1}`
}

function radius(node: Node): number {
  // Held nodes read as anchors whatever their degree; unheld ones grow with
  // recurrence, because a name three relationships land on is the signal.
  const base = node.held ? 5 : 2.5
  return base + Math.min(node.degree, 9) * 0.45
}

function colour(node: Node): string {
  if (!node.held) return NOT_HELD
  return HOW_COLOUR[node.held.how] ?? '#d4d4d4'
}

export function SubgraphGraph({ view }: { view: SubgraphView }) {
  // Imported in an effect rather than through `next/dynamic`. The library
  // touches canvas and window, so it cannot render on the server either way --
  // but this component needs the instance ref to call `zoomToFit`, and
  // next/dynamic's wrapper does not pass a ref through to what it loads.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [ForceGraph2D, setForceGraph2D] = useState<any>(null)
  useEffect(() => {
    let live = true
    import('react-force-graph-2d').then((module) => {
      // The updater form, or React calls the component as a lazy initialiser.
      if (live) setForceGraph2D(() => module.default)
    })
    return () => {
      live = false
    }
  }, [])

  const holder = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({ width: 0, height: 0 })
  const [hover, setHover] = useState<{ node: Node | null; link: Link | null }>({
    node: null,
    link: null,
  })

  // The graph only fills a resizable pane, so its size is not knowable at
  // render time and a hardcoded one is how the old panel ended up a sliver.
  useEffect(() => {
    const element = holder.current
    if (!element) return
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect
      setSize({ width: Math.floor(width), height: Math.floor(height) })
    })
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  // Positions from the previous turn, by name. Without this every answer
  // reshuffles the whole picture and the reader loses the map they had just
  // built; with it, the subject stays put and the new names arrive around it.
  const [previous] = useState(() => new Map<string, Seat>())

  // Seating happens inside `build`, on objects it still owns. These nodes are
  // mutable by contract -- the simulation writes x, y, vx and vy into them
  // every tick -- so they cannot be treated as a frozen derived value, and the
  // seat store cannot be a ref, which may not be read during render.
  const data = useMemo(() => build(view, previous), [view, previous])

  useEffect(() => {
    return () => {
      // Read back after the simulation has moved them, not at build time.
      for (const node of data.nodes) {
        if (typeof node.x === 'number' && typeof node.y === 'number') {
          previous.set(node.id, { x: node.x, y: node.y })
        }
      }
    }
  }, [data, previous])

  const paintNode = useCallback(
    (node: Node, ctx: CanvasRenderingContext2D, scale: number) => {
      const r = radius(node)
      ctx.beginPath()
      ctx.arc(node.x ?? 0, node.y ?? 0, r, 0, 2 * Math.PI)
      ctx.fillStyle = colour(node)
      ctx.fill()
      if (node.held) {
        // A dark ring, so a held dot stays distinct where the neighbourhood
        // crowds around it.
        ctx.lineWidth = 1.5 / scale
        ctx.strokeStyle = '#0a0a0a'
        ctx.stroke()
      }

      // Divided by scale so type stays the same size on screen at every zoom;
      // constant graph-unit type is what made the last attempt illegible.
      const font = 11 / scale
      ctx.font = `${font}px ui-sans-serif, system-ui, sans-serif`
      ctx.textAlign = 'center'
      ctx.textBaseline = 'top'
      ctx.fillStyle = node.held ? '#e5e5e5' : '#8a8a8a'
      ctx.fillText(node.label, node.x ?? 0, (node.y ?? 0) + r + 2 / scale)
    },
    [],
  )

  const paintLink = useCallback(
    (link: Link, ctx: CanvasRenderingContext2D, scale: number) => {
      // Zoom-gated: at a distance the labels overlap into a smear and the
      // shape of the neighbourhood is what is worth seeing. They appear as
      // soon as you lean in, which is when the question becomes "how".
      if (scale < 1.1) return
      const a = link.source as unknown as Node
      const b = link.target as unknown as Node
      if (typeof a?.x !== 'number' || typeof b?.x !== 'number') return

      const text = linkLabel(link)
      const font = 8 / scale
      ctx.font = `${font}px ui-sans-serif, system-ui, sans-serif`
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      const x = ((a.x ?? 0) + (b.x ?? 0)) / 2
      const y = ((a.y ?? 0) + (b.y ?? 0)) / 2

      // Knocked out of the line rather than drawn over it: a label with the
      // edge running through it is harder to read than no label.
      const width = ctx.measureText(text).width
      ctx.fillStyle = '#0a0a0a'
      ctx.fillRect(x - width / 2 - 1 / scale, y - font / 2, width + 2 / scale, font)
      ctx.fillStyle = link.rels.length === 0
        ? '#5b7fa8'
        : link.accepted > 0
          ? '#c8c8c8'
          : '#6b6b6b'
      ctx.fillText(text, x, y)
    },
    [],
  )

  const paintPointerArea = useCallback(
    (node: Node, hitColour: string, ctx: CanvasRenderingContext2D) => {
      ctx.beginPath()
      ctx.arc(node.x ?? 0, node.y ?? 0, radius(node) + 3, 0, 2 * Math.PI)
      ctx.fillStyle = hitColour
      ctx.fill()
    },
    [],
  )

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const graph = useRef<any>(null)
  // Refit once per (data, size) pair. Without the guard the simulation's own
  // settling re-triggers the fit and the view creeps while you are reading it.
  const fitted = useRef('')
  const fitKey = `${view.turn}:${data.nodes.length}:${size.width}x${size.height}`

  const fit = useCallback(() => {
    if (fitted.current === fitKey) return
    fitted.current = fitKey
    // Default zoom left the picture using about half the pane -- measured 52%
    // wide by 38% tall on a 24-node turn, which is the "too small" complaint
    // in numbers. `maxZoom` is what keeps this from going the other way on a
    // one-node subgraph, whose bounding box is a point and would otherwise
    // magnify without limit.
    ringIsolated(data.nodes)
    graph.current?.zoomToFit(400, 48)
  }, [fitKey, data])

  // The default d3 forces pack twenty nodes into a knot a couple of hundred
  // units across, which then has to be magnified past `maxZoom` to fill the
  // pane -- measured: the fit asked for more than 3x, got clamped to 3, and
  // the drawing still covered 38% of the width. Spreading the layout in graph
  // units is the half of the fix that also separates the labels; raising the
  // cap is the other half.
  useEffect(() => {
    if (!ForceGraph2D) return
    graph.current?.d3Force('charge')?.strength(-220)
    graph.current?.d3Force('link')?.distance(60)
  }, [ForceGraph2D, data])

  // A drag or a pane resize should re-fit, but only after the layout settles.
  useEffect(() => {
    fitted.current = ''
  }, [fitKey])

  const detail = hover.node
    ? nodeDetail(hover.node)
    : hover.link
      ? linkDetail(hover.link)
      : ''

  return (
    <div className="flex h-full flex-col">
      <div ref={holder} className="min-h-0 flex-1">
        {ForceGraph2D && size.width > 0 && size.height > 0 && (
          <ForceGraph2D
            ref={graph}
            width={size.width}
            height={size.height}
            graphData={data}
            onEngineStop={fit}
            backgroundColor="rgba(0,0,0,0)"
            nodeCanvasObject={paintNode}
            nodePointerAreaPaint={paintPointerArea}
            onNodeHover={(node: Node | null) => setHover({ node, link: null })}
            onLinkHover={(link: Link | null) => setHover({ node: null, link })}
            // Three classes, and the dashed one is not a relationship. A
            // solid line is something the graph asserts about the pair; a
            // dashed one is only "the book named these in one sentence", which
            // `cooccurrence` is emphatic must not be read as more than that.
            linkColor={(link: Link) =>
              link.rels.length === 0
                ? '#5b7fa8'
                : link.accepted > 0
                  ? '#8a8a8a'
                  : '#3f3f3f'
            }
            linkLineDash={(link: Link) => (link.rels.length === 0 ? [3, 3] : null)}
            linkCanvasObjectMode={() => 'after'}
            linkCanvasObject={paintLink}
            linkWidth={(link: Link) =>
              link.rels.length === 0
                ? Math.min(0.5 + link.sentences * 0.35, 2)
                : Math.min(0.6 + link.rels.length * 0.55, 4)
            }
            // Long enough that a hub's neighbours ring it rather than pile on
            // top of the label, which is most of what made the old one a blob.
            linkDirectionalArrowLength={0}
            d3VelocityDecay={0.35}
            cooldownTicks={90}
            warmupTicks={20}
            enableNodeDrag
            minZoom={0.4}
            // Generous, because it also caps `zoomToFit`. It only binds in the
            // degenerate case -- a lone held node, whose bounding box is a
            // point -- and one large dot with a readable name is a fine
            // rendering of "the conversation is holding exactly one thing".
            maxZoom={8}
          />
        )}
      </div>
      {/* One strip rather than a floating tooltip: the detail is several lines
          of relationship types, and a box that follows the cursor covers the
          neighbours you are comparing against. */}
      <p className="h-8 shrink-0 truncate border-t border-line px-3 py-2 text-meta text-ink-dim">
        {detail || 'Hover a name or a line. Drag to rearrange, scroll to zoom.'}
      </p>
    </div>
  )
}

function nodeDetail(node: Node): string {
  if (!node.held) {
    const times = node.degree === 1 ? 'one relationship' : `${node.degree} relationships`
    return `${node.label} — named in ${times}, not held`
  }
  const labels = node.held.labels.join('/')
  const where = `${labels}, ${node.held.how}, turn ${node.held.turn}`
  // The ring needs to explain itself, or being flung to the edge reads as a
  // layout accident rather than the fact it is.
  return node.degree === 0
    ? `${node.label} — ${where}; still held, but no relationships in the working set`
    : `${node.label} — ${where}`
}

function linkDetail(link: Link): string {
  const sentences =
    link.sentences === 0
      ? ''
      : `named together in ${link.sentences} sentence${link.sentences === 1 ? '' : 's'}`
  if (link.rels.length === 0) {
    // No relationship type at all. Say exactly that, because the whole risk of
    // showing this layer is it being read as one.
    return `${link.source} / ${link.target}:  ${sentences} — no relationship recorded`
  }
  const shown = link.rels
    .slice(0, 6)
    .map((r) => `${r.from === link.source ? '→' : '←'} ${r.type}${r.status === 'accepted' ? '' : '?'}`)
    .join('  ')
  const more = link.rels.length > 6 ? `  +${link.rels.length - 6} more` : ''
  // `?` marks a guessed relationship, matching the ledger's dim styling; a
  // third of them are wrong and the picture must not imply otherwise.
  const also = sentences ? `;  ${sentences}` : ''
  return `${link.source} / ${link.target}:  ${shown}${more}${also}`
}
