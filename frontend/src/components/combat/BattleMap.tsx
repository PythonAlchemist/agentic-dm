import { useMemo } from 'react';
import type { Combatant, GridSize } from './types';
import { BattleMapToken } from './BattleMapToken';

interface BattleMapProps {
  combatants: Combatant[];
  positions: Map<string, { x: number; y: number }>;
  gridSize: GridSize;
  currentTurnName: string | null;
  selectedToken: string | null;
  onSelectToken: (name: string | null) => void;
  onCellClick: (x: number, y: number) => void;
}

// Column labels A-T
const COL_LABELS = 'ABCDEFGHIJKLMNOPQRST'.split('');

export function BattleMap({
  combatants,
  positions,
  gridSize,
  currentTurnName,
  selectedToken,
  onSelectToken,
  onCellClick,
}: BattleMapProps) {
  // Build a lookup: "x,y" -> combatant
  const positionMap = useMemo(() => {
    const map = new Map<string, Combatant>();
    for (const c of combatants) {
      const pos = positions.get(c.name);
      if (pos) {
        map.set(`${pos.x},${pos.y}`, c);
      }
    }
    return map;
  }, [combatants, positions]);

  const handleCellClick = (x: number, y: number) => {
    const occupant = positionMap.get(`${x},${y}`);
    if (occupant) {
      // Clicked on a token
      if (selectedToken === occupant.name) {
        onSelectToken(null); // Deselect
      } else {
        onSelectToken(occupant.name);
      }
    } else if (selectedToken) {
      // Clicked empty cell with a token selected -> move
      onCellClick(x, y);
    }
  };

  return (
    <div className="flex flex-col select-none">
      {/* Column labels */}
      <div className="flex ml-6">
        {Array.from({ length: gridSize.width }, (_, x) => (
          <div
            key={x}
            className="flex-1 text-center text-[9px] text-gray-500 font-mono"
          >
            {COL_LABELS[x] || ''}
          </div>
        ))}
      </div>

      <div className="flex">
        {/* Row labels */}
        <div className="flex flex-col w-6 flex-shrink-0">
          {Array.from({ length: gridSize.height }, (_, y) => (
            <div
              key={y}
              className="flex-1 flex items-center justify-center text-[9px] text-gray-500 font-mono"
              style={{ minHeight: '2.5rem' }}
            >
              {y + 1}
            </div>
          ))}
        </div>

        {/* Grid */}
        <div
          className="flex-1 border border-gray-600/40 rounded"
          style={{
            display: 'grid',
            gridTemplateColumns: `repeat(${gridSize.width}, 1fr)`,
            gridTemplateRows: `repeat(${gridSize.height}, 1fr)`,
            aspectRatio: `${gridSize.width} / ${gridSize.height}`,
          }}
        >
          {Array.from({ length: gridSize.height }, (_, y) =>
            Array.from({ length: gridSize.width }, (_, x) => {
              const key = `${x},${y}`;
              const occupant = positionMap.get(key);
              const isDark = (x + y) % 2 === 0;

              return (
                <div
                  key={key}
                  onClick={() => handleCellClick(x, y)}
                  className={`
                    flex items-center justify-center
                    border border-gray-700/20 transition-colors
                    ${isDark ? 'bg-gray-800/60' : 'bg-gray-800/30'}
                    ${selectedToken && !occupant ? 'hover:bg-blue-600/20 cursor-crosshair' : ''}
                    ${!selectedToken && !occupant ? 'cursor-default' : ''}
                  `}
                  style={{ minHeight: '2.5rem', minWidth: '2.5rem' }}
                >
                  {occupant && (
                    <BattleMapToken
                      combatant={occupant}
                      isCurrentTurn={occupant.name === currentTurnName}
                      isSelected={occupant.name === selectedToken}
                      onClick={() => {
                        if (selectedToken === occupant.name) {
                          onSelectToken(null);
                        } else {
                          onSelectToken(occupant.name);
                        }
                      }}
                    />
                  )}
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}
