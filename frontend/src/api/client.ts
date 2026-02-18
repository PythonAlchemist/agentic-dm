import type {
  ChatRequest,
  ChatResponse,
  SessionInfo,
  DiceRollResult,
  NPCResult,
  EncounterResult,
  Entity,
  EntityCreate,
  Player,
  PlayerCreate,
  PlayerUpdate,
  PC,
  PCCreate,
  Campaign,
  CampaignCreate,
  Session,
  SessionCreate,
  SessionAttendance,
  ShopProfile,
  ShopGenerateRequest,
  ShopItem,
} from '../types';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';

class APIError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = 'APIError';
    this.status = status;
  }
}

async function fetchAPI<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const url = `${API_BASE}${endpoint}`;
  const response = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
    throw new APIError(response.status, error.detail || 'Request failed');
  }

  return response.json();
}

// Chat API
export const chatAPI = {
  send: (request: ChatRequest): Promise<ChatResponse> =>
    fetchAPI('/chat/', {
      method: 'POST',
      body: JSON.stringify(request),
    }),

  getSession: (sessionId: string): Promise<SessionInfo> =>
    fetchAPI(`/chat/sessions/${sessionId}`),

  deleteSession: (sessionId: string): Promise<{ success: boolean }> =>
    fetchAPI(`/chat/sessions/${sessionId}`, { method: 'DELETE' }),

  getHistory: (sessionId: string): Promise<{ session_id: string; history: unknown[] }> =>
    fetchAPI(`/chat/sessions/${sessionId}/history`),

  clearHistory: (sessionId: string): Promise<{ success: boolean }> =>
    fetchAPI(`/chat/sessions/${sessionId}/clear`, { method: 'POST' }),

  changeMode: (sessionId: string, mode: string): Promise<SessionInfo> =>
    fetchAPI(`/chat/sessions/${sessionId}/mode?mode=${mode}`, { method: 'POST' }),
};

// Tools API
export const toolsAPI = {
  rollDice: (expression: string): Promise<DiceRollResult> =>
    fetchAPI('/chat/tools/roll', {
      method: 'POST',
      body: JSON.stringify({ expression }),
    }),

  generateNPC: (role: string, race?: string): Promise<NPCResult> =>
    fetchAPI('/chat/tools/npc', {
      method: 'POST',
      body: JSON.stringify({ role, race }),
    }),

  generateEncounter: (
    difficulty: string,
    environment: string,
    partyLevel: number,
    partySize: number
  ): Promise<EncounterResult> =>
    fetchAPI('/chat/tools/encounter', {
      method: 'POST',
      body: JSON.stringify({
        difficulty,
        environment,
        party_level: partyLevel,
        party_size: partySize,
      }),
    }),
};

// Campaign API
export const campaignAPI = {
  listEntities: (
    entityType?: string,
    limit = 50
  ): Promise<{ entities: Entity[]; total: number }> => {
    const params = new URLSearchParams();
    if (entityType) params.set('entity_type', entityType);
    params.set('limit', String(limit));
    return fetchAPI(`/campaign/entities?${params}`);
  },

  getEntity: (entityId: string): Promise<Entity> =>
    fetchAPI(`/campaign/entities/${entityId}`),

  createEntity: (entity: EntityCreate): Promise<Entity> =>
    fetchAPI('/campaign/entities', {
      method: 'POST',
      body: JSON.stringify(entity),
    }),

  getNeighbors: (
    entityId: string,
    maxHops = 1
  ): Promise<{ entity_id: string; neighbors: Entity[] }> =>
    fetchAPI(`/campaign/entities/${entityId}/neighbors?max_hops=${maxHops}`),

  search: (
    query: string,
    entityTypes?: string[],
    limit = 10
  ): Promise<{ query: string; results: Entity[] }> => {
    const params = new URLSearchParams({ q: query, limit: String(limit) });
    if (entityTypes?.length) params.set('entity_types', entityTypes.join(','));
    return fetchAPI(`/campaign/search?${params}`);
  },

  getGraph: (
    entityTypes?: string[],
    limit = 200
  ): Promise<{
    nodes: Entity[];
    links: Array<{ source: string; target: string; type: string }>;
    node_count: number;
    link_count: number;
  }> => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (entityTypes?.length) params.set('entity_types', entityTypes.join(','));
    return fetchAPI(`/campaign/graph?${params}`);
  },
};

