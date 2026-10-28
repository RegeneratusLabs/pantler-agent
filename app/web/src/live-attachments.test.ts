/**
 * The live attachment check.
 *
 * The other half of `live.test.ts`: that one proves a conversation renders, this one proves
 * that a *file* survives the journey — browser-shaped upload, composed turn, engine, answer —
 * and that the transcript can be read back into chips afterwards.
 *
 * It drives the same two clients the screens use (`BffClient`, `SeamClient`) and the same
 * parser (`parseTurn`), because the point is the wiring, not the components.
 *
 * Two servers have to be running: the gateway (8644) and the BFF (8650). Costs one model
 * call, so it is skipped unless asked for:
 *
 *     PANTLER_LIVE=1 npx vitest run src/live-attachments.test.ts --testTimeout=260000
 */

import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { parseTurn } from '@shared/attachments'
import { BffClient } from './seam/bff'
import { SeamClient } from './seam/client'
import { applyFrame, createRunState, displayText, type RunState } from './seam/reducer'

const live = process.env.PANTLER_LIVE === '1'
const ENV_FILE = '/home/you/projects/pantler/.hermes-dev/profiles/pantler/.env'
const BASE_URL = process.env.PANTLER_API ?? 'http://127.0.0.1:8644'
const BFF_URL = process.env.PANTLER_BFF ?? 'http://127.0.0.1:8650'
const PROFILE = process.env.PANTLER_PROFILE ?? 'pantler'

/** A one-pixel PNG: the smallest thing that still has to go through the image path. */
const PNG = Uint8Array.from(
  Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==',
    'base64'
  )
)

function apiKey(): string {
  const raw = readFileSync(ENV_FILE, 'utf8')
  for (const line of raw.split('\n')) {
    if (line.startsWith('API_SERVER_KEY=')) return line.slice('API_SERVER_KEY='.length).trim()
  }
  throw new Error(`no API_SERVER_KEY in ${ENV_FILE}`)
}

async function runToCompletion(
  client: SeamClient,
  input: string,
  sessionId: string
): Promise<RunState> {
  const started = await client.startRun(input, sessionId)
  let state = createRunState(started.run_id)
  for await (const frame of client.streamRun(started.run_id, { lastSeq: 0 })) {
    state = applyFrame(state, frame)
    if (['completed', 'failed', 'cancelled', 'interrupted'].includes(state.phase)) break
  }
  return state
}

describe.skipIf(!live)('attachments, live', () => {
  it('carries a document and an image from upload to answer', async () => {
    const bff = new BffClient(`${BFF_URL}/api`)
    const client = new SeamClient({ baseUrl: BASE_URL, apiKey: apiKey(), profile: PROFILE })
    const sessionId = `web-live-attach-${Date.now()}`

    // 1. Upload, exactly as the composer does: one raw body per file, metadata in headers.
    const csv = await bff.uploadAttachment(sessionId, {
      name: 'bean-order.csv',
      blob: new Blob(['customer,qty,unit_price\nBellview CSA,12,$12.00\n'], { type: 'text/csv' })
    })
    const image = await bff.uploadAttachment(sessionId, {
      name: 'paddock.png',
      blob: new Blob([PNG], { type: 'image/png' })
    })
    expect(csv.kind).toBe('text')
    expect(image.kind).toBe('image')
    expect(csv.path.startsWith('/')).toBe(true)

    // 2. Compose. The listing names the paths; the CSV is inlined; the image is not.
    const composed = await bff.composeTurn(
      sessionId,
      'What is in the attached file, and what is in the image?',
      [csv.id, image.id]
    )
    expect(composed.input).toContain('Attached files (2):')
    expect(composed.input).toContain(csv.path)
    expect(composed.input).toContain('Bellview CSA,12,$12.00')

    // 3. The same parse the transcript uses, so a reloaded turn gets these chips.
    const parsed = parseTurn(composed.input)
    expect(parsed.recognised).toBe(true)
    expect(parsed.attachments.map(ref => ref.name)).toEqual(['bean-order.csv', 'paddock.png'])
    expect(parsed.attachments[0].id).toBe(csv.id)
    expect(parsed.attachments[1].image).toBe(true)

    // 4. Run it.
    const state = await runToCompletion(client, composed.input, sessionId)
    const tools = state.tools.map(tool => `${tool.tool}:${tool.status}`).join(', ')
    expect(state.phase, `tools=[${tools}]`).toBe('completed')

    const answer = displayText(state)
    // The document reached the model — either inlined or through read_file — and it is the
    // only place that token exists.
    expect(answer, `tools=[${tools}]`).toContain('Bellview')
    // And the image went through vision, which is the whole reason a path is enough.
    expect(
      state.tools.some(tool => tool.tool === 'vision_analyze' && tool.status === 'ok'),
      `tools=[${tools}]`
    ).toBe(true)

    // 5. The bytes are still there for the transcript's thumbnail.
    const raw = await fetch(`${BFF_URL}/api/attachments/${image.id}/raw`)
    expect(raw.status).toBe(200)
    expect(raw.headers.get('content-type')).toBe('image/png')
  })
})
