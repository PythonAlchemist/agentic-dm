/**
 * The lab's own client. Deliberately not sharing `src/api/client.ts`: that file
 * serves the campaign UI, and a lab that imports from it would couple two
 * things whose whole point is being separable.
 */

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000/api'

export interface ModelInfo {
  id: string
  label: string
  note: string
  input_per_1m: number | null
  output_per_1m: number | null
  /** null means nobody has confirmed this rate. The UI says so rather than hiding it. */
  last_verified: string | null
}

export interface LabConfig {
  models: ModelInfo[]
  default_model: string
  kinds: string[]
  defaults: Depth
}

export interface Depth {
  passages: number
  max_edges: number
  include_proposed: boolean
  history_turns: number
}

export interface Usage {
  input: number
  output: number
  total: number
}

export interface Cost {
  usd: number | null
  model: string
  last_verified: string | null
  verified: boolean
  unpriced: boolean
}

export interface RetrievalReport {
  path: string
  anchors: string[]
  passages: number
  dropped: number
  accepted_edges: number
  proposed_edges: number
  proposed_withheld: boolean
  loose: boolean
  terms: string[]
  miss_reason: string
}

export interface Source {
  source: string
  type: string
  chapter?: string
  section?: string
  path?: string
  citation?: string
}

export interface ChatReply {
  message: string
  sources: Source[]
  usage: Usage
  cost: Cost
  retrieval: RetrievalReport | null
  model: string
}

export interface GeneratedReply {
  kind: string
  subject: string
  title: string
  body: string
  from_canon: { claim: string; cite: string }[]
  invented: string[]
  sources: Source[]
  usage: Usage
  cost: Cost
  retrieval: RetrievalReport | null
  error: string
  raw: string
  model: string
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}/lab${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) {
    const detail = await response.text()
    throw new Error(`${response.status}: ${detail}`)
  }
  return response.json() as Promise<T>
}

export const labAPI = {
  async config(): Promise<LabConfig> {
    const response = await fetch(`${API_BASE}/lab/config`)
    if (!response.ok) throw new Error(`config failed: ${response.status}`)
    return response.json()
  },

  chat(message: string, model: string, depth: Depth, sessionId: string) {
    return post<ChatReply>('/chat', { message, model, depth, session_id: sessionId })
  },

  generate(kind: string, subject: string, model: string, depth: Depth) {
    return post<GeneratedReply>('/generate', { kind, subject, model, depth })
  },

  reset(sessionId: string) {
    return post<{ ok: boolean }>(`/reset?session_id=${encodeURIComponent(sessionId)}`, {})
  },
}
