import { useState, useCallback, useRef, useEffect } from 'react';
import type { Combatant, CombatState, Player, ChatMessage } from '../types';
import { combatAPI } from '../api/client';
import type { AvailableNPC } from '../api/client';

const NPC_TURN_DELAY = 2500; // ms between NPC turn reveals
const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

interface Props {
  onClose: () => void;
  players?: Player[];
  onNPCTurn?: (message: ChatMessage) => void;
}

// Types for setup phase (before combat starts)
interface SetupCombatant {
  name: string;
  initiative_bonus: number;
  hp: number;
  max_hp: number;
  ac: number;
  is_player: boolean;
  is_npc: boolean;  // AI-controlled
  is_friendly?: boolean;  // Fights alongside players
  npc_id?: string;
  player_id?: string;
  player_name?: string;
  pc_id?: string;
}

export function CombatTracker({ onClose, players = [], onNPCTurn }: Props) {
  const [combatState, setCombatState] = useState<CombatState | null>(null);
  const [setupCombatants, setSetupCombatants] = useState<SetupCombatant[]>([]);
  const [showAddCombatant, setShowAddCombatant] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Track which NPC is actively taking their turn (for highlight sync during slow roll)
  const [activeTurnName, setActiveTurnName] = useState<string | null>(null);

  // Combat log for theatrical display
  interface CombatLogEntry {
    id: number;
    type: 'npc' | 'system';
    npcName?: string;
    dialogue?: string;
    action?: string;
    target?: string;
    result?: string;
    message?: string;
  }
  const [combatLog, setCombatLog] = useState<CombatLogEntry[]>([]);
  const logIdRef = useRef(0);

  // Helper to display a single NPC turn result in the combat log + chat
  const displayNPCTurn = useCallback((npcTurn: { combatant_name: string; narration: string; npc_action?: any }) => {
    let actionDesc = '';
    let resultDesc = '';

    if (npcTurn.npc_action) {
      const action = npcTurn.npc_action.action;
      actionDesc = action?.action_name
        ? `${action.action_type} - ${action.action_name}`
        : action?.action_type || '';

      if (npcTurn.npc_action.hit !== undefined) {
        resultDesc = npcTurn.npc_action.hit
          ? `Hit! ${npcTurn.npc_action.damage_dealt || 0} damage`
          : 'Miss';
      }
    }

    setCombatLog(prev => [...prev, {
      id: ++logIdRef.current,
      type: 'npc',
      npcName: npcTurn.combatant_name,
      dialogue: npcTurn.npc_action?.action?.combat_dialogue,
      action: actionDesc || npcTurn.narration,
      target: npcTurn.npc_action?.action?.target_name,
      result: resultDesc,
    }]);

    if (onNPCTurn) {
      onNPCTurn({
        role: 'npc',
        content: npcTurn.narration || '',
        npcData: {
          name: npcTurn.combatant_name,
          dialogue: npcTurn.npc_action?.action?.combat_dialogue,
          action: actionDesc || npcTurn.narration,
          target: npcTurn.npc_action?.action?.target_name,
          result: resultDesc,
        },
      });
    }
  }, [onNPCTurn]);

  // Slow-roll multiple NPC turn results with delays
  const slowRollNPCTurns = useCallback(async (npcTurns: any[]) => {
    for (let i = 0; i < npcTurns.length; i++) {
      // Highlight the NPC whose turn is about to display
      setActiveTurnName(npcTurns[i].combatant_name);
      if (i > 0) await sleep(NPC_TURN_DELAY);
      displayNPCTurn(npcTurns[i]);

      // Refresh combat status after each NPC turn for HP updates
      try {
        const status = await combatAPI.getStatus();
        if ('initiative_order' in status) {
          const initiativeOrder: Combatant[] = status.initiative_order.map((c: any) => ({
            name: c.name,
            initiative: c.initiative,
            hp: c.hp,
            max_hp: c.max_hp,
            is_player: c.is_player,
            is_npc: c.is_npc,
            conditions: c.conditions || [],
          }));

          const currentIdx = initiativeOrder.findIndex(c => c.name === status.current.name);
          setCombatState({
            round: status.round,
            initiative_order: initiativeOrder,
            current_turn_idx: currentIdx >= 0 ? currentIdx : 0,
            active: status.active,
            current_turn_type: status.current_turn_type,
            current_is_npc: status.current_is_npc,
          });
        }
      } catch {
        // Status refresh is best-effort during slow roll
      }
    }
    // Clear override so the real current turn highlights
    setActiveTurnName(null);
  }, [displayNPCTurn]);

  // Helper to emit combat system message
  const emitCombatMessage = useCallback((type: 'round_start' | 'turn_start' | 'action' | 'combat_end', content: string, round?: number) => {
    // Add to local combat log
    setCombatLog(prev => [...prev, {
      id: ++logIdRef.current,
      type: 'system',
      message: content,
    }]);

    // Also emit to main chat
    if (onNPCTurn) {
      onNPCTurn({
        role: 'combat',
        content,
        combatData: { type, round },
      });
    }
  }, [onNPCTurn]);

  const startCombat = async () => {
    setIsLoading(true);
    setError(null);
    setCombatLog([]); // Clear combat log

    try {
      // Separate combatants into players, npcs (AI), and monsters (DM-controlled)
      const playerCombatants = setupCombatants
        .filter(c => c.is_player)
        .map(c => ({
          name: c.name,
          initiative_bonus: c.initiative_bonus,
          hp: c.hp,
          max_hp: c.max_hp,
          ac: c.ac,
          player_id: c.player_id,
          player_name: c.player_name,
          pc_id: c.pc_id,
        }));

      const npcCombatants = setupCombatants
        .filter(c => c.is_npc && c.npc_id)
        .map(c => ({
          name: c.name,
          npc_id: c.npc_id!,
          initiative_bonus: c.initiative_bonus,
          hp: c.hp,
          max_hp: c.max_hp,
          ac: c.ac,
          ...(c.is_friendly !== undefined && { is_friendly: c.is_friendly }),
        }));

      const monsterCombatants = setupCombatants
        .filter(c => !c.is_player && !c.is_npc)
        .map(c => ({
          name: c.name,
          initiative_bonus: c.initiative_bonus,
          hp: c.hp,
          max_hp: c.max_hp,
          ac: c.ac,
        }));

      const result = await combatAPI.start({
        players: playerCombatants,
        npcs: npcCombatants,
        monsters: monsterCombatants,
        auto_npc_turns: true,
      });

      // Map backend response to our CombatState
      const initiativeOrder: Combatant[] = result.initiative_order.map((c) => ({
        name: c.name,
        initiative: c.initiative,
        hp: c.hp,
        max_hp: c.max_hp,
        is_player: c.is_player,
        is_npc: c.is_npc,
        conditions: [],
      }));

      // Find the current turn index by name
      const currentIdx = initiativeOrder.findIndex(c => c.name === result.current_turn);

      setCombatState({
        round: result.round,
        initiative_order: initiativeOrder,
        current_turn_idx: currentIdx >= 0 ? currentIdx : 0,
        active: true,
        current_is_npc: result.current_is_npc,
      });

      // Emit combat started message to chat
      emitCombatMessage('round_start', `Combat begins! Round ${result.round}`, result.round);

      // Slow-roll any NPC turns that happened before the first player turn
      if (result.npc_turn_results && result.npc_turn_results.length > 0) {
        await sleep(1000); // Brief pause after "combat begins"
        await slowRollNPCTurns(result.npc_turn_results);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start combat');
    } finally {
      setIsLoading(false);
    }
  };

  const addFromPlayers = () => {
    const playerCombatants: SetupCombatant[] = players
      .filter((p) => p.active_pc)
      .map((p) => ({
        name: p.active_pc!.name,
        initiative_bonus: p.active_pc!.initiative_bonus || 0,
        hp: p.active_pc!.hp || 10,
        max_hp: p.active_pc!.max_hp || 10,
        ac: 15,
        is_player: true,
        is_npc: false,
        player_id: p.id,
        player_name: p.name,
        pc_id: p.active_pc!.id,
      }));

    setSetupCombatants((prev) => [...prev, ...playerCombatants]);
  };

  const addCombatant = (combatant: SetupCombatant) => {
    setSetupCombatants((prev) => [...prev, combatant]);
    setShowAddCombatant(false);
  };

  const removeCombatant = (index: number) => {
    setSetupCombatants((prev) => prev.filter((_, i) => i !== index));
  };

  const nextTurn = async () => {
    if (!combatState) return;

    setIsLoading(true);
    setError(null);

    try {
      // End current turn and process next (auto-processes NPC turns)
      const result = await combatAPI.endTurn();

      // Refresh combat status
      const status = await combatAPI.getStatus();

      if ('active' in status && status.active === false) {
        // Combat ended
        setCombatState(null);
        setSetupCombatants([]);
        return;
      }

      if ('initiative_order' in status) {
        const initiativeOrder: Combatant[] = status.initiative_order.map(c => ({
          name: c.name,
          initiative: c.initiative,
          hp: c.hp,
          max_hp: c.max_hp,
          is_player: c.is_player,
          conditions: c.conditions || [],
        }));

        const currentIdx = initiativeOrder.findIndex(c => c.name === status.current.name);

        setCombatState({
          round: status.round,
          initiative_order: initiativeOrder,
          current_turn_idx: currentIdx >= 0 ? currentIdx : 0,
          active: status.active,
          current_turn_type: status.current_turn_type,
          current_is_npc: status.current_is_npc,
        });
      }

      // Slow-roll NPC turn results one at a time
      if (result.npc_turn_results && result.npc_turn_results.length > 0) {
        await slowRollNPCTurns(result.npc_turn_results);
      }

      // Check for round change
      if (status && 'round' in status && status.round > (combatState?.round || 1)) {
        emitCombatMessage('round_start', `Round ${status.round}`, status.round);
      }

      // Check for combat end
      if (!result.combat_active && result.combat_ended_reason) {
        emitCombatMessage('combat_end', `Combat ended: ${result.combat_ended_reason}`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to advance turn');
    } finally {
      setIsLoading(false);
    }
  };

  const applyDamage = useCallback(async (targetName: string, damage: number) => {
    if (!combatState) return;

    try {
      const result = await combatAPI.applyDamage(targetName, damage);

      // Update local state
      setCombatState(prev => {
        if (!prev) return prev;

        const updated = prev.initiative_order.map(c =>
          c.name === targetName
            ? { ...c, hp: result.current_hp }
            : c
        );

        return { ...prev, initiative_order: updated };
      });

      // Check if combat ended
      if (result.combat_ended) {
        setCombatState(null);
        setSetupCombatants([]);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to apply damage');
    }
  }, [combatState]);

  const applyHealing = useCallback(async (targetName: string, healing: number) => {
    if (!combatState) return;

    try {
      const result = await combatAPI.applyHealing(targetName, healing);

      // Update local state
      setCombatState(prev => {
        if (!prev) return prev;

        const updated = prev.initiative_order.map(c =>
          c.name === targetName
            ? { ...c, hp: result.current_hp }
            : c
        );

        return { ...prev, initiative_order: updated };
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to apply healing');
    }
  }, [combatState]);

  const endCombat = async () => {
    setIsLoading(true);

    try {
      const summary = await combatAPI.end();
      console.log('Combat summary:', summary);

      // Emit combat end message to chat
      const survivorNames = summary.survivors.map(s => s.name).join(', ');
      emitCombatMessage('combat_end', `Combat ended after ${summary.rounds} rounds. Survivors: ${survivorNames || 'None'}`);
    } catch (err) {
      // Combat might already be ended
      emitCombatMessage('combat_end', 'Combat ended');
    } finally {
      setCombatState(null);
      setSetupCombatants([]);
      setIsLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-gray-800 rounded-lg shadow-xl w-full max-w-4xl max-h-[85vh] flex flex-col">
        {/* Header */}
        <div className="px-6 py-4 border-b border-gray-700 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <h2 className="text-xl font-bold">Combat Tracker</h2>
            {combatState && (
              <span className="px-3 py-1 bg-red-600/30 text-red-400 rounded-full text-sm">
                Round {combatState.round}
              </span>
            )}
            {isLoading && (
              <span className="text-yellow-400 text-sm animate-pulse">Processing...</span>
            )}
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-white transition-colors"
          >
            ✕
          </button>
        </div>

        {/* Error Display */}
        {error && (
          <div className="mx-6 mt-4 p-3 bg-red-600/20 border border-red-600 rounded-lg text-red-400 text-sm">
            {error}
          </div>
        )}

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6">
          {!combatState ? (
            // Setup Phase
            <div className="space-y-6">
              <div className="flex items-center justify-between">
                <h3 className="font-medium">Combatants</h3>
                <div className="flex gap-2">
                  {players.length > 0 && (
                    <button
                      onClick={addFromPlayers}
                      className="px-3 py-1 text-sm bg-green-600 hover:bg-green-700 rounded transition-colors"
                    >
                      + Add Players
                    </button>
                  )}
                  <button
                    onClick={() => setShowAddCombatant(true)}
                    className="px-3 py-1 text-sm bg-blue-600 hover:bg-blue-700 rounded transition-colors"
                  >
                    + Add Monster/NPC
                  </button>
                </div>
              </div>

              {setupCombatants.length === 0 ? (
                <div className="text-center text-gray-400 py-8">
                  Add combatants to start combat
                </div>
              ) : (
                <div className="space-y-2">
                  {setupCombatants.map((c, idx) => (
                    <div
                      key={idx}
                      className={`p-3 rounded-lg flex items-center justify-between ${
                        c.is_player
                          ? 'bg-blue-600/20'
                          : c.is_friendly
                            ? 'bg-green-600/20 border border-green-500/30'
                            : c.is_npc
                              ? 'bg-purple-600/20 border border-purple-500/30'
                              : 'bg-red-600/20'
                      }`}
                    >
                      <div>
                        <div className="font-medium flex items-center gap-2">
                          {c.name}
                          {c.is_npc && (
                            <span className="px-2 py-0.5 bg-purple-600 text-purple-100 text-xs rounded">
                              AI
                            </span>
                          )}
                          {c.is_friendly && (
                            <span className="px-2 py-0.5 bg-green-600 text-green-100 text-xs rounded">
                              Friendly
                            </span>
                          )}
                        </div>
                        <div className="text-sm text-gray-400">
                          {c.is_player
                            ? `${c.player_name}'s character`
                            : c.is_npc
                              ? 'AI-controlled NPC'
                              : 'DM-controlled Monster'}
                          {' | '}Init: +{c.initiative_bonus || 0}
                          {' | '}HP: {c.hp}/{c.max_hp}
                          {' | '}AC: {c.ac}
                        </div>
                      </div>
                      <button
                        onClick={() => removeCombatant(idx)}
                        className="text-gray-400 hover:text-red-400 transition-colors"
                      >
                        ✕
                      </button>
                    </div>
                  ))}
                </div>
              )}

              {setupCombatants.length >= 2 && (
                <div className="flex justify-center pt-4">
                  <button
                    onClick={startCombat}
                    disabled={isLoading}
                    className="px-6 py-3 bg-red-600 hover:bg-red-700 rounded-lg font-medium transition-colors disabled:opacity-50"
                  >
                    {isLoading ? 'Starting...' : 'Roll Initiative & Start Combat'}
                  </button>
                </div>
              )}
            </div>
          ) : (
            // Combat Phase - Split Layout
            <div className="flex gap-4 h-full">
              {/* Left: Initiative Order */}
              <div className="flex-1 space-y-3 overflow-y-auto">
                {combatState.initiative_order.map((c, idx) => (
                  <CombatantCard
                    key={idx}
                    combatant={c}
                    isCurrentTurn={
                      activeTurnName
                        ? c.name === activeTurnName
                        : idx === combatState.current_turn_idx
                    }
                    onDamage={(dmg) => applyDamage(c.name, dmg)}
                    onHeal={(heal) => applyHealing(c.name, heal)}
                  />
                ))}
              </div>

              {/* Right: Combat Log */}
              <div className="w-80 bg-gray-900/50 rounded-lg border border-gray-700 flex flex-col">
                <div className="px-3 py-2 border-b border-gray-700 text-sm font-medium text-gray-400">
                  Combat Log
                </div>
                <div className="flex-1 overflow-y-auto p-3 space-y-3">
                  {combatLog.length === 0 ? (
                    <div className="text-center text-gray-500 text-sm py-4">
                      NPC actions will appear here...
                    </div>
                  ) : (
                    combatLog.map((entry) => (
                      <CombatLogEntry key={entry.id} entry={entry} />
                    ))
                  )}
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-gray-700 flex justify-between items-center">
          {combatState ? (
            <>
              <div className="text-sm text-gray-400">
                Current: {activeTurnName || combatState.initiative_order[combatState.current_turn_idx]?.name}
                {(activeTurnName || combatState.current_is_npc) && (
                  <span className="ml-2 text-purple-400">(AI Turn)</span>
                )}
              </div>
              <div className="flex gap-3">
                <button
                  onClick={endCombat}
                  disabled={isLoading}
                  className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg transition-colors disabled:opacity-50"
                >
                  End Combat
                </button>
                <button
                  onClick={nextTurn}
                  disabled={isLoading}
                  className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors disabled:opacity-50"
                >
                  {isLoading ? 'Processing...' : 'Next Turn'}
                </button>
              </div>
            </>
          ) : (
            <button
              onClick={onClose}
              className="ml-auto px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg transition-colors"
            >
              Close
            </button>
          )}
        </div>
      </div>

      {/* Add Combatant Modal */}
      {showAddCombatant && (
        <AddCombatantModal
          onClose={() => setShowAddCombatant(false)}
          onAdd={addCombatant}
        />
      )}

    </div>
  );
}

interface CombatantCardProps {
  combatant: Combatant;
  isCurrentTurn: boolean;
  onDamage: (damage: number) => void;
  onHeal: (healing: number) => void;
}

function CombatantCard({ combatant, isCurrentTurn, onDamage, onHeal }: CombatantCardProps) {
  const [damageInput, setDamageInput] = useState('');
  const [healInput, setHealInput] = useState('');

  const isDead = combatant.hp <= 0;
  const hpPercent = (combatant.hp / combatant.max_hp) * 100;

  const handleDamage = () => {
    const dmg = parseInt(damageInput);
    if (dmg > 0) {
      onDamage(dmg);
      setDamageInput('');
    }
  };

  const handleHeal = () => {
    const heal = parseInt(healInput);
    if (heal > 0) {
      onHeal(heal);
      setHealInput('');
    }
  };

  return (
    <div
      className={`p-4 rounded-lg transition-all ${
        isDead
          ? 'bg-gray-700/30 opacity-50'
          : isCurrentTurn
          ? 'bg-yellow-600/30 border-2 border-yellow-500'
          : combatant.is_player
          ? 'bg-blue-600/20'
          : combatant.is_npc
          ? 'bg-purple-600/20 border border-purple-500/30'
          : 'bg-red-600/20'
      }`}
    >
      <div className="flex items-center gap-4">
        {/* Initiative */}
        <div className="text-center w-12">
          <div className="text-2xl font-bold">{combatant.initiative}</div>
          <div className="text-xs text-gray-400">INIT</div>
        </div>

        {/* Info */}
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <span className="font-medium text-lg">{combatant.name}</span>
            {combatant.is_npc && !combatant.is_player && (
              <span className="px-2 py-0.5 bg-purple-600 text-purple-100 text-xs rounded">AI</span>
            )}
            {isCurrentTurn && !isDead && (
              <span className="px-2 py-0.5 bg-yellow-500 text-black text-xs rounded">CURRENT</span>
            )}
            {isDead && (
              <span className="px-2 py-0.5 bg-gray-600 text-gray-300 text-xs rounded">DOWN</span>
            )}
          </div>
          {combatant.is_player && combatant.player_name && (
            <div className="text-sm text-gray-400">{combatant.player_name}'s character</div>
          )}

          {/* HP Bar */}
          <div className="mt-2">
            <div className="flex items-center gap-2">
              <div className="flex-1 h-3 bg-gray-700 rounded-full overflow-hidden">
                <div
                  className={`h-full transition-all ${
                    hpPercent > 50 ? 'bg-green-500' : hpPercent > 25 ? 'bg-yellow-500' : 'bg-red-500'
                  }`}
                  style={{ width: `${Math.max(0, hpPercent)}%` }}
                />
              </div>
              <span className="text-sm font-mono w-20 text-right">
                {combatant.hp}/{combatant.max_hp}
              </span>
            </div>
          </div>

          {/* Conditions */}
          {combatant.conditions && combatant.conditions.length > 0 && (
            <div className="mt-2 flex gap-1">
              {combatant.conditions.map((cond, i) => (
                <span key={i} className="px-2 py-0.5 bg-purple-600/50 text-purple-200 text-xs rounded">
                  {cond}
                </span>
              ))}
            </div>
          )}
        </div>

        {/* Actions */}
        {!isDead && (
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1">
              <input
                type="number"
                min="1"
                value={damageInput}
                onChange={(e) => setDamageInput(e.target.value)}
                placeholder="Dmg"
                className="w-16 px-2 py-1 text-sm bg-gray-700 border border-gray-600 rounded"
                onKeyDown={(e) => e.key === 'Enter' && handleDamage()}
              />
              <button
                onClick={handleDamage}
                disabled={!damageInput}
                className="px-2 py-1 text-sm bg-red-600 hover:bg-red-700 rounded disabled:opacity-50"
              >
                -
              </button>
            </div>
            <div className="flex items-center gap-1">
              <input
                type="number"
                min="1"
                value={healInput}
                onChange={(e) => setHealInput(e.target.value)}
                placeholder="Heal"
                className="w-16 px-2 py-1 text-sm bg-gray-700 border border-gray-600 rounded"
                onKeyDown={(e) => e.key === 'Enter' && handleHeal()}
              />
              <button
                onClick={handleHeal}
                disabled={!healInput}
                className="px-2 py-1 text-sm bg-green-600 hover:bg-green-700 rounded disabled:opacity-50"
              >
                +
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

interface AddCombatantModalProps {
  onClose: () => void;
  onAdd: (combatant: SetupCombatant) => void;
}

function AddCombatantModal({ onClose, onAdd }: AddCombatantModalProps) {
  const [mode, setMode] = useState<'manual' | 'npc'>('npc');
  const [name, setName] = useState('');
  const [hp, setHp] = useState(10);
  const [ac, setAc] = useState(12);
  const [initiativeBonus, setInitiativeBonus] = useState(0);
  const [count, setCount] = useState(1);

  // NPC selection state
  const [availableNPCs, setAvailableNPCs] = useState<AvailableNPC[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [loadingNPCs, setLoadingNPCs] = useState(false);
  const [selectedNPC, setSelectedNPC] = useState<AvailableNPC | null>(null);
  const [isFriendly, setIsFriendly] = useState(false);

  // Load available NPCs
  useEffect(() => {
    const loadNPCs = async () => {
      setLoadingNPCs(true);
      try {
        const npcs = await combatAPI.searchNPCs(searchQuery || undefined, false, 20);
        setAvailableNPCs(npcs);
      } catch (err) {
        console.error('Failed to load NPCs:', err);
      } finally {
        setLoadingNPCs(false);
      }
    };

    const debounce = setTimeout(loadNPCs, 300);
    return () => clearTimeout(debounce);
  }, [searchQuery]);

  const handleSelectNPC = (npc: AvailableNPC) => {
    setSelectedNPC(npc);
    setName(npc.name);
    setHp(npc.hp);
    setAc(npc.ac);
    setInitiativeBonus(npc.initiative_bonus);
    setIsFriendly(false);  // Reset to hostile by default
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;

    for (let i = 0; i < count; i++) {
      const suffix = count > 1 ? ` ${i + 1}` : '';
      onAdd({
        name: name.trim() + suffix,
        initiative_bonus: initiativeBonus,
        hp,
        max_hp: hp,
        ac,
        is_player: false,
        is_npc: selectedNPC !== null,
        is_friendly: selectedNPC !== null ? isFriendly : undefined,
        npc_id: selectedNPC?.entity_id,
      });
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-[60]">
      <div className="bg-gray-800 rounded-lg shadow-xl w-full max-w-lg p-6">
        <h3 className="text-lg font-bold mb-4">Add Monster/NPC</h3>

        {/* Mode Toggle */}
        <div className="flex gap-2 mb-4">
          <button
            type="button"
            onClick={() => { setMode('npc'); setSelectedNPC(null); }}
            className={`flex-1 py-2 rounded-lg transition-colors ${
              mode === 'npc'
                ? 'bg-purple-600 text-white'
                : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
            }`}
          >
            AI NPCs
          </button>
          <button
            type="button"
            onClick={() => { setMode('manual'); setSelectedNPC(null); }}
            className={`flex-1 py-2 rounded-lg transition-colors ${
              mode === 'manual'
                ? 'bg-blue-600 text-white'
                : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
            }`}
          >
            Manual Entry
          </button>
        </div>

        {mode === 'npc' ? (
          // NPC Selection Mode
          <div className="space-y-4">
            <div>
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search NPCs..."
                className="w-full px-4 py-2 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:border-purple-500"
                autoFocus
              />
            </div>

            {/* NPC List */}
            <div className="max-h-60 overflow-y-auto space-y-2">
              {loadingNPCs ? (
                <div className="text-center text-gray-400 py-4">Loading NPCs...</div>
              ) : availableNPCs.length === 0 ? (
                <div className="text-center text-gray-400 py-4">
                  No AI NPCs found. Use Manual Entry to add basic monsters.
                </div>
              ) : (
                availableNPCs.map((npc) => (
                  <button
                    key={npc.entity_id}
                    type="button"
                    onClick={() => handleSelectNPC(npc)}
                    className={`w-full p-3 rounded-lg text-left transition-colors ${
                      selectedNPC?.entity_id === npc.entity_id
                        ? 'bg-purple-600/30 border-2 border-purple-500'
                        : 'bg-gray-700/50 hover:bg-gray-700 border border-transparent'
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <div>
                        <div className="font-medium">{npc.name}</div>
                        <div className="text-sm text-gray-400">
                          {npc.race} {npc.role} | CR {npc.challenge_rating}
                        </div>
                      </div>
                      <div className="text-right text-sm">
                        <div className="text-red-400">HP: {npc.hp}</div>
                        <div className="text-blue-400">AC: {npc.ac}</div>
                      </div>
                    </div>
                  </button>
                ))
              )}
            </div>

            {selectedNPC && (
              <div className="border-t border-gray-700 pt-4 space-y-4">
                {/* Friendly Toggle */}
                <div className="flex items-center justify-between p-3 bg-gray-700/50 rounded-lg">
                  <div>
                    <div className="font-medium">Friendly NPC</div>
                    <div className="text-sm text-gray-400">Fights alongside the party</div>
                  </div>
                  <button
                    type="button"
                    onClick={() => setIsFriendly(!isFriendly)}
                    className={`relative w-14 h-8 rounded-full transition-colors ${
                      isFriendly ? 'bg-green-600' : 'bg-gray-600'
                    }`}
                  >
                    <div
                      className={`absolute top-1 w-6 h-6 bg-white rounded-full transition-transform ${
                        isFriendly ? 'translate-x-7' : 'translate-x-1'
                      }`}
                    />
                  </button>
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm text-gray-400 mb-1">Count</label>
                    <input
                      type="number"
                      min={1}
                      max={10}
                      value={count}
                      onChange={(e) => setCount(parseInt(e.target.value) || 1)}
                      className="w-full px-4 py-2 bg-gray-700 border border-gray-600 rounded-lg"
                    />
                  </div>
                  <div className="flex items-end">
                    <button
                      type="button"
                      onClick={handleSubmit}
                      className={`w-full px-4 py-2 rounded-lg transition-colors ${
                        isFriendly
                          ? 'bg-green-600 hover:bg-green-700'
                          : 'bg-purple-600 hover:bg-purple-700'
                      }`}
                    >
                      Add {count > 1 ? `${count}x ${selectedNPC.name}` : selectedNPC.name}
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        ) : (
          // Manual Entry Mode
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm text-gray-400 mb-1">Name *</label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g., Goblin"
                className="w-full px-4 py-2 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:border-blue-500"
                autoFocus
              />
            </div>

            <div className="grid grid-cols-3 gap-4">
              <div>
                <label className="block text-sm text-gray-400 mb-1">HP</label>
                <input
                  type="number"
                  min={1}
                  value={hp}
                  onChange={(e) => setHp(parseInt(e.target.value) || 1)}
                  className="w-full px-4 py-2 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:border-blue-500"
                />
              </div>
              <div>
                <label className="block text-sm text-gray-400 mb-1">AC</label>
                <input
                  type="number"
                  min={1}
                  value={ac}
                  onChange={(e) => setAc(parseInt(e.target.value) || 10)}
                  className="w-full px-4 py-2 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:border-blue-500"
                />
              </div>
              <div>
                <label className="block text-sm text-gray-400 mb-1">Init Bonus</label>
                <input
                  type="number"
                  value={initiativeBonus}
                  onChange={(e) => setInitiativeBonus(parseInt(e.target.value) || 0)}
                  className="w-full px-4 py-2 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:border-blue-500"
                />
              </div>
            </div>

            <div>
              <label className="block text-sm text-gray-400 mb-1">Count</label>
              <input
                type="number"
                min={1}
                max={20}
                value={count}
                onChange={(e) => setCount(parseInt(e.target.value) || 1)}
                className="w-full px-4 py-2 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:border-blue-500"
              />
            </div>

            <div className="text-sm text-gray-500 bg-gray-700/30 p-3 rounded-lg">
              Manual entries are DM-controlled. For AI-controlled NPCs with autonomous combat actions, use the AI NPCs tab.
            </div>

            <div className="flex justify-end gap-3 pt-4">
              <button
                type="button"
                onClick={onClose}
                className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={!name.trim()}
                className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors disabled:opacity-50"
              >
                Add {count > 1 ? `${count} Combatants` : 'Combatant'}
              </button>
            </div>
          </form>
        )}

        {/* Close button for NPC mode */}
        {mode === 'npc' && (
          <div className="flex justify-end mt-4 pt-4 border-t border-gray-700">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg transition-colors"
            >
              Cancel
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

// Combat log entry - theatrical display within tracker
interface CombatLogEntryData {
  id: number;
  type: 'npc' | 'system';
  npcName?: string;
  dialogue?: string;
  action?: string;
  target?: string;
  result?: string;
  message?: string;
}

function CombatLogEntry({ entry }: { entry: CombatLogEntryData }) {
  if (entry.type === 'system') {
    return (
      <div className="text-center text-xs text-gray-400 py-1">
        {entry.message}
      </div>
    );
  }

  return (
    <div className="border-l-2 border-purple-500 pl-2 text-sm">
      {/* NPC Name */}
      <div className="font-bold text-purple-400 text-xs uppercase tracking-wide">
        {entry.npcName}
      </div>

      {/* Dialogue */}
      {entry.dialogue && (
        <div className="text-white">"{entry.dialogue}"</div>
      )}

      {/* Action (stage direction) */}
      {entry.action && (
        <div className="text-gray-400 italic text-xs">[{entry.action}]</div>
      )}

      {/* Target & Result */}
      {(entry.target || entry.result) && (
        <div className="text-xs mt-1 font-mono">
          {entry.target && <span className="text-red-400">{entry.target}</span>}
          {entry.target && entry.result && <span className="text-gray-600"> - </span>}
          {entry.result && <span className="text-yellow-400">{entry.result}</span>}
        </div>
      )}
    </div>
  );
}

