import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import ForceGraph2D from 'react-force-graph-2d';
import { campaignAPI } from '../api/client';
import type { Entity } from '../types';

interface NodeObject {
  id?: string | number;
  x?: number;
  y?: number;
  vx?: number;
  vy?: number;
  fx?: number;
  fy?: number;
}

interface LinkObject {
  source?: string | number | NodeObject;
  target?: string | number | NodeObject;
}

interface Props {
  onClose: () => void;
  onSelectEntity: (entity: Entity) => void;
}

interface GraphNode extends NodeObject {
  id: string;
  name: string;
  entity_type: string;
  description?: string;
  val?: number;
  color?: string;
}

interface GraphLink extends LinkObject {
  source: string | GraphNode;
  target: string | GraphNode;
  type: string;
}

interface GraphData {
  nodes: GraphNode[];
  links: GraphLink[];
}

// Entity type colors (Neo4j-like palette)
const TYPE_COLORS: Record<string, string> = {
  PC: '#4CAF50',        // Green - Player Characters
  NPC: '#2196F3',       // Blue - NPCs
  LOCATION: '#FF9800',  // Orange - Locations
  ITEM: '#9C27B0',      // Purple - Items
  FACTION: '#F44336',   // Red - Factions
  EVENT: '#00BCD4',     // Cyan - Events
  MONSTER: '#E91E63',   // Pink - Monsters
  SPELL: '#FFEB3B',     // Yellow - Spells
  CAMPAIGN: '#795548',  // Brown - Campaign
  LORE: '#607D8B',      // Blue-grey - Lore
  SESSION: '#3F51B5',   // Indigo - Sessions
  SETTING: '#8BC34A',   // Light green - Settings
  QUEST: '#FF5722',     // Deep orange - Quests
  default: '#9E9E9E',   // Grey - default
};

// Entity type sizes
const TYPE_SIZES: Record<string, number> = {
  PC: 12,
  NPC: 8,
  LOCATION: 10,
  CAMPAIGN: 15,
  FACTION: 10,
  default: 6,
};

const ENTITY_TYPES = [
  { value: '', label: 'All Types' },
  { value: 'PC', label: 'Player Characters' },
  { value: 'NPC', label: 'NPCs' },
  { value: 'LOCATION', label: 'Locations' },
  { value: 'ITEM', label: 'Items' },
  { value: 'FACTION', label: 'Factions' },
  { value: 'EVENT', label: 'Events' },
  { value: 'QUEST', label: 'Quests' },
  { value: 'LORE', label: 'Lore' },
  { value: 'SESSION', label: 'Sessions' },
];

