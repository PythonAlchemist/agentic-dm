'use client'

import { useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'

import { DraftCard } from '@/components/product/DraftCard'
import { EntityProfile } from '@/components/product/EntityProfile'
import { MaterialRail, type MaterialAction } from '@/components/product/MaterialRail'
import { Reveal } from '@/components/product/Reveal'
import { Shell } from '@/components/product/Shell'
import { StoredBlock } from '@/components/product/StoredBlock'
import { WriteBlock } from '@/components/product/WriteBlock'
import { labAPI, type EntityRead, type GeneratedReply, type SectionRead } from '@/lib/api'
import { EMPHASIS_MARK, readingBlocks, withEmphasis } from '@/lib/reading'
import {
  SOURCE,
  SOURCE_EDGE,
  SOURCE_GLYPH,
  SOURCE_WORD,
} from '@/lib/palette'

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
 *
 * THE BOOK'S WORDS ARE SET IN THE BOOK'S FACE. Literata appears here and in
 * almost nowhere else in the product, because the face is a provenance channel
 * rather than a mood: a reader who cannot use the hues at all still sees that
 * this page is quoting and the app's chrome is not. A DM's own scene is set in
 * the app's face for exactly the same reason -- it is their writing, not the
 * book's -- so the two never look alike even in a screenshot with no colour.
 *
 * AND IT IS SET TO BE READ, at 16px on a 42rem measure. It was 13px full-width
 * sans, which is how you set a log file.
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
  const [material, setMaterial] = useState<MaterialAction | null>(null)
  const [kept, setKept] = useState<{ title: string; body: string } | null>(null)
  const [draft, setDraft] = useState<GeneratedReply | null>(null)
  const [drafting, setDrafting] = useState(false)
  const [draftFailed, setDraftFailed] = useState('')

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
    if (material !== 'draft' || draft || drafting || !section) return
    let cancelled = false
    setDrafting(true)
    setDraftFailed('')
    labAPI
      .config()
      .then((config) => {
        // The book this section belongs to, matched rather than assumed: the
        // section id carries a prefix and the config carries the list, and the
        // two spellings have disagreed before.
        const prefix = section.section_id.split(':')[0]
        const book = config.books.find((b) => b.slug.endsWith(prefix))?.slug ?? prefix
        return labAPI.generate(
          'scene',
          section.heading,
          config.default_model,
          config.defaults,
          book,
          campaign,
        )
      })
      .then(setDraft)
      // THE RAIL RETURNS TO REST AND SAYS WHY. Nothing was written, so there is
      // nothing to roll back -- but a silent failure leaves a DM clicking an
      // action that appears to do nothing at all.
      .catch((error) => {
        // A DM who has moved on has moved on. Without this, a failure that
        // lands after they opened the write form unmounts it and takes the
        // words they had already typed with it.
        if (cancelled) return
        setMaterial(null)
        setDraftFailed(String(error).replace(/^Error:\s*/, ''))
      })
      .finally(() => setDrafting(false))
    return () => {
      cancelled = true
    }
    // `drafting` IS DELIBERATELY NOT A DEPENDENCY, though the guard above
    // reads it. This effect sets `drafting` to `true` on its own first line,
    // and if `drafting` were listed, THAT state change would re-fire the
    // effect on the very next render -- which runs this invocation's cleanup
    // (`cancelled = true`) before the network has had any chance to answer.
    // Two things then follow, both confirmed by instrumenting the effect and
    // watching the actual sequence rather than assuming it: every outcome of
    // this request lands with `cancelled` already true, so a failure while
    // the DM is still sitting in draft mode shows nothing at all -- and once
    // that settled request's unguarded `.finally` resets `drafting` back to
    // `false`, THAT change re-passes the guard and fires a brand new request
    // nobody asked for, which repeats the same cycle on its own failure. Left
    // in, this is not a smaller version of the bug being fixed here -- it is
    // an uncapped retry loop against a real model endpoint, silent to the DM
    // for as long as every attempt keeps failing.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [material, draft, section, campaign])

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
        <p className="mx-auto max-w-3xl px-6 py-12 text-ui text-ink-dim">
          Could not open that section.
        </p>
      )}

      {section && (
        <div className="mx-auto grid max-w-5xl gap-8 px-6 py-12 lg:grid-cols-[42rem_1fr]">
        <article>
          {/* WHOSE WORDS THESE ARE, before the words -- in all three channels
              the grammar requires: the glyph, the word, and the hue. */}
          <p className="label">
            {yours ? (
              <>
                <span className={SOURCE.yours}>
                  {SOURCE_GLYPH.yours} {SOURCE_WORD.yours}
                </span>{' '}
                <span className="text-ink-faint">written for this campaign</span>
              </>
            ) : (
              <>
                <span className={SOURCE.book}>
                  {SOURCE_GLYPH.book} {SOURCE_WORD.book}
                </span>{' '}
                <span className="text-ink-faint">{section.chapter}</span>
              </>
            )}
          </p>
          <h1 className="mt-2 text-title font-medium text-ink">
            {section.heading}
          </h1>

          <div className="mt-8 flex flex-col gap-6">
            {readingBlocks(section.text, section.heading).map((block, i) =>
              block.kind === 'aloud' ? (
                /* THE PASSAGE A DM READS OUT WORD FOR WORD, which is the most
                   literally "the book's" text on the screen -- so it takes the
                   book's grammar in full: the edge, the glyph, the word, and
                   the one type step reserved for it. It had been rendering
                   with a literal `>` at the head of every line. */
                <blockquote key={i} className={`py-2 pl-4 ${SOURCE_EDGE.book}`}>
                  <p className={`label ${SOURCE.book}`}>
                    {SOURCE_GLYPH.book} read aloud
                  </p>
                  <p className="mt-2 whitespace-pre-wrap font-serif text-aloud text-ink">
                    <Named
                      text={withEmphasis(block.text)}
                      mentions={section.mentions}
                      onOpen={openEntity}
                    />
                  </p>
                </blockquote>
              ) : block.kind === 'illustration' ? (
                <figure key={i} className="my-4 plate">
                  {/* THE PLATE SINKS INTO THE TABLE rather than sitting in a
                      box: it bleeds to the column, and its edge fades into the
                      ground so the caption can sit on the image itself. A
                      frame around a printed illustration is a second frame. */}
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={block.src}
                    alt={block.alt}
                    loading="lazy"
                    className="block w-full"
                  />
                  <span className="plate-scrim" />
                  <figcaption
                    className={`absolute bottom-0 left-0 px-3 py-2 label ${SOURCE.book}`}
                  >
                    {SOURCE_GLYPH.book} the book&rsquo;s art
                  </figcaption>
                </figure>
              ) : (
                <p
                  key={i}
                  className={`whitespace-pre-wrap ${
                    yours ? 'text-body text-ink' : 'font-serif text-canon text-ink'
                  }`}
                >
                  <Named
                    text={withEmphasis(block.text)}
                    mentions={section.mentions}
                    onOpen={openEntity}
                  />
                </p>
              ),
            )}
          </div>

          {kept && <StoredBlock title={kept.title} body={kept.body} />}
          {!kept && material === 'write' && (
            <WriteBlock
              campaign={campaign}
              anchor={section.section_id}
              onStored={(title, body) => {
                setKept({ title, body })
                setMaterial(null)
              }}
              onDiscard={() => setMaterial(null)}
            />
          )}
          {!kept && material === 'draft' && drafting && (
            <p className="my-6 text-ui text-ink-dim">drafting…</p>
          )}
          {!kept && draftFailed && <p className="my-6 text-label text-ink-dim">⚠ {draftFailed}</p>}
          {!kept && material === 'draft' && draft && (
            <DraftCard
              campaign={campaign}
              reply={draft}
              anchor={section.section_id}
              onStored={() => {
                setKept({ title: draft.title, body: draft.body })
                setMaterial(null)
                setDraft(null)
              }}
              onDiscard={() => {
                setDraft(null)
                setMaterial(null)
              }}
            />
          )}
        </article>

        {/* THE RAIL IS WHERE THE APPARATUS LIVES. The reveal control sat
            between the title and the first sentence, so a DM's decision
            interrupted the reading every single time -- and this page exists
            to be read aloud. Beside the column it is one glance away and never
            in the way.

            IT IS THE OTHER HALF OF THE GRANT, and the half the whole design
            rests on: telling the table an NPC exists is not letting them read
            what the book says about him. */}
        {/* NOT `hidden lg:block`: on a laptop-half-width window that removed
            the DM's only way to show the scene to the table. Below `lg` the
            grid collapses and the rail simply follows the prose. */}
        <aside>
          <Reveal
            campaign={campaign}
            target={section.section_id}
            name={section.heading}
          />
          <MaterialRail
            campaign={campaign}
            open={material}
            onOpen={(action) => {
              // A new choice clears the last one's complaint. Without this the
              // rail returns to rest after a failed draft and the error outlives
              // it, sitting beside whatever the DM opens next.
              setDraftFailed('')
              setMaterial(action)
            }}
          />
        </aside>
        </div>
      )}

      {popout && (
        <div
          className="fixed inset-0 z-20 flex items-start justify-center bg-ink/40 p-6 pt-20"
          onClick={() => setPopout(null)}
        >
          <div
            // A POPOVER IS THE OVERLAY STEP OF THE GROUND LADDER, lit from
            // above. A drop shadow is invisible on a near-black ground, which is
            // why elevation here is lightness and why shadows are banned.
            className="max-h-[70vh] w-full max-w-md overflow-y-auto rounded-md bg-overlay p-5 lit"
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

/** Turn the marked runs into real emphasis. */
function emphasise(piece: string, key: number) {
  return (
    <span key={key}>
      {piece.split(EMPHASIS_MARK).map((part, n) =>
        n % 2 === 1 ? <em key={n}>{part}</em> : part,
      )}
    </span>
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
        // THE BOOK'S ITALICS, restored. `withEmphasis` marked them with an
        // invisible separator so this pass can turn them into <em> without a
        // second regex fighting the mention split.
        if (!mention) return piece.includes(EMPHASIS_MARK) ? emphasise(piece, i) : piece
        return (
          <button
            key={i}
            onClick={() => onOpen(mention.entity_id)}
            // A GLYPH BEFORE EVERY NAME WOULD WRECK THE READING, so the
            // second channel is the underline itself: the DM's own insertions
            // are dashed, the book's own names dotted. Different in kind, and
            // legible with the colour removed.
            className={`underline underline-offset-2 hover:decoration-solid ${
              mention.plane === 'campaign'
                ? `decoration-dashed ${SOURCE.yours}`
                : 'decoration-dotted text-ink'
            }`}
          >
            {piece}
          </button>
        )
      })}
    </>
  )
}
