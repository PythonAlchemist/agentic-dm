// @vitest-environment jsdom
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { DraftCard } from '@/components/product/DraftCard'
import { StoredBlock } from '@/components/product/StoredBlock'
import type { GeneratedReply } from '@/lib/api'

describe('StoredBlock', () => {
  it('carries the yours grammar in all three channels', () => {
    const { container } = render(<StoredBlock title="A quiet scene" body="She goes quiet." />)
    expect(screen.getByText(/✎ YOURS/)).toBeDefined()
    expect(container.querySelector('.border-yours')).not.toBeNull()
    expect(container.querySelector('.border-dashed')).toBeNull()
  })
})

describe('the draft/stored contrast', () => {
  // THE PRODUCT'S CENTRAL TRANSITION, asserted directly: a draft is dashed and
  // marked invented until it is stored, and a stored block is solid and marked
  // yours. On the hand-written path (WriteBlock) there is no contrast to lose --
  // it is already solid yours -- so this is the first test that can catch the
  // two grammars being swapped.
  const reply: GeneratedReply = {
    kind: 'scene',
    subject: 'A quiet room',
    title: 'A quiet scene',
    body: 'She goes quiet.',
    from_canon: [],
    invented: [],
    sources: [],
    usage: { input: 0, output: 0, total: 0 },
    cost: { usd: null, model: 'gpt-4o-mini', last_verified: null, verified: false, unpriced: false },
    retrieval: null,
    error: '',
    raw: '',
    model: 'gpt-4o-mini',
  }

  it('renders a draft dashed and invented, and a stored block solid and yours', () => {
    const { container: draftContainer } = render(
      <DraftCard
        campaign="cos"
        reply={reply}
        anchor="cos:section-1"
        onStored={() => {}}
        onDiscard={() => {}}
      />,
    )
    expect(draftContainer.querySelector('.border-dashed')).not.toBeNull()
    expect(screen.getByText(/◇ INVENTED/)).toBeDefined()

    const { container: storedContainer } = render(
      <StoredBlock title="A quiet scene" body="She goes quiet." />,
    )
    expect(storedContainer.querySelector('.border-dashed')).toBeNull()
    expect(screen.getByText(/✎ YOURS/)).toBeDefined()
  })
})
