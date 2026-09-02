'use client'

import Link from 'next/link'

import type { EntityRead } from '@/lib/api'
import { Portraits } from '@/components/product/Portraits'
import { Reveal } from '@/components/product/Reveal'
import { useRuns } from '@/lib/role'
import { SOURCE } from '@/lib/palette'

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
            className={`font-medium text-neutral-100 ${
              compact ? 'text-lg' : 'text-2xl'
            }`}
          >
            {entity.name}
          </h1>

          <p className="mt-1 text-xs">
            {yours ? (
              <>
                <span className={SOURCE.yours}>
                  {runs === false ? 'Your DM wrote this.' : 'Yours.'}
                </span>{' '}
                <span className="text-neutral-500">
                  {runs === false
                    ? 'It is not in the book.'
                    : 'Written for this campaign.'}
                </span>
              </>
            ) : unnamed ? (
              <>
                <span className={SOURCE.invented}>Not named in the book.</span>{' '}
                <span className="text-neutral-500">Came from extraction.</span>
              </>
            ) : (
              <>
                <span className={SOURCE.book}>The book.</span>{' '}
                <span className="text-neutral-500">
                  Named in {quotes.length} section{quotes.length === 1 ? '' : 's'}.
                </span>
              </>
            )}
          </p>

          <p className="mt-1.5 text-xs uppercase tracking-wide text-neutral-600">
            {entity.labels.join(' · ').toLowerCase() || 'unclassified'}
          </p>

          {entity.role && (
            <p className="mt-2 text-sm text-neutral-400">{entity.role}</p>
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
        <p className="mt-4 rounded border border-rose-900/60 bg-rose-950/30 p-3 text-xs leading-relaxed text-rose-200/70">
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
          <h2 className="text-[11px] uppercase tracking-widest text-neutral-600">
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
                    className={`text-[11px] ${
                      where.plane === 'campaign' ? SOURCE.yours : 'text-neutral-500'
                    }`}
                  >
                    {where.heading || where.section_id}
                  </span>
                  <p className="mt-0.5 text-sm leading-relaxed text-neutral-300">
                    {where.says[0]}
                  </p>
                </button>
              </li>
            ))}
          </ul>
          {compact && quotes.length > shown.length && (
            <p className="mt-2 text-xs text-neutral-600">
              and {quotes.length - shown.length} more
            </p>
          )}
        </section>
      )}

      {/* THE DM'S OWN NOTE, and the server does not send it to a player at
          all -- this is the second lock on the same door. */}
      {entity.invented.length > 0 && !compact && runs === true && (
        <section className="mt-6">
          <h2 className="text-[11px] uppercase tracking-widest text-neutral-600">
            Invented for this campaign
          </h2>
          <ul className={`mt-2 flex flex-col gap-1 text-sm ${SOURCE.invented}`}>
            {entity.invented.map((line, i) => (
              <li key={i}>{line}</li>
            ))}
          </ul>
        </section>
      )}

      {connections.length > 0 && (
        <section className="mt-6">
          <h2 className="text-[11px] uppercase tracking-widest text-neutral-600">
            Connections
          </h2>
          <ul className="mt-2 flex flex-col gap-1">
            {connections.map((c, i) => (
              <li key={i} className="flex items-baseline gap-2 text-sm">
                {/* A GUESS SAYS SO. The extractor is wrong about roughly a
                    third of these, and a profile that rendered them like
                    derived facts would be the tidiest place in the product to
                    launder one. */}
                <span
                  className={
                    c.status === 'accepted' ? 'text-neutral-500' : 'text-neutral-700'
                  }
                >
                  {c.dir === 'out' ? '→' : '←'}
                </span>
                <span className="text-xs uppercase tracking-wide text-neutral-600">
                  {c.rel.toLowerCase().replace(/_/g, ' ')}
                </span>
                <Link
                  href={`/c/${campaign}/e/${encodeURIComponent(c.other_id)}`}
                  className={
                    c.other_plane === 'campaign'
                      ? `${SOURCE.yours} hover:underline`
                      : 'text-neutral-300 hover:underline'
                  }
                >
                  {c.other}
                </Link>
                {c.status !== 'accepted' && (
                  <span className="text-[11px] text-neutral-700">guessed</span>
                )}
              </li>
            ))}
          </ul>
          {compact && entity.connections.length > connections.length && (
            <p className="mt-2 text-xs text-neutral-600">
              and {entity.connections.length - connections.length} more
            </p>
          )}
        </section>
      )}

      {compact && (
        <Link
          href={`/c/${campaign}/e/${encodeURIComponent(entity.entity_id)}`}
          className="mt-5 inline-block text-xs text-neutral-400 underline hover:text-neutral-200"
        >
          Open profile
        </Link>
      )}
    </article>
  )
}
