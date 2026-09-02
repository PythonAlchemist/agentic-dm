'use client'

import { useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'

import { EntityProfile } from '@/components/product/EntityProfile'
import { Shell } from '@/components/product/Shell'
import { labAPI, type EntityRead, type SectionRead } from '@/lib/api'
import { readingBlocks } from '@/lib/reading'
import { SOURCE } from '@/lib/palette'

/**
 * A section, read the way the book set it.
 *
 * THE BOOK'S OWN ART IS BACK. 286 illustrations came in with the harvest and
 * were being replaced with the string "[illustration]". They are the book's
 * plates, on the book's pages, and they carry an emerald caption for the same
 * reason its sentences do: a DM must be able to tell them from a portrait
 * somebody generated.
 *
 * CLICKING A NAME OPENS A POPOUT, NOT A NEW PAGE. Mid-session a DM wants to
 * know who somebody is without losing the paragraph they were reading aloud.
 * Escape returns them to it.
 */
export default function SectionPage() {
  const params = useParams<{ campaign: string; id: string }>()
  const router = useRouter()
  // DECODED HERE BECAUSE `useParams` DOES NOT. Entity and section ids carry a
  // colon (`cos:strahd-von-zarovich`), so every link encodes them -- and Next
  // 16 hands the raw `cos%3Astrahd-von-zarovich` back. Verified against a dev
  // server rather than assumed; removing this decode breaks every link in the
  // product.
  const campaign = decodeURIComponent(params.campaign)
  const sectionId = decodeURIComponent(params.id)

  const [section, setSection] = useState<SectionRead | null>(null)
  const [popout, setPopout] = useState<EntityRead | null>(null)
  const [failed, setFailed] = useState('')

  useEffect(() => {
    let cancelled = false
    labAPI
      .section(sectionId, campaign)
      .then((found) => !cancelled && setSection(found))
      .catch((error) => !cancelled && setFailed(String(error)))
    return () => {
      cancelled = true
    }
  }, [sectionId, campaign])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setPopout(null)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const openEntity = (entityId: string) => {
    labAPI.entity(entityId, campaign).then(setPopout).catch(() => undefined)
  }

  const yours = section?.plane === 'campaign'

  return (
    <Shell campaign={campaign} section="library">
      {failed && (
        <p className="mx-auto max-w-3xl px-6 py-10 text-sm text-neutral-500">
          Could not open that section.
        </p>
      )}

      {section && (
        <article className="mx-auto max-w-3xl px-6 py-10">
          {/* WHOSE WORDS THESE ARE, before the words. */}
          <p className="text-xs">
            {yours ? (
              <>
                <span className={SOURCE.yours}>Yours.</span>{' '}
                <span className="text-neutral-500">Written for this campaign.</span>
              </>
            ) : (
              <>
                <span className={SOURCE.book}>The book.</span>{' '}
                <span className="text-neutral-500">{section.chapter}</span>
              </>
            )}
          </p>
          <h1 className="mt-1 text-2xl font-medium text-neutral-100">
            {section.heading}
          </h1>

          <div className="mt-6 flex flex-col gap-5">
            {readingBlocks(section.text, section.heading).map((block, i) =>
              block.kind === 'illustration' ? (
                <figure key={i} className="flex flex-col gap-1.5">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={block.src}
                    alt={block.alt}
                    loading="lazy"
                    className="max-w-full rounded border border-neutral-800"
                  />
                  <figcaption className={`text-[11px] ${SOURCE.book}`}>
                    the book&rsquo;s art
                  </figcaption>
                </figure>
              ) : (
                <p
                  key={i}
                  className="whitespace-pre-wrap text-sm leading-relaxed text-neutral-200"
                >
                  <Named
                    text={block.text}
                    mentions={section.mentions}
                    onOpen={openEntity}
                  />
                </p>
              ),
            )}
          </div>
        </article>
      )}

      {popout && (
        <div
          className="fixed inset-0 z-20 flex items-start justify-center bg-neutral-950/70 p-6 pt-20"
          onClick={() => setPopout(null)}
        >
          <div
            className="max-h-[70vh] w-full max-w-md overflow-y-auto rounded-lg border border-neutral-800 bg-neutral-900 p-5 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <EntityProfile
              entity={popout}
              campaign={campaign}
              compact
              onOpenSection={(id) =>
                router.push(`/c/${campaign}/s/${encodeURIComponent(id)}`)
              }
            />
          </div>
        </div>
      )}
    </Shell>
  )
}

/**
 * The prose, with the names the GRAPH says are in it made clickable.
 *
 * WHICH names is not decided here: the mention triangle already recorded that
 * this section refers to this entity, so this only has to find them. A reader
 * scanning for names of its own would disagree with retrieval the first time
 * two things shared a spelling.
 */
function Named({
  text,
  mentions,
  onOpen,
}: {
  text: string
  mentions: SectionRead['mentions']
  onOpen: (entityId: string) => void
}) {
  const surfaces = [...mentions]
    .filter((m) => m.surface)
    // LONGEST FIRST, so `Captain Saltmarrow` wins over `Saltmarrow` and the
    // short match cannot eat the start of the long one.
    .sort((a, b) => b.surface.length - a.surface.length)
  if (surfaces.length === 0) return <>{text}</>

  const pattern = new RegExp(
    `(${surfaces.map((m) => m.surface.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})`,
    'g',
  )
  const found = new Map(surfaces.map((m) => [m.surface.toLowerCase(), m]))

  return (
    <>
      {text.split(pattern).map((piece, i) => {
        const mention = found.get(piece.toLowerCase())
        if (!mention) return piece
        return (
          <button
            key={i}
            onClick={() => onOpen(mention.entity_id)}
            className={`underline decoration-dotted underline-offset-2 hover:decoration-solid ${
              mention.plane === 'campaign' ? SOURCE.yours : 'text-neutral-100'
            }`}
          >
            {piece}
          </button>
        )
      })}
    </>
  )
}
