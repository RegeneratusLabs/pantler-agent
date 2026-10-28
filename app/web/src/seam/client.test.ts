/**
 * The SSE decoder and the retry policy are the two places where a subtle mistake costs a
 * operator a duplicated invoice or a blank screen. Both are tested here without a socket.
 */

import { afterEach, describe, expect, it, vi } from 'vitest'
import { SeamClient, SeamUnreachable, SseDecoder } from './client'

describe('SseDecoder', () => {
  it('decodes a frame and its resume cursor', () => {
    const frames = new SseDecoder().push('id: 4\ndata: {"event":"run.started","run_id":"r1"}\n\n')
    expect(frames).toHaveLength(1)
    expect(frames[0].id).toBe(4)
    expect(frames[0].data.event).toBe('run.started')
  })

  it('reassembles a frame split across chunks', () => {
    const decoder = new SseDecoder()
    expect(decoder.push('id: 1\ndata: {"event":"message.del')).toHaveLength(0)
    expect(decoder.push('ta","delta":"hello"}\n\n')).toHaveLength(1)
  })

  it('decodes several frames from one chunk', () => {
    const frames = new SseDecoder().push(
      'id: 1\ndata: {"event":"message.delta","delta":"a"}\n\nid: 2\ndata: {"event":"message.delta","delta":"b"}\n\n'
    )
    expect(frames.map(f => f.id)).toEqual([1, 2])
    expect(frames.map(f => (f.data as { delta: string }).delta)).toEqual(['a', 'b'])
  })

  it('ignores the comment frames the engine opens with', () => {
    // `: open` and `: keepalive` carry no payload and must not become events.
    const frames = new SseDecoder().push(': open\n\n: keepalive\n\nid: 1\ndata: {"event":"run.started"}\n\n')
    expect(frames).toHaveLength(1)
    expect(frames[0].id).toBe(1)
  })

  it('survives a malformed frame without killing the stream', () => {
    const frames = new SseDecoder().push('id: 1\ndata: {not json}\n\nid: 2\ndata: {"event":"run.started"}\n\n')
    expect(frames).toHaveLength(1)
    expect(frames[0].id).toBe(2)
  })

  it('handles CRLF line endings and a data line with no space', () => {
    const frames = new SseDecoder().push('id: 9\r\ndata:{"event":"run.started"}\r\n\r\n')
    expect(frames).toHaveLength(1)
    expect(frames[0].id).toBe(9)
  })

  it('keeps a frame whose id is missing', () => {
    const frames = new SseDecoder().push('data: {"event":"replay.truncated"}\n\n')
    expect(frames[0].id).toBeNull()
  })
})

describe('retry policy', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  const client = () => new SeamClient({ baseUrl: 'http://127.0.0.1:8644', apiKey: 'k'.repeat(32) })

  it('does NOT retry a run submission, because a retry can double-submit a turn', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError('socket hang up'))
    vi.stubGlobal('fetch', fetchMock)

    await expect(client().startRun('invoice Bellview CSA')).rejects.toBeInstanceOf(SeamUnreachable)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('does NOT retry an approval answer', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError('socket hang up'))
    vi.stubGlobal('fetch', fetchMock)

    await expect(client().respondToApproval('run-1', 'deny')).rejects.toBeInstanceOf(SeamUnreachable)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('names the prompt and generation a host-multiplex approval requires', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ run_id: 'run-1', status: 'resolved' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' }
      })
    )
    vi.stubGlobal('fetch', fetchMock)

    await client().respondToApproval('run-1', 'once', 'prompt-1', 3)

    const init = fetchMock.mock.calls[0][1] as RequestInit
    expect(init.body).toBe(
      '{"choice":"once","request_id":"prompt-1","execution_generation":3}'
    )
  })

  it('does NOT retry a clarifying-question answer', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError('socket hang up'))
    vi.stubGlobal('fetch', fetchMock)

    await expect(
      client().respondToClarify('run-1', 'Pears', 'prompt-1', 3)
    ).rejects.toBeInstanceOf(SeamUnreachable)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('sends the exact three fields the clarify route accepts', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ run_id: 'run-1', status: 'resolved', prompt_id: 'prompt-1' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' }
      })
    )
    vi.stubGlobal('fetch', fetchMock)

    await client().respondToClarify('run-1', 'Pears', 'prompt-1', 3)

    const init = fetchMock.mock.calls[0][1] as RequestInit
    expect(fetchMock.mock.calls[0][0]).toBe('http://127.0.0.1:8644/v1/runs/run-1/clarify')
    expect(init.body).toBe(
      '{"answer":"Pears","request_id":"prompt-1","execution_generation":3}'
    )
  })

  it('retries a health check, which is idempotent by definition', async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new TypeError('connect ECONNREFUSED'))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ status: 'ok' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' }
        })
      )
    vi.stubGlobal('fetch', fetchMock)

    await expect(client().health()).resolves.toEqual({ status: 'ok' })
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('sends the bearer token', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: 'ok' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' }
      })
    )
    vi.stubGlobal('fetch', fetchMock)

    await client().health()
    const init = fetchMock.mock.calls[0][1] as RequestInit
    expect((init.headers as Record<string, string>).Authorization).toBe(`Bearer ${'k'.repeat(32)}`)
  })

  it('explains a 403 as a key or origin problem rather than a bare status', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response('nope', { status: 403 }))
    )

    await expect(client().capabilities()).rejects.toThrow(/API_SERVER_CORS_ORIGINS/)
  })
})

