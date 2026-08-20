import type { Cost, RetrievalReport, Usage } from './api'

export interface Running {
  calls: number
  input: number
  output: number
  usd: number
  /** True once any call used a rate nobody has confirmed. Sticky on purpose:
   *  a running total mixing checked and unchecked rates is unchecked. */
  unverified: boolean
}

export const ZERO: Running = {
  calls: 0,
  input: 0,
  output: 0,
  usd: 0,
  unverified: false,
}

export function accumulate(running: Running, usage: Usage, cost: Cost): Running {
  return {
    calls: running.calls + 1,
    input: running.input + usage.input,
    output: running.output + usage.output,
    usd: running.usd + (cost.usd ?? 0),
    unverified: running.unverified || !cost.verified,
  }
}

/** What one call cost, beside the answer it paid for. */
export function CallMeter({ usage, cost }: { usage: Usage; cost: Cost }) {
  return (
    <div className="text-xs text-neutral-400 flex flex-wrap gap-x-4 gap-y-1">
      <span className="tabular-nums">
        {usage.input.toLocaleString()} in / {usage.output.toLocaleString()} out
      </span>
      <span className="tabular-nums">{money(cost)}</span>
      <span>{age(cost)}</span>
    </div>
  )
}

/** The session total. The number that answers "what did this afternoon cost". */
export function SessionMeter({ running, onReset }: { running: Running; onReset: () => void }) {
  return (
    <div className="rounded border border-neutral-700 p-3 text-sm">
      <div className="flex justify-between items-baseline mb-2">
        <h3 className="text-xs uppercase tracking-wide text-neutral-400">This session</h3>
        <button
          onClick={onReset}
          className="text-xs text-neutral-500 hover:text-neutral-300 underline"
        >
          reset
        </button>
      </div>
      <dl className="grid grid-cols-2 gap-y-1 tabular-nums">
        <dt className="text-neutral-400">calls</dt>
        <dd className="text-right">{running.calls}</dd>
        <dt className="text-neutral-400">input</dt>
        <dd className="text-right">{running.input.toLocaleString()}</dd>
        <dt className="text-neutral-400">output</dt>
        <dd className="text-right">{running.output.toLocaleString()}</dd>
        <dt className="text-neutral-400">estimated</dt>
        <dd className="text-right">${running.usd.toFixed(4)}</dd>
      </dl>
      {running.unverified && running.calls > 0 && (
        <p className="mt-2 text-xs text-amber-400/90">
          Includes rates nobody has verified.
        </p>
      )}
    </div>
  )
}

/** What retrieval did. Shown so a thin answer can be traced to thin context. */
export function RetrievalPanel({ report }: { report: RetrievalReport | null }) {
  if (!report) return null
  const byText = report.path === 'text'
  // Per PASSAGE, not per question. A question that resolved a name still gets
  // text passages -- `TEXT_SLOTS` reserves room for them -- and this panel used
  // to label the whole result "by name" over passages Lucene had found.
  const byName = report.passages_by_path?.graph ?? 0
  const byKeyword = report.passages_by_path?.text ?? 0
  return (
    <div className="rounded border border-neutral-700 p-3 text-xs space-y-1">
      <div className="flex justify-between">
        <span className="uppercase tracking-wide text-neutral-400">Retrieval</span>
        <span
          className={
            byText ? 'text-amber-400' : report.path ? 'text-emerald-400' : 'text-neutral-500'
          }
        >
          {byText ? 'keyword match' : report.path ? 'by name' : 'nothing'}
        </span>
      </div>

      {report.anchors.length > 0 && (
        <p className="text-neutral-300">{report.anchors.join(', ')}</p>
      )}
      {byText && report.terms.length > 0 && (
        <p className="text-neutral-400">searched: {report.terms.join(', ')}</p>
      )}
      {report.loose && (
        <p className="text-neutral-500">matched with relaxed capitalisation</p>
      )}
      {report.carried && (
        <p className="text-neutral-500">carried from the conversation</p>
      )}

      <p className="text-neutral-400">
        {report.passages} passage{report.passages === 1 ? '' : 's'}
        {byName > 0 && byKeyword > 0 && ` (${byName} by name, ${byKeyword} by keyword)`}
        {report.dropped > 0 && `, ${report.dropped} cut by the budget`}
      </p>
      <p className="text-neutral-400">
        {report.accepted_edges} derived · {report.proposed_edges} guessed
        {report.proposed_withheld && ' (withheld)'}
      </p>
      {report.miss_reason && <p className="text-amber-400/80">{report.miss_reason}</p>}
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
