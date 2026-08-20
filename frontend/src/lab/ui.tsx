import * as RadixSlider from '@radix-ui/react-slider'
import * as RadixTooltip from '@radix-ui/react-tooltip'
import type { ReactNode } from 'react'

/**
 * The lab's shared controls.
 *
 * Behaviour comes from Radix, appearance from here, and the point of the split
 * is that neither is hand-rolled twice. The sliders were bare `input[range]`
 * elements styled per-instance -- which is why they looked approximate and why
 * a keyboard could not drive them properly.
 *
 * Deliberately small. This is the handful of primitives the lab actually uses,
 * not a component library: a design system for four controls is more
 * maintenance than the four controls.
 */

/** One labelled value, dragged or typed. Radix gives it keyboard and focus. */
export function Slider({
  label,
  hint,
  value,
  min,
  max,
  onChange,
}: {
  label: string
  hint?: string
  value: number
  min: number
  max: number
  onChange: (value: number) => void
}) {
  return (
    <div className="mb-4">
      <div className="flex justify-between items-baseline text-sm mb-1">
        <span>{label}</span>
        <span className="tabular-nums text-neutral-400">{value}</span>
      </div>
      <RadixSlider.Root
        value={[value]}
        min={min}
        max={max}
        step={1}
        onValueChange={([next]) => onChange(next)}
        className="relative flex items-center select-none touch-none h-5 w-full"
      >
        <RadixSlider.Track className="relative h-1 grow rounded-full bg-neutral-700">
          <RadixSlider.Range className="absolute h-full rounded-full bg-amber-600" />
        </RadixSlider.Track>
        <RadixSlider.Thumb
          aria-label={label}
          className="block h-4 w-4 rounded-full bg-amber-500 shadow focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
        />
      </RadixSlider.Root>
      {hint && <p className="text-xs text-neutral-500 mt-1">{hint}</p>}
    </div>
  )
}

/**
 * A hover explanation.
 *
 * Used for the provenance marks -- `keyword match`, `carried from the
 * conversation`, an unverified rate. Those labels are terse because they sit
 * inline, and terse is only honest if the full reason is one hover away.
 */
export function Explain({
  children,
  text,
}: {
  children: ReactNode
  text: string
}) {
  return (
    <RadixTooltip.Root delayDuration={200}>
      <RadixTooltip.Trigger asChild>
        <span className="cursor-help underline decoration-dotted underline-offset-2">
          {children}
        </span>
      </RadixTooltip.Trigger>
      <RadixTooltip.Portal>
        <RadixTooltip.Content
          side="top"
          sideOffset={6}
          className="max-w-xs rounded border border-neutral-700 bg-neutral-900 px-2 py-1.5 text-xs text-neutral-300 shadow-lg"
        >
          {text}
          <RadixTooltip.Arrow className="fill-neutral-700" />
        </RadixTooltip.Content>
      </RadixTooltip.Portal>
    </RadixTooltip.Root>
  )
}

/** One provider at the root, so every `Explain` shares a delay and a portal. */
export const TooltipProvider = RadixTooltip.Provider

/** Tabs that keep every pane MOUNTED.
 *
 * Radix's own `Tabs` unmounts the inactive one, which would throw away a
 * conversation or a generated NPC every time you switched -- and comparing two
 * settings means switching back and forth. So this is a button row plus
 * `hidden`, which is what the lab already did, with the styling in one place.
 */
export function TabBar<T extends string>({
  tabs,
  active,
  onChange,
}: {
  tabs: { id: T; label: string }[]
  active: T
  onChange: (id: T) => void
}) {
  return (
    <div className="flex gap-2" role="tablist">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          role="tab"
          aria-selected={tab.id === active}
          onClick={() => onChange(tab.id)}
          className={`px-4 py-1.5 rounded text-sm border transition-colors ${
            tab.id === active
              ? 'border-amber-500 bg-amber-500/10 text-neutral-100'
              : 'border-neutral-700 text-neutral-400 hover:border-neutral-600 hover:text-neutral-200'
          }`}
        >
          {tab.label}
        </button>
      ))}
    </div>
  )
}