describe('where the key may travel', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  const json = (body: unknown) =>
    new Response(JSON.stringify(body), {
      status: 200,
      headers: { 'Content-Type': 'application/json' }
    })

  it('does not attach a key to an address that is not this origin or loopback', async () => {
    // The shape the audit executed with, straight into the constructor this time: a stored or
    // handed-in absolute address must not receive the credential beside it
    // (the internal security audit A19-WEB-4).
    const fetchMock = vi.fn().mockResolvedValue(json({ status: 'ok' }))
    vi.stubGlobal('fetch', fetchMock)

    await new SeamClient({ baseUrl: 'https://attacker.example', apiKey: 'sk-secret' }).health()

    expect(fetchMock.mock.calls[0][0]).toBe('https://attacker.example/health')
    const init = fetchMock.mock.calls[0][1] as RequestInit
    expect((init.headers as Record<string, string>).Authorization).toBeUndefined()
  })

  it('still attaches it to a same-origin path, which the dev server turns into the real key', async () => {
    const fetchMock = vi.fn().mockResolvedValue(json({ status: 'ok' }))
    vi.stubGlobal('fetch', fetchMock)

    await new SeamClient({ baseUrl: '/seam', apiKey: 'sk-shell' }).health()

    const init = fetchMock.mock.calls[0][1] as RequestInit
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer sk-shell')
  })
})

