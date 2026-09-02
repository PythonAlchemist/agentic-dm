'use client'

import Link from 'next/link'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams } from 'next/navigation'

import { Shell } from '@/components/product/Shell'
import { tableAPI, type Found, type MapRow, type Pin } from '@/lib/api'
import { CHROME, SOURCE } from '@/lib/palette'

/**
 * A map, and the things a DM has put on it.
 *
 * COORDINATES ARE FRACTIONS, AND THE CONVERSION HAPPENS HERE ONCE. A click
 * arrives in pixels; it is divided by the rendered box before it goes anywhere
 * near the API, which refuses anything outside 0..1. That refusal is the
 * backstop, not the design: the reason it is a fraction is that a DM will
 * re-upload a better scan, and every pin has to survive it.
 *
 * PINS ARE BORN HIDDEN AND THE SCREEN SAYS SO. A hidden pin is drawn hollow to
 * the DM and does not exist in the player's view at all -- not dimmed, not
 * silhouetted, because a blurred pin is a spoiler of existence.
 *
 * "SHOW THE TABLE" IS THE ONE CONTROL THAT MATTERS. Before you share a screen
 * you want to see exactly what they will see, and the toggle asks the API for
 * the player's view rather than hiding things locally -- a client-side filter
 * would be a picture of safety rather than the thing itself.
 */
