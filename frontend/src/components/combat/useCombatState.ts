import { useState, useCallback, useRef } from 'react';
import type { Player } from '../../types';
import type { Combatant, CombatState, ChatMessage, SetupCombatant, CombatLogEntry, GridSize } from './types';
import { combatAPI } from '../../api/client';

const DEFAULT_GRID: GridSize = { width: 20, height: 15 };

// Auto-place combatants on the grid: players left, enemies right
function autoPlaceCombatants(
  combatants: Combatant[],
  grid: GridSize
): Map<string, { x: number; y: number }> {
  const positions = new Map<string, { x: number; y: number }>();

  const playerSide = combatants.filter(c => c.is_player || c.is_friendly);
  const enemySide = combatants.filter(c => !c.is_player && !c.is_friendly);

  const playerCol = 3;
  const enemyCol = grid.width - 4;

  // Center vertically
  const placeGroup = (group: Combatant[], col: number) => {
    const startRow = Math.max(0, Math.floor((grid.height - group.length) / 2));
    group.forEach((c, i) => {
      positions.set(c.name, { x: col, y: startRow + i });
    });
  };

  placeGroup(playerSide, playerCol);
  placeGroup(enemySide, enemyCol);

  return positions;
}

interface UseCombatStateOptions {
  players: Player[];
  onNPCTurn?: (message: ChatMessage) => void;
}

