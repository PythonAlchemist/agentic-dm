import { useState, useCallback, useRef, useEffect } from 'react';
import type { Player } from '../../types';
import type { Combatant, CombatState, ChatMessage, SetupCombatant, CombatLogEntry, GridSize } from './types';
import { combatAPI } from '../../api/client';

const NPC_TURN_DELAY = 2500;
const DEFAULT_GRID: GridSize = { width: 20, height: 15 };
const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

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
  const pendingNPCTurnsRef = useRef<any[] | null>(null);

  // Grid / battlemap state
  const [gridSize] = useState<GridSize>(DEFAULT_GRID);
  const [positions, setPositions] = useState<Map<string, { x: number; y: number }>>(new Map());
  const [selectedToken, setSelectedToken] = useState<string | null>(null);

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
    setActiveTurnName(null);
  }, [displayNPCTurn]);

  // Process pending NPC turns after the battlemap has rendered.
  // useEffect fires after React commits the DOM update, so the BattleMap
  // component is guaranteed to be mounted and visible when this runs.
  useEffect(() => {
    if (combatState && pendingNPCTurnsRef.current) {
      const turns = pendingNPCTurnsRef.current;
      pendingNPCTurnsRef.current = null;

      // Small delay so the user can see the battlemap before turns begin
      sleep(500).then(async () => {
        await slowRollNPCTurns(turns);
        setIsLoading(false);
      });
    }
  }, [combatState, slowRollNPCTurns]);

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

      const result = await combatAPI.start({
        players: playerCombatants,
        npcs: npcCombatants,
        monsters: monsterCombatants,
        auto_npc_turns: true,
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

      // Queue NPC turns to run after React renders the battlemap
      if (result.npc_turn_results && result.npc_turn_results.length > 0) {
        pendingNPCTurnsRef.current = result.npc_turn_results;
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start combat');
    } finally {
      // Only clear loading if no NPC turns are queued (useEffect will handle it)
      if (!pendingNPCTurnsRef.current) {
        setIsLoading(false);
      }
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
      const result = await combatAPI.endTurn();
      const status = await combatAPI.getStatus();

      if ('active' in status && status.active === false) {
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

      if (result.npc_turn_results && result.npc_turn_results.length > 0) {
        await slowRollNPCTurns(result.npc_turn_results);
      }

      if (status && 'round' in status && status.round > (combatState?.round || 1)) {
        emitCombatMessage('round_start', `Round ${status.round}`, status.round);
      }

      if (!result.combat_active && result.combat_ended_reason) {
        emitCombatMessage('combat_end', `Combat ended: ${result.combat_ended_reason}`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to advance turn');
    } finally {
      setIsLoading(false);
    }
  }, [combatState, slowRollNPCTurns, emitCombatMessage]);

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