export function KnowledgeGraph({ onClose, onSelectEntity }: Props) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const graphRef = useRef<any>();
  const containerRef = useRef<HTMLDivElement>(null);

  const [graphData, setGraphData] = useState<GraphData>({ nodes: [], links: [] });
  const [selectedType, setSelectedType] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hoveredNode, setHoveredNode] = useState<GraphNode | null>(null);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });
  const [showLabels, setShowLabels] = useState(true);
  const [highlightNodes, setHighlightNodes] = useState(new Set<string>());
  const [highlightLinks, setHighlightLinks] = useState(new Set<string>());

  // Update dimensions on resize
  useEffect(() => {
    const updateDimensions = () => {
      if (containerRef.current) {
        const rect = containerRef.current.getBoundingClientRect();
        setDimensions({
          width: rect.width,
          height: rect.height - 120, // Account for header and controls
        });
      }
    };

    updateDimensions();
    window.addEventListener('resize', updateDimensions);
    return () => window.removeEventListener('resize', updateDimensions);
  }, []);

  const loadGraph = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const types = selectedType ? [selectedType] : undefined;
      const result = await campaignAPI.getGraph(types, 200);

      // Transform nodes with colors and sizes
      const nodes: GraphNode[] = result.nodes.map((node) => ({
        ...node,
        val: TYPE_SIZES[node.entity_type] || TYPE_SIZES.default,
        color: TYPE_COLORS[node.entity_type] || TYPE_COLORS.default,
      }));

      // Transform links
      const links: GraphLink[] = result.links.map((link) => ({
        source: link.source,
        target: link.target,
        type: link.type,
      }));

      setGraphData({ nodes, links });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load graph');
      setGraphData({ nodes: [], links: [] });
    } finally {
      setIsLoading(false);
    }
  }, [selectedType]);

  useEffect(() => {
    loadGraph();
  }, [loadGraph]);

  // Handle node hover - highlight connected nodes and links
  const handleNodeHover = useCallback((node: GraphNode | null) => {
    setHoveredNode(node);

    if (!node) {
      setHighlightNodes(new Set());
      setHighlightLinks(new Set());
      return;
    }

    const connectedNodes = new Set<string>();
    const connectedLinks = new Set<string>();

    connectedNodes.add(node.id);

    graphData.links.forEach((link) => {
      const sourceId = typeof link.source === 'object' ? link.source.id : link.source;
      const targetId = typeof link.target === 'object' ? link.target.id : link.target;

      if (sourceId === node.id) {
        connectedNodes.add(targetId as string);
        connectedLinks.add(`${sourceId}-${targetId}`);
      } else if (targetId === node.id) {
        connectedNodes.add(sourceId as string);
        connectedLinks.add(`${sourceId}-${targetId}`);
      }
    });

    setHighlightNodes(connectedNodes);
    setHighlightLinks(connectedLinks);
  }, [graphData.links]);

  // Handle node click
  const handleNodeClick = useCallback((node: GraphNode) => {
    setSelectedNode(node);
    // Center on the clicked node
    if (graphRef.current) {
      graphRef.current.centerAt(node.x, node.y, 500);
      graphRef.current.zoom(2, 500);
    }
  }, []);

  // Handle double click to open entity detail
  const handleNodeDoubleClick = useCallback((node: GraphNode) => {
    const entity: Entity = {
      id: node.id,
      name: node.name,
      entity_type: node.entity_type,
      description: node.description,
    };
    onSelectEntity(entity);
  }, [onSelectEntity]);

  // Custom node painting
  const paintNode = useCallback((node: GraphNode, ctx: CanvasRenderingContext2D, globalScale: number) => {
    const isHighlighted = highlightNodes.size === 0 || highlightNodes.has(node.id);
    const isSelected = selectedNode?.id === node.id;
    const size = (node.val || 6) * (isSelected ? 1.5 : 1);
    const fontSize = 12 / globalScale;

    // Node circle
    ctx.beginPath();
    ctx.arc(node.x!, node.y!, size, 0, 2 * Math.PI);
    ctx.fillStyle = isHighlighted ? (node.color || '#9E9E9E') : 'rgba(100, 100, 100, 0.3)';
    ctx.fill();

    // Selection ring
    if (isSelected) {
      ctx.strokeStyle = '#fff';
      ctx.lineWidth = 2 / globalScale;
      ctx.stroke();
    }

    // Hover ring
    if (hoveredNode?.id === node.id) {
      ctx.strokeStyle = '#fff';
      ctx.lineWidth = 1 / globalScale;
      ctx.stroke();
    }

    // Label
    if (showLabels && globalScale > 0.5) {
      ctx.font = `${fontSize}px Sans-Serif`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillStyle = isHighlighted ? '#fff' : 'rgba(255, 255, 255, 0.3)';
      ctx.fillText(node.name, node.x!, node.y! + size + fontSize);
    }
  }, [highlightNodes, hoveredNode, selectedNode, showLabels]);

  // Custom link painting
  const paintLink = useCallback((link: GraphLink, ctx: CanvasRenderingContext2D, globalScale: number) => {
    const source = link.source as GraphNode;
    const target = link.target as GraphNode;

    if (!source.x || !source.y || !target.x || !target.y) return;

    const linkId = `${source.id}-${target.id}`;
    const isHighlighted = highlightLinks.size === 0 || highlightLinks.has(linkId);

    ctx.beginPath();
    ctx.moveTo(source.x, source.y);
    ctx.lineTo(target.x, target.y);
    ctx.strokeStyle = isHighlighted ? 'rgba(255, 255, 255, 0.6)' : 'rgba(100, 100, 100, 0.2)';
    ctx.lineWidth = isHighlighted ? 1.5 / globalScale : 0.5 / globalScale;
    ctx.stroke();

    // Draw arrow
    if (isHighlighted) {
      const dx = target.x - source.x;
      const dy = target.y - source.y;
      const angle = Math.atan2(dy, dx);
      const targetSize = (target.val || 6);

      const arrowX = target.x - Math.cos(angle) * targetSize;
      const arrowY = target.y - Math.sin(angle) * targetSize;
      const arrowSize = 4 / globalScale;

      ctx.beginPath();
      ctx.moveTo(arrowX, arrowY);
      ctx.lineTo(
        arrowX - arrowSize * Math.cos(angle - Math.PI / 6),
        arrowY - arrowSize * Math.sin(angle - Math.PI / 6)
      );
      ctx.lineTo(
        arrowX - arrowSize * Math.cos(angle + Math.PI / 6),
        arrowY - arrowSize * Math.sin(angle + Math.PI / 6)
      );
      ctx.closePath();
      ctx.fillStyle = 'rgba(255, 255, 255, 0.6)';
      ctx.fill();
    }

    // Link label on hover
    if (isHighlighted && highlightLinks.size > 0 && globalScale > 1) {
      const midX = (source.x + target.x) / 2;
      const midY = (source.y + target.y) / 2;
      const fontSize = 10 / globalScale;

      ctx.font = `${fontSize}px Sans-Serif`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillStyle = 'rgba(255, 255, 255, 0.8)';
      ctx.fillText(link.type.replace(/_/g, ' '), midX, midY);
    }
  }, [highlightLinks]);

  // Legend component
  const Legend = useMemo(() => (
    <div className="absolute bottom-4 left-4 bg-gray-900/90 rounded-lg p-3 text-xs">
      <div className="font-semibold mb-2 text-gray-300">Entity Types</div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-1">
        {Object.entries(TYPE_COLORS)
          .filter(([type]) => type !== 'default')
          .map(([type, color]) => (
            <div key={type} className="flex items-center gap-2">
              <div
                className="w-3 h-3 rounded-full"
                style={{ backgroundColor: color }}
              />
              <span className="text-gray-400">{type}</span>
            </div>
          ))}
      </div>
    </div>
  ), []);

  return (
    <div
      ref={containerRef}
      className="fixed inset-0 bg-gray-900 flex flex-col z-50"
    >
      {/* Header */}
      <div className="px-6 py-4 bg-gray-800 border-b border-gray-700 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <h2 className="text-xl font-bold">Knowledge Graph</h2>
          <span className="text-sm text-gray-400">
            {graphData.nodes.length} nodes, {graphData.links.length} relationships
          </span>
        </div>
        <button
          onClick={onClose}
          className="text-gray-400 hover:text-white transition-colors text-2xl"
        >
          &times;
        </button>
      </div>

      {/* Controls */}
      <div className="px-6 py-3 bg-gray-800/50 border-b border-gray-700 flex items-center gap-4">
        <select
          value={selectedType}
          onChange={(e) => setSelectedType(e.target.value)}
          className="px-3 py-1.5 bg-gray-700 border border-gray-600 rounded text-sm focus:outline-none focus:border-blue-500"
        >
          {ENTITY_TYPES.map((type) => (
            <option key={type.value} value={type.value}>
              {type.label}
            </option>
          ))}
        </select>

        <label className="flex items-center gap-2 text-sm text-gray-300">
          <input
            type="checkbox"
            checked={showLabels}
            onChange={(e) => setShowLabels(e.target.checked)}
            className="rounded bg-gray-700 border-gray-600"
          />
          Show labels
        </label>

        <button
          onClick={loadGraph}
          disabled={isLoading}
          className="px-3 py-1.5 bg-blue-600 hover:bg-blue-700 rounded text-sm transition-colors disabled:opacity-50"
        >
          {isLoading ? 'Loading...' : 'Refresh'}
        </button>

        <button
          onClick={() => {
            if (graphRef.current) {
              graphRef.current.zoomToFit(400);
            }
          }}
          className="px-3 py-1.5 bg-gray-700 hover:bg-gray-600 rounded text-sm transition-colors"
        >
          Fit to View
        </button>

        <div className="flex-1" />

        <div className="text-sm text-gray-400">
          Click node to focus | Double-click for details | Drag to pan | Scroll to zoom
        </div>
      </div>

      {/* Graph Area */}
      <div className="flex-1 relative">
        {error ? (
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="text-center">
              <div className="text-red-400 mb-2 text-lg">{error}</div>
              <p className="text-gray-500">Make sure Neo4j is running and connected.</p>
            </div>
          </div>
        ) : isLoading && graphData.nodes.length === 0 ? (
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="text-gray-400">Loading graph...</div>
          </div>
        ) : (
          <ForceGraph2D
            ref={graphRef}
            width={dimensions.width}
            height={dimensions.height}
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
            onNodeClick={handleNodeClick as any}
            onNodeDragEnd={(node) => {
              node.fx = node.x;
              node.fy = node.y;
            }}
            onBackgroundClick={() => {
              setSelectedNode(null);
              setHighlightNodes(new Set());
              setHighlightLinks(new Set());
            }}
            onBackgroundRightClick={() => {
              // Release all fixed nodes
              graphData.nodes.forEach((node) => {
                node.fx = undefined;
                node.fy = undefined;
              });
            }}
            cooldownTicks={100}
            d3AlphaDecay={0.02}
            d3VelocityDecay={0.3}
            backgroundColor="#111827"
          />
        )}

        {/* Legend */}
        {Legend}

        {/* Node info panel */}
        {(hoveredNode || selectedNode) && (
          <div className="absolute top-4 right-4 bg-gray-800/95 rounded-lg p-4 max-w-xs border border-gray-700">
            <div className="flex items-center gap-2 mb-2">
              <div
                className="w-4 h-4 rounded-full"
                style={{
                  backgroundColor:
                    TYPE_COLORS[(hoveredNode || selectedNode)!.entity_type] ||
                    TYPE_COLORS.default,
                }}
              />
              <span className="font-semibold">
                {(hoveredNode || selectedNode)!.name}
              </span>
            </div>
            <div className="text-xs text-gray-400 uppercase tracking-wide mb-2">
              {(hoveredNode || selectedNode)!.entity_type}
            </div>
            {(hoveredNode || selectedNode)!.description && (
              <p className="text-sm text-gray-300 line-clamp-3">
                {(hoveredNode || selectedNode)!.description}
              </p>
            )}
            {selectedNode && (
              <button
                onClick={() => handleNodeDoubleClick(selectedNode)}
                className="mt-3 w-full px-3 py-1.5 bg-blue-600 hover:bg-blue-700 rounded text-sm transition-colors"
              >
                View Details
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
