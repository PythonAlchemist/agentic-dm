// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  labAPI: { store: vi.fn(), deriveEdges: vi.fn().mockResolvedValue({ written: 0, dropped: {} }) },
}))
import { labAPI } from '@/lib/api'
import type { GeneratedReply } from '@/lib/api'
import { DraftCard } from '@/components/product/DraftCard'

const reply = {
  kind: 'scene', subject: 's', title: 'A quiet scene', body: 'the model wrote this',
  from_canon: [{ claim: 'the book said it', cite: 'A Cry for Help' }],
  from_context: ['said at the table'],
  invented: ['nothing stands behind this one'],
  sources: [], usage: {}, cost: {}, retrieval: null, error: '', raw: '', model: 'm',
} as unknown as GeneratedReply

const props = { campaign: 'p13-home', reply, anchor: 'kftgv:x#3', onStored: () => {}, onDiscard: () => {} }

describe('DraftCard', () => {
  it('shows each source that contributed, and omits the one that did not', () => {
    render(<DraftCard {...props} />)
    expect(screen.getByText(/§ BOOK/)).toBeDefined()
    expect(screen.getByText(/❝ TABLE/)).toBeDefined()
    // Twice, deliberately: the header badge says the whole card is invented,
    // and the list heading says which claims are.
    expect(screen.getAllByText(/◇ INVENTED/)).toHaveLength(2)
    expect(screen.queryByText(/✎ YOURS/)).toBeNull()
  })

  it('is marked invented until it is stored', () => {
    const { container } = render(<DraftCard {...props} />)
    expect(container.querySelector('.border-dashed')).not.toBeNull()
    expect(screen.getByText(/nothing is in the graph until you store it/i)).toBeDefined()
  })

  it('stays invented when the store refuses', async () => {
    vi.mocked(labAPI.store).mockRejectedValue(new Error('Error: refused'))
    const { container } = render(<DraftCard {...props} />)
    fireEvent.click(screen.getByText('store as yours'))
    await waitFor(() => expect(screen.getByText(/refused/)).toBeDefined())
    expect(container.querySelector('.border-dashed')).not.toBeNull()
    expect(screen.queryByText(/✎ YOURS/)).toBeNull()
  })
})