export function useCombatState({ players, onNPCTurn }: UseCombatStateOptions) {
  const [combatState, setCombatState] = useState<CombatState | null>(null);
  const [setupCombatants, setSetupCombatants] = useState<SetupCombatant[]>([]);
  const [showAddCombatant, setShowAddCombatant] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTurnName, setActiveTurnName] = useState<string | null>(null);
  const [combatLog, setCombatLog] = useState<CombatLogEntry[]>([]);
  const logIdRef = useRef(0);

  // Grid / battlemap state
  const [gridSize] = useState<GridSize>(DEFAULT_GRID);
  const [positions, setPositions] = useState<Map<string, { x: number; y: number }>>(new Map());
  const [selectedToken, setSelectedToken] = useState<string | null>(null);

  // Helper to display a single NPC turn result in the combat log + chat
  const displayNPCTurn = useCallback((npcTurn: { combatant_name: string; narration: string; npc_action?: any }) => {
    let movementDesc = '';
    let actionDesc = '';
    let resultDesc = '';
    let targetName = '';

    if (npcTurn.npc_action) {
      const action = npcTurn.npc_action.action;
      const actionType = action?.action_type || '';
      const actionName = action?.action_name || '';
      targetName = action?.target_name || '';

      // Parse movement from narration (look for "Move Xft to Y" or "Dash Xft to Y")
      const moveMatch = npcTurn.narration?.match(/\*\*Movement:\*\*\s*(?:Move|Dash)\s+(\d+)ft\s+to\s+(\w+)/i);
      if (moveMatch) {
        const isDash = actionType === 'dash';
        movementDesc = isDash ? `Dash ${moveMatch[1]}ft → ${moveMatch[2]}` : `Move ${moveMatch[1]}ft → ${moveMatch[2]}`;
      }

      // Build action description based on action type
      if (actionType === 'attack' || actionType === 'multiattack') {
        actionDesc = `Attack — ${actionName || 'weapon'}`;
      } else if (actionType === 'cast_spell') {
        actionDesc = `Cast — ${actionName || 'spell'}`;
      } else if (actionType === 'dash') {
        actionDesc = 'Dash';
      } else if (actionType === 'dodge') {
        actionDesc = 'Dodge';
      } else if (actionType === 'disengage') {
        actionDesc = 'Disengage';
      } else if (actionType === 'hide') {
        actionDesc = 'Hide';
      } else if (actionType === 'flee') {
        actionDesc = 'Flee';
      } else if (actionType === 'surrender') {
        actionDesc = 'Surrender';
      } else {
        actionDesc = actionName || actionType || '';
      }

      // Build result description
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
      movement: movementDesc || undefined,
      action: actionDesc || undefined,
      target: targetName ? `Target: ${targetName}` : undefined,
      result: resultDesc || undefined,
    }]);

    if (onNPCTurn) {
      onNPCTurn({
        role: 'npc',
        content: npcTurn.narration || '',
        npcData: {
          name: npcTurn.combatant_name,
          dialogue: npcTurn.npc_action?.action?.combat_dialogue,
          action: actionDesc || npcTurn.narration,
          target: targetName,
          result: resultDesc,
        },
      });
    }
  }, [onNPCTurn]);

  // Helper to refresh combat state from backend
  const refreshCombatState = useCallback(async () => {
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
          is_friendly: c.is_friendly,
          conditions: c.conditions || [],
          x: c.x,
          y: c.y,
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

        // Update positions map from backend coordinates
        setPositions(prev => {
          const newPositions = new Map(prev);
          for (const c of initiativeOrder) {
            if (c.x !== undefined && c.y !== undefined) {
              newPositions.set(c.name, { x: c.x, y: c.y });
            }
          }
          return newPositions;
        });

        return status;
      }
    } catch {
      // Status refresh is best-effort
    }
    return null;
  }, []);

  // Helper to emit combat system message
  const emitCombatMessage = useCallback((type: 'round_start' | 'turn_start' | 'action' | 'combat_end', content: string, round?: number) => {
    setCombatLog(prev => [...prev, {
      id: ++logIdRef.current,
      type: 'system',
      message: content,
    }]);

    if (onNPCTurn) {
      onNPCTurn({
        role: 'combat',
        content,
        combatData: { type, round },
      });
    }
  }, [onNPCTurn]);

  const startCombat = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    setCombatLog([]);

    try {
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

      // Don't auto-process NPC turns - require manual "Next" for each turn
      const result = await combatAPI.start({
        players: playerCombatants,
        npcs: npcCombatants,
        monsters: monsterCombatants,
        auto_npc_turns: false,
      });

      const initiativeOrder: Combatant[] = result.initiative_order.map((c) => ({
        name: c.name,
        initiative: c.initiative,
        hp: c.hp,
        max_hp: c.max_hp,
        is_player: c.is_player,
        is_npc: c.is_npc,
        is_friendly: c.is_friendly,
        conditions: [],
        x: c.x,
        y: c.y,
      }));

      const currentIdx = initiativeOrder.findIndex(c => c.name === result.current_turn);

      setCombatState({
        round: result.round,
        initiative_order: initiativeOrder,
        current_turn_idx: currentIdx >= 0 ? currentIdx : 0,
        active: true,
        current_is_npc: result.current_is_npc,
      });

      // Use backend positions if available, else auto-place locally
      const backendPositions = new Map<string, { x: number; y: number }>();
      let hasBackendPositions = false;
      for (const c of result.initiative_order) {
        if (c.x != null && c.y != null) {
          backendPositions.set(c.name, { x: c.x, y: c.y });
          hasBackendPositions = true;
        }
      }
      setPositions(hasBackendPositions ? backendPositions : autoPlaceCombatants(initiativeOrder, gridSize));
      setSelectedToken(null);

      emitCombatMessage('round_start', `Combat begins! Round ${result.round}`, result.round);
      setActiveTurnName(result.current_turn);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start combat');
    } finally {
      setIsLoading(false);
    }
  }, [setupCombatants, emitCombatMessage, gridSize]);

  const addFromPlayers = useCallback(() => {
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
  }, [players]);

  const addCombatant = useCallback((combatant: SetupCombatant) => {
    setSetupCombatants((prev) => [...prev, combatant]);
    setShowAddCombatant(false);
  }, []);

  const removeCombatant = useCallback((index: number) => {
    setSetupCombatants((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const nextTurn = useCallback(async () => {
    if (!combatState) return;

    setIsLoading(true);
    setError(null);

    try {
      const currentRound = combatState.round;

      // If current turn is an NPC, process their turn first
      if (combatState.current_is_npc) {
        const npcResult = await combatAPI.processTurn();

        // Display the NPC's action
        if (npcResult.npc_action) {
          displayNPCTurn({
            combatant_name: npcResult.combatant_name,
            narration: npcResult.narration,
            npc_action: npcResult.npc_action,
          });
        }

        // Check if combat ended
        if (!npcResult.combat_active && npcResult.combat_ended_reason) {
          emitCombatMessage('combat_end', `Combat ended: ${npcResult.combat_ended_reason}`);
          setCombatState(null);
          setSetupCombatants([]);
          setActiveTurnName(null);
          return;
        }
      }

      // Advance to the next combatant
      const advanceResult = await combatAPI.advanceTurn();

      if (!advanceResult.combat_active) {
        emitCombatMessage('combat_end', `Combat ended: ${advanceResult.combat_ended_reason || 'Unknown'}`);
        setCombatState(null);
        setSetupCombatants([]);
        setActiveTurnName(null);
        return;
      }

      // Refresh full combat state from backend
      const status = await refreshCombatState();

      // Check for new round
      if (status && 'round' in status && status.round > currentRound) {
        emitCombatMessage('round_start', `Round ${status.round}`, status.round);
      }

      // Update active turn indicator
      setActiveTurnName(advanceResult.combatant_name || null);

    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to advance turn');
    } finally {
      setIsLoading(false);
    }
  }, [combatState, displayNPCTurn, refreshCombatState, emitCombatMessage]);

  const applyDamage = useCallback(async (targetName: string, damage: number) => {
    if (!combatState) return;

    try {
      const result = await combatAPI.applyDamage(targetName, damage);

      setCombatState(prev => {
        if (!prev) return prev;
        const updated = prev.initiative_order.map(c =>
          c.name === targetName ? { ...c, hp: result.current_hp } : c
        );
        return { ...prev, initiative_order: updated };
      });

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

      setCombatState(prev => {
        if (!prev) return prev;
        const updated = prev.initiative_order.map(c =>
          c.name === targetName ? { ...c, hp: result.current_hp } : c
        );
        return { ...prev, initiative_order: updated };
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to apply healing');
    }
  }, [combatState]);

  const endCombat = useCallback(async () => {
    setIsLoading(true);

    try {
      const summary = await combatAPI.end();
      const survivorNames = summary.survivors.map(s => s.name).join(', ');
      emitCombatMessage('combat_end', `Combat ended after ${summary.rounds} rounds. Survivors: ${survivorNames || 'None'}`);
    } catch {
      emitCombatMessage('combat_end', 'Combat ended');
    } finally {
      setCombatState(null);
      setSetupCombatants([]);
      setPositions(new Map());
      setSelectedToken(null);
      setIsLoading(false);
    }
  }, [emitCombatMessage]);

  // Move a combatant token on the grid (optimistic update + backend sync)
  const moveCombatant = useCallback((name: string, x: number, y: number) => {
    // Check bounds
    if (x < 0 || x >= gridSize.width || y < 0 || y >= gridSize.height) return;

    // Check collision
    for (const [existingName, pos] of positions) {
      if (existingName !== name && pos.x === x && pos.y === y) return;
    }

    // Save previous position for rollback
    const prevPos = positions.get(name);

    // Optimistic update
    setPositions(prev => {
      const next = new Map(prev);
      next.set(name, { x, y });
      return next;
    });
    setSelectedToken(null);

    // Sync to backend (fire and forget with rollback on failure)
    combatAPI.moveCombatant(name, x, y).catch(() => {
      // Revert on failure
      setPositions(prev => {
        const next = new Map(prev);
        if (prevPos) {
          next.set(name, prevPos);
        } else {
          next.delete(name);
        }
        return next;
      });
    });
  }, [gridSize, positions]);

  // Add a combatant mid-combat
  const addCombatantMidCombat = useCallback(async (combatant: SetupCombatant & { x?: number; y?: number }) => {
    if (!combatState) return;

    try {
      const result = await combatAPI.addMidCombat({
        name: combatant.name,
        initiative_bonus: combatant.initiative_bonus,
        hp: combatant.hp,
        max_hp: combatant.max_hp,
        ac: combatant.ac,
        is_player: combatant.is_player,
        is_npc: combatant.is_npc,
        is_friendly: combatant.is_friendly,
        npc_id: combatant.npc_id,
        x: combatant.x,
        y: combatant.y,
      });

      // Refresh combat status to get the updated initiative order
      const status = await combatAPI.getStatus();
      if ('initiative_order' in status) {
        const initiativeOrder: Combatant[] = status.initiative_order.map((c: any) => ({
          name: c.name,
          initiative: c.initiative,
          hp: c.hp,
          max_hp: c.max_hp,
          is_player: c.is_player,
          is_npc: c.is_npc,
          is_friendly: c.is_friendly,
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

      // Set position if provided
      if (result.x != null && result.y != null) {
        setPositions(prev => {
          const next = new Map(prev);
          next.set(result.name, { x: result.x!, y: result.y! });
          return next;
        });
      } else if (combatant.x != null && combatant.y != null) {
        setPositions(prev => {
          const next = new Map(prev);
          next.set(combatant.name, { x: combatant.x!, y: combatant.y! });
          return next;
        });
      }

      setShowAddCombatant(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to add combatant');
    }
  }, [combatState]);

  // Remove a combatant mid-combat
  const removeCombatantMidCombat = useCallback(async (name: string) => {
    if (!combatState) return;

    try {
      await combatAPI.removeMidCombat(name);

      // Remove from positions
      setPositions(prev => {
        const next = new Map(prev);
        next.delete(name);
        return next;
      });

      // Refresh combat status
      const status = await combatAPI.getStatus();
      if ('initiative_order' in status) {
        const initiativeOrder: Combatant[] = status.initiative_order.map((c: any) => ({
          name: c.name,
          initiative: c.initiative,
          hp: c.hp,
          max_hp: c.max_hp,
          is_player: c.is_player,
          is_npc: c.is_npc,
          is_friendly: c.is_friendly,
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
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to remove combatant');
    }
  }, [combatState]);

  return {
    // State
    combatState,
    setupCombatants,
    showAddCombatant,
    isLoading,
    error,
    activeTurnName,
    combatLog,

    // Grid state
    gridSize,
    positions,
    selectedToken,

    // Actions
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
  };
}
