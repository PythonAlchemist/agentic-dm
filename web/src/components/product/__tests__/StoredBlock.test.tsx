// @vitest-environment jsdom
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { StoredBlock } from '@/components/product/StoredBlock'

describe('StoredBlock', () => {
  it('carries the yours grammar in all three channels', () => {
    const { container } = render(<StoredBlock title="A quiet scene" body="She goes quiet." />)
    expect(screen.getByText(/✎ YOURS/)).toBeDefined()
    expect(container.querySelector('.border-yours')).not.toBeNull()
    expect(container.querySelector('.border-dashed')).toBeNull()
  })
})