export default function MapPage() {
  const params = useParams<{ campaign: string; id: string }>()
  const campaign = decodeURIComponent(params.campaign)
  const mapId = decodeURIComponent(params.id)

  const [maps, setMaps] = useState<MapRow[]>([])
  const [pins, setPins] = useState<Pin[]>([])
  const [asPlayer, setAsPlayer] = useState(false)
  const [preview, setPreview] = useState(false)
  const [placing, setPlacing] = useState<{ x: number; y: number } | null>(null)
  const [failed, setFailed] = useState('')
  const image = useRef<HTMLDivElement>(null)

  useEffect(() => {
    tableAPI.maps(campaign).then((r) => setMaps(r.maps)).catch(() => undefined)
  }, [campaign])

  const loadPins = useCallback(() => {
    tableAPI
      .pins(campaign, mapId, preview)
      .then((r) => {
        setPins(r.pins)
        setAsPlayer(r.as_player)
      })
      .catch((error) => setFailed(String(error)))
  }, [campaign, mapId, preview])

  useEffect(loadPins, [loadPins])

  const sheet = maps.find((m) => m.id === mapId)

  const onClick = (event: React.MouseEvent<HTMLDivElement>) => {
    if (asPlayer) return
    const box = event.currentTarget.getBoundingClientRect()
    // FRACTIONS OF THE RENDERED BOX. Not of the natural image size, which is
    // not what was clicked, and not pixels, which shear on the next upload.
    setPlacing({
      x: (event.clientX - box.left) / box.width,
      y: (event.clientY - box.top) / box.height,
    })
  }

  const place = (entity: Found) => {
    if (!placing) return
    tableAPI
      .pin(campaign, mapId, entity.entity_id, placing.x, placing.y)
      .then(() => {
        setPlacing(null)
        loadPins()
      })
      .catch((error) => setFailed(String(error)))
  }

  const toggleReveal = (pin: Pin) => {
    tableAPI
      .reveal(campaign, mapId, pin.entity_id, !pin.revealed, pin.as_name ?? '')
      .then(loadPins)
      .catch((error) => setFailed(String(error)))
  }

  return (
    <Shell
      campaign={campaign}
      section="play"
      aside={
        <button
          onClick={() => setPreview((was) => !was)}
          aria-pressed={preview}
          className={`rounded px-2 py-1 text-xs ${
            preview ? CHROME.selected : 'text-neutral-500 hover:text-neutral-300'
          }`}
          title="What the table sees. Asks the API for the player's view."
        >
          show the table
        </button>
      }
    >
      <div className="mx-auto max-w-6xl px-6 py-8">
        <div className="flex items-baseline gap-3">
          <h1 className="text-xl font-medium text-neutral-100">
            {sheet?.name ?? mapId}
          </h1>
          {sheet && (
            <Link
              href={`/c/${campaign}/e/${encodeURIComponent(sheet.place_id)}`}
              className="text-sm text-neutral-500 hover:underline"
            >
              {sheet.place}
            </Link>
          )}
          <span className="ml-auto text-xs text-neutral-600">
            {asPlayer
              ? 'the table’s view — only what you have revealed'
              : 'your view — click the map to pin something'}
          </span>
        </div>

        {failed && (
          <p className="mt-3 text-xs text-neutral-400">⚠ {failed}</p>
        )}

        <div
          ref={image}
          onClick={onClick}
          className={`relative mt-4 overflow-hidden rounded border border-neutral-800 bg-neutral-900 ${
            asPlayer ? '' : 'cursor-crosshair'
          }`}
        >
          {sheet ? (
            /* eslint-disable-next-line @next/next/no-img-element */
            <img
              src={tableAPI.assetURL(sheet.asset_id)}
              alt={sheet.name}
              className="block w-full select-none"
              draggable={false}
            />
          ) : (
            <div className="flex h-64 items-center justify-center text-sm text-neutral-600">
              No image for this map.
            </div>
          )}

          {pins.map((pin) => (
            <button
              key={pin.entity_id}
              onClick={(event) => {
                event.stopPropagation()
                if (!asPlayer) toggleReveal(pin)
              }}
              style={{ left: `${pin.x * 100}%`, top: `${pin.y * 100}%` }}
              title={
                asPlayer
                  ? pin.name
                  : `${pin.name} — ${pinState(pin)}`
              }
              className="absolute -translate-x-1/2 -translate-y-1/2"
            >
              {/* FILLED ONLY WHEN THE TABLE ACTUALLY SEES IT, which takes
                  both halves: the pin face-up AND the thing known. A pin
                  face-up on a subject nobody has been told about renders for
                  nobody, and a hollow token is the honest drawing of that. */}
              <span
                className={`block h-3 w-3 rounded-full border-2 ${
                  pin.revealed && pin.known
                    ? 'border-neutral-950 bg-neutral-200'
                    : 'border-neutral-400 bg-transparent'
                }`}
              />
              <span className="mt-0.5 block whitespace-nowrap rounded bg-neutral-950/80 px-1 text-[10px] text-neutral-200">
                {pin.name}
              </span>
            </button>
          ))}

          {placing && (
            <span
              style={{ left: `${placing.x * 100}%`, top: `${placing.y * 100}%` }}
              className="pointer-events-none absolute -translate-x-1/2 -translate-y-1/2 text-lg text-neutral-300"
            >
              +
            </span>
          )}
        </div>

        {placing && !asPlayer && (
          <PinPicker
            campaign={campaign}
            onPick={place}
            onCancel={() => setPlacing(null)}
          />
        )}

        {!asPlayer && pins.length > 0 && (
          <ul className="mt-6 flex flex-col gap-1">
            {pins.map((pin) => (
              <li key={pin.entity_id} className="flex items-baseline gap-3 text-sm">
                <Link
                  href={`/c/${campaign}/e/${encodeURIComponent(pin.entity_id)}`}
                  className={`hover:underline ${
                    pin.plane === 'campaign' ? SOURCE.yours : 'text-neutral-300'
                  }`}
                >
                  {pin.name}
                </Link>
                {pin.as_name && (
                  <span className="text-xs text-neutral-500">
                    the table knows it as &ldquo;{pin.as_name}&rdquo;
                  </span>
                )}
                {/* WHY A FACE-UP PIN IS STILL INVISIBLE, said rather than left
                    for the DM to work out. */}
                {pin.revealed && !pin.known && (
                  <span className="text-[11px] text-neutral-500">
                    face-up, but your table has not been told this exists
                  </span>
                )}
                <button
                  onClick={() => toggleReveal(pin)}
                  className="ml-auto text-[11px] text-neutral-500 hover:text-neutral-300"
                >
                  {pin.revealed ? 'hide' : 'reveal'}
                </button>
                <button
                  onClick={() =>
                    tableAPI.unpin(campaign, mapId, pin.entity_id).then(loadPins)
                  }
                  className="text-[11px] text-neutral-600 hover:text-neutral-400"
                >
                  unpin
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Shell>
  )
}

/** Why a pin does or does not reach the table's screen. */
function pinState(pin: Pin): string {
  if (!pin.revealed) return 'hidden'
  if (!pin.known) return 'face-up, but the table has not been told this exists'
  return 'the table can see this'
}

/** What goes on the spot you just clicked. */
function PinPicker({
  campaign,
  onPick,
  onCancel,
}: {
  campaign: string
  onPick: (entity: Found) => void
  onCancel: () => void
}) {
  const [q, setQ] = useState('')
  const [found, setFound] = useState<Found[]>([])

  useEffect(() => {
    // The empty query is handled by NOT SHOWING the last results rather than
    // by clearing them in the effect body: a synchronous setState there
    // cascades a render on every keystroke.
    if (!q.trim()) return
    let cancelled = false
    tableAPI
      .search(campaign, q)
      .then((r) => !cancelled && setFound(r.found))
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [q, campaign])

  const shown = q.trim() ? found : []

  return (
    <div className="mt-4 max-w-sm rounded border border-neutral-800 bg-neutral-900/60 p-3">
      <div className="flex items-baseline gap-2">
        <input
          autoFocus
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="what is here?"
          className={`flex-1 rounded border border-neutral-800 bg-neutral-950 px-2 py-1 text-sm text-neutral-200 outline-none ${CHROME.focus}`}
        />
        <button onClick={onCancel} className="text-[11px] text-neutral-500 hover:text-neutral-300">
          cancel
        </button>
      </div>
      <ul className="mt-2 flex max-h-60 flex-col overflow-y-auto">
        {shown.map((entity) => (
          <li key={entity.entity_id}>
            <button
              onClick={() => onPick(entity)}
              className="flex w-full items-baseline gap-2 rounded px-1.5 py-1 text-left text-sm hover:bg-neutral-800"
            >
              <span
                className={
                  entity.plane === 'campaign' ? SOURCE.yours : 'text-neutral-200'
                }
              >
                {entity.name}
              </span>
              <span className="ml-auto text-[10px] uppercase tracking-wide text-neutral-600">
                {entity.labels.join(' ').toLowerCase()}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
