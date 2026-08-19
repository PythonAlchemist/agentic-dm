import type { Depth, ModelInfo } from './api'

/**
 * Model and context depth. The two things this lab exists to vary.
 */
export function Controls({
  models,
  model,
  onModel,
  depth,
  onDepth,
}: {
  models: ModelInfo[]
  model: string
  onModel: (m: string) => void
  depth: Depth
  onDepth: (d: Depth) => void
}) {
  const chosen = models.find((m) => m.id === model)

  return (
    <div className="space-y-5">
      <section>
        <h3 className="text-xs uppercase tracking-wide text-neutral-400 mb-2">Model</h3>
        <div className="space-y-1">
          {models.map((m) => (
            <label
              key={m.id}
              className={`block rounded px-3 py-2 cursor-pointer border text-sm ${
                m.id === model
                  ? 'border-amber-500 bg-amber-500/10'
                  : 'border-neutral-700 hover:border-neutral-600'
              }`}
            >
              <input
                type="radio"
                name="model"
                className="sr-only"
                checked={m.id === model}
                onChange={() => onModel(m.id)}
              />
              <span className="font-medium">{m.label}</span>
              <span className="block text-xs text-neutral-400">{m.note}</span>
              <span className="block text-xs text-neutral-500 mt-1">
                {m.input_per_1m === null || m.output_per_1m === null
                  ? 'no rate on file'
                  : `$${m.input_per_1m} in / $${m.output_per_1m} out per 1M`}
              </span>
            </label>
          ))}
        </div>
        {/* An unverified rate is shown, not hidden: it is still what is about to
            be spent. What must never happen is showing it as though checked. */}
        {chosen && !chosen.last_verified && (
          <p className="mt-2 text-xs text-amber-400/90">
            ⚠ This rate has never been verified by a human. Costs below are
            arithmetic on an unchecked number — correct{' '}
            <code className="text-amber-300">backend/core/pricing.yaml</code> and
            set <code className="text-amber-300">last_verified</code>.
          </p>
        )}
      </section>

      <section>
        <h3 className="text-xs uppercase tracking-wide text-neutral-400 mb-2">
          Context depth
        </h3>

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

        <div className="mt-3">
          <div className="text-sm mb-1">Passage width</div>
          <div className="flex gap-2">
            {(['section', 'sentence'] as const).map((w) => (
              <button
                key={w}
                onClick={() => onDepth({ ...depth, passage_width: w })}
                className={`px-3 py-1 rounded text-xs border ${
                  depth.passage_width === w
                    ? 'border-amber-500 bg-amber-500/10'
                    : 'border-neutral-700 hover:border-neutral-600'
                }`}
              >
                {w}
              </button>
            ))}
          </div>
          <p className="text-xs text-neutral-500 mt-1">
            A sentence is cheap and often too narrow: the tavern's owners are
            named 3,300 characters after its first mention, in the same section.
          </p>
        </div>

        <label className="flex items-start gap-2 mt-3 text-sm cursor-pointer">
          <input
            type="checkbox"
            className="mt-1"
            checked={depth.include_proposed}
            onChange={(e) => onDepth({ ...depth, include_proposed: e.target.checked })}
          />
          <span>
            Include unverified relationships
            <span className="block text-xs text-neutral-400">
              Extractor guesses, wrong about a third of the time. Turn off and
              re-ask to see whether a bad answer came from the model or from a
              false edge fed to it.
            </span>
          </span>
        </label>
      </section>
    </div>
  )
}

function Slider({
  label,
  hint,
  value,
  min,
  max,
  onChange,
}: {
  label: string
  hint: string
  value: number
  min: number
  max: number
  onChange: (v: number) => void
}) {
  return (
    <div className="mb-3">
      <div className="flex justify-between text-sm">
        <span>{label}</span>
        <span className="tabular-nums text-neutral-300">{value}</span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full accent-amber-500"
      />
      <p className="text-xs text-neutral-500">{hint}</p>
    </div>
  )
}
