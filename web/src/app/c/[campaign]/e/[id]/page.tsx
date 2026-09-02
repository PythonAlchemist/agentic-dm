'use client'

import { useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'

import { Shell } from '@/components/product/Shell'
import { EntityProfile } from '@/components/product/EntityProfile'
import { labAPI, type EntityRead } from '@/lib/api'

/**
 * One entity, at its own address.
 *
 * A URL IS THE POINT. This is the first thing in the product a DM can bookmark,
 * send to a player, or reopen tomorrow -- the app had exactly one route and
 * kept everything in React state, so none of that was possible.
 */
export default function EntityPage() {
  const params = useParams<{ campaign: string; id: string }>()
  const router = useRouter()
  // DECODED HERE BECAUSE `useParams` DOES NOT. Entity and section ids carry a
  // colon (`cos:strahd-von-zarovich`), so every link encodes them -- and Next
  // 16 hands the raw `cos%3Astrahd-von-zarovich` back. Verified against a dev
  // server rather than assumed; removing this decode breaks every link in the
  // product.
  const campaign = decodeURIComponent(params.campaign)
  const entityId = decodeURIComponent(params.id)

  const [entity, setEntity] = useState<EntityRead | null>(null)
  const [failed, setFailed] = useState('')

  useEffect(() => {
    let cancelled = false
    labAPI
      .entity(entityId, campaign)
      .then((found) => !cancelled && setEntity(found))
      .catch((error) => !cancelled && setFailed(String(error)))
    return () => {
      cancelled = true
    }
  }, [entityId, campaign])

  return (
    <Shell campaign={campaign} section="library">
      {failed && (
        <p className="mx-auto max-w-3xl px-6 py-10 text-ui text-ink-dim">
          {failed.includes('404')
            ? `This table holds nothing called ${entityId}.`
            : 'Could not reach the API.'}
        </p>
      )}
      {entity && (
        <EntityProfile
          entity={entity}
          campaign={campaign}
          onOpenSection={(id) =>
            router.push(`/c/${campaign}/s/${encodeURIComponent(id)}`)
          }
        />
      )}
    </Shell>
  )
}
