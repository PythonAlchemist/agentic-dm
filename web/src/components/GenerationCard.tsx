'use client'

import { useCallback, useState } from 'react'
import type { ClusterPlan, GeneratedReply, OrderRow } from '@/lib/api'
import { labAPI } from '@/lib/api'
import { ClusterReview } from './ClusterReview'

/**
 * One draft, with its three sources kept apart, and the button that is the gate.
 *
 * THE SPLIT IS SHOWN, NOT SUMMARISED. A DM acting on this at a table cannot
 * afford to mistake an invented detail for the book's text, so what came from
 * canon, what came from the conversation and what the model supplied are three
 * lists a person reads before approving -- never one blended paragraph.
 *
 * NOTHING HERE IS IN THE GRAPH until Store is pressed. That is the whole shape
 * of the flow: a model proposes, a human reads, one step applies.
 */
//: The kinds that CONTAIN things, and so have a cast worth asking about. An
//: NPC or a monster IS one thing; asking it what it contains is a question
//: with no answer, so the control is not offered. Mirrors `CLUSTER_KINDS` in
//: `dm_agent`, which decides the same thing on the way out.
const CAN_CONTAIN = new Set(['quest', 'scene', 'encounter'])

//: The kinds that ARE a position in the running order rather than a write-up
//: about something. A quest is not one: it spans the adventure rather than
//: happening at a point in it.
const PLAYS_SOMEWHERE = new Set(['scene', 'encounter'])


