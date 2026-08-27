'use client'

import { useEffect, useState } from 'react'
import { Group, Panel, Separator } from 'react-resizable-panels'
import {
  labAPI,
  type ChatReply,
  type Depth,
  type GeneratedReply,
  type OrderRow,
} from '@/lib/api'
import { GenerationCard } from './GenerationCard'
import { CallMeter, MissReason, RetrievalPanel } from './Meters'
import { useDebug } from '@/lib/debug'
import { PaneHeader } from './ui'
import { SubgraphPanel } from './SubgraphPanel'


type Turn = { question: string; reply?: ChatReply; error?: string }

export function ChatPane({
  raised,
  onRaisedHandled,
  suggestion,
  book,
  campaign,
  onChainChanged,
  model,
  depth,
  sessionId,
  onSpend,
  focus,
  onClearFocus,
}: {
  /** From the selected book's seed -- a Barovia tavern used to sit in this box
   *  while the lab answered out of a heist anthology. Empty means no chip. */
  suggestion: string
  book: string
  campaign: string | null
  onChainChanged: () => void
  /** A draft raised outside the conversation -- from the material panel --
   *  shown in the same card as anything the chat produced. One review
   *  surface, however a draft was asked for. */
  raised: GeneratedReply | null
  onRaisedHandled: () => void
  model: string
  depth: Depth
  sessionId: string
  onSpend: (reply: ChatReply) => void
  /** What the DM has open. A prior on retrieval, shown so it can be argued
   *  with — an invisible bias reads as the tool getting quietly worse. */
  focus: { id: string; label: string } | null
  onClearFocus: () => void
}) {
  const [debug] = useDebug()
  const [openHeld, setOpenHeld] = useState(false)
  const [turns, setTurns] = useState<Turn[]>([])
  const [raisedCards, setRaisedCards] = useState<GeneratedReply[]>([])

  // A draft raised from the material panel joins the transcript as its own
  // entry, so the DM reviews it exactly where they review everything else.
  //
  // DEFERRED OUT OF THE SYNCHRONOUS EFFECT BODY: setting state straight from
  // an effect cascades renders, and this one also clears the prop that
  // triggered it, which is exactly the loop the rule exists to stop.
  useEffect(() => {
    if (!raised) return
    const timer = setTimeout(() => {
      setRaisedCards((prior) => [...prior, raised])
      onRaisedHandled()
    }, 0)
    return () => clearTimeout(timer)
  }, [raised, onRaisedHandled])
  // The anchor picker on a card needs the book's sections to choose from.
  // Fetched once per table rather than per card: it is the same list.
  const [order, setOrder] = useState<OrderRow[]>([])

  useEffect(() => {
    if (!campaign) return
    // `cancelled` is not lint appeasement: switching tables mid-fetch would
    // otherwise let the previous table's order land and be offered as this
    // one's insertion points.
    let cancelled = false
    labAPI
      .runningOrder(campaign)
      .then((r) => {
        if (!cancelled) setOrder(r.sections)
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [campaign])

  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)

  const ask = async () => {
    const question = draft.trim()
    if (!question || busy) return
    setDraft('')
    setBusy(true)
    setTurns((t) => [...t, { question }])
    try {
      const reply = await labAPI.chat(
        question, model, depth, sessionId, book, campaign, focus?.id ?? '',
      )
      setTurns((t) => t.map((turn, i) => (i === t.length - 1 ? { ...turn, reply } : turn)))
      onSpend(reply)
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      setTurns((t) => t.map((turn, i) => (i === t.length - 1 ? { ...turn, error: message } : turn)))
    } finally {
      setBusy(false)
    }
  }

  // The LAST turn's subgraph, because it is cumulative: every turn carries the
  // whole working set, so the newest reply is the current state.
  const held = [...turns].reverse().find((turn) => turn.reply)?.reply?.subgraph ?? null

  // WHAT THE AGENT IS HOLDING, as one line until it is asked for. The panel
  // took 38% of the screen permanently to answer a question — "did the agent
  // forget this, or never know it?" — that is only ever asked when an answer
  // looks wrong. The strip keeps the COUNTS, so an anomaly (nothing held, all
  // of it guessed, names it never resolved) is still visible without opening
  // anything; the drag handle and the ledger/graph pair come back untouched
  // when it is open.
  const counts = held
    ? `${held.nodes.length} held · ${held.edges.filter((e) => e.status !== 'accepted').length} guessed`
    : 'nothing held yet'

  return (
    // VERTICAL NOW THAT CHAT IS A COLUMN. Splitting an 833px column
    // horizontally gave the ledger 313px, which is narrower than the entity
    // names in it. Opening downward is what the shape of the pane wants.
    <Group orientation="vertical" className="h-full">
      <Panel defaultSize={openHeld ? '62%' : '100%'} minSize="30%">
        <div className="flex h-full flex-col overflow-hidden rounded-lg border border-neutral-800 bg-neutral-900/20">
          <PaneHeader title="Chat" subtitle={focus ? focus.label : undefined}>
            {focus && (
              <button
                onClick={onClearFocus}
                title="Ask about the whole book instead"
                className="text-neutral-600 hover:text-neutral-300"
              >
                unfocus
              </button>
            )}
          </PaneHeader>
          <div className="flex min-h-0 flex-1 flex-col p-3">
          <div className="min-h-0 flex-1 space-y-8 overflow-y-auto pr-1">
            {raisedCards.map((card, index) => (
              <div key={`raised-${index}`} className="mb-4">
                <p className="mb-1 text-xs text-neutral-500">
                  Drafted from your material panel — nothing is stored yet.
                </p>
                <GenerationCard
                  card={card}
                  campaign={campaign}
                  order={campaign ? order : []}
                  onStored={onChainChanged}
                />
              </div>
            ))}
            {turns.length === 0 && raisedCards.length === 0 && (
              <p className="text-sm leading-relaxed text-neutral-600">
                Ask about the setting. Answers are grounded in the chapters
                loaded into the graph, and every one is cited.
              </p>
            )}

            {turns.map((turn, i) => (
              <div key={i} className="space-y-2">
                <p className="text-sm font-medium text-neutral-100">{turn.question}</p>

                {turn.error && (
                  <p className="rounded-md border border-red-900/60 bg-red-950/30 px-3 py-2 text-sm text-red-400">
                    {turn.error}
                  </p>
                )}

                {turn.reply && (
                  <>
                    <div className="whitespace-pre-wrap text-sm leading-relaxed text-neutral-200">
                      {turn.reply.message}
                    </div>

                    {turn.reply.sources.length > 0 && (
                      <ul className="space-y-0.5 text-xs text-neutral-600">
                        {turn.reply.sources.map((s) => (
                          <li key={s.citation}>
                            {s.citation} {s.section}
                            {/* Per PASSAGE. A mixed result is now the normal
                                case, and labelling the whole answer by how the
                                QUESTION resolved credited the graph for
                                answers a keyword match earned. */}
                            {s.path === 'text' && (
                              <span className="text-neutral-500"> · keyword match</span>
                            )}
                            {/* THE PRIOR, MADE VISIBLE. A passage here because
                                of what is open — not because the question named
                                it — has to say so, or a DM watches answers drift
                                toward whatever they last clicked with no way to
                                know why. */}
                            {s.path === 'focus' && (
                              <span className="text-neutral-500">
                                {' '}· from what you’re reading
                              </span>
                            )}
                          </li>
                        ))}
                      </ul>
                    )}

                    {/* CARDS, NOT PROSE. The model was told to say a draft is
                        ready and not to write it; this is where the draft
                        actually appears, with its provenance split intact and
                        a person's approval between it and the graph. */}
                    {(turn.reply.generations ?? []).map((card, index) => (
                      <div key={index} className="mt-3">
                        <GenerationCard
                          card={card}
                          campaign={campaign}
                          order={campaign ? order : []}
                          onStored={onChainChanged}
                        />
                      </div>
                    ))}

                    {/* MECHANISM, BEHIND THE FLIP. These ran on every turn,
                        so a ten-turn conversation carried ten retrieval
                        reports about questions the DM had already moved past.
                        The miss reason stays: an answer that retrieved nothing
                        is a trust event, not a diagnostic. */}
                    <MissReason report={turn.reply.retrieval} />
                    {debug && (
                      <>
                        <CallMeter usage={turn.reply.usage} cost={turn.reply.cost} />
                        <RetrievalPanel report={turn.reply.retrieval} />
                      </>
                    )}
                  </>
                )}

                {!turn.reply && !turn.error && (
                  <p className="text-sm text-neutral-600">thinking…</p>
                )}
              </div>
            ))}
          </div>

          <div className="mt-4 flex shrink-0 gap-2 border-t border-neutral-800 pt-4">
            <input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') return void ask()
                // Tab fills the suggestion, but only into an EMPTY field --
                // with anything typed, Tab has to go on moving focus.
                if (e.key === 'Tab' && !draft) {
                  e.preventDefault()
                  setDraft(suggestion)
                }
              }}
              placeholder={suggestion}
              className="flex-1 rounded-md border border-neutral-800 bg-neutral-900/60 px-3 py-2 text-sm outline-none placeholder:text-neutral-600 focus:border-neutral-500"
            />
            <button
              onClick={ask}
              disabled={busy || !draft.trim()}
              className="rounded-md bg-neutral-200 px-4 py-2 text-sm font-medium text-neutral-950 hover:bg-white transition-opacity disabled:opacity-30"
            >
              Ask
            </button>
          </div>

          <button
            onClick={() => setOpenHeld((prior) => !prior)}
            className="mt-2 self-start text-xs text-neutral-600 hover:text-neutral-300"
          >
            {openHeld ? '▾' : '▸'} in this conversation — {counts}
          </button>
          </div>
        </div>
      </Panel>

      {/* A DRAG HANDLE RATHER THAN A TOGGLE, still: two hardcoded widths were
          two guesses at what somebody wanted to read, and both were wrong. */}
      {openHeld && (
        <>
          <Separator className="my-1 h-1.5 rounded bg-neutral-800 transition-colors hover:bg-neutral-600" />
          <Panel defaultSize="38%" minSize="20%">
            <div className="h-full overflow-hidden rounded-lg border border-neutral-800 bg-neutral-900/30">
              <SubgraphPanel view={held} />
            </div>
          </Panel>
        </>
      )}
    </Group>
  )
}
