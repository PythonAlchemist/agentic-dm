import { useState, useEffect, useCallback } from 'react';
import { campaignAPI } from '../api/client';
import type { Entity } from '../types';

interface Props {
  onClose: () => void;
  onSelectEntity: (entity: Entity) => void;
}

const ENTITY_TYPES = [
  { value: '', label: 'All Types' },
  { value: 'PC', label: 'Player Characters' },
  { value: 'NPC', label: 'NPCs' },
  { value: 'LOCATION', label: 'Locations' },
  { value: 'ITEM', label: 'Items' },
  { value: 'FACTION', label: 'Factions' },
  { value: 'EVENT', label: 'Events' },
];

const ENTITY_ICONS: Record<string, string> = {
  PC: '🧙',
  NPC: '👤',
  LOCATION: '🏰',
  ITEM: '⚔️',
  FACTION: '🏴',
  EVENT: '📜',
  MONSTER: '👹',
  SPELL: '✨',
  default: '📋',
};

export function CampaignDashboard({ onClose, onSelectEntity }: Props) {
  const [entities, setEntities] = useState<Entity[]>([]);
  const [selectedType, setSelectedType] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadEntities = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      if (searchQuery) {
        const result = await campaignAPI.search(
          searchQuery,
          selectedType ? [selectedType] : undefined
        );
        setEntities(result.results);
      } else {
        const result = await campaignAPI.listEntities(
          selectedType || undefined,
          50
        );
        setEntities(result.entities);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load entities');
      setEntities([]);
    } finally {
      setIsLoading(false);
    }
  }, [selectedType, searchQuery]);

  useEffect(() => {
    loadEntities();
  }, [loadEntities]);

  const getEntityIcon = (entityType: string) => {
    return ENTITY_ICONS[entityType] || ENTITY_ICONS.default;
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-gray-800 rounded-lg shadow-xl w-full max-w-4xl max-h-[80vh] flex flex-col">
        {/* Header */}
        <div className="px-6 py-4 border-b border-gray-700 flex items-center justify-between">
          <h2 className="text-xl font-bold">Campaign Knowledge Graph</h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-white transition-colors"
          >
            ✕
          </button>
        </div>

        {/* Filters */}
        <div className="px-6 py-4 border-b border-gray-700 flex gap-4">
          <div className="flex-1">
            <input
              type="text"
              placeholder="Search entities..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full px-4 py-2 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:border-blue-500"
            />
          </div>
          <select
            value={selectedType}
            onChange={(e) => setSelectedType(e.target.value)}
            className="px-4 py-2 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:border-blue-500"
          >
            {ENTITY_TYPES.map((type) => (
              <option key={type.value} value={type.value}>
                {type.label}
              </option>
            ))}
          </select>
          <button
            onClick={loadEntities}
            disabled={isLoading}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors disabled:opacity-50"
          >
            {isLoading ? 'Loading...' : 'Refresh'}
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6">
          {error ? (
            <div className="text-center py-8">
              <div className="text-red-400 mb-2">⚠️ {error}</div>
              <p className="text-gray-500 text-sm">
                Make sure Neo4j is running and connected.
              </p>
            </div>
          ) : entities.length === 0 ? (
            <div className="text-center py-8 text-gray-400">
              {isLoading ? 'Loading entities...' : 'No entities found'}
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {entities.map((entity) => (
                <EntityCard
                  key={entity.id}
                  entity={entity}
                  icon={getEntityIcon(entity.entity_type)}
                  onClick={() => onSelectEntity(entity)}
                />
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-gray-700 flex justify-between items-center">
          <span className="text-sm text-gray-400">
            {entities.length} entities
          </span>
          <button
            onClick={onClose}
            className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg transition-colors"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

interface EntityCardProps {
  entity: Entity;
  icon: string;
  onClick: () => void;
}

function EntityCard({ entity, icon, onClick }: EntityCardProps) {
  return (
    <button
      onClick={onClick}
      className="p-4 bg-gray-700/50 hover:bg-gray-700 rounded-lg text-left transition-colors"
    >
      <div className="flex items-start gap-3">
        <div className="text-2xl">{icon}</div>
        <div className="flex-1 min-w-0">
          <div className="font-medium truncate">{entity.name}</div>
          <div className="text-xs text-gray-400 uppercase tracking-wide">
            {entity.entity_type}
          </div>
          {entity.description && (
            <p className="text-sm text-gray-300 mt-2 line-clamp-2">
              {entity.description}
            </p>
          )}
          {entity.aliases && entity.aliases.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
              {entity.aliases.slice(0, 3).map((alias, i) => (
                <span
                  key={i}
                  className="text-xs px-2 py-0.5 bg-gray-600 rounded"
                >
                  {alias}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>
    </button>
  );
}
