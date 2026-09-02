'use client'

import * as RadixSlider from '@radix-ui/react-slider'
import * as RadixTooltip from '@radix-ui/react-tooltip'
import type { ReactNode } from 'react'

/**
 * The lab's primitives. Behaviour from Radix, appearance from here.
 *
 * Deliberately small: this is what the lab actually uses, not a design system.
 * A framework for four controls is more maintenance than the four controls.
 */

export const TooltipProvider = RadixTooltip.Provider

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
    <div>
      <div className="mb-1.5 flex items-baseline justify-between text-ui">
        <span className="text-ink-dim">{label}</span>
        <span className="tabular-nums text-ink-dim">{value}</span>
      </div>
      <RadixSlider.Root
        value={[value]}
        min={min}
        max={max}
        step={1}
        onValueChange={([next]) => onChange(next)}
        className="relative flex h-5 w-full touch-none select-none items-center"
      >
        <RadixSlider.Track className="relative h-1 grow rounded-full bg-overlay">
          <RadixSlider.Range className="absolute h-full rounded-full bg-ink-dim" />
        </RadixSlider.Track>
        <RadixSlider.Thumb
          aria-label={label}
          className="block h-4 w-4 rounded-full bg-chrome shadow transition-shadow focus:focus-visible:ring-2 focus-visible:ring-amber-400"
        />
      </RadixSlider.Root>
      {hint && <p className="mt-2 text-meta leading-relaxed text-ink-dim">{hint}</p>}
    </div>
  )
}

/**
 * A hover explanation for a terse label.
 *
 * Every provenance mark in this lab is short because it sits inline, and short
 * is only honest when the full reason is one hover away.
 */
export function Explain({ children, text }: { children: ReactNode; text: string }) {
  return (
    <RadixTooltip.Root delayDuration={150}>
      <RadixTooltip.Trigger asChild>
        <span className="cursor-help underline decoration-dotted underline-offset-2">
          {children}
        </span>
      </RadixTooltip.Trigger>
      <RadixTooltip.Portal>
        <RadixTooltip.Content
          side="top"
          sideOffset={6}
          collisionPadding={12}
          className="z-50 max-w-xs rounded-md border border-line bg-surface px-3 py-2 text-meta leading-relaxed text-ink-dim "
        >
          {text}
          <RadixTooltip.Arrow className="fill-neutral-700" />
        </RadixTooltip.Content>
      </RadixTooltip.Portal>
    </RadixTooltip.Root>
  )
}

export function Card({
  title,
  right,
  children,
  className = '',
}: {
  title?: string
  right?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <div className={`rounded-md border border-line bg-surface/40 ${className}`}>
      {title && (
        <div className="flex items-baseline justify-between border-b border-line px-3 py-2">
          <span className="text-label font-medium uppercase tracking-wider text-ink-dim">
            {title}
          </span>
          {right}
        </div>
      )}
      {children}
    </div>
  )
}

/**
 * Tabs that keep every pane MOUNTED.
 *
 * Radix `Tabs` unmounts the inactive one, which would throw away a
 * conversation every time you switched -- and comparing two settings means
 * switching back and forth.
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
    <div className="inline-flex gap-1 rounded-md border border-line bg-surface/60 p-1" role="tablist">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          role="tab"
          aria-selected={tab.id === active}
          onClick={() => onChange(tab.id)}
          className={`rounded-md px-3 py-1 text-ui transition-colors ${
            tab.id === active
              ? 'bg-overlay text-ink'
              : 'text-ink-dim hover:bg-overlay/60 hover:text-ink'
          }`}
        >
          {tab.label}
        </button>
      ))}
    </div>
  )
}


/**
 * The strip at the top of a pane: what it is, and what you can do to it.
 *
 * The explorer's cards have carried one of these all along; the viewer and the
 * chat did not, so two thirds of the screen read as loose regions beside a
 * sidebar rather than as panes of one thing. Same type, same height, same
 * casing — the sameness is the point.
 */
export function PaneHeader({
  title,
  subtitle,
  children,
}: {
  title: string
  subtitle?: string
  children?: ReactNode
}) {
  return (
    <div className="flex shrink-0 items-baseline gap-3 border-b border-line px-3 py-2">
      <span className="text-label font-medium uppercase tracking-wider text-ink-dim">
        {title}
      </span>
      {subtitle && (
        <span className="min-w-0 truncate text-meta text-ink-dim">{subtitle}</span>
      )}
      <span className="ml-auto flex shrink-0 items-baseline gap-3 text-meta">
        {children}
      </span>
    </div>
  )
}
