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

/**
 * The reader token, and the single door every request goes through.
 *
 * WHY A TOKEN AT ALL: the graph holds the prose of two published books, so the
 * deployment is gated and each reader is a person the DM confirmed owns them.
 * `backend/api/auth.py` is the other half and explains the rest.
 *
 * EVERY REQUEST GOES THROUGH `send`, rather than each call site remembering to
 * attach a header. Five sites is few enough to edit by hand and exactly few
 * enough that the sixth, added later, would be the one that forgot -- and a
 * forgotten header here is not a bug that shows up as a header problem, it is
 * a login screen appearing at random.
 */
const TOKEN_KEY = 'agentic-dm.reader-token'

let token = ''
let refusedHandler: (() => void) | null = null

const SESSION_KEY = 'agentic-dm.session'

/** This browser's own conversation, kept across reloads.
 *
 *  IT USED TO BE THE CONSTANT `'lab'`, WHICH WAS FINE FOR ONE PERSON ON
 *  LOCALHOST AND IS NOT FINE NOW. The API holds `_SESSIONS: dict[str, DMAgent]`
 *  keyed on this, and the agent carries the conversation, so every reader of
 *  the deployment shared one history: what one of them asked arrived in the
 *  next one's context, and any reader's Reset emptied it for all of them.
 *
 *  PERSISTED RATHER THAN GENERATED PER LOAD, because the id is also the
 *  bookmark -- a refresh should return to the conversation, not start a new
 *  one and strand the old agent in the API's memory.
 */
