// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('next/navigation', () => ({
  useParams: () => ({ campaign: 'p1', id: 'kftgv:the-thing' }),
  useRouter: () => ({ push: vi.fn() }),
}))

vi.mock('@/lib/api', async (orig) => {
  const real = await orig<typeof import('@/lib/api')>()
  return {
    ...real,
    tableAPI: {
      ...real.tableAPI,
      // AN UNIDENTIFIED READER RUNS THE TABLE, per `useRuns` -- so the rail's
      // two buttons are offered without a login flow in the test.
      whoami: vi.fn().mockResolvedValue({ reader: '', role: '', identified: false }),
      revealed: vi.fn().mockResolvedValue({ revealed: [] }),
    },
    labAPI: {
      ...real.labAPI,
      config: vi.fn(),
      generate: vi.fn(),
      section: vi.fn().mockResolvedValue({
        section_id: 'kftgv:the-thing',
        describes: null,
        heading: 'The Thing',
        text: 'Something happens.',
        plane: 'canon',
        kind: null,
        chapter: 'Chapter One',
        from_canon: [],
        from_yours: [],
        from_context: [],
        invented: [],
        edited: null,
        cites: [],
        connections: [],
        mentions: [],
      }),
    },
  }
})

import SectionPage from '@/app/c/[campaign]/s/[id]/page'
import { labAPI } from '@/lib/api'

/**
 * THE CROSS-TALK A REVIEW CAUGHT: the drafting line, the draft error and
 * `DraftCard` were guarded only by `!kept`, so a request still in flight
 * when the DM opened `WriteBlock` kept rendering into the same slot as the
 * write form, and a draft failure's error survived past the rail returning
 * to rest into whatever the DM opened next. These four assertions are the
 * regression tests for that fix -- each one fails if the corresponding
 * guard regresses to `!kept` alone.
 */
describe('SectionPage draft/write mode isolation', () => {
  it('shows drafting only while draft mode is open, and clears it on switching to write', async () => {
    let resolveConfig!: (v: unknown) => void
    const configPromise = new Promise((resolve) => {
      resolveConfig = resolve
    })
    vi.mocked(labAPI.config).mockReturnValue(configPromise as never)

    render(<SectionPage />)

    const draftButton = await screen.findByText('draft it for me')
    fireEvent.click(draftButton)

    // (a) drafting shows only while the draft mode is open.
    await screen.findByText('drafting…')

    const writeButton = screen.getByText('write a scene here')
    fireEvent.click(writeButton)

    // (b) switching to write mid-flight shows the write form and NOT the
    // drafting line, even though the config() promise is still pending.
    await screen.findByPlaceholderText('your words')
    expect(screen.queryByText('drafting…')).toBeNull()

    // Let the in-flight request settle so it does not leak into the next test.
    resolveConfig({ default_model: 'm', defaults: {}, books: [] })
  })

  it('shows a failed draft error at rest, and clears it when write opens next', async () => {
    vi.mocked(labAPI.config).mockRejectedValue(new Error('Error: the model refused'))

    render(<SectionPage />)

    const draftButton = await screen.findByText('draft it for me')
    fireEvent.click(draftButton)

    // (c) a failed draft still shows its error, with the rail back at rest --
    // no rail button left selected.
    await waitFor(() => expect(screen.getByText(/the model refused/)).toBeDefined())
    expect(screen.getByText('draft it for me').getAttribute('aria-pressed')).toBe('false')
    expect(screen.getByText('write a scene here').getAttribute('aria-pressed')).toBe('false')

    // (d) opening write after a failure shows no stale error.
    fireEvent.click(screen.getByText('write a scene here'))
    await screen.findByPlaceholderText('your words')
    expect(screen.queryByText(/the model refused/)).toBeNull()
  })
})
