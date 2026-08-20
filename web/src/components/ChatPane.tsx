'use client'

import { useState } from 'react'
import { Group, Panel, Separator } from 'react-resizable-panels'
import { labAPI, type ChatReply, type Depth } from '@/lib/api'
import { CallMeter, RetrievalPanel } from './Meters'
import { SubgraphPanel } from './SubgraphPanel'

const SUGGESTION = 'Who owns the Blood of the Vine Tavern?'

type Turn = { question: string; reply?: ChatReply; error?: string }

export function ChatPane({
  model,
  depth,
  sessionId,
  onSpend,
}: {
  model: string
  depth: Depth
  sessionId: string
  onSpend: (reply: ChatReply) => void
}) {
  const [turns, setTurns] = useState<Turn[]>([])
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)

  const ask = async () => {
    const question = draft.trim()
    if (!question || busy) return
    setDraft('')
    setBusy(true)
    setTurns((t) => [...t, { question }])
    try {
      const reply = await labAPI.chat(question, model, depth, sessionId)
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

  return (
    // A DRAG HANDLE RATHER THAN A TOGGLE. Two hardcoded widths were two guesses
    // at what somebody wanted to read, and both were wrong.
    <Group orientation="horizontal" className="h-full">
      <Panel defaultSize="62%" minSize="30%">
        <div className="flex h-full flex-col pr-3">
          <div className="min-h-0 flex-1 space-y-8 overflow-y-auto pr-1">
            {turns.length === 0 && (
              <p className="text-sm leading-relaxed text-neutral-600">
                Ask about the setting. Answers are grounded in the chapters
                loaded into the graph, and every one is cited.
              </p>
            )}

            {turns.map((turn, i) => (
              <div key={i} className="space-y-2">
                <p className="text-sm font-medium text-amber-300/90">{turn.question}</p>

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
                              <span className="text-amber-500/70"> · keyword match</span>
                            )}
                          </li>
                        ))}
                      </ul>
                    )}

                    <CallMeter usage={turn.reply.usage} cost={turn.reply.cost} />
                    <RetrievalPanel report={turn.reply.retrieval} />
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
                  setDraft(SUGGESTION)
                }
              }}
              placeholder={SUGGESTION}
              className="flex-1 rounded-md border border-neutral-800 bg-neutral-900/60 px-3 py-2 text-sm outline-none placeholder:text-neutral-600 focus:border-amber-600/60"
            />
            <button
              onClick={ask}
              disabled={busy || !draft.trim()}
              className="rounded-md bg-amber-600 px-4 py-2 text-sm font-medium text-neutral-950 transition-opacity disabled:opacity-30"
            >
              Ask
            </button>
          </div>
        </div>
      </Panel>

      <Separator className="mx-1 w-1.5 rounded bg-neutral-800 transition-colors hover:bg-amber-600/60" />

      <Panel defaultSize="38%" minSize="20%">
        <div className="h-full overflow-hidden rounded-lg border border-neutral-800 bg-neutral-900/30">
          <SubgraphPanel view={held} />
        </div>
      </Panel>
    </Group>
  )
}
