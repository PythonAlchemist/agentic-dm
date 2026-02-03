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

// UI State types
export type DMMode = 'assistant' | 'autonomous';

export interface AppState {
  sessionId: string | null;
  mode: DMMode;
  campaignId: string | null;
  messages: ChatMessage[];
  isLoading: boolean;
}