// Player API
export const playerAPI = {
  list: (campaignId?: string): Promise<Player[]> => {
    const params = campaignId ? `?campaign_id=${campaignId}` : '';
    return fetchAPI(`/players${params}`);
  },

  get: (playerId: string): Promise<Player> =>
    fetchAPI(`/players/${playerId}`),

  create: (data: PlayerCreate): Promise<Player> =>
    fetchAPI('/players', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  update: (playerId: string, data: PlayerUpdate): Promise<Player> =>
    fetchAPI(`/players/${playerId}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  delete: (playerId: string): Promise<{ success: boolean }> =>
    fetchAPI(`/players/${playerId}`, { method: 'DELETE' }),

  getCharacters: (playerId: string): Promise<PC[]> =>
    fetchAPI(`/players/${playerId}/characters`),

  createCharacter: (playerId: string, data: PCCreate): Promise<PC> =>
    fetchAPI(`/players/${playerId}/characters`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  setActiveCharacter: (playerId: string, pcId: string): Promise<Player> =>
    fetchAPI(`/players/${playerId}/active-character`, {
      method: 'PUT',
      body: JSON.stringify({ pc_id: pcId }),
    }),
};

// Campaign management API (extends existing campaignAPI)
export const campaignManagementAPI = {
  create: (data: CampaignCreate): Promise<Campaign> =>
    fetchAPI('/campaigns', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  getPlayers: (campaignId: string): Promise<Player[]> =>
    fetchAPI(`/campaigns/${campaignId}/players`),

  addPlayer: (campaignId: string, playerId: string): Promise<{ success: boolean }> =>
    fetchAPI(`/campaigns/${campaignId}/players`, {
      method: 'POST',
      body: JSON.stringify({ player_id: playerId }),
    }),

  removePlayer: (campaignId: string, playerId: string): Promise<{ success: boolean }> =>
    fetchAPI(`/campaigns/${campaignId}/players/${playerId}`, { method: 'DELETE' }),

  createSession: (campaignId: string, data: SessionCreate): Promise<Session> =>
    fetchAPI(`/campaigns/${campaignId}/sessions`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
};

// Session API
export const sessionAPI = {
  recordAttendance: (sessionId: string, attendance: SessionAttendance): Promise<{ success: boolean }> =>
    fetchAPI(`/sessions/${sessionId}/attendance`, {
      method: 'POST',
      body: JSON.stringify(attendance),
    }),

  getAttendees: (sessionId: string): Promise<Player[]> =>
    fetchAPI(`/sessions/${sessionId}/attendance`),
};

// Combat API
export interface CombatStartRequest {
  players: Array<{
    name: string;
    initiative_bonus?: number;
    hp?: number;
    max_hp?: number;
    ac?: number;
    player_id?: string;
    player_name?: string;
    pc_id?: string;
  }>;
  npcs: Array<{
    name: string;
    npc_id: string;
    initiative_bonus?: number;
    hp?: number;
    max_hp?: number;
    ac?: number;
  }>;
  monsters?: Array<{
    name: string;
    initiative_bonus?: number;
    hp?: number;
    max_hp?: number;
    ac?: number;
  }>;
  auto_npc_turns?: boolean;
}

export interface CombatStatus {
  active: boolean;
  round: number;
  current: {
    name: string;
    initiative: number;
    hp: number;
    max_hp: number;
    is_player: boolean;
    conditions: string[];
  };
  current_turn_type: string;
  current_is_npc: boolean;
  initiative_order: Array<{
    name: string;
    initiative: number;
    hp: number;
    max_hp: number;
    is_player: boolean;
    conditions: string[];
  }>;
}

export interface NPCTurnResultItem {
  combatant_name: string;
  turn_type: string;
  round: number;
  narration: string;
  npc_action?: {
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
  };
}

export interface TurnResult {
  combatant_name: string;
  turn_type: string;
  round: number;
  awaiting_action: boolean;
  combat_active: boolean;
  combat_ended_reason?: string;
  narration: string;
  npc_action?: {
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
  };
  npc_turn_results?: NPCTurnResultItem[];
}

export interface AvailableNPC {
  entity_id: string;
  name: string;
  race: string;
  role: string;
  hp: number;
  max_hp: number;
  ac: number;
  initiative_bonus: number;
  challenge_rating: number;
  description?: string;
}

export const combatAPI = {
  // Search for available NPCs to add to combat
  searchNPCs: (query?: string, hostileOnly?: boolean, limit?: number): Promise<AvailableNPC[]> => {
    const params = new URLSearchParams();
    if (query) params.set('query', query);
    if (hostileOnly) params.set('hostile_only', 'true');
    if (limit) params.set('limit', String(limit));
    return fetchAPI(`/combat/npcs?${params}`);
  },

  getNPC: (npcId: string): Promise<AvailableNPC> =>
    fetchAPI(`/combat/npcs/${npcId}`),

  start: (request: CombatStartRequest): Promise<{
    combat_started: boolean;
    round: number;
    initiative_order: Array<{
      name: string;
      initiative: number;
      hp: number;
      max_hp: number;
      is_player: boolean;
      is_npc: boolean;
      is_friendly?: boolean;
      x?: number;
      y?: number;
    }>;
    current_turn: string;
    current_is_npc: boolean;
    grid_width: number;
    grid_height: number;
    npc_turn_results?: Array<{
      combatant_name: string;
      turn_type: string;
      narration: string;
      npc_action?: {
        action: {
          action_type: string;
          action_name?: string;
          target_name?: string;
          combat_dialogue?: string;
        };
        hit?: boolean;
        damage_dealt?: number;
        narration: string;
      };
    }>;
  }> =>
    fetchAPI('/combat/start', {
      method: 'POST',
      body: JSON.stringify(request),
    }),

  getStatus: (): Promise<CombatStatus | { active: false; message: string }> =>
    fetchAPI('/combat/status'),

  getCurrentTurn: (): Promise<{
    combatant: string;
    turn_type: string;
    is_npc: boolean;
    round: number;
    hp: number;
    max_hp: number;
    conditions: string[];
  } | { active: false; message: string }> =>
    fetchAPI('/combat/turn'),

  processTurn: (): Promise<TurnResult> =>
    fetchAPI('/combat/turn/process', { method: 'POST' }),

  endTurn: (): Promise<TurnResult> =>
    fetchAPI('/combat/turn/end', { method: 'POST' }),

  // Advance to next combatant without processing their turn (for step-by-step combat)
  advanceTurn: (): Promise<{
    combat_active: boolean;
    combat_ended_reason?: string;
    round?: number;
    combatant_name?: string;
    is_npc?: boolean;
    is_player?: boolean;
    hp?: number;
    max_hp?: number;
  }> =>
    fetchAPI('/combat/turn/advance', { method: 'POST' }),

  processAllNPCTurns: (): Promise<TurnResult[]> =>
    fetchAPI('/combat/turn/npc-all', { method: 'POST' }),

  applyDamage: (target: string, damage: number): Promise<{
    name: string;
    damage_taken: number;
    current_hp: number;
    max_hp: number;
    status: string;
    combat_ended?: boolean;
    end_reason?: string;
  }> =>
    fetchAPI('/combat/damage', {
      method: 'POST',
      body: JSON.stringify({ target, damage }),
    }),

  applyHealing: (target: string, healing: number): Promise<{
    name: string;
    healing_received: number;
    current_hp: number;
    max_hp: number;
    status: string;
  }> =>
    fetchAPI('/combat/heal', {
      method: 'POST',
      body: JSON.stringify({ target, healing }),
    }),

  addCondition: (target: string, condition: string): Promise<{
    name: string;
    conditions: string[];
  }> =>
    fetchAPI('/combat/condition/add', {
      method: 'POST',
      body: JSON.stringify({ target, condition }),
    }),

  removeCondition: (target: string, condition: string): Promise<{
    name: string;
    conditions: string[];
  }> =>
    fetchAPI('/combat/condition/remove', {
      method: 'POST',
      body: JSON.stringify({ target, condition }),
    }),

  end: (): Promise<{
    rounds: number;
    survivors: Array<{ name: string; hp: number; max_hp: number }>;
    defeated: Array<{ name: string }>;
    player_survivors: Array<{ player_name: string; character_name: string; hp: number; max_hp: number }>;
    player_casualties: Array<{ player_name: string; character_name: string }>;
  }> =>
    fetchAPI('/combat/end', { method: 'POST' }),

  // Grid / Position API
  moveCombatant: (name: string, x: number, y: number): Promise<{
    name: string;
    x: number;
    y: number;
  }> =>
    fetchAPI('/combat/move', {
      method: 'POST',
      body: JSON.stringify({ name, x, y }),
    }),

  addMidCombat: (combatant: {
    name: string;
    initiative_bonus?: number;
    hp?: number;
    max_hp?: number;
    ac?: number;
    is_player?: boolean;
    is_npc?: boolean;
    is_friendly?: boolean;
    npc_id?: string;
    x?: number;
    y?: number;
  }): Promise<{
    name: string;
    initiative: number;
    hp: number;
    max_hp: number;
    x?: number;
    y?: number;
    index: number;
  }> =>
    fetchAPI('/combat/combatant/add', {
      method: 'POST',
      body: JSON.stringify(combatant),
    }),

  removeMidCombat: (name: string): Promise<{
    removed: string;
    remaining: number;
  }> =>
    fetchAPI('/combat/combatant/remove', {
      method: 'POST',
      body: JSON.stringify({ name }),
    }),

  setGridSize: (width: number, height: number): Promise<{
    grid_width: number;
    grid_height: number;
  }> =>
    fetchAPI('/combat/grid', {
      method: 'POST',
      body: JSON.stringify({ width, height }),
    }),
};

// Shop API
export const shopAPI = {
  generate: (request: ShopGenerateRequest): Promise<ShopProfile> =>
    fetchAPI('/shop/generate', {
      method: 'POST',
      body: JSON.stringify(request),
    }),

  get: (shopId: string): Promise<ShopProfile> =>
    fetchAPI(`/shop/${shopId}`),

  list: (limit?: number): Promise<ShopProfile[]> => {
    const params = limit ? `?limit=${limit}` : '';
    return fetchAPI(`/shops${params}`);
  },

  update: (shopId: string, data: { name?: string; description?: string; gold_reserves?: number }): Promise<ShopProfile> =>
    fetchAPI(`/shop/${shopId}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  delete: (shopId: string): Promise<{ success: boolean }> =>
    fetchAPI(`/shop/${shopId}`, { method: 'DELETE' }),

  addItem: (shopId: string, item: Omit<ShopItem, 'entity_id'>): Promise<ShopItem> =>
    fetchAPI(`/shop/${shopId}/inventory`, {
      method: 'POST',
      body: JSON.stringify(item),
    }),

  updateItem: (shopId: string, itemId: string, updates: Partial<ShopItem>): Promise<ShopItem> =>
    fetchAPI(`/shop/${shopId}/inventory/${itemId}`, {
      method: 'PUT',
      body: JSON.stringify(updates),
    }),

  removeItem: (shopId: string, itemId: string): Promise<{ success: boolean }> =>
    fetchAPI(`/shop/${shopId}/inventory/${itemId}`, { method: 'DELETE' }),

  getShopkeeper: (shopId: string): Promise<Record<string, unknown>> =>
    fetchAPI(`/shop/${shopId}/shopkeeper`),

  chat: (
    shopId: string,
    message: string,
    playerName?: string,
    conversationHistory?: Array<{ role: string; content: string }>,
  ): Promise<{
    response: string;
    transactions: Array<{ item: string; qty: number; price_each: number; total: number; action: 'buy' | 'sell' }>;
  }> =>
    fetchAPI(`/shop/${shopId}/chat`, {
      method: 'POST',
      body: JSON.stringify({
        message,
        player_name: playerName,
        conversation_history: conversationHistory || [],
      }),
    }),
};

// Health check
export const healthAPI = {
  check: (): Promise<{ status: string; components: Record<string, string> }> =>
    fetchAPI('/health'.replace('/api', '')),
};

export { APIError };
