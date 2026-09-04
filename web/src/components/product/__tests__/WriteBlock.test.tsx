// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  labAPI: { store: vi.fn(), deriveEdges: vi.fn().mockResolvedValue({ written: 0, dropped: {} }) },
}))
import { labAPI } from '@/lib/api'
import { WriteBlock } from '@/components/product/WriteBlock'

const props = { campaign: 'p13-home', anchor: 'kftgv:x#3', onStored: () => {}, onDiscard: () => {} }

describe('WriteBlock', () => {
  it('stores what was typed, with no model and no sources', async () => {
    vi.mocked(labAPI.store).mockResolvedValue({ section_id: 's', entity_id: 'e', citations: 0, chain_changes: 0, anchored_after: '' })
    render(<WriteBlock {...props} />)
    fireEvent.change(screen.getByPlaceholderText('what happens here?'), { target: { value: 'A quiet scene' } })
    fireEvent.change(screen.getByPlaceholderText('your words'), { target: { value: 'She goes quiet.' } })
    fireEvent.click(screen.getByText('store as yours'))
    await waitFor(() => expect(labAPI.store).toHaveBeenCalled())
    const body = vi.mocked(labAPI.store).mock.calls[0][0]
    expect(body.title).toBe('A quiet scene')
    expect(body.generated_body).toBe('')
    expect(body.anchor).toBe('kftgv:x#3')
  })

  it('says what went wrong and keeps the words when the store refuses', async () => {
    vi.mocked(labAPI.store).mockRejectedValue(new Error('Error: refused'))
    render(<WriteBlock {...props} />)
    fireEvent.change(screen.getByPlaceholderText('your words'), { target: { value: 'She goes quiet.' } })
    fireEvent.click(screen.getByText('store as yours'))
    await waitFor(() => expect(screen.getByText(/refused/)).toBeDefined())
    expect((screen.getByPlaceholderText('your words') as HTMLTextAreaElement).value).toBe('She goes quiet.')
  })
})
