'use client'

import type { BookInfo, CampaignInfo, Depth, ModelInfo } from '@/lib/api'
import { Card, Slider } from './ui'

/**
 * Model and context depth: the two things this lab exists to vary.
 *
 * Every hint here is a measured claim rather than a description, and they are
 * carried over verbatim. "A sentence is cheap and often too narrow" is a fact
 * somebody established -- the tavern's owners really are named 3,300
 * characters after its first mention -- and losing it would leave a knob with
 * no reason attached.
 */
export function Controls({
  campaigns,
  campaign,
  onCampaign,
  books,
  book,
  onBook,
  models,
  model,
  onModel,
  depth,
  onDepth,
  debug,
}: {
  campaigns: CampaignInfo[]
  campaign: string | null
  onCampaign: (c: string | null) => void
  books: BookInfo[]
  book: string
  onBook: (b: string) => void
  models: ModelInfo[]
  model: string
  onModel: (m: string) => void
  depth: Depth
  onDepth: (d: Depth) => void
  /** Depth knobs exist "to vary" -- bench posture. At the table they should
   *  sit at the defaults the harness measured, so they render only here. */
  debug: boolean
}) {
  const chosen = models.find((m) => m.id === model)

  return (
    <div className="space-y-4">
      {/* FIRST, above the model: which world the answers come from matters
          more than which model writes them. Every book here is one the graph
          actually holds -- the list is counted, not written down. */}
      <Card title="Book">
        <div className="space-y-1 p-2">
          {books.map((b) => (
            <button
              key={b.slug}
              onClick={() => onBook(b.slug)}
              className={`block w-full rounded-md border px-3 py-2 text-left transition-colors ${
                b.slug === book
                  ? 'border-amber-600/60 bg-amber-500/10'
                  : 'border-transparent hover:bg-neutral-800/50'
              }`}
            >
              <span className="text-sm font-medium text-neutral-200">{b.title}</span>
              <span className="mt-0.5 block text-xs tabular-nums text-neutral-600">
                {b.chapters} chapters loaded
              </span>
            </button>
          ))}
        </div>
        {/* Said plainly, because the transcript vanishing is otherwise
            indistinguishable from a bug. */}
        <p className="border-t border-neutral-800 px-3 py-2 text-xs leading-relaxed text-neutral-500">
          Switching campaigns starts a new conversation. A session reads one
          book, so what the agent is holding onto has to go with it.
        </p>
      </Card>

      {/* SEPARATE FROM THE BOOK, because they answer different questions: the
          book is which world, the table is whose. Canon only is the DEFAULT
          and is what every measurement this project reports is taken with. */}
      <Card title="Table — your campaign">
        <div className="space-y-1 p-2">
          <button
            onClick={() => onCampaign(null)}
            className={`block w-full rounded-md border px-3 py-2 text-left transition-colors ${
              campaign === null
                ? 'border-amber-600/60 bg-amber-500/10'
                : 'border-transparent hover:bg-neutral-800/50'
            }`}
          >
            <span className="text-sm font-medium text-neutral-200">Canon only</span>
            <span className="mt-0.5 block text-xs leading-relaxed text-neutral-500">
              The published book, with nothing of yours in it.
            </span>
          </button>
          {campaigns.map((c) => (
            <button
              key={c.slug}
              onClick={() => onCampaign(c.slug)}
              className={`block w-full rounded-md border px-3 py-2 text-left transition-colors ${
                c.slug === campaign
                  ? 'border-amber-600/60 bg-amber-500/10'
                  : 'border-transparent hover:bg-neutral-800/50'
              }`}
            >
              <span className="text-sm font-medium text-neutral-200">{c.name}</span>
              <span className="mt-0.5 block text-xs tabular-nums text-neutral-600">
                {c.sections} sections in your running order
              </span>
            </button>
          ))}
        </div>
        <p className="border-t border-neutral-800 px-3 py-2 text-xs leading-relaxed text-neutral-500">
          Your own material rides alongside canon and is always labelled as
          yours. Switching tables starts a new conversation.
        </p>
      </Card>

      <Card title="Model">
        <div className="space-y-1 p-2">
          {models.map((m) => (
            <button
              key={m.id}
              onClick={() => onModel(m.id)}
              className={`block w-full rounded-md border px-3 py-2 text-left transition-colors ${
                m.id === model
                  ? 'border-amber-600/60 bg-amber-500/10'
                  : 'border-transparent hover:bg-neutral-800/50'
              }`}
            >
              <span className="text-sm font-medium text-neutral-200">{m.label}</span>
              <span className="mt-0.5 block text-xs leading-relaxed text-neutral-500">
                {m.note}
              </span>
              <span className="mt-1 block text-xs tabular-nums text-neutral-600">
                {m.input_per_1m === null || m.output_per_1m === null
                  ? 'no rate on file'
                  : `$${m.input_per_1m} in / $${m.output_per_1m} out per 1M`}
              </span>
            </button>
          ))}
        </div>

        {/* An unverified rate is SHOWN, not hidden: it is still what is about
            to be spent. What must never happen is showing it as though it had
            been checked. */}
        {chosen && !chosen.last_verified && (
          <p className="border-t border-neutral-800 px-3 py-2 text-xs leading-relaxed text-amber-500/90">
            This rate has never been verified by a human. Costs are arithmetic
            on an unchecked number — correct{' '}
            <code className="text-amber-300">backend/core/pricing.yaml</code> and
            set <code className="text-amber-300">last_verified</code>.
          </p>
        )}
      </Card>

      {debug && <Card title="Context depth">
        <div className="space-y-4 p-3">
          <Slider
            label="Canon passages"
            hint="Sections of the book put in front of the model."
            value={depth.passages}
            min={0}
            max={20}
            onChange={(passages) => onDepth({ ...depth, passages })}
          />
          <Slider
            label="Relationships"
            hint="Graph edges listed per answer."
            value={depth.max_edges}
            min={0}
            max={50}
            onChange={(max_edges) => onDepth({ ...depth, max_edges })}
          />

          <div>
            <div className="mb-1.5 text-sm text-neutral-300">Passage width</div>
            <div className="inline-flex gap-1 rounded-md border border-neutral-800 p-1">
              {(['section', 'sentence'] as const).map((w) => (
                <button
                  key={w}
                  onClick={() => onDepth({ ...depth, passage_width: w })}
                  className={`rounded px-3 py-1 text-xs transition-colors ${
                    depth.passage_width === w
                      ? 'bg-amber-500/15 text-amber-200'
                      : 'text-neutral-400 hover:bg-neutral-800/60'
                  }`}
                >
                  {w}
                </button>
              ))}
            </div>
            <p className="mt-1.5 text-xs leading-relaxed text-neutral-500">
              A sentence is cheap and often too narrow: the tavern&apos;s owners
              are named 3,300 characters after its first mention, in the same
              section.
            </p>
          </div>

          <label className="flex cursor-pointer items-start gap-2">
            <input
              type="checkbox"
              className="mt-1 accent-amber-500"
              checked={depth.include_proposed}
              onChange={(e) => onDepth({ ...depth, include_proposed: e.target.checked })}
            />
            <span className="text-sm text-neutral-300">
              Include unverified relationships
              <span className="mt-0.5 block text-xs leading-relaxed text-neutral-500">
                Extractor guesses, wrong about a third of the time. Turn off and
                re-ask to see whether a bad answer came from the model or from a
                false edge fed to it.
              </span>
            </span>
          </label>
        </div>
      </Card>}
    </div>
  )
}
