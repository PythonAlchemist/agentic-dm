'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'

import { tableAPI, type Known } from '@/lib/api'
import { CHROME, SOURCE } from '@/lib/palette'

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
      <h2 className="text-[11px] uppercase tracking-widest text-neutral-600">
        What we know
      </h2>

      <div className="mt-2 flex gap-2">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && setAsked(q)}
          placeholder="who was the burgomaster again?"
          className={`min-w-0 flex-1 rounded border border-neutral-800 bg-neutral-950 px-2 py-1.5 text-sm text-neutral-200 outline-none ${CHROME.focus}`}
        />
        <button
          onClick={() => setAsked(q)}
          className={`shrink-0 rounded px-3 py-1.5 text-xs ${CHROME.primary}`}
        >
          look it up
        </button>
      </div>

      {found && found.anchors.length > 0 && (
        <ul className="mt-3 flex flex-wrap gap-2">
          {found.anchors.map((a) => (
            <li key={a.entity_id}>
              <Link
                href={`/c/${campaign}/e/${encodeURIComponent(a.entity_id)}`}
                className="text-sm text-neutral-300 hover:underline"
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
              <Link
                href={`/c/${campaign}/s/${encodeURIComponent(p.section_id)}`}
                className={`text-[11px] hover:underline ${
                  p.origin === 'campaign' ? SOURCE.yours : SOURCE.book
                }`}
              >
                {p.heading}
              </Link>
              {/* QUOTED, NEVER SUMMARISED. Trimmed for length only, and the
                  link goes to the whole of it. */}
              <p className="mt-0.5 line-clamp-4 text-sm leading-relaxed text-neutral-300">
                {p.text}
              </p>
            </li>
          ))}
        </ul>
      )}

      {found && found.passages.length === 0 && found.why && (
        <p className="mt-3 text-sm text-neutral-500">{found.why}.</p>
      )}
    </section>
  )
}
