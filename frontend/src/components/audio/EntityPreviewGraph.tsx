import { useRef, useState, useCallback, useEffect, useMemo } from 'react';
import ForceGraph2D from 'react-force-graph-2d';
import type { ExtractedEntityItem, ExtractedRelationshipItem } from '../../types';

interface NodeObject {
  id?: string | number;
  x?: number;
  y?: number;
  vx?: number;
  vy?: number;
  fx?: number;
  fy?: number;
}

interface GraphNode extends NodeObject {
  id: string;
  name: string;
  entity_type: string;
  confidence: number;
  val: number;
  color: string;
}

interface GraphLink {
  source: string | GraphNode;
  target: string | GraphNode;
  type: string;
}

const TYPE_COLORS: Record<string, string> = {
  PC: '#4CAF50',
  NPC: '#2196F3',
  LOCATION: '#FF9800',
  ITEM: '#9C27B0',
  FACTION: '#F44336',
  EVENT: '#00BCD4',
  MONSTER: '#E91E63',
  SPELL: '#FFEB3B',
  CAMPAIGN: '#795548',
  LORE: '#607D8B',
  SESSION: '#3F51B5',
  SETTING: '#8BC34A',
  QUEST: '#FF5722',
  CLASS: '#00E676',
  default: '#9E9E9E',
};

const TYPE_SIZES: Record<string, number> = {
  PC: 12,
  NPC: 8,
  LOCATION: 10,
  CAMPAIGN: 14,
  FACTION: 10,
  default: 6,
};

interface Props {
  entities: ExtractedEntityItem[];
  relationships: ExtractedRelationshipItem[];
  height?: number;
}

