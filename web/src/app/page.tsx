'use client'

import { useCallback, useEffect, useState } from 'react'
import { ChatPane } from '@/components/ChatPane'
import { RunningOrder } from '@/components/RunningOrder'
import { SectionReader } from '@/components/SectionReader'
import { Setup } from '@/components/Setup'
import { useDebug } from '@/lib/debug'
import { YourMaterial } from '@/components/YourMaterial'
import { GeneratePane } from '@/components/GeneratePane'
import { SpendChip, type Running } from '@/components/Meters'
import { TabBar, TooltipProvider } from '@/components/ui'
import {
  labAPI,
  type CampaignInfo,
  type Cost,
  type Depth,
  type GeneratedReply,
  type LabConfig,
  type Usage,
} from '@/lib/api'

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
  const [book, setBook] = useState('')
  const [campaign, setCampaign] = useState<string | null>(null)
  const [campaigns, setCampaigns] = useState<CampaignInfo[]>([])
  //: Bumped whenever something changes the chain, so the panel re-reads it.
  //  The order is derived from the graph, never mirrored in React state: two
  //  copies of a running order are two running orders.
  const [orderVersion, setOrderVersion] = useState(0)
  //: A draft raised from the material panel rather than from a conversation.
  //  It lands in the chat pane as a card, so there is ONE review surface
  //  however a draft was raised.
  const [raised, setRaised] = useState<GeneratedReply | null>(null)
  //: Which section a DM is reading. A drawer rather than a route: reading is a
  //  glance mid-conversation, and the chat it interrupts stays behind it.
  const [reading, setReading] = useState<string | null>(null)
  //: Setup is a once-per-session act. It held 1,512px at the top of a 288px
  //  rail -- taller than the viewport -- so the two panels a DM actually works
  //  in could never be on screen at the same time as the pickers above them.
  //  Switching book or table RESETS the conversation anyway, so there is no
  //  mid-session cost to putting them one click away.
  const [setupOpen, setSetupOpen] = useState(false)
  const [debug, setDebug] = useDebug()
  const [depth, setDepth] = useState<Depth>(FALLBACK_DEPTH)
  const [tab, setTab] = useState<'chat' | 'generate'>('chat')
  const [running, setRunning] = useState<Running>(ZERO)

  useEffect(() => {
    labAPI
      .config()
      .then((c) => {
        setConfig(c)
        setModel(c.default_model)
        // The first book the graph holds, rather than a slug written here:
        // this list is counted, and a hardcoded default outlives the book.
        setBook(c.books[0]?.slug ?? '')
        setDepth(c.defaults ?? FALLBACK_DEPTH)
      })
      .catch((e) => setFailed(e instanceof Error ? e.message : String(e)))
  }, [])

  useEffect(() => {
    labAPI.campaigns().then((c) => setCampaigns(c.campaigns)).catch(() => undefined)
  }, [])

  const noteChainChanged = useCallback(() => setOrderVersion((v) => v + 1), [])

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

  const here = config.books.find((b) => b.slug === book)

  return (
    <TooltipProvider>
      <div className="flex h-full flex-col">
        {/* IDENTITY, SPEND, AND THE FLIP -- the three things that are true of
            the whole screen rather than of any panel on it. The book and table
            phrase replaces two rail cards: it has to stay VISIBLE (the lab once
            said "Curse of Strahd" while answering out of a heist anthology) but
            it does not have to stay EDITABLE. */}
        <header className="flex shrink-0 items-baseline gap-4 border-b border-neutral-800 px-6 py-3">
          <h1 className="text-base font-medium">Agent Lab</h1>
          <button
            onClick={() => setSetupOpen(true)}
            className="text-xs text-neutral-500 hover:text-neutral-300"
          >
            {here ? here.title : 'no books loaded'}
            <span className="text-neutral-700"> · </span>
            {campaigns.find((c) => c.slug === campaign)?.name ?? 'canon only'}
            <span className="text-neutral-700"> · </span>
            {model}
          </button>
          <div className="ml-auto flex items-baseline gap-4">
            <SpendChip running={running} onReset={resetSession} debug={debug} />
            <button
              onClick={() => setDebug(!debug)}
              className={`text-xs ${debug ? 'text-neutral-100' : 'text-neutral-700 hover:text-neutral-500'}`}
              title="Show how answers were produced (⌘.)"
            >
              debug
            </button>
          </div>
        </header>

        <div className="flex min-h-0 flex-1 gap-6 p-6">
          {/* WHAT A DM WORKS IN, and nothing else. Running order first: it is
              where they are in the session. */}
          <aside className="flex w-72 shrink-0 flex-col gap-4 overflow-hidden">
            <RunningOrder
              campaign={campaign}
              refreshKey={orderVersion}
              onRead={setReading}
            />
            <YourMaterial
              campaign={campaign}
              refreshKey={orderVersion}
              onDraft={setRaised}
              onRead={setReading}
            />
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
                key={`${book}:${campaign ?? 'canon'}`}
                book={book}
                campaign={campaign}
                onChainChanged={noteChainChanged}
                raised={raised}
                onRaisedHandled={() => setRaised(null)}
                suggestion={here?.examples.ask ?? ''}
                model={model}
                depth={depth}
                sessionId={SESSION_ID}
                onSpend={spend}
              />
            </div>
            <div className={tab === 'generate' ? 'min-h-0 flex-1' : 'hidden'}>
              <GeneratePane
                key={`${book}:${campaign ?? 'canon'}`}
                book={book}
                campaign={campaign}
                onChainChanged={noteChainChanged}
                examples={here?.examples ?? {}}
                model={model}
                depth={depth}
                onSpend={spend}
              />
            </div>
          </main>
        </div>
      </div>

      <Setup
        open={setupOpen}
        onClose={() => setSetupOpen(false)}
        campaigns={campaigns}
        campaign={campaign}
        onCampaign={setCampaign}
        books={config.books}
        book={book}
        onBook={setBook}
        models={config.models}
        model={model}
        onModel={setModel}
        depth={depth}
        onDepth={setDepth}
        debug={debug}
      />

      <SectionReader
        sectionId={reading}
        campaign={campaign}
        onClose={() => setReading(null)}
        onEdited={noteChainChanged}
        onJump={setReading}
      />
    </TooltipProvider>
  )
}
