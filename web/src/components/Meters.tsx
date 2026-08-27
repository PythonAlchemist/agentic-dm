'use client'

import type { Cost, RetrievalReport, Usage } from '@/lib/api'
import { Explain } from './ui'

/**
 * What a call cost and what retrieval did.
 *
 * Every label here is terse and every one has its reason on hover. That pairing
 * is the point: a DM acting on an answer needs to know at a glance whether a
 * passage was found by a resolved name or by a keyword score, and needs the
 * long version available without leaving the page.
 */

export function CallMeter({ usage, cost }: { usage: Usage; cost: Cost }) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 text-xs text-neutral-500">
      <span className="tabular-nums">
        {usage.input.toLocaleString()} in / {usage.output.toLocaleString()} out
      </span>
      <span className="tabular-nums">{money(cost)}</span>
      {age(cost) && (
        <Explain text="Every rate is a claim about the outside world this repository cannot check. An unverified one is arithmetic on a number nobody has confirmed — correct it in backend/core/pricing.yaml and set last_verified.">
          <span className={cost.verified ? '' : 'text-neutral-400'}>{age(cost)}</span>
        </Explain>
      )}
    </div>
  )
}

/**
 * The one line of a retrieval report that is TRUST rather than mechanism.
 *
 * An answer that retrieved nothing is not a diagnostic detail -- it is the
 * difference between a grounded answer and a model talking from memory, which
 * is the thing this product exists to keep visible. So it survives the debug
 * flip while the anchors, terms and counts around it do not.
 */
export function MissReason({ report }: { report: RetrievalReport | null }) {
  if (!report?.miss_reason) return null
  return (
    <p className="mt-2 text-xs text-neutral-400">{report.miss_reason}</p>
  )
}


export function RetrievalPanel({ report }: { report: RetrievalReport | null }) {
  if (!report) return null

  const byText = report.path === 'text'
  const byName = report.passages_by_path?.graph ?? 0
  const byKeyword = report.passages_by_path?.text ?? 0

  return (
    <div className="mt-2 rounded-md border border-neutral-800 bg-neutral-900/40 p-3 text-xs">
      <div className="mb-2 flex items-baseline justify-between">
        <span className="text-[11px] font-medium uppercase tracking-wider text-neutral-500">
          Retrieval
        </span>
        <Explain
          text={
            byText
              ? 'Nothing in the question resolved to a canon entity, so the sections were chosen by a full-text score. They share words with the question and may be about something else.'
              : report.path
                ? 'A name in the question resolved through the alias graph, so these sections are ones the book itself links to that entity.'
                : 'Retrieval returned nothing at all.'
          }
        >
          <span className={byText ? 'text-neutral-400' : report.path ? 'text-neutral-200' : 'text-neutral-500'}>
            {byText ? 'keyword match' : report.path ? 'by name' : 'nothing'}
          </span>
        </Explain>
      </div>

      {report.anchors.length > 0 && (
        <p className="text-neutral-300">{report.anchors.join(', ')}</p>
      )}
      {byText && report.terms.length > 0 && (
        <p className="text-neutral-500">searched: {report.terms.join(', ')}</p>
      )}
      {report.loose && (
        <p className="text-neutral-500">
          <Explain text="Nothing matched under the scan's own casing rule, so a case-folded pass was used. Weaker evidence than an exact match, which is why it is shown at all.">
            matched with relaxed capitalisation
          </Explain>
        </p>
      )}
      {report.carried && (
        <p className="text-neutral-500">
          <Explain text="This question resolved no name of its own, so it was anchored on what the conversation was already about. A question that names something is never overridden this way.">
            carried from the conversation
          </Explain>
        </p>
      )}

      <p className="mt-1 text-neutral-500">
        {report.passages} passage{report.passages === 1 ? '' : 's'}
        {byName > 0 && byKeyword > 0 && ` (${byName} by name, ${byKeyword} by keyword)`}
        {report.dropped > 0 && `, ${report.dropped} cut by the budget`}
      </p>
      <p className="text-neutral-500">
        <Explain text="Derived relationships come from the book's own structure and are reliable. Guessed ones come from an extractor and roughly a third are wrong — treat each as a lead to check, never as fact.">
          {report.accepted_edges} derived · {report.proposed_edges} guessed
        </Explain>
        {report.proposed_withheld && ' (withheld)'}
      </p>
      {report.miss_reason && (
        <p className="mt-1 text-neutral-400">{report.miss_reason}</p>
      )}
    </div>
  )
}

