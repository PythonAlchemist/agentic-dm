// Chat types
export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  timestamp?: string;
  sources?: Source[];
  toolResults?: ToolResult[];
  suggestions?: string[];
}

export interface Source {
  type: string;
  source?: string;
  page?: number;
  score?: number;
}

export interface ToolResult {
  type: string;
  result: Record<string, unknown>;
}

export interface ChatRequest {
  message: string;
  session_id?: string;
  mode?: 'assistant' | 'autonomous';
  campaign_id?: string;
  use_rag?: boolean;
}

export interface ChatResponse {
  response: string;
  session_id: string;
  query_type?: string;
  sources: Source[];
  tool_results: ToolResult[];
  suggestions: string[];
  mode: string;
}

export interface SessionInfo {
  session_id: string;
  mode: string;
  message_count: number;
  campaign_id?: string;
}

// Tool types
export interface DiceRollResult {
  expression: string;
  rolls: number[];
  modifier: number;
  total: number;
  critical: boolean;
}

export interface NPCResult {
  name: string;
  role: string;
  race: string;
  personality: string[];
  motivations: string[];
  appearance: string;
  voice_notes: string;
  secret?: string;
}

export interface EncounterResult {
  difficulty: string;
  environment: string;
  party_level: number;
  monsters: Monster[];
  total_xp: number;
  description: string;
  tactics: string;
}

export interface Monster {
  name: string;
  cr: number;
  type: string;
}

// Campaign types
export interface Entity {
  id: string;
  name: string;
  entity_type: string;
  description?: string;
  aliases?: string[];
  created_at?: string;
  // Allow additional properties (race, class, level, etc.)
  [key: string]: unknown;
}

export interface EntityCreate {
  name: string;
  entity_type: string;
  description?: string;
  properties?: Record<string, unknown>;
}

// Player types
export interface Player {
  id: string;
  name: string;
  email?: string;
  discord_id?: string;
  joined_at?: string;
  active_pc_id?: string;
  active_pc?: PC;
  characters: PC[];
}

export interface PlayerCreate {
  name: string;
  email?: string;
  discord_id?: string;
}

export interface PlayerUpdate {
  name?: string;
  email?: string;
  discord_id?: string;
  active_pc_id?: string;
  notes?: string;
}

export interface PC extends Entity {
  player_id?: string;
  player_name?: string;
  character_class?: string;
  level: number;
  race?: string;
  hp?: number;
  max_hp?: number;
  initiative_bonus?: number;
  status?: string;
}

export interface PCCreate {
  name: string;
  character_class: string;
  level?: number;
  race?: string;
  hp?: number;
  max_hp?: number;
  initiative_bonus?: number;
  description?: string;
}

// Campaign and Session types
export interface Campaign {
  id: string;
  name: string;
  setting?: string;
  description?: string;
  status?: string;
}

export interface CampaignCreate {
  name: string;
  setting?: string;
  description?: string;
}

export interface Session extends Entity {
  session_number: number;
  campaign_id?: string;
  date?: string;
  summary?: string;
}

export interface SessionCreate {
  session_number: number;
  name?: string;
  date?: string;
  summary?: string;
}

export interface SessionAttendance {
  player_ids: string[];
  character_ids?: string[];
}

// Combat types
export interface Combatant {
  name: string;
  initiative: number;
  initiative_bonus?: number;
  hp: number;
  max_hp: number;
  is_player: boolean;
  player_id?: string;
  player_name?: string;
  pc_id?: string;
  character_name?: string;
  conditions?: string[];
}

export interface CombatState {
  round: number;
  initiative_order: Combatant[];
  current_turn_idx: number;
  active: boolean;
}

export interface CombatStartRequest {
  combatants: Array<{
    name: string;
    initiative_bonus?: number;
    hp?: number;
    max_hp?: number;
    is_player?: boolean;
    player_id?: string;
    player_name?: string;
    pc_id?: string;
    character_name?: string;
  }>;
}

// UI State types
export type DMMode = 'assistant' | 'autonomous';

export interface AppState {
  sessionId: string | null;
  mode: DMMode;
  campaignId: string | null;
  messages: ChatMessage[];
  isLoading: boolean;
}