export function sessionId(): string {
  if (typeof window === 'undefined') return 'lab'
  let found = window.localStorage.getItem(SESSION_KEY)
  if (!found) {
    found =
      typeof crypto !== 'undefined' && 'randomUUID' in crypto
        ? crypto.randomUUID()
        : `s-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
    window.localStorage.setItem(SESSION_KEY, found)
  }
  return found
}

export const auth = {
  /** Read back what this browser was given. Guarded for the server render,
   *  where `localStorage` does not exist and touching it throws. */
  load(): string {
    if (typeof window === 'undefined') return ''
    token = window.localStorage.getItem(TOKEN_KEY) ?? ''
    return token
  },
  set(value: string) {
    token = value.trim()
    if (typeof window !== 'undefined') window.localStorage.setItem(TOKEN_KEY, token)
  },
  clear() {
    token = ''
    if (typeof window !== 'undefined') window.localStorage.removeItem(TOKEN_KEY)
  },
  has(): boolean {
    return token.length > 0
  },
  /** Called when the API refuses us, so the app can show the door again. */
  onRefused(handler: () => void) {
    refusedHandler = handler
  },
  /**
   * Does the API accept what we are holding?
   *
   * ASKED OF THE API RATHER THAN DECIDED HERE, and `/lab/config` is the
   * cheapest thing behind the gate -- it reads a handful of counts and no book
   * text. A frontend that judged its own token would be a gate anyone could
   * walk through with the devtools open.
   */
  /** Whether this token is one of theirs, or why we cannot say.
   *
   *  THREE ANSWERS, NOT TWO. `ok`/`not ok` told a reader with a perfectly good
   *  token that it had been refused whenever the API was merely down -- a
   *  Railway cold start, a dead Neo4j, no network at all -- which is the one
   *  message that makes somebody stop trying. A refusal is a 401 and nothing
   *  else; every other failure is "we could not ask".
   */
  async check(): Promise<'ok' | 'refused' | 'unreachable'> {
    try {
      const response = await send(`${API_BASE}/lab/config`)
      if (response.ok) return 'ok'
      return response.status === 401 ? 'refused' : 'unreachable'
    } catch {
      // `send` rejects on a network failure. Unhandled, this left the Door's
      // button stuck on "checking..." forever, because the line that cleared
      // it never ran.
      return 'unreachable'
    }
  },
}

/**
 * `fetch`, carrying the token and noticing when it is rejected.
 *
 * A 401 CLEARS THE STORED TOKEN rather than retrying, because the only two
 * ways to get one are a token that was never right and a token that has been
 * revoked -- and in both the answer is to ask for a new one, not to keep
 * sending the old one at every endpoint the page touches.
 */
async function send(url: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers)
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const response = await fetch(url, { ...init, headers })
  if (response.status === 401) {
    auth.clear()
    refusedHandler?.()
  }
  return response
}

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
  nodes: {
    id: string
    name: string
    labels: string[]
    how: string
    turn: number
    /** False when no section of the book names this — the node came from
     *  extraction, holds no mention, and there is no sentence to quote. The
     *  panel is where a DM sees what an answer was built on, so it has to be
     *  able to show one of these apart from a thing the book prints. */
    named_by_book?: boolean
  }[]
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
  /** The section this REPLACES, when the DM asked to change something that
   *  already exists. Storing it rewrites rather than mints. */
  revises?: string
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
  /** The entity this section is ABOUT, when it is about one. A write-up of
   *  Captain Saltmarrow names her, so she is among its mentions -- which is
   *  right for underlining her in her own prose and wrong for listing her as
   *  something she is connected to. */
  describes: string | null
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
  /** One hop out from everything this prose names: what those things are
   *  connected to. The prose does not say it; the graph does. */
  connections: {
    from: string
    /** Both ends by id, so a guess can be addressed well enough to reject. */
    from_id: string
    rel: string
    to: string
    to_id: string
    plane: 'canon' | 'campaign'
    status: string | null
  }[]
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
  /** Whether any section of the book actually names this. False for entities
   *  the extractor described rather than found — `Side Room 2`, or a common
   *  noun it title-cased. They are kept deliberately, so the card has to say
   *  which kind it is showing. Meaningless on the campaign plane. */
  named_by_book: boolean
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
  /** What it is connected to. The card never needed these — it answers "who is
   *  this again" — but a profile is where a DM grooms an entity's
   *  relationships, and `status` travels so a guess can never be rendered as a
   *  derived fact. */
  connections: {
    dir: 'in' | 'out'
    rel: string
    status: string | null
    other: string
    other_id: string
    other_labels: string[]
    other_plane: 'canon' | 'campaign'
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
  /** What this sits INSIDE, or "". Containment, which is a different axis
   *  from the order — see `backend/campaign/ontology.py`. */
  parent: string
  /** chapter | section | subsection | scene | encounter */
  level: string
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
  const response = await send(`${API_BASE}${path}`)
  if (!response.ok) throw new Error(`${path} failed: ${response.status}`)
  return response.json()
}

/** Posts to a path OUTSIDE `/lab`, which `post` below prefixes. */
async function postTo<T>(path: string, body: unknown): Promise<T> {
  const response = await send(`${API_BASE}${path}`, {
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
  const response = await send(`${API_BASE}/lab${path}`, {
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
    const response = await send(`${API_BASE}/lab/config`)
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
    /** A section or entity id the DM has open. Biases retrieval; never
     *  narrows it. */
    focus = '',
  ) {
    return post<ChatReply>('/chat', {
      message, model, depth, session_id: sessionId, book, campaign,
      focus,
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

  /** Read a stored section back and propose the relationships in its prose.
   *  Costs a model call, so it runs AFTER a write rather than inside one, and
   *  what it writes is `proposed` — a guess, dimmed and labelled, never mixed
   *  in with what the DM asserted. */
  deriveEdges(campaign: string, sectionId: string) {
    return postTo<{ written: number; dropped: Record<string, number> }>(
      '/homebrew/derive-edges',
      { campaign, section_id: sectionId },
    )
  },

  /** Put a section immediately after another in the running order.
   *  Sequence only — what it sits inside is untouched. */
  move(campaign: string, sectionId: string, after: string) {
    return postTo<{ changed: number; noop?: string }>('/homebrew/move', {
      campaign,
      section_id: sectionId,
      after,
    })
  },

  /** Put a section INSIDE another, or pass '' to pull it to the top level.
   *  Containment only — the order is untouched. */
  nest(campaign: string, sectionId: string, parent: string) {
    return postTo<{ section_id: string; parent: string }>('/homebrew/nest', {
      campaign,
      section_id: sectionId,
      parent,
    })
  },

  /** Ask a draft what things it contains, after the fact. The write path
   *  annotates a quest or scene as it is generated; when that finds nothing
   *  the DM is left with one entity and no way to ask again. */
  findElements(
    body: string,
    subject: string,
    kind: string,
    book: string,
    campaign: string | null,
    model: string,
  ) {
    return post<{
      elements: GeneratedReply['elements']
      edges: GeneratedReply['edges']
      dropped: Record<string, number>
    }>('/find-elements', { body, subject, kind, book, campaign, model })
  },

  /** Say no to a guess, so it stays said. Deleting one only removes it until
   *  the next read-back proposes it again. */
  rejectEdge(campaign: string, source: string, relType: string, target: string) {
    return postTo<{ rejected: number; note?: string }>('/homebrew/reject-edge', {
      campaign,
      source,
      rel_type: relType,
      target,
    })
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
    return send(`${API_BASE}/lab/reset?session_id=${encodeURIComponent(sessionId)}`, {
      method: 'POST',
    })
  },
}

/**
 * The table's own API: who sits at it, what it played, and what it may see.
 *
 * A SEPARATE OBJECT FROM `labAPI`, because it is a separate audience. The lab
 * is one person's research console and every one of its calls assumes the
 * reader is the DM. These are read by players, and the difference has to be
 * visible in the code and not only in the routes.
 *
 * NOTHING HERE ASKS FOR A VIEW. There is no `asDM` parameter to pass, because
 * the server derives the audience from the seat -- see `_for_player` in
 * `backend/api/routes/table.py`. `preview` is the exception that proves it:
 * it can only ever narrow a DM to what the table sees.
 */

export interface Seat {
  reader: string
  role: 'dm' | 'player'
}

export interface Whoami {
  reader: string
  role: string
  identified: boolean
}

export interface SessionRow {
  id: string
  number: number
  title: string
  status: string
  held_on: string
  planned: number
  covered: number
}

export interface Scene {
  id: string
  heading: string
}

export interface SessionDiff {
  planned: Scene[]
  covered: Scene[]
  /** Meant and not reached. */
  missed: Scene[]
  /** Reached and never planned -- where a campaign actually leaves the book. */
  unplanned: Scene[]
}

export interface MapRow {
  id: string
  name: string
  place_id: string
  place: string
  asset_id: string
  origin: string
}

export interface Pin {
  entity_id: string
  /** What THIS reader may call it. A player sees the alias when the DM set
   *  one, and the true name is not in the payload at all. */
  name: string
  labels: string[]
  x: number
  y: number
  /** DM view only. */
  plane?: string
  note?: string
  revealed?: boolean
  as_name?: string
}

export interface Portrait {
  id: string
  origin: string
  media_type: string
  primary: boolean
  /** "the book's art", "yours", "imagined" -- written beside the property
   *  that decides it so the two cannot drift. */
  caption: string
}

function query(params: Record<string, string | boolean | undefined>): string {
  const pairs = Object.entries(params).filter(([, v]) => v !== undefined && v !== '')
  return pairs.map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`).join('&')
}

