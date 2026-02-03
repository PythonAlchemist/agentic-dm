import { useState, useEffect } from 'react';
import { campaignAPI } from '../api/client';
import type { Entity } from '../types';

interface Props {
  entity: Entity;
  onClose: () => void;
  onNavigate: (entity: Entity) => void;
}

export function EntityDetail({ entity, onClose, onNavigate }: Props) {
  const [neighbors, setNeighbors] = useState<Entity[]>([]);
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    loadNeighbors();
  }, [entity.id]);

  const loadNeighbors = async () => {
    setIsLoading(true);
    try {
      const result = await campaignAPI.getNeighbors(entity.id, 1);
      setNeighbors(result.neighbors);
    } catch (err) {
      console.error('Failed to load neighbors:', err);
      setNeighbors([]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-gray-800 rounded-lg shadow-xl w-full max-w-2xl max-h-[80vh] flex flex-col">
        {/* Header */}
        <div className="px-6 py-4 border-b border-gray-700 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <EntityIcon type={entity.entity_type} />
            <div>
              <h2 className="text-xl font-bold">{entity.name}</h2>
              <span className="text-sm text-gray-400 uppercase tracking-wide">
                {entity.entity_type}
              </span>
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-white transition-colors"
          >
            ✕
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {/* Description */}
          {entity.description && (
            <section>
              <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-2">
                Description
              </h3>
              <p className="text-gray-200">{entity.description}</p>
            </section>
          )}

          {/* Aliases */}
          {entity.aliases && entity.aliases.length > 0 && (
            <section>
              <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-2">
                Also Known As
              </h3>
              <div className="flex flex-wrap gap-2">
                {entity.aliases.map((alias, i) => (
                  <span
                    key={i}
                    className="px-3 py-1 bg-gray-700 rounded-full text-sm"
                  >
                    {alias}
                  </span>
                ))}
              </div>
            </section>
          )}

          {/* Properties */}
          {(() => {
            const excludeKeys = ['id', 'name', 'entity_type', 'description', 'aliases', 'created_at', 'updated_at', 'relationship_types', 'distance'];
            const properties = Object.entries(entity).filter(([key]) => !excludeKeys.includes(key));
            return properties.length > 0 ? (
              <section>
                <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-2">
                  Properties
                </h3>
                <dl className="grid grid-cols-2 gap-2">
                  {properties.map(([key, value]) => (
                    <div key={key} className="bg-gray-700/50 rounded p-2">
                      <dt className="text-xs text-gray-400">{key}</dt>
                      <dd className="text-sm font-medium">
                        {String(value)}
                      </dd>
                    </div>
                  ))}
                </dl>
              </section>
            ) : null;
          })()}

          {/* Related Entities */}
          <section>
            <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-2">
              Related Entities
            </h3>
            {isLoading ? (
              <div className="text-gray-400 text-sm">Loading...</div>
            ) : neighbors.length === 0 ? (
              <div className="text-gray-400 text-sm">No related entities</div>
            ) : (
              <div className="grid grid-cols-2 gap-2">
                {neighbors.map((neighbor) => (
                  <button
                    key={neighbor.id}
                    onClick={() => onNavigate(neighbor)}
                    className="flex items-center gap-2 p-2 bg-gray-700/50 hover:bg-gray-700 rounded transition-colors text-left"
                  >
                    <EntityIcon type={neighbor.entity_type} size="sm" />
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium truncate">
                        {neighbor.name}
                      </div>
                      <div className="text-xs text-gray-400">
                        {neighbor.entity_type}
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </section>

          {/* Metadata */}
          {entity.created_at && (
            <section className="text-xs text-gray-500">
              Created: {new Date(entity.created_at).toLocaleDateString()}
            </section>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-gray-700 flex justify-end gap-2">
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

interface EntityIconProps {
  type: string;
  size?: 'sm' | 'md';
}

function EntityIcon({ type, size = 'md' }: EntityIconProps) {
  const icons: Record<string, string> = {
    PC: '🧙',
    NPC: '👤',
    LOCATION: '🏰',
    ITEM: '⚔️',
    FACTION: '🏴',
    EVENT: '📜',
    MONSTER: '👹',
    SPELL: '✨',
  };

  const sizeClass = size === 'sm' ? 'text-xl' : 'text-3xl';

  return (
    <span className={sizeClass}>{icons[type] || '📋'}</span>
  );
}
