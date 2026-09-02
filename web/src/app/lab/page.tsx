'use client'

import { useCallback, useEffect, useState } from 'react'
import { ChatPane } from '@/components/ChatPane'
import { RunningOrder } from '@/components/RunningOrder'
import { Group, Panel, Separator } from 'react-resizable-panels'

import { Door } from '@/components/Door'
import { SectionReader } from '@/components/SectionReader'
import { Setup } from '@/components/Setup'
import { useDebug } from '@/lib/debug'
import { YourMaterial } from '@/components/YourMaterial'
import { SpendChip, type Running } from '@/components/Meters'
import { TooltipProvider } from '@/components/ui'
import {
  auth,
  labAPI,
  sessionId,
  type CampaignInfo,
  type Cost,
  type Depth,
  type GeneratedReply,
  type LabConfig,
  type Usage,
} from '@/lib/api'


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
  //: Whether the API has refused us. STARTS UNKNOWN (`null`) rather than
  //  false, because the answer takes a round trip and rendering the lab for
  //  that instant flashes a screenful of book text at somebody who may turn
  //  out not to be allowed to see it.
  // THIS BROWSER'S OWN CONVERSATION. Read once, in a state initialiser, so
  // the id is stable across renders and the same one reaches every request.
  const [session] = useState(sessionId)
  const [locked, setLocked] = useState<boolean | null>(null)
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
  //: WHAT THE DM IS LOOKING AT, biasing what the chat retrieves. Held here
  //  rather than in the reader because it must OUTLIVE the drawer: they open a
  //  scene, close it, and go on asking about it. Cleared explicitly, never by
  //  a component unmounting.
  const [focus, setFocus] = useState<{ id: string; label: string } | null>(null)
  const [debug, setDebug] = useDebug()
  const [depth, setDepth] = useState<Depth>(FALLBACK_DEPTH)
  const [running, setRunning] = useState<Running>(ZERO)

  //: Pulled out of the mount effect so the door can call it again on the way
  //  in, rather than the page needing a remount to notice it was opened.
  const open = useCallback(() => {
    labAPI
      .config()
      .then((c) => {
        setLocked(false)
        setConfig(c)
        setModel(c.default_model)
        // The first book the graph holds, rather than a slug written here:
        // this list is counted, and a hardcoded default outlives the book.
        setBook(c.books[0]?.slug ?? '')
        setDepth(c.defaults ?? FALLBACK_DEPTH)
        labAPI.campaigns().then((r) => setCampaigns(r.campaigns)).catch(() => undefined)
      })
      // A 401 IS NOT A FAILURE TO REACH THE API, and showing it as one told a
      // reader with a revoked token that the backend was down. `send` has
      // already flipped `locked` through `onRefused` by the time this runs.
      .catch((e) => {
        const message = e instanceof Error ? e.message : String(e)
        if (!message.includes('401')) setFailed(message)
      })
  }, [])

  useEffect(() => {
    // REGISTERED BEFORE THE FIRST REQUEST, so a 401 from that request is the
    // thing that raises the door -- the app never has to guess whether this
    // deployment is gated, it finds out by asking.
    auth.onRefused(() => setLocked(true))
    auth.load()
    open()
  }, [open])

  const noteChainChanged = useCallback(() => setOrderVersion((v) => v + 1), [])

  const spend = (reply: { usage: Usage; cost: Cost }) =>
    setRunning((r) => accumulate(r, reply.usage, reply.cost))

  const resetSession = async () => {
    setRunning(ZERO)
    await labAPI.reset(session).catch(() => undefined)
  }

  if (locked) {
    return <Door onOpened={open} />
  }

  if (failed) {
    return (
      <div className="p-8">
        <h1 className="mb-2 text-title">Agent Lab</h1>
        <p className="text-ui text-red-400">Could not reach the API: {failed}</p>
        <p className="mt-2 text-ui text-ink-dim">
          Start the backend with{' '}
          <code className="text-ink-dim">
            uv run uvicorn backend.api.main:app --reload
          </code>
          .
        </p>
      </div>
    )
  }

  // `locked === null` is the round trip still in flight, and lands here.
  if (!config) {
    return <div className="p-8 text-ui text-ink-faint">Loading…</div>
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
        <header className="flex shrink-0 items-baseline gap-4 border-b border-line px-6 py-3">
          <h1 className="text-body font-medium">Agent Lab</h1>
          <button
            onClick={() => setSetupOpen(true)}
            className="text-meta text-ink-dim hover:text-ink-dim"
          >
            {here ? here.title : 'no books loaded'}
            <span className="text-ink-faint"> · </span>
            {campaigns.find((c) => c.slug === campaign)?.name ?? 'canon only'}
            <span className="text-ink-faint"> · </span>
            {model}
          </button>
          <div className="ml-auto flex items-baseline gap-4">
            <SpendChip running={running} onReset={resetSession} debug={debug} />
            <button
              onClick={() => setDebug(!debug)}
              className={`text-meta ${debug ? 'text-ink' : 'text-ink-faint hover:text-ink-dim'}`}
              title="Show how answers were produced (⌘.)"
            >
              debug
            </button>
          </div>
        </header>

        {/* THREE PANES, NOT A TAB BAR. A DM does the same three things all
            session -- find something, read it, ask about it -- and tabbing
            between them made two of the three invisible while doing the
            third. Explorer, viewer, chat: what an editor would do, because
            the shape of the work is the same shape.

            RESIZABLE, for the reason the chat/subgraph split already is: two
            hardcoded widths are two guesses about what somebody wants to
            read, and both are wrong. */}
        <Group orientation="horizontal" className="min-h-0 flex-1 p-4">
          <Panel defaultSize="20%" minSize="14%">
            <div className="flex h-full min-h-0 flex-col gap-3 overflow-hidden">
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
            </div>
          </Panel>

          <Separator className="mx-1.5 w-1.5 rounded-md bg-overlay transition-colors hover:bg-ink-faint" />

          <Panel defaultSize="46%" minSize="24%">
            <SectionReader
              sectionId={reading}
              campaign={campaign}
              onClose={() => setReading(null)}
              onEdited={noteChainChanged}
              onJump={setReading}
              onFocus={setFocus}
            />
          </Panel>

          <Separator className="mx-1.5 w-1.5 rounded-md bg-overlay transition-colors hover:bg-ink-faint" />

          <Panel defaultSize="34%" minSize="22%">
            <ChatPane
              key={`${book}:${campaign ?? 'canon'}`}
              book={book}
              campaign={campaign}
              onChainChanged={noteChainChanged}
              focus={focus}
              onClearFocus={() => setFocus(null)}
              raised={raised}
              onRaisedHandled={() => setRaised(null)}
              suggestion={here?.examples.ask ?? ''}
              model={model}
              depth={depth}
              sessionId={session}
              onSpend={spend}
            />
          </Panel>
        </Group>
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

    </TooltipProvider>
  )
}
