/**
 * The two window readings: what a session list says about its own page, and what a transcript
 * says about its own completeness.
 *
 * Both are pure functions on purpose — the engine answers with a page size rather than a boolean
 * for the transcript (`api_server.py:3251-3254`), and the shell's whole failure mode in this area
 * is presenting a window as the whole thing (the internal audit CON-1, CON-2).
 */

import { describe, expect, it } from 'vitest'
import type { SessionListResponse, SessionMessagesResponse } from '@shared/wire'
import { readSessionsWindow, transcriptMayBeIncomplete } from './app-context'

const list = (fields: Partial<SessionListResponse> = {}): SessionListResponse => ({
  object: 'list',
  data: [{ id: 'web-1' } as never],
  ...fields
})

describe('readSessionsWindow', () => {
  it("takes the engine's own has_more as the answer", () => {
    expect(readSessionsWindow(list({ has_more: true, limit: 50 })).hasMore).toBe(true)
    expect(readSessionsWindow(list({ has_more: false, limit: 50 })).hasMore).toBe(false)
  })

  it('treats a full page with no flag as more', () => {
    // 50 rows against a window of 50 and no `has_more`: the older engine shape, where the page
    // size is the only evidence there is.
    const rows = Array.from({ length: 50 }, (_, index) => ({ id: `web-${index}` }) as never)
    const window = readSessionsWindow({ object: 'list', data: rows, limit: 50 })
    expect(window.hasMore).toBe(true)
    expect(window.sessions).toHaveLength(50)
  })

  it('does not invent more when the page is short', () => {
    expect(readSessionsWindow(list({ limit: 50 })).hasMore).toBe(false)
  })

  it('falls back to the window the rail asked for', () => {
    expect(readSessionsWindow({ object: 'list', data: [] }).limit).toBe(100)
  })
})

describe('transcriptMayBeIncomplete', () => {
  const messages = (pagination?: SessionMessagesResponse['pagination']): SessionMessagesResponse => ({
    object: 'list',
    session_id: 'web-1',
    data: [{ role: 'user', content: 'hi' } as never],
    ...(pagination ? { pagination } : {})
  })

  it('is true when the engine sent a full page', () => {
    expect(transcriptMayBeIncomplete(messages({ limit: 500, offset: 0, returned: 500 }))).toBe(true)
  })

  it('is false when the page is short of the window', () => {
    expect(transcriptMayBeIncomplete(messages({ limit: 500, offset: 0, returned: 12 }))).toBe(false)
  })

  it('is false when the engine said nothing about the page', () => {
    // An engine that does not paginate this route cannot be truncating it.
    expect(transcriptMayBeIncomplete(messages())).toBe(false)
    expect(transcriptMayBeIncomplete(messages({ returned: 500 }))).toBe(false)
  })
})
