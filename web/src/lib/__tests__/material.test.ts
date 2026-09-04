import { describe, expect, it } from 'vitest'

import { splitOf } from '@/lib/material'
import type { GeneratedReply } from '@/lib/api'

function reply(over: Partial<GeneratedReply> = {}): GeneratedReply {
  return {
    kind: 'scene', subject: 's', title: 't', body: 'b',
    from_canon: [], invented: [], sources: [],
    usage: {} as never, cost: {} as never, retrieval: null,
    error: '', raw: '', model: 'm',
    ...over,
  } as GeneratedReply
}

describe('splitOf', () => {
  it('maps every API field to the source whose hue may name it', () => {
    const groups = splitOf(reply({
      from_canon: [{ claim: 'the book said it', cite: 'A Cry for Help' }],
      from_yours: [{ claim: 'you wrote it', cite: 'This campaign' }],
      from_context: ['somebody said it'],
      invented: ['the model supplied it'],
    }))
    expect(groups.map((g) => g.source)).toEqual(['book', 'yours', 'table', 'invented'])
    expect(groups[2].claims).toEqual([{ claim: 'somebody said it', cite: '' }])
    expect(groups[3].claims).toEqual([{ claim: 'the model supplied it', cite: '' }])
  })

  it('omits a source that contributed nothing rather than rendering it empty', () => {
    const groups = splitOf(reply({ invented: ['only this'] }))
    expect(groups.map((g) => g.source)).toEqual(['invented'])
  })

  it('treats absent optional fields as contributing nothing', () => {
    expect(splitOf(reply())).toEqual([])
  })
})
