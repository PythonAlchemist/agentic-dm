import { useState } from 'react'
import { labAPI, type ChatReply, type Depth } from './api'
import { CallMeter, RetrievalPanel } from './Meters'
import { SubgraphPanel } from './SubgraphPanel'

interface Turn {
  question: string
  reply?: ChatReply
  error?: string
}

/** Use case one: general chat about the setting, grounded in canon. */
/** The example question, shown as a placeholder and filled in by Tab. One
 *  constant so the two cannot drift into suggesting different things. */
const SUGGESTION = 'Who owns the Blood of the Vine Tavern?'

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
    } catch (e) {
      const error = e instanceof Error ? e.message : String(e)
      setTurns((t) => t.map((turn, i) => (i === t.length - 1 ? { ...turn, error } : turn)))
    } finally {
      setBusy(false)
    }
  }

  // The LAST turn's subgraph, because it is cumulative -- every turn carries
  // the whole working set, so the newest reply is the current state rather
  // than a delta to be merged.
  const held = [...turns].reverse().find((turn) => turn.reply)?.reply?.subgraph ?? null

  return (
    <div className="flex gap-4 h-full">
      <div className="flex flex-col h-full flex-1 min-w-0">
      <div className="flex-1 overflow-y-auto space-y-6 pr-1">
        {turns.length === 0 && (
          <p className="text-sm text-neutral-500">
            Ask about the setting. Answers are grounded in the chapters loaded
            into the graph, and every one is cited.
          </p>
        )}

        {turns.map((turn, i) => (
          <div key={i} className="space-y-2">
            <p className="text-sm text-amber-300">{turn.question}</p>

            {turn.error && (
              <p className="text-sm text-red-400 border border-red-900 rounded p-2">
                {turn.error}
              </p>
            )}

            {turn.reply && (
              <>
                <p className="text-sm whitespace-pre-wrap">{turn.reply.message}</p>

                {turn.reply.sources.length > 0 && (
                  <ul className="text-xs text-neutral-400 space-y-0.5">
                    {turn.reply.sources.map((s, j) => (
                      <li key={j}>
                        <span className="text-neutral-500">{s.citation}</span>{' '}
                        {s.section ?? s.source}
                        {s.path === 'text' && (
                          <span className="text-amber-500/80"> · keyword match</span>
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
              <p className="text-sm text-neutral-500">thinking…</p>
            )}
          </div>
        ))}
      </div>

      <div className="pt-3 mt-3 border-t border-neutral-800 flex gap-2">
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') return ask()
            // Tab fills the suggestion, but ONLY into an empty field -- with
            // anything typed, Tab has to go on moving focus or the form
            // becomes unnavigable by keyboard.
            if (e.key === 'Tab' && !draft) {
              e.preventDefault()
              setDraft(SUGGESTION)
            }
          }}
          placeholder={SUGGESTION}
          className="flex-1 bg-neutral-900 border border-neutral-700 rounded px-3 py-2 text-sm"
        />
        <button
          onClick={ask}
          disabled={busy || !draft.trim()}
          className="px-4 py-2 rounded bg-amber-600 text-sm disabled:opacity-40"
        >
          Ask
        </button>
      </div>
      </div>

      <aside className="w-[300px] shrink-0 border-l border-neutral-800 overflow-y-auto">
        <SubgraphPanel view={held} />
      </aside>
    </div>
  )
}
