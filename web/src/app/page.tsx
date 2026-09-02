'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useCallback, useEffect, useState } from 'react'

import { Door } from '@/components/Door'
import { Shell } from '@/components/product/Shell'
import { auth, labAPI, tableAPI, type BookRow, type CampaignInfo } from '@/lib/api'

/**
 * The way in: pick a table.
 *
 * THE CAMPAIGN IS THE CONTAINER, and it is now in the URL. Everything the
 * roadmap adds -- an entity profile a player can be sent a link to, a map, a
 * session -- needs to be addressable, and the app had exactly one route with
 * every piece of state in React. You could not bookmark a scene or reopen
 * where you were.
 *
 * "TABLE" IS THE WORD FOR THE PRODUCT, NOT FOR A CAMPAIGN. `palette.ts` spends
 * `sky` on "the table -- said in conversation, in no book", and the old Setup
 * drawer also called a campaign "your table". One of those had to give, and it
 * was not the provenance hue.
 */
export default function Home() {
  const router = useRouter()
  const [locked, setLocked] = useState<boolean | null>(null)
  const [campaigns, setCampaigns] = useState<CampaignInfo[]>([])
  const [reachable, setReachable] = useState(true)
  const [books, setBooks] = useState<BookRow[]>([])
  const [making, setMaking] = useState(false)
  const [name, setName] = useState('')
  const [book, setBook] = useState('')
  const [failed, setFailed] = useState('')

  // A CALLBACK, NOT AN AWAIT IN THE EFFECT BODY. The same shape the lab uses:
  // setState belongs in a promise callback, which is what the effect rule
  // permits and what keeps a cascading render out of first paint.
  const open = useCallback(() => {
    labAPI
      .campaigns()
      .then((found) => {
        setCampaigns(found.campaigns)
        setReachable(true)
        setLocked(false)
      })
      .catch((error) => {
        // A 401 raises the Door through `auth.onRefused`; anything else is the
        // API being unreachable, which must never read as "you have no tables".
        if (!String(error).includes('401')) setReachable(false)
        setLocked(false)
      })
  }, [])

  useEffect(() => {
    auth.onRefused(() => setLocked(true))
    auth.load()
    open()
    tableAPI.books().then((r) => setBooks(r.books)).catch(() => undefined)
  }, [open])

  // A SLUG IS DERIVED, NOT ASKED FOR. It is the key every node this table will
  // ever write carries, and it can never change -- so it is the last thing to
  // put in front of somebody who has typed a name and wants to start playing.
  const slug = name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')

  const make = () => {
    if (!slug) return
    setFailed('')
    tableAPI
      .createTable(slug, name.trim(), book)
      .then((made) => router.push(`/c/${made.slug}`))
      .catch((error) => setFailed(String(error).replace(/^Error:\s*/, '')))
  }

  if (locked === null) return <div className="h-full bg-neutral-950" />
  if (locked) return <Door onOpened={open} />

  return (
    <Shell>
      <div className="mx-auto max-w-3xl px-6 py-14">
        <h1 className="text-2xl font-medium text-neutral-100">Your tables</h1>
        <p className="mt-2 max-w-prose text-sm leading-relaxed text-neutral-500">
          Each one draws on the books it was set up with. What the book says and
          what you wrote are kept apart everywhere in here.
        </p>

        {!reachable && (
          <p className="mt-8 rounded border border-amber-900/60 bg-amber-950/20 p-3 text-sm text-amber-200/80">
            Could not reach the API. This is not &ldquo;you have no
            campaigns&rdquo; &mdash; it may be starting up.
          </p>
        )}

        <div className="mt-8 flex flex-col gap-2">
          {campaigns.map((c) => (
            <Link
              key={c.slug}
              href={`/c/${c.slug}`}
              className="group flex items-baseline gap-3 rounded-md border border-neutral-800 bg-neutral-900/40 px-4 py-3 transition-colors hover:border-neutral-700 hover:bg-neutral-900"
            >
              <span className="font-medium text-neutral-200 group-hover:text-neutral-100">
                {c.name}
              </span>
              <span className="text-xs text-neutral-600">{c.slug}</span>
              <span className="ml-auto text-xs tabular-nums text-neutral-600">
                {c.sections} sections
              </span>
            </Link>
          ))}

          {reachable && campaigns.length === 0 && !making && (
            <p className="text-sm text-neutral-500">No tables yet.</p>
          )}
        </div>

        {/* MAKING ONE WAS A SCRIPT. `store.create` had exactly one caller and
            it was a command line, while this page said the lab could do it --
            which was not true of the lab either. */}
        <div className="mt-6">
          {making ? (
            <div className="flex flex-col gap-2 rounded-md border border-neutral-800 bg-neutral-900/40 p-4">
              <input
                autoFocus
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="what do you call it?"
                className="rounded border border-neutral-800 bg-neutral-950 px-2 py-1.5 text-sm text-neutral-200 outline-none focus:border-neutral-500"
              />
              <select
                value={book}
                onChange={(e) => setBook(e.target.value)}
                className="rounded border border-neutral-800 bg-neutral-950 px-2 py-1.5 text-sm text-neutral-300"
              >
                <option value="">no book yet</option>
                {books.map((b) => (
                  <option key={b.slug} value={b.slug}>
                    {b.title}
                  </option>
                ))}
              </select>
              <div className="flex items-baseline gap-3">
                <button
                  onClick={make}
                  disabled={!slug}
                  className="rounded bg-neutral-200 px-3 py-1.5 text-xs text-neutral-950 transition-colors hover:bg-white disabled:opacity-30"
                >
                  make it
                </button>
                <button
                  onClick={() => setMaking(false)}
                  className="text-[11px] text-neutral-600 hover:text-neutral-400"
                >
                  cancel
                </button>
                {slug && <span className="text-[11px] text-neutral-600">{slug}</span>}
              </div>
              {failed && <p className="text-[11px] text-neutral-400">⚠ {failed}</p>}
            </div>
          ) : (
            <button
              onClick={() => setMaking(true)}
              className="text-sm text-neutral-500 hover:text-neutral-300"
            >
              Start a table
            </button>
          )}
        </div>
      </div>
    </Shell>
  )
}
