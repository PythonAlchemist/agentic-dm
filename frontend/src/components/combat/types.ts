import type { Combatant, CombatState, ChatMessage } from '../../types';

// Re-export for convenience
export type { Combatant, CombatState, ChatMessage };

// Setup phase combatant (before combat starts)
export interface SetupCombatant {
  name: string;
  initiative_bonus: number;
  hp: number;
  max_hp: number;
  ac: number;
  is_player: boolean;
  is_npc: boolean;
  is_friendly?: boolean;
  npc_id?: string;
  player_id?: string;
  player_name?: string;
  pc_id?: string;
}

// Combat log entry
export interface CombatLogEntry {
  id: number;
  type: 'npc' | 'system';
  npcName?: string;
  dialogue?: string;
  movement?: string;  // e.g., "Move 30ft to E8" or "Dash 60ft to E8"
  action?: string;    // e.g., "Attack — Greataxe"
  target?: string;    // e.g., "Thorin"
  result?: string;    // e.g., "Hit! 10 damage" or "Miss"
  message?: string;
}

// Grid position for battlemap (Phase 3+)
export interface GridPosition {
  x: number;
  y: number;
}

export interface GridSize {
  width: number;
  height: number;
}

// Token faction colors
export type TokenFaction = 'player' | 'friendly' | 'hostile' | 'monster' | 'dead';

export const FACTION_COLORS: Record<TokenFaction, { token: string; card: string; border: string }> = {
  player:   { token: 'bg-blue-600',   card: 'bg-blue-600/20',   border: 'border-blue-500/30' },
  friendly: { token: 'bg-green-600',  card: 'bg-green-600/20',  border: 'border-green-500/30' },
  hostile:  { token: 'bg-purple-600', card: 'bg-purple-600/20', border: 'border-purple-500/30' },
  monster:  { token: 'bg-red-600',    card: 'bg-red-600/20',    border: 'border-red-500/30' },
  dead:     { token: 'bg-gray-600',   card: 'bg-gray-700/30',   border: 'border-gray-600/30' },
};

// Helper to determine faction from combatant
export function getCombatantFaction(c: Combatant): TokenFaction {
  if (c.hp <= 0) return 'dead';
  if (c.is_player) return 'player';
  if (c.is_npc && c.is_friendly) return 'friendly';
  if (c.is_npc) return 'hostile';
  return 'monster';
}
