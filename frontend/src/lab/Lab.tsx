import { useEffect, useState } from 'react'
import { labAPI, type Cost, type Depth, type LabConfig, type Usage } from './api'
import { ChatPane } from './ChatPane'
import { Controls } from './Controls'
import { GeneratePane } from './GeneratePane'
import { accumulate, SessionMeter, ZERO, type Running } from './Meters'

const SESSION_ID = 'lab'

const FALLBACK_DEPTH: Depth = {
  passages: 5,
  max_edges: 12,
  include_proposed: true,
  history_turns: 6,
}

export function Lab() {
  const [config, setConfig] = useState<LabConfig | null>(null)
  const [failed, setFailed] = useState('')
  const [model, setModel] = useState('')
  const [depth, setDepth] = useState<Depth>(FALLBACK_DEPTH)
  const [tab, setTab] = useState<'chat' | 'generate'>('chat')
  const [running, setRunning] = useState<Running>(ZERO)

  useEffect(() => {
    labAPI
      .config()
      .then((c) => {
        setConfig(c)
        setModel(c.default_model)
        setDepth(c.defaults ?? FALLBACK_DEPTH)
      })
      .catch((e) => setFailed(e instanceof Error ? e.message : String(e)))
  }, [])

  /** Both panes report the same two fields, so one accumulator serves both. */
  const spend = (reply: { usage: Usage; cost: Cost }) =>
    setRunning((r) => accumulate(r, reply.usage, reply.cost))

  const resetSession = async () => {
    setRunning(ZERO)
    await labAPI.reset(SESSION_ID).catch(() => undefined)
  }

  if (failed) {
    return (
      <div className="min-h-screen bg-neutral-950 text-neutral-200 p-8">
        <h1 className="text-lg mb-2">Agent Lab</h1>
        <p className="text-sm text-red-400">Could not reach the API: {failed}</p>
        <p className="text-sm text-neutral-500 mt-2">
          Start the backend, then reload.
        </p>
      </div>
    )
  }

  if (!config) {
    return (
      <div className="min-h-screen bg-neutral-950 text-neutral-500 p-8 text-sm">
        Loading…
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-neutral-950 text-neutral-200">
      <header className="border-b border-neutral-800 px-6 py-3 flex items-baseline gap-4">
        <h1 className="text-base font-medium">Agent Lab</h1>
        <p className="text-xs text-neutral-500">
          Curse of Strahd canon · 3 of 25 chapters loaded
        </p>
      </header>

      <div className="grid lg:grid-cols-[280px_1fr] gap-6 p-6 max-w-[1400px]">
        <aside className="space-y-5">
          <Controls
            models={config.models}
            model={model}
            onModel={setModel}
            depth={depth}
            onDepth={setDepth}
          />
          <SessionMeter running={running} onReset={resetSession} />
        </aside>

        <main className="min-h-[70vh] flex flex-col">
          <div className="flex gap-2 mb-4">
            {(['chat', 'generate'] as const).map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={`px-4 py-1.5 rounded text-sm border ${
                  t === tab
                    ? 'border-amber-500 bg-amber-500/10'
                    : 'border-neutral-700 hover:border-neutral-600'
                }`}
              >
                {t === 'chat' ? 'Setting chat' : 'Generate'}
              </button>
            ))}
          </div>

          {/* Both panes stay MOUNTED. Switching tabs must not throw away a
              conversation or a generated NPC -- comparing two settings means
              going back and forth. */}
          <div className={tab === 'chat' ? 'flex-1 min-h-0' : 'hidden'}>
            <ChatPane
              model={model}
              depth={depth}
              sessionId={SESSION_ID}
              onSpend={spend}
            />
          </div>
          <div className={tab === 'generate' ? 'flex-1 min-h-0' : 'hidden'}>
            <GeneratePane model={model} depth={depth} onSpend={spend} />
          </div>
        </main>
      </div>
    </div>
  )
}
