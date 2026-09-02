'use client'

import Link from 'next/link'

import type { EntityRead } from '@/lib/api'
import { Portraits } from '@/components/product/Portraits'
import { Reveal } from '@/components/product/Reveal'
import { useRuns } from '@/lib/role'
import { SOURCE, SOURCE_GLYPH, SOURCE_WORD } from '@/lib/palette'

/**
 * An entity, as a DM reads it.
 *
 * IT LEADS WITH THE BOOK'S OWN SENTENCES, NOT A BIOGRAPHY. D&D Beyond opens a
 * monster page with flavour prose; this cannot and should not. An entity here
 * holds no biography field -- it is a name, a role, and the sentences that name
 * it -- so a summary paragraph at the top would have to be composed by a model,
 * which is invented prose wearing the entity's name as a headline, on the one
 * screen whose job is telling those apart. Mid-session the quotes are the more
 * useful artifact anyway: they are what a DM reads aloud.
 *
 * WHOSE WORD IT IS COMES FIRST, before any content, which is the rule the
 * section reader already follows. A reader who learns the provenance after the
 * prose has already read the prose.
 *
 * ONE LAYOUT FOR EVERY KIND. An NPC, a place, an item and a faction are the
 * same shape in this graph -- five templates would be designing for structure
 * the data does not have, and each would mostly render quotes.
 */
