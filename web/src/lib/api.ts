/**
 * The lab's view of the FastAPI backend.
 *
 * A PORT, NOT A REDESIGN. The contract is unchanged, and every provenance
 * field survives it deliberately: which path found each passage, how many
 * guessed relationships were withheld, whether a question resolved a name of
 * its own or inherited one from the conversation, and how old each price is.
 * Those are what make this a thing you can trust rather than a dashboard, and
 * they are exactly what a rewrite loses if nobody is watching for it.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? 'http://127.0.0.1:8000/api'

export interface ModelInfo {
  id: string
  label: string
  note: string
  input_per_1m: number | null
  output_per_1m: number | null
  /** `null` means NOBODY HAS CHECKED this rate, and the UI has to say so. */
  last_verified: string | null
}

export interface Depth {
  passages: number
  max_edges: number
  include_proposed: boolean
  passage_width: 'section' | 'sentence'
}

export interface LabConfig {
  models: ModelInfo[]
  default_model: string
  kinds: string[]
  defaults: Depth
  /** Counted from the graph, never written down -- it went stale twice. */
  chapters: number
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
  /** The model is not in the rate table at all: distinct from an old rate. */
  unpriced: boolean
}

export interface Source {
  source: string
  type: string
  chapter: string
  section: string
  /** Per PASSAGE, not per question -- a mixed result is the normal case. */
  path: string
  citation: string
}

export interface RetrievalReport {
  /** How the QUESTION resolved: on a name, or on nothing. */
  path: string
  /** Which path put each passage there. */
  passages_by_path: Record<string, number>
  anchors: string[]
  passages: number
  dropped: number
  accepted_edges: number
  proposed_edges: number
  proposed_withheld: boolean
  loose: boolean
  /** The question resolved nothing; the anchors came from the conversation. */
  carried: boolean
  terms: string[]
  miss_reason: string
}

export interface SubgraphView {
  nodes: { id: string; name: string; labels: string[]; how: string; turn: number }[]
  edges: {
    source: string
    rel_type: string
    target: string
    status: string
    how: string
    turn: number
  }[]
  /** Pairs of held entities the book names in ONE SENTENCE. A reader's layer,
   *  never sent to the model -- see `lookup.TOGETHER` for why. */
  together?: { source: string; target: string; sentences: number }[]
  passages: number
  turn: number
}

export interface ChatReply {
  message: string
  sources: Source[]
  usage: Usage
  cost: Cost
  retrieval: RetrievalReport | null
  subgraph: SubgraphView | null
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
    // The backend's own message, not a generic failure. A 500 here usually
    // carries the real reason -- a dead Neo4j, a missing key -- and swallowing
    // it costs an afternoon.
    const detail = await response.text()
    throw new Error(`${response.status}: ${detail}`)
  }
  return response.json()
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
    return fetch(`${API_BASE}/lab/reset?session_id=${encodeURIComponent(sessionId)}`, {
      method: 'POST',
    })
  },
}
