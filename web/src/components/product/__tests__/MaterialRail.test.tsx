// @vitest-environment jsdom
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { MaterialRail } from '@/components/product/MaterialRail'

vi.mock('@/lib/role', () => ({ useRuns: vi.fn() }))
import { useRuns } from '@/lib/role'

describe('MaterialRail', () => {
  it('offers nothing to a player', () => {
    vi.mocked(useRuns).mockReturnValue(false)
    const { container } = render(<MaterialRail campaign="p13-home" open={null} onOpen={() => {}} />)
    expect(container.innerHTML).toBe('')
  })

  it('offers nothing while the answer is still in flight', () => {
    vi.mocked(useRuns).mockReturnValue(null)
    const { container } = render(<MaterialRail campaign="p13-home" open={null} onOpen={() => {}} />)
    expect(container.innerHTML).toBe('')
  })

  it('offers the DM both ways in', () => {
    vi.mocked(useRuns).mockReturnValue(true)
    render(<MaterialRail campaign="p13-home" open={null} onOpen={() => {}} />)
    expect(screen.getByText('write a scene here')).toBeDefined()
    expect(screen.getByText('draft it for me')).toBeDefined()
  })

  it('shows the unbuilt action without pretending it is pressable', () => {
    vi.mocked(useRuns).mockReturnValue(true)
    render(<MaterialRail campaign="p13-home" open={null} onOpen={() => {}} />)
    expect(screen.getByText('not yet')).toBeDefined()
    expect(screen.queryByRole('button', { name: /add someone/ })).toBeNull()
  })
})
