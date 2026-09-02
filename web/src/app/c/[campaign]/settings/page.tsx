'use client'

import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'next/navigation'

import { Shell } from '@/components/product/Shell'
import { tableAPI, type BookRow, type Seat, type Settings } from '@/lib/api'
import { CHROME } from '@/lib/palette'

/**
 * What is true of the whole table.
 *
 * THE PREMISE IS PROSE, NOT A FIELD. A name and a list of books are facts about
 * the container; what the campaign IS -- the pitch, the house rules, what the
 * party did before session one -- is writing, and writing here is a section in
 * the campaign plane. So it is stored as one and scanned like one: a premise
 * saying the party owes Bildrath money connects the table to Bildrath without
 * anybody linking anything.
 *
 * THE SLUG IS NOT EDITABLE AND THE SCREEN SAYS WHY. Every node the table ever
 * wrote carries it, so changing it is a migration wearing a settings control.
 *
 * DROPPING A BOOK IS NOT A DELETE, and the copy says that too. It stops new
 * scans looking there; the DM's own words about that book stay exactly where
 * they are.
 */
export default function SettingsPage() {
  const params = useParams<{ campaign: string }>()
  const campaign = decodeURIComponent(params.campaign)

  const [settings, setSettings] = useState<Settings | null>(null)
  const [books, setBooks] = useState<BookRow[]>([])
  const [seats, setSeats] = useState<Seat[]>([])
  const [name, setName] = useState('')
  const [premise, setPremise] = useState('')
  const [who, setWho] = useState('')
  const [role, setRole] = useState('player')
  const [saved, setSaved] = useState('')
  const [failed, setFailed] = useState('')

  const load = useCallback(() => {
    tableAPI
      .settings(campaign)
      .then((found) => {
        setSettings(found)
        setName(found.name)
        setPremise(found.premise)
      })
      .catch((error) => setFailed(String(error)))
    tableAPI.seats(campaign).then((r) => setSeats(r.seats)).catch(() => undefined)
    tableAPI.books().then((r) => setBooks(r.books)).catch(() => undefined)
  }, [campaign])

  useEffect(load, [load])

  const save = (body: { name?: string; book?: string; premise?: string }) => {
    setFailed('')
    tableAPI
      .saveSettings({ campaign, ...body })
      .then(() => {
        setSaved('Saved.')
        load()
      })
      .catch((error) => setFailed(String(error).replace(/^Error:\s*/, '')))
  }

  const drawn = new Set(settings?.books ?? [])

  return (
    <Shell campaign={campaign} section="settings">
      <div className="mx-auto flex max-w-3xl flex-col gap-10 px-6 py-10">
        <section>
          <h1 className="text-title font-medium text-ink">This table</h1>
          <div className="mt-4 flex gap-2">
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              className={`min-w-0 flex-1 rounded-md border border-line bg-ground px-2 py-1.5 text-ui text-ink`}
            />
            <button
              onClick={() => save({ name })}
              className="shrink-0 rounded-md border border-line px-3 py-1.5 text-meta text-ink-dim hover:text-ink"
            >
              rename
            </button>
          </div>
          <p className="mt-2 text-label text-ink-faint">
            Keyed as <span className="text-ink-dim">{campaign}</span>, which
            cannot change &mdash; every scene, entity and mention this table has
            ever written carries it.
            {settings?.owner && <> Run by {settings.owner}.</>}
          </p>
        </section>

        <section>
          <h2 className="text-label uppercase tracking-widest text-ink-faint">
            What this campaign is
          </h2>
          <p className="mt-1 text-label text-ink-faint">
            Written down, and read like any other scene &mdash; names you use
            here connect to the book on their own.
          </p>
          <textarea
            value={premise}
            onChange={(e) => setPremise(e.target.value)}
            rows={6}
            placeholder="The pitch, the house rules, what happened before session one."
            className={`mt-2 w-full resize-y rounded-md border border-line bg-ground px-3 py-2 text-ui leading-relaxed text-ink`}
          />
          <button
            onClick={() => save({ premise })}
            className={`mt-3 rounded-md px-3 py-1.5 text-ui ${CHROME.primary}`}
          >
            save
          </button>
        </section>

        <section>
          <h2 className="text-label uppercase tracking-widest text-ink-faint">
            Books it draws on
          </h2>
          <ul className="mt-2 flex flex-col gap-1">
            {books.map((book) => (
              <li key={book.slug} className="flex items-baseline gap-3 text-ui">
                {/* THE HUE WAS MARKING SELECTION, not source. Every row here
                    is a book, so colouring only the ones in play made emerald
                    mean "chosen" on this screen and "the published book"
                    everywhere else -- the same borrowing the rule forbids.
                    Whether a table plays from it is chrome, and reads from the
                    weight and the action beside it. */}
                <span className={drawn.has(book.slug) ? 'text-ink' : 'text-ink-dim'}>
                  {book.title}
                </span>
                <span className="text-label text-ink-faint">
                  {book.chapters} chapters
                </span>
                <button
                  onClick={() =>
                    drawn.has(book.slug)
                      ? tableAPI.dropBook(campaign, book.slug).then(load)
                      : save({ book: book.slug })
                  }
                  className="ml-auto text-label text-ink-dim hover:text-ink"
                >
                  {drawn.has(book.slug) ? 'stop playing from it' : 'play from it'}
                </button>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-label text-ink-faint">
            Stopping does not delete anything. New scans stop looking in that
            book; what you wrote about it stays.
          </p>
        </section>

        <section>
          <h2 className="text-label uppercase tracking-widest text-ink-faint">
            Who sits here
          </h2>
          <ul className="mt-2 flex flex-col gap-1">
            {seats.map((seat) => (
              <li key={seat.reader} className="flex items-baseline gap-3 text-ui">
                <span className="text-ink">{seat.reader}</span>
                <span className="text-label uppercase tracking-wide text-ink-faint">
                  {seat.role}
                </span>
                <button
                  onClick={() => tableAPI.unseat(campaign, seat.reader).then(load)}
                  className="ml-auto text-label text-ink-faint hover:text-ink-dim"
                >
                  remove
                </button>
              </li>
            ))}
            {seats.length === 0 && (
              <li className="text-ui text-ink-faint">
                Only you. The owner of a table is its DM without being seated.
              </li>
            )}
          </ul>

          <div className="mt-3 flex gap-2">
            <input
              value={who}
              onChange={(e) => setWho(e.target.value)}
              placeholder="reader name"
              className={`min-w-0 flex-1 rounded-md border border-line bg-ground px-2 py-1 text-ui text-ink`}
            />
            <select
              value={role}
              onChange={(e) => setRole(e.target.value)}
              className="shrink-0 rounded-md border border-line bg-ground px-2 py-1 text-ui text-ink-dim"
            >
              <option value="player">player</option>
              <option value="dm">dm</option>
            </select>
            <button
              onClick={() =>
                tableAPI
                  .seat(campaign, who, role)
                  .then(() => {
                    setWho('')
                    load()
                  })
                  .catch((error) => setFailed(String(error).replace(/^Error:\s*/, '')))
              }
              className="shrink-0 rounded-md border border-line px-3 py-1 text-meta text-ink-dim hover:text-ink"
            >
              seat
            </button>
          </div>
        </section>

        {(saved || failed) && (
          <p className="text-label text-ink-dim">{failed ? `⚠ ${failed}` : saved}</p>
        )}
      </div>
    </Shell>
  )
}
