import { useState, useEffect } from 'react';
import type { Player, ChatMessage } from '../../types';
import { useCombatState } from './useCombatState';
import { CombatSetup } from './CombatSetup';
import { InitiativePanel } from './InitiativePanel';
import { BattleMap } from './BattleMap';
import { CombatLog } from './CombatLog';
import { AddCombatantPanel } from './AddCombatantPanel';

interface CombatDashboardProps {
  onClose: () => void;
  players?: Player[];
  onNPCTurn?: (message: ChatMessage) => void;
}

export function CombatDashboard({ onClose, players = [], onNPCTurn }: CombatDashboardProps) {
  const {
    combatState,
    setupCombatants,
    showAddCombatant,
    isLoading,
    error,
    activeTurnName,
    combatLog,
    gridSize,
    positions,
    selectedToken,
    setShowAddCombatant,
    startCombat,
    addFromPlayers,
    addCombatant,
    removeCombatant,
    nextTurn,
    applyDamage,
    applyHealing,
    endCombat,
    setSelectedToken,
    moveCombatant,
    addCombatantMidCombat,
    removeCombatantMidCombat,
  } = useCombatState({ players, onNPCTurn });

  const [showLog, setShowLog] = useState(false);
  const [showRemoveMenu, setShowRemoveMenu] = useState(false);

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Don't trigger shortcuts when typing in inputs
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;

      if (e.key === 'Escape') {
        setSelectedToken(null);
        setShowRemoveMenu(false);
      }
      if (e.key === 'n' && combatState && !isLoading && !showAddCombatant) {
        nextTurn();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [setSelectedToken, combatState, isLoading, showAddCombatant, nextTurn]);

  const currentTurnName = activeTurnName
    || combatState?.initiative_order[combatState.current_turn_idx]?.name
    || null;

  return (
    <div className="flex-[2] flex flex-col bg-gray-800 border-r border-gray-700 min-w-0">
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-700 flex items-center justify-between bg-gray-900/50 flex-shrink-0">
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-bold">Combat</h2>
          {combatState && (
            <span className="px-2 py-0.5 bg-red-600/30 text-red-400 rounded-full text-xs font-medium">
              Round {combatState.round}
            </span>
          )}
          {isLoading && (
            <span className="text-yellow-400 text-xs animate-pulse">Processing...</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {combatState && (
            <>
              <button
                onClick={() => setShowAddCombatant(true)}
                className="px-2 py-1 text-xs bg-green-700 hover:bg-green-600 rounded transition-colors"
                title="Add combatant mid-combat"
              >
                + Add
              </button>
              <div className="relative">
                <button
                  onClick={() => setShowRemoveMenu(!showRemoveMenu)}
                  className="px-2 py-1 text-xs bg-red-700 hover:bg-red-600 rounded transition-colors"
                  title="Remove combatant"
                >
                  - Remove
                </button>
                {showRemoveMenu && (
                  <div className="absolute right-0 top-full mt-1 w-48 bg-gray-700 rounded-lg shadow-xl border border-gray-600 z-20 max-h-48 overflow-y-auto">
                    {combatState.initiative_order
                      .filter(c => c.hp > 0)
                      .map(c => (
                        <button
                          key={c.name}
                          onClick={() => {
                            removeCombatantMidCombat(c.name);
                            setShowRemoveMenu(false);
                          }}
                          className="w-full text-left px-3 py-2 text-sm hover:bg-gray-600 transition-colors flex items-center gap-2"
                        >
                          <span className={`w-2 h-2 rounded-full ${
                            c.is_player ? 'bg-blue-500' : c.is_npc ? 'bg-purple-500' : 'bg-red-500'
                          }`} />
                          {c.name}
                        </button>
                      ))}
                  </div>
                )}
              </div>
              <button
                onClick={() => setShowLog(!showLog)}
                className={`px-2 py-1 text-xs rounded transition-colors ${
                  showLog ? 'bg-purple-600 text-white' : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                }`}
              >
                Log
              </button>
            </>
          )}
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-white transition-colors text-sm"
            title="Close combat panel"
          >
            ✕
          </button>
        </div>
      </div>

      {/* Error Display */}
      {error && (
        <div className="mx-4 mt-3 p-2 bg-red-600/20 border border-red-600 rounded text-red-400 text-xs flex-shrink-0">
          {error}
        </div>
      )}

      {/* Content */}
      <div className="flex-1 overflow-hidden p-3 min-h-0">
        {!combatState ? (
          <div className="overflow-y-auto h-full">
            <CombatSetup
              setupCombatants={setupCombatants}
              players={players}
              isLoading={isLoading}
              onAddFromPlayers={addFromPlayers}
              onOpenAddCombatant={() => setShowAddCombatant(true)}
              onRemoveCombatant={removeCombatant}
              onStartCombat={startCombat}
            />
          </div>
        ) : (
          // Combat Phase: BattleMap + Initiative Panel + optional Log
          <div className="flex gap-3 h-full min-h-0">
            {/* BattleMap */}
            <div className="flex-1 overflow-auto min-w-0">
              <BattleMap
                combatants={combatState.initiative_order}
                positions={positions}
                gridSize={gridSize}
                currentTurnName={currentTurnName}
                selectedToken={selectedToken}
                onSelectToken={setSelectedToken}
                onCellClick={(x, y) => {
                  if (selectedToken) {
                    moveCombatant(selectedToken, x, y);
                  }
                }}
              />
            </div>

            {/* Initiative Panel */}
            <InitiativePanel
              combatants={combatState.initiative_order}
              currentTurnIdx={combatState.current_turn_idx}
              activeTurnName={activeTurnName}
              onDamage={applyDamage}
              onHeal={applyHealing}
            />

            {/* Combat Log (collapsible) */}
            {showLog && (
              <CombatLog entries={combatLog} />
            )}
          </div>
        )}
      </div>

      {/* Action Bar */}
      <div className="px-4 py-3 border-t border-gray-700 flex justify-between items-center bg-gray-900/50 flex-shrink-0">
        {combatState ? (
          <>
            <div className="text-xs text-gray-400 truncate mr-2">
              Current: {currentTurnName}
              {(activeTurnName || combatState.current_is_npc) && (
                <span className="ml-1 text-purple-400">(AI)</span>
              )}
              {selectedToken && (
                <span className="ml-2 text-yellow-400">
                  Moving: {selectedToken} (click cell or Esc)
                </span>
              )}
            </div>
            <div className="flex gap-2 flex-shrink-0">
              <button
                onClick={endCombat}
                disabled={isLoading}
                className="px-3 py-1.5 text-sm bg-gray-700 hover:bg-gray-600 rounded-lg transition-colors disabled:opacity-50"
              >
                End Combat
              </button>
              <button
                onClick={nextTurn}
                disabled={isLoading}
                className="px-3 py-1.5 text-sm bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors disabled:opacity-50"
              >
                {isLoading ? 'Processing...' : 'Next Turn (N)'}
              </button>
            </div>
          </>
        ) : (
          <button
            onClick={onClose}
            className="ml-auto px-3 py-1.5 text-sm bg-gray-700 hover:bg-gray-600 rounded-lg transition-colors"
          >
            Close
          </button>
        )}
      </div>

      {/* Add Combatant Modal */}
      {showAddCombatant && (
        <AddCombatantPanel
          onClose={() => setShowAddCombatant(false)}
          onAdd={combatState ? addCombatantMidCombat : addCombatant}
          midCombat={!!combatState}
        />
      )}
    </div>
  );
}