export function GenerationCard({
  card,
  campaign,
  order,
  onStored,
  onDiscard,
  onRevise,
  book,
  busy: revising,
}: {
  card: GeneratedReply
  campaign: string | null
  order: OrderRow[]
  /** Which book the session reads, for the retrieval that grounds a
   *  cast asked for after the fact. */
  book: string
  onStored?: () => void
  /** Throw the draft away. Nothing was written, so this is the whole of it --
   *  but without it the only exit from a draft you do not want is to scroll
   *  past it forever. */
  onDiscard?: () => void
  /** Ask for the same thing again with one change. Absent where revision has
   *  nowhere to put the answer -- the chat card is a message in a transcript,
   *  not a pane that can be replaced. */
  onRevise?: (note: string) => void
  busy?: boolean
}) {
  const [body, setBody] = useState(card.body)
  // AN EXPANSION STARTS UNPLACED, matching what `expand` does on the server:
  // a character's write-up is not an episode, and defaulting it into the
  // running order would tell the table to play "The Red Barge" as a scene. A
  // DM can still place one deliberately.
  //
  // UNLESS IT IS AN EPISODE. A scene or an encounter IS a position -- that is
  // what distinguishes it from a write-up -- so fleshing one out and leaving
  // it nowhere is the one case where the default is wrong. Reachable since
  // those two became element kinds and a quest could mint them as stubs.
  const [anchor, setAnchor] = useState(
    card.expands && !PLAYS_SOMEWHERE.has(card.kind) ? '' : (card.anchor ?? ''),
  )
  const [busy, setBusy] = useState(false)
  const [stored, setStored] = useState('')
  const [failed, setFailed] = useState('')
  const [plan, setPlan] = useState<ClusterPlan | null>(null)
  const [clusterBody, setClusterBody] = useState<Record<string, unknown> | null>(null)

  // STABLE ACROSS RENDERS, and the effect that calls it lists it as a
  // dependency. As an inline arrow this was a new function every render, so:
  // plan arrives -> setPlan/setClusterBody -> re-render -> new identity ->
  // ClusterReview's effect sees changed deps -> plans again, for as long as the
  // card is on screen. Each turn is a POST to `/homebrew/plan-cluster`.
  // `ClusterReview` carries a comment memoising `card.elements` against this
  // exact loop; the hole came back one prop over.
  const onClusterPlanned = useCallback(
    (next: ClusterPlan | null, body: Record<string, unknown>) => {
      setPlan(next)
      setClusterBody(body)
    },
    [],
  )
  //: A cast asked for AFTER the draft was written, when the pass that runs at
  //  write time found nothing. Held beside the card rather than in it: the
  //  card is what the model returned and stays that.
  const [found, setFound] = useState<GeneratedReply | null>(null)
  const [finding, setFinding] = useState(false)

  const shown = found ?? card

  const findCast = async () => {
    if (finding) return
    setFinding(true)
    setFailed('')
    try {
      // THE BODY AS IT NOW STANDS, not as it was generated. By the time a DM
      // notices the cast is missing they have usually edited the prose, and
      // annotating what the model first wrote would read the wrong scene.
      const cast = await labAPI.findElements(
        body, shown.subject, shown.kind, book, campaign, card.model ?? '',
      )
      setFound({ ...card, elements: cast.elements, edges: cast.edges })
      if (!cast.elements?.length) {
        setFailed('Nothing in it that the graph would mint as its own thing.')
      }
    } catch (error) {
      setFailed(error instanceof Error ? error.message : String(error))
    } finally {
      setFinding(false)
    }
  }
  const isCluster = (shown.elements?.length ?? 0) > 0
  // A draft ABOUT something that already exists takes the expand path. The
  // minting path would raise `AlreadyStored` -- correctly, since a second
  // Captain Saltmarrow is not what "tell me more about him" means.
  const isExpansion = Boolean(card.expands)
  // A REWRITE REPLACES. `write` would mint a second entity of the same name
  // and `AlreadyStored` would refuse it -- correctly, since two sea battles is
  // not what "build this out" means. So storing a revision is an edit of the
  // section it revises, which is also why it needs no anchor: it already has
  // the position of the thing it is replacing.
  const isRevision = Boolean(card.revises)
  // A collision is a question only a person can answer, so it BLOCKS the
  // write rather than resolving itself in either direction.
  const blocked = isCluster && plan !== null && !plan.storable

  const edited = body.trim() !== card.body.trim()
  //: What to change, while a DM is typing it. A revision keeps the shape and
  //  changes one thing; editing the prose by hand changes the words and keeps
  //  the citations, which is a different move for a different moment.
  const [note, setNote] = useState('')

  const store = async () => {
    if (!campaign || busy) return
    setBusy(true)
    setFailed('')
    try {
      // A cluster posts the payload the REVIEW built, with the edited body
      // laid over it -- so what is written is what was planned and shown, not
      // a second guess assembled here.
      const common = {
        campaign,
        kind: card.kind,
        title: card.title,
        body,
        generated_body: card.body,
        from_canon: card.from_canon,
        from_yours: card.from_yours ?? [],
        invented: card.invented,
        from_context: card.from_context ?? [],
        sources: card.sources,
        anchor: anchor || null,
        model: card.model,
      }
      const result = isRevision
        ? await labAPI
            .editSection(campaign, card.revises!, body)
            .then((r) => ({ entity_id: r.section_id }))
        : isExpansion
        ? await labAPI.expand({ ...common, entity_id: card.expands })
        : isCluster
        ? await labAPI.storeCluster({ ...(clusterBody ?? {}), body })
        : await labAPI.store({
            campaign,
            kind: card.kind,
            title: card.title,
            body,
            generated_body: card.body,
            from_canon: card.from_canon,
        from_yours: card.from_yours ?? [],
            invented: card.invented,
            from_context: card.from_context ?? [],
            sources: card.sources,
            anchor: anchor || null,
            model: card.model,
          })
      setStored(result.entity_id)
      // A NEW NODE IS READ BACK the same way an edited one is: the graph
      // should hold what the prose says, not only what the manifest declared.
      const section = (result as { section_id?: string }).section_id
      if (campaign && section) {
        try {
          await labAPI.deriveEdges(campaign, section)
        } catch {
          /* stored is stored; the guesses can be re-derived later */
        }
      }
      onStored?.()
    } catch (error) {
      setFailed(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(false)
    }
  }

  if (card.error) {
    return (
      <div className="rounded-md border border-line bg-surface p-3 text-ui">
        <p className="text-ink-dim">
          The {card.kind} draft failed: {card.error}
        </p>
      </div>
    )
  }

  return (
    <div className="rounded-md border border-line bg-surface/[0.03] p-3">
      <div className="mb-2 flex items-baseline justify-between gap-3">
        <h3 className="text-ui font-medium text-yours">{card.title}</h3>
        <span className="shrink-0 text-meta uppercase tracking-wide text-ink-faint">
          draft {card.kind}
        </span>
      </div>

      <textarea
        value={body}
        onChange={(e) => setBody(e.target.value)}
        rows={7}
        className="w-full rounded-md border border-line bg-surface/60 p-2 text-ui leading-relaxed focus:border-line"
      />
      {onRevise && (
        <div className="mt-2 flex items-center gap-2">
          <input
            value={note}
            onChange={(event) => setNote(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && note.trim() && !revising) {
                onRevise(note.trim())
                setNote('')
              }
            }}
            placeholder="Same again, but… (make her older, lose the storm)"
            className="min-w-0 flex-1 rounded-md border border-line bg-surface/60 px-2 py-1 text-meta focus:border-line"
          />
          <button
            onClick={() => {
              if (!note.trim() || revising) return
              onRevise(note.trim())
              setNote('')
            }}
            disabled={!note.trim() || revising}
            className="shrink-0 rounded-md border border-line px-2 py-1 text-meta text-ink-dim hover:text-yours disabled:opacity-40"
          >
            {revising ? 'writing…' : 'again'}
          </button>
        </div>
      )}

      {/* Said plainly, because nothing re-checks a body after a person edits
          it -- the citations below still claim what the model claimed. */}
      {edited && (
        <p className="mt-1 text-meta text-ink-dim">
          Edited. The citations below were made about the original text and are
          not re-checked.
        </p>
      )}

      <div className="mt-3 space-y-2 text-meta">
        {/* FOUR SOURCES, FOUR HUES, AND NO TWO OF THEM ADJACENT. `From your own
            material` and `Invented` were amber-200 and amber-300 -- one shade
            step apart, in the one product whose entire promise is that a DM can
            tell those two apart at a glance. Sourced-to-something-you-wrote and
            the-model-made-it-up are the pair MOST worth confusing and were the
            pair hardest to tell apart.

            Green is the book, amber is yours, blue is the table, rose is
            invention. Rose because it is the only one with nothing behind it:
            every other row can be followed somewhere. */}
        <Provenance
          label="From the book"
          hint="Each cites a passage. A pointer for you to check, not a proof."
          items={card.from_canon.map((c) => `${c.claim} ${c.cite}`)}
          tone="text-book"
        />
        {(card.from_yours?.length ?? 0) > 0 && (
          <Provenance
            label="From your own material"
            hint="Cited, but to a section you wrote — not to the book."
            items={(card.from_yours ?? []).map((c) => `${c.claim} ${c.cite}`)}
            tone="text-yours"
          />
        )}
        {(card.from_context?.length ?? 0) > 0 && (
          <Provenance
            label="From this conversation"
            hint="Taken from what you said at the table, not from the book."
            items={card.from_context ?? []}
            tone="text-table"
          />
        )}
        <Provenance
          label="Invented"
          hint="The model supplied these. Nothing in the book says them."
          items={card.invented}
          tone="text-invented"
        />
      </div>

      {campaign && isCluster && (
        <ClusterReview
          card={shown}
          campaign={campaign}
          anchor={anchor}
          onPlan={onClusterPlanned}
        />
      )}

      {campaign && isRevision && (
        <div className="mt-3 border-t border-line pt-3">
          <div className="flex items-center gap-3">
            <button
              onClick={store}
              disabled={busy || !!stored}
              className="rounded-md bg-chrome px-3 py-1.5 text-meta font-medium text-ground transition-colors hover:bg-white disabled:opacity-40"
            >
              {stored ? 'Replaced' : busy ? 'Replacing…' : 'Replace what you have'}
            </button>
            <span className="text-meta text-ink-dim">
              Rewrites the section in place. It keeps its position, its
              citations and everything pointing at it.
            </span>
          </div>
          {failed && <p className="mt-2 text-meta text-ink-dim">{failed}</p>}
        </div>
      )}

      {campaign && !isRevision ? (
        <div className="mt-3 border-t border-line pt-3">
          <label className="block text-meta text-ink-dim">
            {card.expands
              ? 'Where it goes in your running order (a write-up usually goes nowhere)'
              : 'Where it goes in your running order'}
            {/* CHIPS FOR THE SHORTLIST, because the answer is almost always
                one of these and a <select> hides them behind a click. These
                are the passages the draft was written against; `suggest_anchor`
                picks one of them and picks it by score, which answers "which
                section does the subject name most" rather than "which beat is
                this" -- so the DM's eye needs to reach the alternatives, not
                just the default. The full 546 stay in the select below for the
                times the right answer is somewhere else entirely. */}
            {writtenAgainst(card, order).length > 0 && (
              <div className="mt-1 flex flex-wrap gap-1">
                {writtenAgainst(card, order).map((row) => (
                  <button
                    key={`chip-${row.section_id}`}
                    onClick={() => setAnchor(row.section_id)}
                    className={`rounded-full border px-2 py-0.5 text-label transition-colors ${
                      anchor === row.section_id
                        ? 'border-line bg-overlay text-ink'
                        : 'border-line text-ink-dim hover:border-line hover:text-ink-dim'
                    }`}
                  >
                    {row.heading}
                  </button>
                ))}
              </div>
            )}
            <select
              value={anchor}
              onChange={(e) => setAnchor(e.target.value)}
              className="mt-1 w-full rounded-md border border-line bg-surface px-2 py-1.5 text-meta text-ink"
            >
              <option value="">Nowhere in particular</option>
              {/* THE PASSAGES THIS WAS WRITTEN AGAINST, first and by
                  themselves. `suggest_anchor` picks one of these and picks it
                  by score, which answers "which section does the subject name
                  most" rather than "which beat is this". For a sea battle on
                  the voyage that is `Revel's End` at seven mentions, not `Trek
                  to the Prison` at two -- the destination rather than the
                  journey, so the scene lands after they have arrived.
                  Nothing available reorders those scores into the right
                  answer: "voyage" matches no heading. So the shortlist is
                  shown instead of a better guess being faked. These eight are
                  where the scene plausibly goes, and the DM knows which beat
                  they mean. */}
              {writtenAgainst(card, order).length > 0 && (
                <optgroup label="○ Written against">
                  {writtenAgainst(card, order).map((row) => (
                    <option key={`src-${row.section_id}`} value={row.section_id}>
                      after {row.heading}
                    </option>
                  ))}
                </optgroup>
              )}
              {/* GROUPED BY ADVENTURE, WITH THIS SCENE'S OWN FIRST. A flat
                  list offered a museum room from an unrelated heist as
                  readily as the voyage the scene is about -- 546 options
                  across thirteen books that share no continuity. */}
              {groupByChapter(order, card.relevant_chapters ?? []).map((group) => (
                <optgroup
                  key={group.chapter}
                  label={`${group.relevant ? '● ' : ''}${prettyChapter(group.chapter)}`}
                >
                  {group.rows.map((row) => (
                    <option key={row.section_id} value={row.section_id}>
                      after {row.heading}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
            {card.anchor && anchor === card.anchor && (
              <span className="mt-1 block text-label text-ink-dim">
                Suggested from the passages this draft was written against.
              </span>
            )}
          </label>

          <div className="mt-2 flex items-center gap-3">
            <button
              onClick={store}
              disabled={busy || !!stored || blocked}
              className="rounded-md bg-chrome px-3 py-1.5 text-meta font-medium text-ground transition-colors hover:bg-white disabled:opacity-40"
            >
              {stored ? 'Stored' : busy ? 'Storing…' : 'Store in my campaign'}
            </button>
            {stored && (
              <span className="text-meta text-ink-dim">
                Written as <code className="text-ink-dim">{stored}</code>
              </span>
            )}
            {/* Named, not merely disabled: a greyed button with no reason
                beside it is a dead end rather than a decision. */}
            {blocked && (
              <span className="text-meta text-ink-dim">
                Resolve the name{plan!.collisions.length === 1 ? '' : 's'} above first.
              </span>
            )}

            {/* ASK THE DRAFT WHAT IS IN IT. A quest, scene or encounter is
                annotated as it is written, and that pass is element-first --
                it reads prose looking for things to MINT and goes quiet
                exactly when the scene is built out of people who already
                exist. When it finds nothing there was no way to ask again,
                and the DM got one entity where they meant a cast. */}
            {!stored && !isCluster && CAN_CONTAIN.has(shown.kind) && (
              <button
                onClick={findCast}
                disabled={finding || busy}
                className="text-meta text-ink-dim underline-offset-2 transition-colors hover:text-ink hover:underline disabled:opacity-40"
              >
                {finding ? 'reading…' : 'find what it contains'}
              </button>
            )}

            {/* NOTHING WAS WRITTEN, so this is the whole of discarding. It is
                here because without it the only exit from a draft you do not
                want is to scroll past it for the rest of the session. */}
            {!stored && onDiscard && (
              <button
                onClick={onDiscard}
                className="ml-auto text-meta text-ink-faint transition-colors hover:text-invented"
              >
                discard
              </button>
            )}
          </div>
          {failed && <p className="mt-2 text-meta text-ink-dim">{failed}</p>}
        </div>
      ) : campaign ? null : (
        <p className="mt-3 border-t border-line pt-3 text-meta text-ink-dim">
          Pick a table on the left to store this. Canon-only sessions have
          nowhere to put it.
        </p>
      )}
    </div>
  )
}

/**
 * The sections this generation actually cited, as anchor options.
 *
 * Filtered against the running order rather than rendered from `sources`
 * directly: an anchor has to BE in the DM's chain to be a place to insert
 * after, and a citation can point at a section they have skipped.
 */
function writtenAgainst(card: GeneratedReply, order: OrderRow[]) {
  const inOrder = new Map(
    order.filter((r) => r.origin === 'canon' && !r.skipped).map((r) => [r.section_id, r]),
  )
  const seen = new Set<string>()
  return (card.sources ?? [])
    .filter((s) => s.type === 'canon' && !seen.has(s.source) && seen.add(s.source))
    .map((s) => inOrder.get(s.source))
    .filter((row): row is OrderRow => Boolean(row))
}

/**
 * The running order as chapters, with the ones this generation is about first.
 *
 * `relevant` comes from the generation's OWN retrieval -- the chapters its
 * passages came from, heaviest first -- so the picker leads with the adventure
 * the scene belongs to rather than with whatever the book prints first.
 */
function groupByChapter(order: OrderRow[], relevant: string[]) {
  const groups = new Map<string, OrderRow[]>()
  for (const row of order) {
    if (row.origin !== 'canon' || row.skipped) continue
    const chapter = row.chapter || 'elsewhere'
    if (!groups.has(chapter)) groups.set(chapter, [])
    groups.get(chapter)!.push(row)
  }
  const rank = new Map(relevant.map((chapter, index) => [chapter, index]))
  return [...groups.entries()]
    .map(([chapter, rows]) => ({
      chapter,
      rows,
      relevant: rank.has(chapter),
    }))
    .sort((a, b) => {
      const left = rank.get(a.chapter) ?? Number.MAX_SAFE_INTEGER
      const right = rank.get(b.chapter) ?? Number.MAX_SAFE_INTEGER
      return left - right
    })
}

/** `prisoner-13` reads as `Prisoner 13` in a menu a person is scanning. */
function prettyChapter(slug: string) {
  return slug
    .split('-')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
}

function Provenance({
  label,
  hint,
  items,
  tone,
}: {
  label: string
  hint: string
  items: string[]
  tone: string
}) {
  return (
    <div>
      <div className={`font-medium ${tone}`}>
        {label} <span className="text-ink-faint">({items.length})</span>
      </div>
      <p className="text-ink-faint">{hint}</p>
      {items.length > 0 && (
        <ul className="mt-1 space-y-0.5 text-ink-dim">
          {items.map((item, index) => (
            <li key={index}>· {item}</li>
          ))}
        </ul>
      )}
    </div>
  )
}
