// Chat types
export interface ChatMessage {
  role: 'user' | 'assistant' | 'npc' | 'combat';
  content: string;
  timestamp?: string;
  sources?: Source[];
  toolResults?: ToolResult[];
  suggestions?: string[];
  // NPC theatrical message data
  npcData?: {
    name: string;
    dialogue?: string;      // What the NPC says (in quotes)
    action?: string;        // Stage direction (what they do)
    target?: string;        // Who they're targeting
    result?: string;        // Hit/miss, damage, etc.
  };
  // Combat system message data
  combatData?: {
    type: 'round_start' | 'turn_start' | 'action' | 'combat_end';
    round?: number;
    combatantName?: string;
  };
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
}

export interface SessionInfo {
  session_id: string;
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
  entity_type?: string;
  // World & Setting
  setting?: string;
  world_description?: string;
  theme?: string;
  description?: string;
  // Rules & Mechanics
  rule_system?: string;
  level_range?: string;
  house_rules?: string;
  allowed_sources?: string;
  // Story Context
  premise?: string;
  current_story_arc?: string;
  dm_notes?: string;
  // Meta
  start_date?: string;
  status?: string;
  player_count?: number;
}

export interface CampaignCreate {
  name: string;
  setting?: string;
  world_description?: string;
  theme?: string;
  description?: string;
  rule_system?: string;
  level_range?: string;
  house_rules?: string;
  allowed_sources?: string;
  premise?: string;
  current_story_arc?: string;
  dm_notes?: string;
}

export interface CampaignUpdate {
  name?: string;
  setting?: string;
  world_description?: string;
  theme?: string;
  description?: string;
  rule_system?: string;
  level_range?: string;
  house_rules?: string;
  allowed_sources?: string;
  premise?: string;
  current_story_arc?: string;
  dm_notes?: string;
  status?: string;
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
  ac?: number;
  is_player: boolean;
  is_npc?: boolean;  // AI-controlled NPC
  is_friendly?: boolean;  // Fights alongside players
  npc_id?: string;   // NPC entity ID for AI control
  player_id?: string;
  player_name?: string;
  pc_id?: string;
  character_name?: string;
  conditions?: string[];
  x?: number;  // Grid column position
  y?: number;  // Grid row position
}

export interface CombatState {
  round: number;
  initiative_order: Combatant[];
  current_turn_idx: number;
  active: boolean;
  current_turn_type?: string;
  current_is_npc?: boolean;
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

// NPC Combat Action Result
export interface NPCActionResult {
  action: {
    action_type: string;
    action_name?: string;
    target_name?: string;
    reasoning: string;
    combat_dialogue?: string;
  };
  hit?: boolean;
  damage_dealt?: number;
  target_new_hp?: number;
  narration: string;
}

// Individual NPC turn result (from npc_turn_results array)
export interface NPCTurnResultItem {
  combatant_name: string;
  turn_type: string;
  round: number;
  narration: string;
  npc_action?: NPCActionResult;
}

// Turn Result from backend
export interface TurnResult {
  combatant_name: string;
  turn_type: string;
  round: number;
  awaiting_action: boolean;
  combat_active: boolean;
  combat_ended_reason?: string;
  narration: string;
  npc_action?: NPCActionResult;
  npc_turn_results?: NPCTurnResultItem[];
}

// Shop types
export interface ShopItem {
  entity_id?: string;
  name: string;
  description?: string;
  price_gp: number;
  quantity: number;
  rarity: string;
  category: string;
  magical: boolean;
  weight?: number;
}

export interface ShopProfile {
  entity_id: string;
  name: string;
  description?: string;
  shop_size: string;
  shop_specialty: string;
  gold_reserves: number;
  shopkeeper_id?: string;
  location_id?: string;
  inventory: ShopItem[];
  shopkeeper_name?: string;
  shopkeeper_race?: string;
  shopkeeper_description?: string;
  shopkeeper_personality?: Record<string, unknown>;
}

export interface ShopGenerateRequest {
  size: 'small' | 'medium' | 'large';
  specialty: string;
  name?: string;
  shopkeeper_name?: string;
  shopkeeper_race?: string;
  location_id?: string;
}

export interface ShopTransaction {
  item: string;
  qty: number;
  price_each: number;
  total: number;
  action: 'buy' | 'sell';
}

export interface ShopChatMessage {
  role: 'user' | 'shopkeeper';
  content: string;
  transactions?: ShopTransaction[];
}

// Audio transcription types
export type AudioJobPhase =
  | 'uploading'
  | 'transcribing'
  | 'awaiting_mapping'
  | 'processing_transcript'
  | 'awaiting_review'
  | 'completed'
  | 'failed';

export interface SpeakerSample {
  speaker_index: number;
  utterance_count: number;
  total_duration: number;
  sample_texts: string[];
}

export interface SpeakerMappingEntry {
  speaker_index: number;
  role: 'dm' | 'player';
  player_name: string;
  character_name?: string;
}

export interface ExtractedEntityItem {
  name: string;
  entity_type: string;
  confidence: number;
}

export interface ExtractedRelationshipItem {
  source: string;
  target: string;
  type: string;
}

export interface AudioTranscriptResult {
  session_id: string;
  session_number?: number;
  campaign_id?: string;
  segments_processed: number;
  entities_extracted: number;
  entities_created: number;
  relationships_extracted: number;
  relationships_created: number;
  entity_counts: Record<string, number>;
  processing_time_ms: number;
  errors: string[];
  entities?: ExtractedEntityItem[];
  relationships?: ExtractedRelationshipItem[];
}

export interface DiarizedSegment {
  speaker: number;
  text: string;
  start: number;
  end: number;
  confidence: number;
}

export interface AudioJobStatus {
  job_id: string;
  filename: string;
  phase: AudioJobPhase;
  error?: string;
  speaker_samples?: SpeakerSample[];
  segments?: DiarizedSegment[];
  total_duration?: number;
  segment_count?: number;
  transcript_result?: AudioTranscriptResult;
  // Available during awaiting_review phase
  entities?: ExtractedEntityItem[];
  relationships?: ExtractedRelationshipItem[];
  entity_counts?: Record<string, number>;
  segments_processed?: number;
}

export interface AudioJobListItem {
  job_id: string;
  filename: string;
  phase: AudioJobPhase;
  error?: string;
}

// Transcript history types
export interface TranscriptHistoryItem {
  job_id: string;
  filename: string;
  completed_at: string;
  session_number?: number;
  total_duration?: number;
  segment_count?: number;
  entities_extracted?: number;
}

export interface TranscriptDetail {
  job_id: string;
  filename: string;
  completed_at: string;
  session_number?: number;
  campaign_id?: string;
  total_duration?: number;
  segment_count?: number;
  speaker_mappings: Array<{
    speaker_index: number;
    role: string;
    player_name: string;
    character_name?: string;
  }>;
  transcript_text: string;
  transcript_result?: AudioTranscriptResult;
}

// UI State types
export interface AppState {
  sessionId: string | null;
  campaignId: string | null;
  messages: ChatMessage[];
  isLoading: boolean;
}
