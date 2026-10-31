/**
 * A capture result, read from the `capture_save` tool's JSON.
 *
 * The card is deliberately small: the operator's own words, the CAP id, when it happened, and
 * where it went. It is not a record and it must not look like one — the typed record is the card
 * the record tool draws, and this is the note that led to it.
 */

export interface CaptureCard {
  id: string
  text: string
  occurredOn?: string
  status: 'captured' | 'promoted' | 'dismissed'
  source?: string
  recordType?: string
  recordId?: string
  savedAt?: string
}

const STATUSES = new Set(['captured', 'promoted', 'dismissed'])

export function parseCapture(raw: string | undefined | null): CaptureCard | null {
  if (!raw) return null
  let value: unknown
  try {
    value = JSON.parse(raw)
  } catch {
    return null
  }
  if (!value || typeof value !== 'object') return null
  const envelope = value as Record<string, unknown>
  if (envelope.success !== true || envelope.type !== 'capture') return null
  const record = envelope.record
  if (!record || typeof record !== 'object') return null
  const data = record as Record<string, unknown>
  const id = typeof envelope.id === 'string' ? envelope.id : ''
  const text = typeof data.text === 'string' ? data.text : ''
  const status = typeof data.status === 'string' ? data.status : ''
  if (!id || !text.trim() || !STATUSES.has(status)) return null
  return {
    id,
    text,
    occurredOn: typeof data.occurred_on === 'string' ? data.occurred_on : undefined,
    status: status as CaptureCard['status'],
    source: typeof data.source === 'string' ? data.source : undefined,
    recordType: typeof data.record_type === 'string' ? data.record_type : undefined,
    recordId: typeof data.record_id === 'string' ? data.record_id : undefined,
    savedAt: typeof envelope.saved_at === 'string' ? envelope.saved_at : undefined
  }
}

/** The paper-trail address for the capture, or the typed record once it is promoted. */
export function captureHref(capture: CaptureCard): string {
  if (capture.status === 'promoted' && capture.recordType && capture.recordId) {
    return `/records?type=${encodeURIComponent(capture.recordType)}&id=${encodeURIComponent(capture.recordId)}`
  }
  return `/records?type=capture&id=${encodeURIComponent(capture.id)}`
}