describe('sessions and jobs', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  const client = () => new SeamClient({ baseUrl: '/seam', apiKey: '' })

  const json = (body: unknown, status = 200) =>
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' }
    })

  it('lists sessions and unwraps the envelope', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(json({ object: 'list', data: [{ id: 'web-1', title: 'One' }] }))
    vi.stubGlobal('fetch', fetchMock)

    await client().listSessions()
    expect(fetchMock.mock.calls[0][0]).toBe('/seam/api/sessions')
  })

  it('does NOT retry a session create — a retry would make a second empty session', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError('socket hang up'))
    vi.stubGlobal('fetch', fetchMock)

    await expect(client().createSession({ id: 'web-x' })).rejects.toBeInstanceOf(SeamUnreachable)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('percent-encodes a session id in the path', async () => {
    // Pinned on the route the rail actually calls: a session id is a path segment, and one with
    // a slash in it would address a different route entirely
    // (the internal audit WEB-17).
    const fetchMock = vi.fn().mockResolvedValue(json({ object: 'hermes.session', session: {} }))
    vi.stubGlobal('fetch', fetchMock)

    await client().patchSession('web/a b', { pinned: true })
    expect(fetchMock.mock.calls[0][0]).toBe('/seam/api/sessions/web%2Fa%20b')
  })

  it('sends a session patch verbatim, because the engine rejects unknown fields', async () => {
    const fetchMock = vi.fn().mockResolvedValue(json({ object: 'hermes.session', session: {} }))
    vi.stubGlobal('fetch', fetchMock)

    await client().patchSession('web-1', { title: 'Renamed' })
    const init = fetchMock.mock.calls[0][1] as RequestInit
    expect(init.method).toBe('PATCH')
    expect(init.body).toBe('{"title":"Renamed"}')
  })

  it('treats an empty 200 as success, so a bare DELETE is not read as an outage', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status: 200 })))
    await expect(client().deleteSession('web-1')).resolves.toBeUndefined()
  })

  it('reports a 2xx with an unparseable body as a seam error, not an unreachable engine', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('<html>', { status: 200 })))
    await expect(client().listSessions()).rejects.toThrow(/not JSON/)
  })

  it('unwraps the job list and asks for disabled jobs too', async () => {
    const fetchMock = vi.fn().mockResolvedValue(json({ jobs: [{ id: 'j1', name: 'Briefing' }] }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(client().listJobs(true)).resolves.toEqual([{ id: 'j1', name: 'Briefing' }])
    expect(fetchMock.mock.calls[0][0]).toBe('/seam/api/jobs?include_disabled=true')
  })

  it('unwraps a created job', async () => {
    const fetchMock = vi.fn().mockResolvedValue(json({ job: { id: 'j2', name: 'Chase' } }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(
      client().createJob({ name: 'Chase', schedule: '0 7 * * 1', prompt: 'Chase' })
    ).resolves.toEqual({ id: 'j2', name: 'Chase' })
    expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe('POST')
  })

  it('updates a job in place with PATCH and unwraps it', async () => {
    const fetchMock = vi.fn().mockResolvedValue(json({ job: { id: 'j2', name: 'Chase' } }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(client().updateJob('j2', { prompt: 'Chase harder' })).resolves.toEqual({
      id: 'j2',
      name: 'Chase'
    })
    expect(fetchMock.mock.calls[0][0]).toBe('/seam/api/jobs/j2')
    const init = fetchMock.mock.calls[0][1] as RequestInit
    expect(init.method).toBe('PATCH')
    expect(init.body).toBe('{"prompt":"Chase harder"}')
  })

  it('drives pause, resume and run at the engine’s own sub-routes', async () => {
    // A fresh Response per call: a body can only be read once.
    const fetchMock = vi
      .fn()
      .mockImplementation(() => Promise.resolve(json({ job: { id: 'j1', name: 'Briefing' } })))
    vi.stubGlobal('fetch', fetchMock)

    await client().pauseJob('j1')
    await client().resumeJob('j1')
    await client().runJob('j1')

    expect(fetchMock.mock.calls.map(call => call[0])).toEqual([
      '/seam/api/jobs/j1/pause',
      '/seam/api/jobs/j1/resume',
      '/seam/api/jobs/j1/run'
    ])
  })

  it('does NOT retry a job run, which is not idempotent', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError('socket hang up'))
    vi.stubGlobal('fetch', fetchMock)

    await expect(client().runJob('j1')).rejects.toBeInstanceOf(SeamUnreachable)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})

describe('profile routing', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('addresses a profile through the engine’s /p/<name>/ surface', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ status: 'ok' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' }
        })
      )
    vi.stubGlobal('fetch', fetchMock)

    await new SeamClient({
      baseUrl: 'http://127.0.0.1:8644',
      apiKey: 'k'.repeat(32),
      profile: 'garden'
    }).health()

    expect(fetchMock.mock.calls[0][0]).toBe('http://127.0.0.1:8644/p/garden/health')
  })

  it('keeps the bare seam when no profile is selected yet', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ status: 'ok' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' }
        })
      )
    vi.stubGlobal('fetch', fetchMock)

    await new SeamClient({ baseUrl: 'http://127.0.0.1:8644', apiKey: '' }).health()

    expect(fetchMock.mock.calls[0][0]).toBe('http://127.0.0.1:8644/health')
  })
})
