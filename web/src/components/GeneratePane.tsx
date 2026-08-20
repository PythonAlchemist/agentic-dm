'use client'

import { useState } from 'react'
import { labAPI, type Depth, type GeneratedReply } from '@/lib/api'
import { CallMeter, RetrievalPanel } from './Meters'

const KINDS = [
  { id: 'quest', label: 'Quest', placeholder: 'a reason to enter the church undercroft' },
  { id: 'npc', label: 'NPC', placeholder: 'a regular at the Blood of the Vine Tavern' },
  { id: 'monster', label: 'Monster', placeholder: 'something stalking the Svalich Woods' },
]

/** A quest, NPC or monster, with what came from the book kept apart from what
 *  was made up. */
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
    <div className="flex h-full flex-col">
      <div className="mb-3 flex shrink-0 gap-1 rounded-lg border border-neutral-800 bg-neutral-900/60 p-1 self-start">
        {KINDS.map((k) => (
          <button
            key={k.id}
            onClick={() => setKind(k.id)}
            className={`rounded-md px-3 py-1.5 text-sm transition-colors ${
              kind === k.id
                ? 'bg-amber-500/15 text-amber-200'
                : 'text-neutral-400 hover:bg-neutral-800/60'
            }`}
          >
            {k.label}
          </button>
        ))}
      </div>

      <div className="mb-4 flex shrink-0 gap-2">
        <input
          value={subject}
          onChange={(e) => setSubject(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') return void run()
            // Fill only into an empty field, so Tab goes on moving focus.
            if (e.key === 'Tab' && !subject) {
              e.preventDefault()
              setSubject(placeholder)
            }
          }}
          placeholder={placeholder}
          className="flex-1 rounded-md border border-neutral-800 bg-neutral-900/60 px-3 py-2 text-sm outline-none placeholder:text-neutral-600 focus:border-amber-600/60"
        />
        <button
          onClick={run}
          disabled={busy || !subject.trim()}
          className="rounded-md bg-amber-600 px-4 py-2 text-sm font-medium text-neutral-950 disabled:opacity-30"
        >
          {busy ? '…' : 'Generate'}
        </button>
      </div>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto pr-1">
        {error && (
          <p className="rounded-md border border-red-900/60 bg-red-950/30 p-3 text-sm text-red-400">
            {error}
          </p>
        )}

        {result?.error && (
          <div className="space-y-2 rounded-md border border-red-900/60 p-3 text-sm">
            <p className="text-red-400">{result.error}</p>
            {/* The raw text travels on failure: a malformed response is
                evidence about the prompt, and hiding it leaves nothing to
                debug from. */}
            <pre className="whitespace-pre-wrap text-xs text-neutral-500">{result.raw}</pre>
          </div>
        )}

        {result && !result.error && (
          <>
            <h2 className="text-lg font-medium text-amber-300">{result.title}</h2>
            <p className="whitespace-pre-wrap text-sm leading-relaxed text-neutral-200">
              {result.body}
            </p>

            {/* THE SPLIT IS THE PRODUCT. A DM who cannot tell which half came
                from the book will eventually contradict the book at the table. */}
            <div className="grid gap-3 md:grid-cols-2">
              <section className="rounded-lg border border-emerald-900/50 bg-emerald-950/10 p-3">
                <h3 className="mb-2 text-[11px] font-medium uppercase tracking-wider text-emerald-400">
                  From canon
                </h3>
                {result.from_canon.length === 0 ? (
                  <p className="text-xs text-neutral-500">
                    Nothing — all of this is invented.
                  </p>
                ) : (
                  <ul className="space-y-1 text-sm text-neutral-200">
                    {result.from_canon.map((c, i) => (
                      <li key={i}>
                        {c.claim} <span className="text-xs text-neutral-600">{c.cite}</span>
                      </li>
                    ))}
                  </ul>
                )}
                <p className="mt-2 text-xs leading-relaxed text-neutral-600">
                  Citations point at the passages supplied. Nothing checks that a
                  passage supports its claim — open it and see.
                </p>
              </section>

              <section className="rounded-lg border border-amber-900/50 bg-amber-950/10 p-3">
                <h3 className="mb-2 text-[11px] font-medium uppercase tracking-wider text-amber-400">
                  Invented
                </h3>
                <ul className="space-y-1 text-sm text-neutral-200">
                  {result.invented.map((c, i) => (
                    <li key={i}>{c}</li>
                  ))}
                </ul>
              </section>
            </div>

            {result.sources.length > 0 && (
              <ul className="space-y-0.5 text-xs text-neutral-600">
                {result.sources.map((s, i) => (
                  <li key={i}>
                    {s.citation} {s.section ?? s.source}
                    {s.path === 'text' && (
                      <span className="text-amber-500/70"> · keyword match</span>
                    )}
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
