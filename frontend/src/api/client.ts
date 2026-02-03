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

// Health check
export const healthAPI = {
  check: (): Promise<{ status: string; components: Record<string, string> }> =>
    fetchAPI('/health'.replace('/api', '')),
};

export { APIError };
