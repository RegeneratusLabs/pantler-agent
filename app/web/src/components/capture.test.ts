import { describe, expect, it } from 'vitest'
import { captureHref, parseCapture } from './capture'

const result = (overrides: Record<string, unknown> = {}) =>
  JSON.stringify({
    success: true,
    id: 'CAP-0001',
    type: 'capture',
    record: {
      text: 'I sprayed the tomatoes in block B today',
      status: 'captured',
      source: 'chat',
      occurred_on: '2026-10-30'
    },
    saved_at: '2026-10-30T10:00:00+00:00',
    ...overrides
  })

describe('parseCapture', () => {
  it('reads the operator words, id and date', () => {
    expect(parseCapture(result())).toEqual({
      id: 'CAP-0001',
      text: 'I sprayed the tomatoes in block B today',
      occurredOn: '2026-10-30',
      status: 'captured',
      source: 'chat',
      savedAt: '2026-10-30T10:00:00+00:00'
    })
  })

  it('reads a promoted capture and points at its typed record', () => {
    const parsed = parseCapture(
      result({
        record: {
          text: 'Harvested the carrots',
          status: 'promoted',
          record_type: 'harvest',
          record_id: 'HAR-0001'
        }
      })
    )
    expect(parsed?.status).toBe('promoted')
    expect(parsed && captureHref(parsed)).toBe('/records?type=harvest&id=HAR-0001')
  })

  it('refuses a non-capture or a malformed result', () => {
    expect(parseCapture(undefined)).toBeNull()
    expect(parseCapture('not json')).toBeNull()
    expect(parseCapture(JSON.stringify({ success: true, id: 'X', type: 'invoice' }))).toBeNull()
    expect(parseCapture(result({ record: { text: 'x', status: 'unknown' } }))).toBeNull()
    expect(parseCapture(result({ success: false }))).toBeNull()
  })

  it('points a raw capture at the capture table', () => {
    const parsed = parseCapture(result())
    expect(parsed && captureHref(parsed)).toBe('/records?type=capture&id=CAP-0001')
  })
})
