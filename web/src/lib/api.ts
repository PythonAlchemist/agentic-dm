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
  /** Counted from the graph, never written down -- the count went stale twice
   *  and the title was hardcoded to Curse of Strahd until there were two. */
  books: BookInfo[]
}

export interface BookInfo {
  slug: string
  title: string
  chapters: number
  /** Starter subjects from the book's own seed, keyed `ask`/`quest`/`npc`/
   *  `monster`. Empty for a book that names none. */
  examples: Record<string, string>
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
  /** Draft cards the model asked for. NEVER part of `message`: a generation
   *  that arrived as prose would carry none of the provenance split. */
  generations?: GeneratedReply[]
}

export interface GeneratedReply {
  kind: string
  subject: string
  title: string
  body: string
  from_canon: { claim: string; cite: string }[]
  from_yours?: { claim: string; cite: string }[]
  invented: string[]
  /** The third source: what came from the conversation rather than the book or
   *  the model. Present only when chat handed context over. */
  from_context?: string[]
  sources: Source[]
  usage: Usage
  cost: Cost
  retrieval: RetrievalReport | null
  error: string
  raw: string
  model: string
  /** Set on a card the chat agent asked for: the canon section it goes after. */
  anchor?: string
  /** Chapters this generation is actually about, heaviest first. The picker
   *  leads with them instead of listing the whole book flat. */
  relevant_chapters?: string[]
  carried?: string[]
  /** What the generation says it contains. Absent on a single-artifact card,
   *  which is every card that existed before clusters. */
  elements?: ClusterElement[]
  /** Declared but NOT stored: measured at 27% type-impossible against a 20%
   *  gate, so they are shown and counted rather than written. */
  edges?: unknown[]
  /** Manifest entries thrown away, by reason. */
  manifest_dropped?: Record<string, number>
  /** Set on a draft ABOUT something that already exists. Store routes to
   *  `/expand`, which mints nothing -- the minting path would raise. */
  expands?: string
}

export interface SectionRead {
  section_id: string
  heading: string
  text: string
  plane: 'canon' | 'campaign'
  kind: string | null
  chapter: string | null
  from_canon: { claim: string; cite: string }[]
  /** Claims that cite the DM's OWN sections, re-filed off `from_canon`. */
  from_yours: { claim: string; cite: string }[]
  from_context: string[]
  invented: string[]
  edited: boolean | null
  cites: string[]
  /** Which entities this prose names, from the mention triangle — not from
   *  matching strings, so the highlight agrees with what retrieval believes. */
  mentions: {
    entity_id: string
    name: string
    kind: string | null
    plane: 'canon' | 'campaign'
    surface: string
  }[]
}

export interface EntityRead {
  entity_id: string
  name: string
  kind: string | null
  plane: 'canon' | 'campaign'
  role: string | null
  invented: string[]
  labels: string[]
  own_section: string | null
  named_in: {
    section_id: string
    heading: string
    plane: string
    /** What that section actually says about it, quoted exactly. */
    says: string[]
  }[]
}

export interface CampaignElement {
  entity_id: string
  name: string
  kind: string
  role: string | null
  introduced_in: string | null
  /** The section written ABOUT it. Null means it is still only a name. */
  own_section: string | null
}

export interface ClusterElement {
  name: string
  kind: string
  role?: string
  from_canon?: { claim: string; cite: string }[]
  invented?: string[]
}

export interface PlannedElement extends ClusterElement {
  entity_id: string
  collides_with: string
}

export interface ClusterCollision {
  name: string
  kind: string
  canon_id: string
  choices: string[]
}

export interface ClusterPlan {
  campaign: string
  elements: PlannedElement[]
  collisions: ClusterCollision[]
  dropped: Record<string, number>
  /** Relationships that survived the type check, between things this cluster
   *  mints. Written on approval. */
  edges: { source: string; target: string; rel_type: string }[]
  /** Reason -> count for the ones that did not, so a card can say WHY rather
   *  than appearing to have lost them. */
  edges_dropped: Record<string, number>
  /** Relationships the model wrote backwards, held in the direction that
   *  would be legal. Offered, never applied. */
  edges_reversible: {
    source: string
    target: string
    rel_type: string
    /** Sent BY the server so the client never re-folds it. */
    key: string
  }[]
  storable: boolean
}

export interface CampaignInfo {
  slug: string
  name: string
  books: string[]
  sections: number
}

export interface OrderRow {
  section_id: string
  heading: string
  origin: 'canon' | 'campaign'
  skipped: boolean
  /** Which chapter it belongs to, so a picker can group by adventure. */
  chapter?: string
}

export interface StoredResult {
  entity_id: string
  section_id: string
  citations: number
  chain_changes: number
  anchored_after: string
}

