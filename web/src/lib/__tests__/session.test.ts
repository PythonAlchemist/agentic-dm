/**
 * The id that keeps one reader's conversation their own.
 *
 * It was the constant `'lab'`, and the API keys its agents on it -- so every
 * reader of the deployment shared one history: what one asked arrived in the
 * next one's context, and any reader's Reset emptied it for all of them.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

function withStorage() {
  const store = new Map<string, string>()
  vi.stubGlobal('window', {
    localStorage: {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => void store.set(k, v),
      removeItem: (k: string) => void store.delete(k),
    },
  })
  return store
}

describe('a browser keeps its own session', () => {
  beforeEach(() => {
    vi.resetModules()
    vi.unstubAllGlobals()
  })

  it('mints one on first use', async () => {
    withStorage()
    const { sessionId } = await import('@/lib/api')
    expect(sessionId()).toMatch(/.+/)
  })

  it('returns the SAME id on the next call, so a refresh keeps the thread', async () => {
    withStorage()
    const { sessionId } = await import('@/lib/api')
    expect(sessionId()).toBe(sessionId())
  })

  it('persists it, which is what makes the id a bookmark', async () => {
    const store = withStorage()
    const { sessionId } = await import('@/lib/api')
    const first = sessionId()
    expect([...store.values()]).toContain(first)
  })

  it('two browsers do not share one', async () => {
    withStorage()
    const a = (await import('@/lib/api')).sessionId()
    vi.resetModules()
    withStorage()
    const b = (await import('@/lib/api')).sessionId()
    expect(a).not.toBe(b)
  })

  it('falls back on the server render, where there is no storage to read', async () => {
    vi.stubGlobal('window', undefined)
    const { sessionId } = await import('@/lib/api')
    expect(sessionId()).toBe('lab')
  })
})

describe('checking a token has three answers, not two', () => {
  beforeEach(() => {
    vi.resetModules()
    vi.unstubAllGlobals()
    withStorage()
  })

  async function check(responder: () => Promise<Response> | never) {
    vi.stubGlobal('fetch', responder)
    const { auth } = await import('@/lib/api')
    return auth.check()
  }

  it('a good token is ok', async () => {
    expect(await check(async () => new Response('{}', { status: 200 })))
      .toBe('ok')
  })

  it('a 401 is a refusal', async () => {
    expect(await check(async () => new Response('', { status: 401 })))
      .toBe('refused')
  })

  it('a 500 is NOT a refusal', async () => {
    // Telling a reader with a good token that it was rejected is the one
    // message that makes them stop trying.
    expect(await check(async () => new Response('', { status: 503 })))
      .toBe('unreachable')
  })

  it('a network failure is unreachable, and does not throw', async () => {
    // Unhandled, this left the Door's button stuck on "checking..." forever.
    expect(await check(async () => { throw new TypeError('failed to fetch') }))
      .toBe('unreachable')
  })
})