function money(cost: Cost): string {
  if (cost.unpriced || cost.usd === null) return 'no rate on file'
  return `$${cost.usd.toFixed(5)} est.`
}

function age(cost: Cost): string {
  if (cost.unpriced) return ''
  return cost.last_verified ? `rate of ${cost.last_verified}` : 'rate unverified'
}

export interface Running {
  calls: number
  input: number
  output: number
  usd: number
  /** True once any counted call used a rate nobody has confirmed. */
  unverified: boolean
}

/** The session total: the number that answers "what did this afternoon cost". */
export function SessionMeter({
  running,
  onReset,
}: {
  running: Running
  onReset: () => void
}) {
  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900/40">
      <div className="flex items-baseline justify-between border-b border-neutral-800 px-3 py-2">
        <span className="text-[11px] font-medium uppercase tracking-wider text-neutral-500">
          This session
        </span>
        <button
          onClick={onReset}
          className="text-xs text-neutral-600 underline hover:text-neutral-400"
        >
          reset
        </button>
      </div>
      <dl className="grid grid-cols-2 gap-y-1 p-3 text-sm tabular-nums">
        <dt className="text-neutral-500">calls</dt>
        <dd className="text-right text-neutral-300">{running.calls}</dd>
        <dt className="text-neutral-500">input</dt>
        <dd className="text-right text-neutral-300">{running.input.toLocaleString()}</dd>
        <dt className="text-neutral-500">output</dt>
        <dd className="text-right text-neutral-300">{running.output.toLocaleString()}</dd>
        <dt className="text-neutral-500">estimated</dt>
        <dd className="text-right text-neutral-300">${running.usd.toFixed(4)}</dd>
      </dl>
      {/* A total built partly from unchecked rates has to say so, or the
          number reads as though somebody confirmed it. */}
      {running.unverified && running.calls > 0 && (
        <p className="border-t border-neutral-800 px-3 py-2 text-xs text-neutral-400">
          Includes rates nobody has verified.
        </p>
      )}
    </div>
  )
}


/**
 * The session total, as one header chip.
 *
 * WAS A RAIL CARD, and cost a rail card's worth of a 288px column to answer a
 * question asked once an afternoon. The number a DM glances at is the dollar;
 * the breakdown behind it is bench data, so it goes where bench data goes.
 *
 * THE UNVERIFIED MARK STAYS ON THE CHIP AND NOT BEHIND THE FLIP. A number
 * nobody has checked is not a diagnostic detail -- it is the difference
 * between a figure and a guess, and money is exactly where that has to show.
 */
export function SpendChip({
  running,
  onReset,
  debug,
}: {
  running: Running
  onReset: () => void
  debug: boolean
}) {
  return (
    <span className="flex items-baseline gap-2 text-xs tabular-nums text-neutral-500">
      <span>
        ${running.usd.toFixed(4)}
        {running.unverified && (
          <Explain text="Some of this used a rate nobody has verified. Correct backend/core/pricing.yaml and set last_verified.">
            <span className="ml-1 text-neutral-400">⚠</span>
          </Explain>
        )}
      </span>
      {debug && (
        <span className="text-neutral-600">
          {running.calls} calls · {running.input.toLocaleString()} in ·{' '}
          {running.output.toLocaleString()} out
        </span>
      )}
      {running.calls > 0 && (
        <button
          onClick={onReset}
          className="text-neutral-700 underline hover:text-neutral-400"
        >
          reset
        </button>
      )}
    </span>
  )
}