async function getJSON<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`)
  if (!response.ok) throw new Error(`${path} failed: ${response.status}`)
  return response.json()
}

/** Posts to a path OUTSIDE `/lab`, which `post` below prefixes. */
async function postTo<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    // A DETAIL IS NOT ALWAYS A STRING. FastAPI returns a list for a validation
    // error and this route returns an object for a collision, and both used to
    // reach the card as the literal text "[object Object]" -- which told a DM
    // that something failed and nothing about what.
    throw new Error(readableDetail(body) || `${path} failed: ${response.status}`)
  }
  return response.json()
}

function readableDetail(body: unknown): string {
  const detail = (body as { detail?: unknown } | null)?.detail
  if (!detail) return ''
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map((entry) => (entry as { msg?: string })?.msg ?? JSON.stringify(entry))
      .join('; ')
  }
  const named = detail as { message?: string }
  return named.message ?? JSON.stringify(detail)
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

  chat(
    message: string,
    model: string,
    depth: Depth,
    sessionId: string,
    book: string,
    campaign: string | null,
  ) {
    return post<ChatReply>('/chat', {
      message, model, depth, session_id: sessionId, book, campaign,
    })
  },

  generate(
    kind: string,
    subject: string,
    model: string,
    depth: Depth,
    book: string,
    campaign: string | null,
    /** The draft being replaced and the one thing to change. Both or neither. */
    revision?: { previous: string; note: string },
  ) {
    return post<GeneratedReply>('/generate', {
      kind,
      subject,
      model,
      depth,
      book,
      campaign,
      previous: revision?.previous ?? '',
      note: revision?.note ?? '',
    })
  },

  campaigns(): Promise<{ campaigns: CampaignInfo[] }> {
    return getJSON('/homebrew/campaigns')
  },

  runningOrder(campaign: string): Promise<{ sections: OrderRow[] }> {
    return getJSON(`/homebrew/running-order?campaign=${encodeURIComponent(campaign)}`)
  },

  /** Approve a card into the graph. The card is the gate; this is the write. */
  store(body: {
    campaign: string
    kind: string
    title: string
    body: string
    generated_body: string
    from_canon: { claim: string; cite: string }[]
    from_yours: { claim: string; cite: string }[]
    invented: string[]
    from_context: string[]
    sources: Source[]
    anchor: string | null
    model: string
  }): Promise<StoredResult> {
    return postTo<StoredResult>('/homebrew/store', body)
  },

  /** What storing WOULD do. Called on every card edit; writes nothing. */
  planCluster(body: Record<string, unknown>): Promise<ClusterPlan> {
    return postTo<ClusterPlan>('/homebrew/plan-cluster', body)
  },

  storeCluster(body: Record<string, unknown>): Promise<StoredResult> {
    return postTo<StoredResult>('/homebrew/store-cluster', body)
  },

  section(sectionId: string, campaign: string | null): Promise<SectionRead> {
    const scope = campaign ? `&campaign=${encodeURIComponent(campaign)}` : ''
    return getJSON(`/homebrew/section?section_id=${encodeURIComponent(sectionId)}${scope}`)
  },

  /** What the graph holds about one thing, for a reader who clicked its name. */
  entity(entityId: string, campaign: string | null): Promise<EntityRead> {
    const scope = campaign ? `&campaign=${encodeURIComponent(campaign)}` : ''
    return getJSON(`/homebrew/entity?entity_id=${encodeURIComponent(entityId)}${scope}`)
  },

  /** Rewrite stored prose. Refuses anything that is not this campaign's,
   *  which includes the book. */
  editSection(campaign: string, sectionId: string, body: string) {
    return postTo<{ section_id: string; edited: boolean; changed: boolean }>(
      '/homebrew/edit',
      { campaign, section_id: sectionId, body },
    )
  },

  /** Change the one line a stub is made of. */
  setRole(campaign: string, entityId: string, role: string) {
    return postTo<{ entity_id: string; role: string }>('/homebrew/role', {
      campaign,
      entity_id: entityId,
      role,
    })
  },

  elements(campaign: string): Promise<{ elements: CampaignElement[]; unwritten: number }> {
    return getJSON(`/homebrew/elements?campaign=${encodeURIComponent(campaign)}`)
  },

  draftExpansion(campaign: string, entityId: string): Promise<GeneratedReply> {
    return postTo<GeneratedReply>('/homebrew/draft-expansion', {
      campaign,
      entity_id: entityId,
    })
  },

  expand(body: Record<string, unknown>): Promise<StoredResult> {
    return postTo<StoredResult>('/homebrew/expand', body)
  },

  skip(campaign: string, sectionId: string) {
    return postTo('/homebrew/skip', { campaign, section_id: sectionId })
  },

  unskip(campaign: string, sectionId: string) {
    return postTo('/homebrew/unskip', { campaign, section_id: sectionId })
  },

  reset(sessionId: string) {
    return fetch(`${API_BASE}/lab/reset?session_id=${encodeURIComponent(sessionId)}`, {
      method: 'POST',
    })
  },
}