export function EntityPreviewGraph({ entities, relationships, height = 400 }: Props) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const graphRef = useRef<any>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(600);
  const [hoveredNode, setHoveredNode] = useState<GraphNode | null>(null);
  const [highlightNodes, setHighlightNodes] = useState(new Set<string>());
  const [highlightLinks, setHighlightLinks] = useState(new Set<string>());

  useEffect(() => {
    const updateWidth = () => {
      if (containerRef.current) {
        setWidth(containerRef.current.getBoundingClientRect().width);
      }
    };
    updateWidth();
    window.addEventListener('resize', updateWidth);
    return () => window.removeEventListener('resize', updateWidth);
  }, []);

  const graphData = useMemo(() => {
    // Build node map from entities — dedupe by name+type
    const nodeMap = new Map<string, GraphNode>();
    for (const e of entities) {
      const key = e.name.toLowerCase();
      if (!nodeMap.has(key)) {
        nodeMap.set(key, {
          id: key,
          name: e.name,
          entity_type: e.entity_type,
          confidence: e.confidence,
          val: TYPE_SIZES[e.entity_type] || TYPE_SIZES.default,
          color: TYPE_COLORS[e.entity_type] || TYPE_COLORS.default,
        });
      }
    }

    // Build links — only include if both endpoints exist
    const links: GraphLink[] = [];
    for (const r of relationships) {
      const srcKey = r.source.toLowerCase();
      const tgtKey = r.target.toLowerCase();
      if (nodeMap.has(srcKey) && nodeMap.has(tgtKey)) {
        links.push({ source: srcKey, target: tgtKey, type: r.type });
      }
    }

    return { nodes: Array.from(nodeMap.values()), links };
  }, [entities, relationships]);

  // Zoom to fit once data is loaded
  useEffect(() => {
    if (graphRef.current && graphData.nodes.length > 0) {
      setTimeout(() => graphRef.current?.zoomToFit(400, 40), 300);
    }
  }, [graphData]);

  const handleNodeHover = useCallback((node: GraphNode | null) => {
    setHoveredNode(node);
    if (!node) {
      setHighlightNodes(new Set());
      setHighlightLinks(new Set());
      return;
    }
    const connNodes = new Set<string>([node.id]);
    const connLinks = new Set<string>();
    graphData.links.forEach((link) => {
      const sId = typeof link.source === 'object' ? link.source.id : link.source;
      const tId = typeof link.target === 'object' ? link.target.id : link.target;
      if (sId === node.id) { connNodes.add(tId); connLinks.add(`${sId}-${tId}`); }
      if (tId === node.id) { connNodes.add(sId); connLinks.add(`${sId}-${tId}`); }
    });
    setHighlightNodes(connNodes);
    setHighlightLinks(connLinks);
  }, [graphData.links]);

  const paintNode = useCallback((node: GraphNode, ctx: CanvasRenderingContext2D, globalScale: number) => {
    const isHighlighted = highlightNodes.size === 0 || highlightNodes.has(node.id);
    const size = node.val || 6;
    const fontSize = 11 / globalScale;

    ctx.beginPath();
    ctx.arc(node.x!, node.y!, size, 0, 2 * Math.PI);
    ctx.fillStyle = isHighlighted ? node.color : 'rgba(100,100,100,0.3)';
    ctx.fill();

    if (hoveredNode?.id === node.id) {
      ctx.strokeStyle = '#fff';
      ctx.lineWidth = 2 / globalScale;
      ctx.stroke();
    }

    if (globalScale > 0.4) {
      ctx.font = `${fontSize}px Sans-Serif`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillStyle = isHighlighted ? '#fff' : 'rgba(255,255,255,0.3)';
      ctx.fillText(node.name, node.x!, node.y! + size + fontSize);
    }
  }, [highlightNodes, hoveredNode]);

  const paintLink = useCallback((link: GraphLink, ctx: CanvasRenderingContext2D, globalScale: number) => {
    const source = link.source as GraphNode;
    const target = link.target as GraphNode;
    if (!source.x || !source.y || !target.x || !target.y) return;

    const linkId = `${source.id}-${target.id}`;
    const isHighlighted = highlightLinks.size === 0 || highlightLinks.has(linkId);

    ctx.beginPath();
    ctx.moveTo(source.x, source.y);
    ctx.lineTo(target.x, target.y);
    ctx.strokeStyle = isHighlighted ? 'rgba(255,255,255,0.5)' : 'rgba(100,100,100,0.15)';
    ctx.lineWidth = isHighlighted ? 1.5 / globalScale : 0.5 / globalScale;
    ctx.stroke();

    // Arrow
    if (isHighlighted) {
      const dx = target.x - source.x;
      const dy = target.y - source.y;
      const angle = Math.atan2(dy, dx);
      const tSize = target.val || 6;
      const ax = target.x - Math.cos(angle) * tSize;
      const ay = target.y - Math.sin(angle) * tSize;
      const as = 4 / globalScale;
      ctx.beginPath();
      ctx.moveTo(ax, ay);
      ctx.lineTo(ax - as * Math.cos(angle - Math.PI / 6), ay - as * Math.sin(angle - Math.PI / 6));
      ctx.lineTo(ax - as * Math.cos(angle + Math.PI / 6), ay - as * Math.sin(angle + Math.PI / 6));
      ctx.closePath();
      ctx.fillStyle = 'rgba(255,255,255,0.5)';
      ctx.fill();
    }

    // Relationship label on hover
    if (isHighlighted && highlightLinks.size > 0 && globalScale > 0.8) {
      const mx = (source.x + target.x) / 2;
      const my = (source.y + target.y) / 2;
      const fs = 9 / globalScale;
      ctx.font = `${fs}px Sans-Serif`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillStyle = 'rgba(255,255,255,0.7)';
      ctx.fillText(link.type.replace(/_/g, ' '), mx, my);
    }
  }, [highlightLinks]);

  // Legend — only show types present in data
  const presentTypes = useMemo(() => {
    const types = new Set(entities.map(e => e.entity_type));
    return Array.from(types).sort();
  }, [entities]);

  return (
    <div ref={containerRef} className="rounded-lg overflow-hidden border border-gray-700 bg-gray-950 relative">
      <ForceGraph2D
        ref={graphRef}
        width={width}
        height={height}
        graphData={graphData}
        nodeId="id"
        nodeVal="val"
        nodeColor="color"
        nodeCanvasObject={paintNode}
        nodePointerAreaPaint={(node, color, ctx) => {
          const size = (node as GraphNode).val || 6;
          ctx.fillStyle = color;
          ctx.beginPath();
          ctx.arc(node.x!, node.y!, size + 4, 0, 2 * Math.PI);
          ctx.fill();
        }}
        linkCanvasObject={paintLink}
        linkDirectionalArrowLength={0}
        onNodeHover={handleNodeHover as any}
        onNodeDragEnd={(node) => { node.fx = node.x; node.fy = node.y; }}
        onBackgroundClick={() => {
          setHighlightNodes(new Set());
          setHighlightLinks(new Set());
          setHoveredNode(null);
        }}
        cooldownTicks={100}
        d3AlphaDecay={0.02}
        d3VelocityDecay={0.3}
        backgroundColor="#030712"
      />

      {/* Compact legend */}
      <div className="absolute bottom-2 left-2 bg-gray-900/90 rounded px-2 py-1.5 flex flex-wrap gap-x-3 gap-y-1 text-[10px]">
        {presentTypes.map(type => (
          <div key={type} className="flex items-center gap-1">
            <div className="w-2 h-2 rounded-full" style={{ backgroundColor: TYPE_COLORS[type] || TYPE_COLORS.default }} />
            <span className="text-gray-400">{type}</span>
          </div>
        ))}
      </div>

      {/* Hover info */}
      {hoveredNode && (
        <div className="absolute top-2 right-2 bg-gray-800/95 rounded-lg px-3 py-2 border border-gray-700 max-w-[200px]">
          <div className="flex items-center gap-1.5 mb-1">
            <div className="w-3 h-3 rounded-full flex-shrink-0" style={{ backgroundColor: hoveredNode.color }} />
            <span className="font-medium text-sm truncate">{hoveredNode.name}</span>
          </div>
          <div className="text-[10px] text-gray-400 uppercase tracking-wide">
            {hoveredNode.entity_type} &middot; {Math.round(hoveredNode.confidence * 100)}%
          </div>
        </div>
      )}

      {/* Stats */}
      <div className="absolute top-2 left-2 text-[10px] text-gray-500">
        {graphData.nodes.length} nodes &middot; {graphData.links.length} edges
      </div>
    </div>
  );
}
