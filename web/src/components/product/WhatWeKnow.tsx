'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'

import { tableAPI, type Known } from '@/lib/api'
import { SOURCE, SOURCE_GLYPH, SOURCE_WORD } from '@/lib/palette'

/**
 * What the table has been told, searched and quoted back.
 *
 * NO MODEL IN THE LOOP. These are the passages the players were actually
 * shown, in the book's own words. A generated summary here would be the one
 * screen where invented prose sits in front of the people least able to check
 * it -- and the retrieval that feeds it is the safe half of a player
 * assistant, not the whole of one.
 *
 * IT IS THE SHARED MEMORY, which is the thing six adults actually lose between
 * sessions. Not "ask the DM's assistant" -- "what did we learn about the
 * burgomaster", answered out of what they heard.
 *
 * AN EMPTY ANSWER SAYS WHY. "Nothing your table has been told about covers
 * that" is a different sentence from "no results", and it is the true one: the
 * book may well cover it.
 */
export function WhatWeKnow({ campaign }: { campaign: string }) {
  const [q, setQ] = useState('')
  const [asked, setAsked] = useState('')
  const [found, setFound] = useState<Known | null>(null)

  useEffect(() => {
    if (!asked.trim()) return
    let cancelled = false
    tableAPI
      .ask(campaign, asked)
      .then((r) => !cancelled && setFound(r))
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [asked, campaign])

  return (
    <section>
      <h2 className="label text-ink-faint">
        What we know
      </h2>

      <div className="mt-2 flex gap-2">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && setAsked(q)}
          placeholder="who was the burgomaster again?"
          className={`min-w-0 flex-1 rounded-md bg-surface px-2 py-1 text-ui text-ink`}
        />
        <button
          onClick={() => setAsked(q)}
          className="shrink-0 rounded-md border border-line px-3 py-1 text-meta text-ink-dim hover:text-ink"
        >
          look it up
        </button>
      </div>

      {found && found.anchors.length > 0 && (
        <ul className="mt-3 flex flex-wrap gap-x-3 gap-y-1">
          {found.anchors.map((a) => (
            <li key={a.entity_id}>
              <Link
                href={`/c/${campaign}/e/${encodeURIComponent(a.entity_id)}`}
                className="text-ui text-ink-dim hover:underline"
              >
                {a.name}
              </Link>
            </li>
          ))}
        </ul>
      )}

      {found && found.passages.length > 0 && (
        <ul className="mt-3 flex flex-col gap-4">
          {found.passages.map((p) => (
            <li key={p.section_id}>
              {/* THE FULL GRAMMAR, because this is the screen where the
                  promise faces a player. It was a colour-only label above a
                  13px line of app-face text, which made the book's own
                  sentences and the DM's writing typographically identical --
                  on the one screen whose entire job is telling them apart. */}
              <p className="label">
                <span
                  className={p.origin === 'campaign' ? SOURCE.yours : SOURCE.book}
                >
                  {p.origin === 'campaign'
                    ? `${SOURCE_GLYPH.yours} ${SOURCE_WORD.yours}`
                    : `${SOURCE_GLYPH.book} ${SOURCE_WORD.book}`}
                </span>{' '}
                <Link
                  href={`/c/${campaign}/s/${encodeURIComponent(p.section_id)}`}
                  className="text-ink-faint hover:text-ink-dim"
                >
                  {p.heading}
                </Link>
              </p>
              {/* QUOTED, NEVER SUMMARISED -- and in the book's own face when
                  they are the book's words. Trimmed for length only; the link
                  above goes to the whole of it. */}
              <p
                className={`mt-1 line-clamp-4 ${
                  p.origin === 'campaign'
                    ? 'text-body text-ink-dim'
                    : 'font-serif text-canon text-ink'
                }`}
              >
                {p.text}
              </p>
            </li>
          ))}
        </ul>
      )}

      {found && found.passages.length === 0 && found.why && (
        <p className="mt-3 text-ui text-ink-dim">{found.why}.</p>
      )}
    </section>
  )
}
