'use client'

import { useEffect, useState } from 'react'
import { ChatPane } from '@/components/ChatPane'
import { Controls } from '@/components/Controls'
import { GeneratePane } from '@/components/GeneratePane'
import { SessionMeter, type Running } from '@/components/Meters'
import { TabBar, TooltipProvider } from '@/components/ui'
import { labAPI, type Cost, type Depth, type LabConfig, type Usage } from '@/lib/api'

const SESSION_ID = 'lab'

/** Used only until `/lab/config` answers. The server owns the real defaults --
 *  they are read from `canon_context.Depth`, so the number the evaluation
 *  harness measures is the number the lab shows. */
const FALLBACK_DEPTH: Depth = {
  passages: 8,
  max_edges: 12,
  include_proposed: true,
  passage_width: 'section',
}

const ZERO: Running = { calls: 0, input: 0, output: 0, usd: 0, unverified: false }

function accumulate(running: Running, usage: Usage, cost: Cost): Running {
  return {
    calls: running.calls + 1,
    input: running.input + usage.input,
    output: running.output + usage.output,
    // A missing price adds nothing rather than guessing, and `unverified`
    // records that the total is now partly built on unchecked numbers.
    usd: running.usd + (cost.usd ?? 0),
    unverified: running.unverified || !cost.verified,
  }
}

export default function Lab() {
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

  const spend = (reply: { usage: Usage; cost: Cost }) =>
    setRunning((r) => accumulate(r, reply.usage, reply.cost))

  const resetSession = async () => {
    setRunning(ZERO)
    await labAPI.reset(SESSION_ID).catch(() => undefined)
  }

  if (failed) {
    return (
      <div className="p-8">
        <h1 className="mb-2 text-lg">Agent Lab</h1>
        <p className="text-sm text-red-400">Could not reach the API: {failed}</p>
        <p className="mt-2 text-sm text-neutral-500">
          Start the backend with{' '}
          <code className="text-neutral-300">
            uv run uvicorn backend.api.main:app --reload
          </code>
          .
        </p>
      </div>
    )
  }

  if (!config) {
    return <div className="p-8 text-sm text-neutral-600">Loading…</div>
  }

  return (
    <TooltipProvider>
      <div className="flex h-full flex-col">
        <header className="flex shrink-0 items-baseline gap-4 border-b border-neutral-800 px-6 py-3">
          <h1 className="text-base font-medium">Agent Lab</h1>
          {/* COUNTED, never written down. This read "3 of 25 chapters loaded"
              long after the whole book was in, in three separate places. */}
          <p className="text-xs text-neutral-600">
            Curse of Strahd canon · {config.chapters} chapters loaded
          </p>
        </header>

        <div className="flex min-h-0 flex-1 gap-6 p-6">
          <aside className="w-72 shrink-0 space-y-4 overflow-y-auto">
            <Controls
              models={config.models}
              model={model}
              onModel={setModel}
              depth={depth}
              onDepth={setDepth}
            />
            <SessionMeter running={running} onReset={resetSession} />
          </aside>

          <main className="flex min-h-0 min-w-0 flex-1 flex-col">
            <div className="mb-4 shrink-0">
              <TabBar
                tabs={[
                  { id: 'chat' as const, label: 'Setting chat' },
                  { id: 'generate' as const, label: 'Generate' },
                ]}
                active={tab}
                onChange={setTab}
              />
            </div>

            {/* Both panes stay MOUNTED. Switching tabs must not throw away a
                conversation or a generated NPC -- comparing two settings means
                going back and forth. */}
            <div className={tab === 'chat' ? 'min-h-0 flex-1' : 'hidden'}>
              <ChatPane
                model={model}
                depth={depth}
                sessionId={SESSION_ID}
                onSpend={spend}
              />
            </div>
            <div className={tab === 'generate' ? 'min-h-0 flex-1' : 'hidden'}>
              <GeneratePane model={model} depth={depth} onSpend={spend} />
            </div>
          </main>
        </div>
      </div>
    </TooltipProvider>
  )
}
