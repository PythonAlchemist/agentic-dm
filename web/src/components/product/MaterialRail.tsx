'use client'

import { useRuns } from '@/lib/role'
import { CHROME, SOURCE, SOURCE_GLYPH } from '@/lib/palette'

export type MaterialAction = 'write' | 'draft'

/**
 * Where a DM starts making something, in the rail that already holds Reveal.
 *
 * AUTHORING IS APPARATUS, NOT A MODE. It sits beside the control that decides
 * what the table knows because both are things done ABOUT the text rather than
 * to it, and a DM mid-session finds them in one place.
 *
 * WITHHELD FROM A PLAYER, and not merely for tidiness. This screen is the one
 * where a player is asked to trust that what they are reading is the book's;
 * an edit control in that frame undermines the claim the screen exists to
 * make, even though the endpoint refuses the write anyway.
 */
export function MaterialRail({
  campaign,
  open,
  onOpen,
}: {
  campaign: string
  open: MaterialAction | null
  onOpen: (action: MaterialAction | null) => void
}) {
  const runs = useRuns(campaign)
  if (runs !== true) return null

  const actions: [MaterialAction, string][] = [
    ['write', 'write a scene here'],
    ['draft', 'draft it for me'],
  ]

  return (
    <section className="mt-4 border-t border-line pt-4">
      <h2 className={`label ${SOURCE.yours}`}>
        {SOURCE_GLYPH.yours} your material
      </h2>
      <ul className="mt-2 flex flex-col">
        {actions.map(([action, label]) => (
          <li key={action}>
            <button
              onClick={() => onOpen(open === action ? null : action)}
              aria-pressed={open === action}
              className={`flex w-full items-center gap-2 rounded-md px-1.5 py-1 text-left text-ui ${CHROME.row} ${
                open === action ? CHROME.selected : 'text-ink-dim'
              }`}
            >
              <span className="text-ink-faint">+</span>
              {label}
            </button>
          </li>
        ))}
        {/* PRESENT, AND HONEST ABOUT NOT WORKING YET. A control that is merely
            missing reads as a product that cannot do this; one that is dimmed
            and says why reads as a product that will. It is not a button: there
            is nothing to press, so it does not pretend to be pressable. */}
        <li className="flex items-center gap-2 px-1.5 py-1 text-ui text-ink-faint">
          <span>+</span>
          add someone
          <span className="ml-auto text-label">not yet</span>
        </li>
      </ul>
    </section>
  )
}
