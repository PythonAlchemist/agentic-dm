import { describe, expect, it } from 'vitest'

import { draftedStore, handWrittenStore, splitOf } from '@/lib/material'
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
    expect(groups[0].claims).toEqual([{ claim: 'the book said it', cite: 'A Cry for Help' }])
    expect(groups[1].claims).toEqual([{ claim: 'you wrote it', cite: 'This campaign' }])
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

describe('handWrittenStore', () => {
  it('marks that no model was involved, and says so with empty sources', () => {
    const body = handWrittenStore({
      campaign: 'p13-home',
      title: 'What Dannell will not say',
      body: 'She goes quiet.',
      anchor: 'kftgv:the-murkmire-malevolence#3',
    })
    expect(body.generated_body).toBe('')
    expect(body.model).toBe('')
    expect(body.from_canon).toEqual([])
    expect(body.from_yours).toEqual([])
    expect(body.from_context).toEqual([])
    expect(body.invented).toEqual([])
    expect(body.sources).toEqual([])
    expect(body.kind).toBe('scene')
    expect(body.anchor).toBe('kftgv:the-murkmire-malevolence#3')
  })
})

describe('draftedStore', () => {
  it('keeps what the model wrote beside what the DM kept', () => {
    const r = reply({
      body: 'the model wrote this',
      from_canon: [{ claim: 'c', cite: 'A Cry for Help' }],
      from_yours: [{ claim: 'you wrote it', cite: 'This campaign' }],
      from_context: ['said at the table'],
      invented: ['invented one'],
    })
    const body = draftedStore({
      campaign: 'p13-home',
      reply: r,
      body: 'the DM edited this',
      anchor: 'kftgv:the-murkmire-malevolence#3',
    })
    expect(body.body).toBe('the DM edited this')
    expect(body.generated_body).toBe('the model wrote this')
    expect(body.from_canon).toEqual([{ claim: 'c', cite: 'A Cry for Help' }])
    expect(body.from_context).toEqual(['said at the table'])
    expect(body.invented).toEqual(['invented one'])
    expect(body.from_yours).toEqual([{ claim: 'you wrote it', cite: 'This campaign' }])
    expect(body.model).toBe('m')
  })
})