export function EntityProfile({
  entity,
  campaign,
  compact = false,
  onOpenSection,
}: {
  entity: EntityRead
  campaign: string
  /** The popout: the same identity, trimmed to what answers "who is this
   *  again?" in five seconds. It carries no curation controls at all -- their
   *  absence is the design telling a DM not to start gardening while their
   *  players wait. */
  compact?: boolean
  onOpenSection?: (sectionId: string) => void
}) {
  // THE PROVENANCE LINE IS ADDRESSED TO SOMEBODY. "Yours. Written for this
  // campaign." is the DM reading their own material; a player reading the same
  // words is being told the campaign belongs to them, which is both wrong and
  // confusing about the one thing this line exists to say.
  const runs = useRuns(campaign)
  const yours = entity.plane === 'campaign'
  const unnamed = !yours && !entity.named_by_book
  const quotes = entity.named_in.filter((n) => n.says.length > 0)
  const shown = compact ? quotes.slice(0, 3) : quotes
  const connections = compact ? entity.connections.slice(0, 5) : entity.connections

  return (
    <article className={compact ? '' : 'mx-auto max-w-3xl px-6 py-10'}>
      <header className="flex gap-4">
        <Portraits
          entityId={entity.entity_id}
          campaign={campaign}
          labels={entity.labels}
          compact={compact}
        />

        <div className="min-w-0 flex-1">
          <h1
            className={`font-medium text-ink ${
              compact ? 'text-title' : 'text-title'
            }`}
          >
            {entity.name}
          </h1>

          {/* THE GLYPH IS MANDATORY. A hue with no second channel is a bug,
              not a style choice -- it is the whole of the promise for a reader
              who cannot use colour. */}
          <p className="mt-1 flex flex-wrap items-baseline gap-x-2 text-label uppercase tracking-widest">
            {yours ? (
              <>
                <span className={SOURCE.yours}>
                  {SOURCE_GLYPH.yours} {runs === false ? 'YOUR DM WROTE THIS' : SOURCE_WORD.yours}
                </span>
                <span className="text-ink-faint">
                  {runs === false ? 'not in the book' : 'written for this campaign'}
                </span>
              </>
            ) : unnamed ? (
              <>
                <span className={SOURCE.invented}>
                  {SOURCE_GLYPH.invented} {SOURCE_WORD.invented}
                </span>
                <span className="text-ink-faint">not named in the book</span>
              </>
            ) : (
              <>
                <span className={SOURCE.book}>
                  {SOURCE_GLYPH.book} {SOURCE_WORD.book}
                </span>
                <span className="text-ink-faint">
                  named in {quotes.length} section{quotes.length === 1 ? '' : 's'}
                </span>
              </>
            )}
          </p>

          <p className="mt-2 text-meta text-ink-faint">
            {entity.labels.join(' · ').toLowerCase() || 'unclassified'}
          </p>

          {entity.role && (
            <p className="mt-2 text-ui text-ink-dim">{entity.role}</p>
          )}

          {/* WHAT THE TABLE KNOWS, decided where the DM is already reading.
              Never on the popout: that exists to answer "who is this again?"
              in five seconds while five people wait, and a visibility decision
              is not a five-second question. */}
          {!compact && (
            <div className="mt-3">
              <Reveal
                campaign={campaign}
                target={entity.entity_id}
                name={entity.name}
              />
            </div>
          )}
        </div>
      </header>

      {unnamed && !compact && (
        <p className="mt-4 rounded-md border border-rose-900/60 bg-rose-950/30 p-3 text-meta leading-relaxed text-rose-200/70">
          No section of the book says this name. It came from the extraction, so
          what it connects to may well be right &mdash; but do not quote it as
          the book&rsquo;s wording at the table.
        </p>
      )}

      {/* WHAT IS ESTABLISHED, quoted exactly. The book's sections first: the
          API already sorts canon before campaign, and a DM checking what is
          settled wants the published word before their own. */}
      {shown.length > 0 && (
        <section className="mt-6">
          <h2 className="text-label uppercase tracking-widest text-ink-faint">
            Established
          </h2>
          <ul className="mt-2 flex flex-col gap-3">
            {shown.map((where) => (
              <li key={where.section_id}>
                <button
                  onClick={() => onOpenSection?.(where.section_id)}
                  disabled={!onOpenSection}
                  className="block w-full text-left disabled:cursor-default"
                >
                  <span
                    className={`text-label ${
                      where.plane === 'campaign' ? SOURCE.yours : 'text-ink-dim'
                    }`}
                  >
                    {where.heading || where.section_id}
                  </span>
                  {/* THE BOOK'S SENTENCE, IN THE BOOK'S FACE. This is the
                      one thing on the profile a DM reads aloud, and it was
                      set in the app's own 13px UI face -- indistinguishable
                      from a tooltip. */}
                  <p
                    className={`mt-1 ${
                      where.plane === 'campaign'
                        ? 'text-body text-ink-dim'
                        : 'font-serif text-canon text-ink'
                    }`}
                  >
                    {where.says[0]}
                  </p>
                </button>
              </li>
            ))}
          </ul>
          {compact && quotes.length > shown.length && (
            <p className="mt-2 text-meta text-ink-faint">
              and {quotes.length - shown.length} more
            </p>
          )}
        </section>
      )}

      {/* THE DM'S OWN NOTE, and the server does not send it to a player at
          all -- this is the second lock on the same door. */}
      {entity.invented.length > 0 && !compact && runs === true && (
        <section className="mt-6">
          <h2 className="text-label uppercase tracking-widest text-ink-faint">
            Invented for this campaign
          </h2>
          <ul className={`mt-2 flex flex-col gap-1 text-ui ${SOURCE.invented}`}>
            {entity.invented.map((line, i) => (
              <li key={i}>{line}</li>
            ))}
          </ul>
        </section>
      )}

      {connections.length > 0 && (
        <section className="mt-6">
          <h2 className="text-label uppercase tracking-widest text-ink-faint">
            Connections
          </h2>
          <ul className="mt-2 flex flex-col gap-1">
            {connections.map((c, i) => (
              <li key={i} className="flex items-baseline gap-2 text-ui">
                {/* A GUESS SAYS SO. The extractor is wrong about roughly a
                    third of these, and a profile that rendered them like
                    derived facts would be the tidiest place in the product to
                    launder one. */}
                <span
                  className={
                    c.status === 'accepted' ? 'text-ink-dim' : 'text-ink-faint'
                  }
                >
                  {c.dir === 'out' ? '→' : '←'}
                </span>
                <span className="text-meta uppercase tracking-wide text-ink-faint">
                  {c.rel.toLowerCase().replace(/_/g, ' ')}
                </span>
                <Link
                  href={`/c/${campaign}/e/${encodeURIComponent(c.other_id)}`}
                  className={
                    c.other_plane === 'campaign'
                      ? `${SOURCE.yours} hover:underline`
                      : 'text-ink-dim hover:underline'
                  }
                >
                  {c.other}
                </Link>
                {c.status !== 'accepted' && (
                  <span className="text-label text-ink-faint">guessed</span>
                )}
              </li>
            ))}
          </ul>
          {compact && entity.connections.length > connections.length && (
            <p className="mt-2 text-meta text-ink-faint">
              and {entity.connections.length - connections.length} more
            </p>
          )}
        </section>
      )}

      {compact && (
        <Link
          href={`/c/${campaign}/e/${encodeURIComponent(entity.entity_id)}`}
          className="mt-5 inline-block text-meta text-ink-dim underline hover:text-ink"
        >
          Open profile
        </Link>
      )}
    </article>
  )
}