export interface Found {
  entity_id: string
  name: string
  plane: string
  labels: string[]
  named_by_book: boolean
}

export const tableAPI = {
  /** Something to pin, portray, or open. Scoped to the books this table drew
   *  on plus what it wrote -- a name belongs to the adventure that says it. */
  search(campaign: string, q: string, label = ''): Promise<{ found: Found[] }> {
    return getJSON(`/table/search?${query({ campaign, q, label })}`)
  },

  /** The URL of an asset's bytes. Content-addressed, so it never means
   *  different pixels later. */
  assetURL(assetId: string): string {
    return `${API_BASE}/table/asset/${encodeURIComponent(assetId)}`
  },

  whoami(campaign: string): Promise<Whoami> {
    return getJSON(`/table/me?${query({ campaign })}`)
  },

  seats(campaign: string): Promise<{ seats: Seat[] }> {
    return getJSON(`/table/seats?${query({ campaign })}`)
  },

  seat(campaign: string, reader: string, role: string) {
    return postTo<Seat>('/table/seat', { campaign, reader, role })
  },

  unseat(campaign: string, reader: string) {
    return send(`${API_BASE}/table/seat?${query({ campaign, reader })}`, {
      method: 'DELETE',
    })
  },

  sessions(campaign: string): Promise<{ sessions: SessionRow[] }> {
    return getJSON(`/table/sessions?${query({ campaign })}`)
  },

  openSession(campaign: string, title = '', heldOn = '') {
    return postTo<SessionRow>('/table/session', {
      campaign, title, held_on: heldOn,
    })
  },

  plan(campaign: string, session: string, section: string) {
    return postTo<{ planned: number }>('/table/session/plan', {
      campaign, session, section,
    })
  },

  cover(campaign: string, session: string, section: string) {
    return postTo<{ covered: number }>('/table/session/cover', {
      campaign, session, section,
    })
  },

  /** What was actually said. Writes sections and mentions; mints nothing. */
  transcript(campaign: string, session: string, content: string) {
    return postTo<{
      replaced: number
      sections: number
      mentions: number
      turns: number
    }>('/table/session/transcript', { campaign, session, content })
  },

  /** Planned scenes the recording appears to have reached. A list to press,
   *  never an edge somebody else wrote for you. */
  touched(campaign: string, sessionId: string): Promise<{
    touched: { section_id: string; heading: string; names: string[]; shared: number }[]
  }> {
    return getJSON(`/table/session/touched?${query({ campaign, session_id: sessionId })}`)
  },

  diff(campaign: string, sessionId: string): Promise<SessionDiff> {
    return getJSON(`/table/session/diff?${query({ campaign, session_id: sessionId })}`)
  },

  maps(campaign: string): Promise<{ maps: MapRow[] }> {
    return getJSON(`/table/maps?${query({ campaign })}`)
  },

  createMap(campaign: string, name: string, place: string, asset: string) {
    return postTo<{ id: string; name: string }>('/table/map', {
      campaign, name, place, asset,
    })
  },

  /** `preview` asks for the player's view of a map you run. It cannot ask for
   *  the other direction. */
  pins(campaign: string, mapId: string, preview = false): Promise<{
    pins: Pin[]
    as_player: boolean
  }> {
    return getJSON(`/table/map/pins?${query({ campaign, map_id: mapId, preview })}`)
  },

  pin(campaign: string, map: string, entity: string, x: number, y: number) {
    return postTo<Pin>('/table/map/pin', { campaign, map, entity, x, y })
  },

  unpin(campaign: string, mapId: string, entity: string) {
    return send(
      `${API_BASE}/table/map/pin?${query({ campaign, map_id: mapId, entity })}`,
      { method: 'DELETE' },
    )
  },

  reveal(campaign: string, map: string, entity: string, revealed: boolean, asName = '') {
    return postTo<{ revealed: boolean }>('/table/map/reveal', {
      campaign, map, entity, revealed, as_name: asName,
    })
  },

  portraits(entityId: string, campaign: string): Promise<{ portraits: Portrait[] }> {
    return getJSON(`/table/portraits?${query({ entity_id: entityId, campaign })}`)
  },

  /** Send the bytes. The route cannot record them as anything but yours. */
  async upload(campaign: string, file: File): Promise<Portrait> {
    const form = new FormData()
    form.append('file', file)
    // NO `Content-Type` HEADER. `fetch` sets it with the multipart boundary,
    // and setting it by hand produces a body the server cannot parse.
    const response = await send(
      `${API_BASE}/table/asset/upload?${query({ campaign })}`,
      { method: 'POST', body: form },
    )
    if (!response.ok) {
      throw new Error(readableDetail(await response.json().catch(() => null))
        || `upload failed: ${response.status}`)
    }
    return response.json()
  },

  portray(campaign: string, entity: string, asset: string) {
    return postTo<{ portrayed: number }>('/table/portray', {
      campaign, entity, asset,
    })
  },
}
