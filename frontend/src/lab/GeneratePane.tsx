import { useState } from 'react'
import { labAPI, type Depth, type GeneratedReply } from './api'
import { CallMeter, RetrievalPanel } from './Meters'

const KINDS = [
  { id: 'quest', label: 'Quest', placeholder: 'a reason to enter the church undercroft' },
  { id: 'npc', label: 'NPC', placeholder: 'a regular at the Blood of the Vine Tavern' },
  { id: 'monster', label: 'Monster', placeholder: 'something stalking the Svalich Woods' },
]

/** Use case two: generate a quest, NPC or monster, with invention marked. */
export function GeneratePane({
  model,
  depth,
  onSpend,
}: {
  model: string
  depth: Depth
  onSpend: (reply: GeneratedReply) => void
}) {
  const [kind, setKind] = useState('npc')
  const [subject, setSubject] = useState('')
  const [result, setResult] = useState<GeneratedReply | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const placeholder = KINDS.find((k) => k.id === kind)?.placeholder ?? ''

  const run = async () => {
    if (!subject.trim() || busy) return
    setBusy(true)
    setError('')
    setResult(null)
    try {
      const reply = await labAPI.generate(kind, subject.trim(), model, depth)
      setResult(reply)
      onSpend(reply)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex gap-2 mb-3">
        {KINDS.map((k) => (
          <button
            key={k.id}
            onClick={() => setKind(k.id)}
            className={`px-3 py-1.5 rounded text-sm border ${
              k.id === kind
                ? 'border-amber-500 bg-amber-500/10'
                : 'border-neutral-700 hover:border-neutral-600'
            }`}
          >
            {k.label}
          </button>
        ))}
      </div>

      <div className="flex gap-2 mb-4">
        <input
          value={subject}
          onChange={(e) => setSubject(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && run()}
          placeholder={placeholder}
          className="flex-1 bg-neutral-900 border border-neutral-700 rounded px-3 py-2 text-sm"
        />
        <button
          onClick={run}
          disabled={busy || !subject.trim()}
          className="px-4 py-2 rounded bg-amber-600 text-sm disabled:opacity-40"
        >
          {busy ? '…' : 'Generate'}
        </button>
      </div>

      <div className="flex-1 overflow-y-auto space-y-4 pr-1">
        {error && (
          <p className="text-sm text-red-400 border border-red-900 rounded p-2">{error}</p>
        )}

        {result && result.error && (
          <div className="text-sm border border-red-900 rounded p-3 space-y-2">
            <p className="text-red-400">{result.error}</p>
            {/* The raw text travels on failure: a malformed response is evidence
                about the prompt, and hiding it leaves nothing to debug from. */}
            <pre className="text-xs text-neutral-500 whitespace-pre-wrap">{result.raw}</pre>
          </div>
        )}

        {result && !result.error && (
          <>
            <h2 className="text-lg font-medium text-amber-300">{result.title}</h2>
            <p className="text-sm whitespace-pre-wrap">{result.body}</p>

            {/* The split IS the product. A DM who cannot tell which half came
                from the book will eventually contradict the book at the table. */}
            <div className="grid gap-3 md:grid-cols-2">
              <section className="rounded border border-emerald-900/60 p-3">
                <h3 className="text-xs uppercase tracking-wide text-emerald-400 mb-2">
                  From canon
                </h3>
                {result.from_canon.length === 0 ? (
                  <p className="text-xs text-neutral-500">
                    Nothing — all of this is invented.
                  </p>
                ) : (
                  <ul className="text-sm space-y-1">
                    {result.from_canon.map((c, i) => (
                      <li key={i}>
                        {c.claim}{' '}
                        <span className="text-xs text-neutral-500">{c.cite}</span>
                      </li>
                    ))}
                  </ul>
                )}
                <p className="mt-2 text-xs text-neutral-500">
                  Citations point at the passages supplied. Nothing checks that a
                  passage supports its claim — open it and see.
                </p>
              </section>

              <section className="rounded border border-amber-900/60 p-3">
                <h3 className="text-xs uppercase tracking-wide text-amber-400 mb-2">
                  Invented
                </h3>
                <ul className="text-sm space-y-1">
                  {result.invented.map((c, i) => (
                    <li key={i}>{c}</li>
                  ))}
                </ul>
              </section>
            </div>

            {result.sources.length > 0 && (
              <ul className="text-xs text-neutral-400 space-y-0.5">
                {result.sources.map((s, i) => (
                  <li key={i}>
                    <span className="text-neutral-500">{s.citation}</span>{' '}
                    {s.section ?? s.source}
                  </li>
                ))}
              </ul>
            )}

            <CallMeter usage={result.usage} cost={result.cost} />
            <RetrievalPanel report={result.retrieval} />
          </>
        )}
      </div>
    </div>
  )
}
