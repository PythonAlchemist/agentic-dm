// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

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

// CALL COUNTS, NOT JUST IMPLEMENTATIONS, RESET BETWEEN TESTS. `config`/
// `generate` are shared `vi.fn()` instances across every test in this file;
// a test that asserts `toHaveBeenCalledTimes` would otherwise be counting
// calls from every test that ran before it in the same file.
beforeEach(() => {
  vi.clearAllMocks()
})

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

  // ROUND 2 FOLLOW-UP: fixing the cross-talk above by tracking `cancelled` in
  // the effect introduced a second, subtler bug -- this effect's own
  // dependency array used to include `drafting`, a piece of state the effect
  // sets on its own first line. That self-triggered a cleanup-and-rerun cycle
  // (drafting false -> true is itself a dependency change) which cancelled
  // the very request that had just started, before the network had any
  // chance to answer. Once that happens, EVERY outcome of that request --
  // including a plain failure with the DM still sitting in draft mode -- is
  // silently swallowed, because `cancelled` reads true in the `.catch`
  // regardless of whether the DM ever switched away. `drafting` is no longer
  // a dependency for exactly this reason; this test fails if it becomes one
  // again, by rejecting only after several real ticks have passed with no
  // mode switch at all -- long enough for that spurious cleanup to have run
  // if `drafting` were still listed.
  it('still shows the error after a real delay, with no mode switch at all', async () => {
    let rejectConfig!: (e: unknown) => void
    const configPromise = new Promise((_resolve, reject) => {
      rejectConfig = reject
    })
    configPromise.catch(() => undefined)
    vi.mocked(labAPI.config).mockReturnValue(configPromise as never)

    render(<SectionPage />)

    fireEvent.click(await screen.findByText('draft it for me'))
    await screen.findByText('drafting…')

    // Several real ticks, deliberately, with the DM doing nothing else.
    await new Promise((resolve) => setTimeout(resolve, 0))
    await new Promise((resolve) => setTimeout(resolve, 0))
    await new Promise((resolve) => setTimeout(resolve, 0))

    rejectConfig(new Error('Error: the model refused, eventually'))
    await waitFor(() =>
      expect(screen.queryByText(/the model refused, eventually/)).not.toBeNull(),
    )
  })
})

/**
 * ROUND 2: a late failure must not cost a DM their own typed words.
 *
 * `.catch` used to run `setMaterial(null)` unconditionally. A draft request
 * that failed AFTER the DM had already switched to `WriteBlock` and started
 * typing set `material` away from `'write'`, which unmounts `WriteBlock` --
 * and its `title`/`body` live only in its own local state, so the DM's words
 * were destroyed by a request they had already walked away from. The effect
 * now tracks `cancelled` and the `.catch` is a no-op once the DM has moved on.
 */
describe('a draft failure that lands after the DM has moved on', () => {
  it('does not unmount WriteBlock or lose what was typed into it', async () => {
    let rejectConfig!: (e: unknown) => void
    const configPromise = new Promise((_resolve, reject) => {
      rejectConfig = reject
    })
    // Swallow the eventual rejection on the promise itself so vitest's
    // unhandled-rejection guard does not also flag it -- the assertion is
    // about the component tree, not about this bookkeeping promise.
    configPromise.catch(() => undefined)
    vi.mocked(labAPI.config).mockReturnValue(configPromise as never)

    render(<SectionPage />)

    fireEvent.click(await screen.findByText('draft it for me'))
    await screen.findByText('drafting…')

    // The DM gives up waiting and starts writing their own scene instead.
    fireEvent.click(screen.getByText('write a scene here'))
    const body = await screen.findByPlaceholderText('your words')
    fireEvent.change(body, { target: { value: 'the words the DM already typed' } })

    // The abandoned draft request now fails.
    rejectConfig(new Error('Error: the model refused'))
    // Give the rejection's microtask queue a turn to run.
    await new Promise((resolve) => setTimeout(resolve, 0))

    // The write form is still here, with the DM's words intact -- it was
    // never unmounted -- and no stale draft error rode in on top of it.
    expect(screen.getByPlaceholderText('your words')).toHaveProperty(
      'value',
      'the words the DM already typed',
    )
    expect(screen.queryByText(/the model refused/)).toBeNull()
  })

  it('still issues a fresh request the next time draft mode opens', async () => {
    // TWO CALLS, TWO PROMISES the test controls independently -- proving
    // `drafting` was not left stuck `true` by the abandoned first run, which
    // would silently block every draft request after it forever.
    const rejectors: Array<(e: unknown) => void> = []
    vi.mocked(labAPI.config).mockImplementation(
      () =>
        new Promise((_resolve, reject) => {
          rejectors.push(reject)
        }) as never,
    )

    render(<SectionPage />)

    fireEvent.click(await screen.findByText('draft it for me'))
    await screen.findByText('drafting…')
    expect(labAPI.config).toHaveBeenCalledTimes(1)

    // Abandon it for write, then let the first request fail once abandoned.
    fireEvent.click(screen.getByText('write a scene here'))
    await screen.findByPlaceholderText('your words')
    rejectors[0](new Error('Error: the model refused'))
    await new Promise((resolve) => setTimeout(resolve, 0))

    // Open draft mode again: a fresh request must go out, which only happens
    // if `drafting` was correctly reset to `false` by the unguarded `.finally`.
    fireEvent.click(screen.getByText('draft it for me'))
    await waitFor(() => expect(labAPI.config).toHaveBeenCalledTimes(2))
  })
})

/**
 * A DEFECT THE SUGGESTED FIX ITSELF WOULD HAVE SHIPPED, found by
 * instrumenting the effect and watching the real sequence: with `drafting`
 * listed as a dependency, `setDrafting(true)` on the effect's first line
 * re-fires the effect on the next render, which runs THIS SAME invocation's
 * cleanup and cancels its own request before the network answers. When that
 * cancelled request eventually settles, its unguarded `.finally` resets
 * `drafting` back to `false` -- which re-passes the guard and fires a brand
 * new, real request nobody asked for. If that one also fails, it repeats.
 * Uncapped, this hammers the model endpoint forever on any persistent
 * failure while showing the DM nothing, because `cancelled` reads `true` in
 * every `.catch` along the way. `drafting` is not a dependency for exactly
 * this reason -- this test fails (with more than one call recorded) if it
 * becomes one again.
 */
describe('a draft failure does not retry itself against the backend', () => {
  it('issues exactly one request per click, even after that request fails', async () => {
    const rejectors: Array<(e: unknown) => void> = []
    vi.mocked(labAPI.config).mockImplementation(
      () =>
        new Promise((_resolve, reject) => {
          rejectors.push(reject)
        }) as never,
    )

    render(<SectionPage />)
    fireEvent.click(await screen.findByText('draft it for me'))
    await screen.findByText('drafting…')
    expect(labAPI.config).toHaveBeenCalledTimes(1)

    // Fail it, without the DM ever leaving draft mode or clicking anything.
    rejectors[0](new Error('Error: backend said no'))
    await waitFor(() => expect(screen.getByText(/backend said no/)).toBeDefined())

    // Give any hidden retry every chance to fire before asserting it didn't.
    for (let i = 0; i < 10; i++) {
      await new Promise((resolve) => setTimeout(resolve, 0))
    }
    expect(labAPI.config).toHaveBeenCalledTimes(1)
  })
})
