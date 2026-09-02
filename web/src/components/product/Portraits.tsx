'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

import { tableAPI, type Portrait } from '@/lib/api'
import { CHROME, SOURCE } from '@/lib/palette'

/**
 * The pictures of an entity, each saying where it came from.
 *
 * `origin` IS `plane` FOR PIXELS, and this is where a reader sees it. The
 * foundational promise -- a DM can tell the published book from what a model
 * invented -- does not stop at sentences, and an image is the most persuasive
 * medium the product has. A face the book printed and a face a model imagined
 * must never render alike, so the mark is ON the picture rather than in a
 * tooltip or an info panel a reader can fail to open.
 *
 * THE SAME FOUR HUES, NOT A FIFTH SCHEME. `palette.ts` already spends emerald
 * on the book, amber on yours and rose on invented; a portrait's origin is the
 * same question about a different medium, so it takes the same answer.
 *
 * THE EMPTY SLOT STAYS UNREMARKABLE. Almost every entity has no picture and
 * will for a long time. A dashed box with a "generate" button on every one of
 * them would make invention ambient, which is the drift the colour rule exists
 * to stop -- so the actions appear on the full profile and never on the popout.
 */

const ORIGIN_HUE: Record<string, string> = {
  book: SOURCE.book,
  uploaded: SOURCE.yours,
  generated: SOURCE.invented,
}

/** A kind mark for an entity nobody has pictured. */
export function kindMark(labels: string[]): string {
  if (labels.includes('NPC')) return '☙'
  if (labels.includes('LOCATION')) return '⌂'
  if (labels.includes('ITEM')) return '◇'
  if (labels.includes('MONSTER')) return '✦'
  return '·'
}

export function Portraits({
  entityId,
  campaign,
  labels,
  compact = false,
}: {
  entityId: string
  campaign: string
  labels: string[]
  /** The popout. Shows the face and nothing you could press. */
  compact?: boolean
}) {
  const [found, setFound] = useState<Portrait[]>([])
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState('')
  const file = useRef<HTMLInputElement>(null)

  const load = useCallback(() => {
    tableAPI
      .portraits(entityId, campaign)
      .then((r) => setFound(r.portraits))
      // An entity with no pictures and an API that is down look identical
      // here, and neither is worth an error banner on a profile.
      .catch(() => undefined)
  }, [entityId, campaign])

  useEffect(load, [load])

  const primary = found[0]
  const size = compact ? 'h-14 w-14' : 'h-24 w-24'

  const onPick = (chosen: File | undefined) => {
    if (!chosen) return
    setBusy(true)
    setFailed('')
    tableAPI
      .upload(campaign, chosen)
      .then((asset) => tableAPI.portray(campaign, entityId, asset.id))
      .then(() => {
        setBusy(false)
        load()
      })
      .catch((error) => {
        setBusy(false)
        setFailed(String(error).replace(/^Error:\s*/, ''))
      })
  }

  return (
    <div className="flex shrink-0 flex-col gap-2">
      <div
        className={`${size} relative overflow-hidden rounded border border-neutral-800 bg-neutral-900/60`}
      >
        {primary ? (
          // A PLAIN `<img>`, DELIBERATELY. The bytes come from our own API at
          // a content-addressed URL, which is already immutable and already
          // cached forever; `next/image` would need a loader configured for an
          // origin it cannot know at build time.
          /* eslint-disable-next-line @next/next/no-img-element */
          <img
            src={tableAPI.assetURL(primary.id)}
            alt=""
            className="h-full w-full object-cover"
          />
        ) : (
          <div
            className="flex h-full w-full items-center justify-center text-2xl text-neutral-700"
            aria-hidden
          >
            {kindMark(labels)}
          </div>
        )}

        {primary && (
          // THE MARK IS ON THE PICTURE. Not beside it, not on hover: a
          // provenance signal a reader can miss is one that will be missed
          // exactly when it matters.
          <span
            className={`absolute inset-x-0 bottom-0 bg-neutral-950/80 px-1 py-0.5 text-center text-[9px] leading-tight ${
              ORIGIN_HUE[primary.origin] ?? 'text-neutral-400'
            }`}
          >
            {primary.caption}
          </span>
        )}
      </div>

      {!compact && (
        <>
          {found.length > 1 && (
            <div className="flex flex-wrap gap-1">
              {found.slice(1).map((p) => (
                <span key={p.id} title={p.caption}>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={tableAPI.assetURL(p.id)}
                    alt={p.caption}
                    className="h-8 w-8 rounded border border-neutral-800 object-cover"
                  />
                </span>
              ))}
            </div>
          )}

          <input
            ref={file}
            type="file"
            accept="image/png,image/jpeg,image/webp,image/gif"
            className="hidden"
            onChange={(event) => onPick(event.target.files?.[0])}
          />
          <button
            onClick={() => file.current?.click()}
            disabled={busy}
            className={`rounded px-2 py-1 text-[11px] ${CHROME.primary}`}
          >
            {busy ? 'storing…' : found.length ? 'another picture' : 'add a picture'}
          </button>
          {failed && (
            <p className="max-w-[9rem] text-[11px] leading-tight text-neutral-400">
              ⚠ {failed}
            </p>
          )}
        </>
      )}
    </div>
  )
}
