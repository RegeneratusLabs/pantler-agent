/**
 * The BFF client's two contracts: unwrap the shapes the server actually sends, and never
 * retry a write. The second one matters more than the first — a retried settings write is a
 * second write to a file the engine reads at startup.
 */

import { afterEach, describe, expect, it, vi } from 'vitest'
import { BffClient } from './bff'

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' }
  })

describe('BffClient', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  const client = () => new BffClient('/api')

  it('unwraps the pack list', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json({ data: [{ id: 'example' }] })))
    await expect(client().packs()).resolves.toEqual([{ id: 'example' }])
  })

  it('reports a 2xx with an unparseable body as a seam error, not an unreachable server', async () => {
    // A proxy's error page or an HTML login redirect, at 200. It used to be retried (a second
    // GET) and finally reported as "Could not reach the records API. Is app/server running?"
    // — advice to start a server that had just answered
    // (the internal audit WEB-6).
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response('<html>not json</html>', { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(client().packs()).rejects.toThrow(/not JSON/)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('reads settings from /api/settings', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(json({ available: true, model: { default: 'glm-5.3' } }))
    vi.stubGlobal('fetch', fetchMock)

    await client().settings()
    expect(fetchMock.mock.calls[0][0]).toBe('/api/settings')
  })

  it('reads a job’s saved runs and one run by its engine id', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json({ available: true, job_id: 'abcdef123456', runs: [] }))
      .mockResolvedValueOnce(
        json({ job_id: 'abcdef123456', run: { id: '2026-10-27_07-00-00', content: 'hi' } })
      )
    vi.stubGlobal('fetch', fetchMock)

    await client().jobRuns('abcdef123456')
    await client().jobRun('abcdef123456', '2026-10-27_07-00-00')

    expect(fetchMock.mock.calls[0][0]).toBe('/api/jobs/abcdef123456/runs')
    expect(fetchMock.mock.calls[1][0]).toBe(
      '/api/jobs/abcdef123456/runs/2026-10-27_07-00-00'
    )
  })

  it('reads the skills index from the BFF, not the broken engine route', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(json({ available: true, data: [{ name: 'invoicing' }] }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(client().skills()).resolves.toEqual({
      available: true,
      data: [{ name: 'invoicing' }]
    })
    expect(fetchMock.mock.calls[0][0]).toBe('/api/skills')
  })

  it('PUTs the disabled toolset list and does NOT retry', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError('socket hang up'))
    vi.stubGlobal('fetch', fetchMock)

    await expect(client().saveDisabledToolsets(['browser'])).rejects.toThrow()
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('PUTs the disabled skill list to its own route', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(json({ disabled_skills: ['youtube-content'], applies_to: 'new_conversations' }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(client().saveDisabledSkills(['youtube-content'])).resolves.toMatchObject({
      disabled_skills: ['youtube-content']
    })
    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(path).toBe('/api/settings/skills')
    expect(init.body).toBe('{"disabled_skills":["youtube-content"]}')
  })

  it('PUTs a reasoning level to its own route, and does NOT retry', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError('socket hang up'))
    vi.stubGlobal('fetch', fetchMock)

    await expect(client().saveReasoningEffort('low')).rejects.toThrow()
    expect(fetchMock).toHaveBeenCalledTimes(1)

    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(path).toBe('/api/settings/reasoning')
    expect(init.method).toBe('PUT')
    expect(init.body).toBe('{"reasoning_effort":"low"}')
  })

  it('sends the disabled choice as the string the engine spells it with', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(json({ reasoning_effort: 'false', applies_to: 'new_conversations' }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(client().saveReasoningEffort('false')).resolves.toMatchObject({
      reasoning_effort: 'false'
    })
    const init = fetchMock.mock.calls[0][1] as RequestInit
    expect(init.body).toBe('{"reasoning_effort":"false"}')
  })

  it('PUTs a model and does NOT retry, because a retry is a second write', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError('socket hang up'))
    vi.stubGlobal('fetch', fetchMock)

    await expect(client().saveModel({ default: 'x' })).rejects.toThrow()
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('reads the capability registry from /api/capabilities', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(json({ available: true, data: [{ id: 'skill:invoicing' }] }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(client().capabilities()).resolves.toMatchObject({ available: true })
    expect(fetchMock.mock.calls[0][0]).toBe('/api/capabilities')
  })

  it('PUTs one capability by its whole id, and does NOT retry', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError('socket hang up'))
    vi.stubGlobal('fetch', fetchMock)

    await expect(client().setCapability('skill:invoicing', false)).rejects.toThrow()
    expect(fetchMock).toHaveBeenCalledTimes(1)

    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    // The colon is encoded; the server unquotes the id before dispatching on its kind.
    expect(path).toBe('/api/capabilities/skill%3Ainvoicing')
    expect(init.method).toBe('PUT')
    expect(init.body).toBe('{"enabled":false}')
  })

  it('round-trips an MCP server id, whose prefix is its whole kind', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(json({ id: 'mcp_server:notion', enabled: true, applies_to: 'next_restart' }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(client().setCapability('mcp_server:notion', true)).resolves.toMatchObject({
      applies_to: 'next_restart'
    })
    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(path).toBe('/api/capabilities/mcp_server%3Anotion')
    expect(init.body).toBe('{"enabled":true}')
  })

  it('sends the model as a bare object, which is what the route expects', async () => {
    const fetchMock = vi.fn().mockResolvedValue(json({ model: {}, restart_required: true }))
    vi.stubGlobal('fetch', fetchMock)

    await client().saveModel({ provider: 'opencode-go' })
    const init = fetchMock.mock.calls[0][1] as RequestInit
    expect(init.method).toBe('PUT')
    expect(init.body).toBe('{"provider":"opencode-go"}')
  })

  it('percent-encodes a key name in the path', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(json({ name: 'A B', is_set: true, restart_required: true }))
    vi.stubGlobal('fetch', fetchMock)

    await client().saveKey('A B', 'secret')
    expect(fetchMock.mock.calls[0][0]).toBe('/api/settings/keys/A%20B')
  })

  it('does NOT retry a key write or a clear', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError('socket hang up'))
    vi.stubGlobal('fetch', fetchMock)

    await expect(client().saveKey('FOO', 'x')).rejects.toThrow()
    await expect(client().clearKey('FOO')).rejects.toThrow()
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('surfaces the server’s own message rather than a status code', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        json({ error: { message: 'this machine only', code: 'not_local' } }, 403)
      )
    )

    await expect(client().saveModel({ default: 'x' })).rejects.toThrow('this machine only')
  })

  it('carries the error code through, so a caller can branch on it', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        json({ error: { message: 'no profile', code: 'settings_unavailable' } }, 503)
      )
    )

    await expect(client().settings()).rejects.toMatchObject({ code: 'settings_unavailable' })
  })

  it('treats an empty 200 as success rather than an outage', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status: 200 })))
    await expect(client().clearKey('FOO')).resolves.toBeUndefined()
  })
})

describe('BffClient connectors', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  const client = () => new BffClient('/api')

  it('reads the live connector state', async () => {
    const fetchMock = vi.fn().mockResolvedValue(json({ configured: true, connectors: [] }))
    vi.stubGlobal('fetch', fetchMock)

    await client().connectors()
    expect(fetchMock.mock.calls[0][0]).toBe('/api/connectors')
    expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe('GET')
  })

  it('starts a connection with a POST and does NOT retry it', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError('socket hang up'))
    vi.stubGlobal('fetch', fetchMock)

    await expect(client().connectConnector('gmail')).rejects.toThrow()
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(path).toBe('/api/connectors/gmail/connect')
    expect(init.method).toBe('POST')
    expect(init.body).toBe('{}')
  })

  it('encodes the connector id in every path', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json({ connector: 'gmail', tools: [] }))
      .mockResolvedValueOnce(json({ connector: 'gmail', disconnected: 1, state: 'not_connected' }))
    vi.stubGlobal('fetch', fetchMock)

    await client().connectorTools('g mail')
    await client().disconnectConnector('g mail')

    expect(fetchMock.mock.calls[0][0]).toBe('/api/connectors/g%20mail/tools')
    expect(fetchMock.mock.calls[1][0]).toBe('/api/connectors/g%20mail')
    expect((fetchMock.mock.calls[1][1] as RequestInit).method).toBe('DELETE')
  })
})

describe('BffClient profile scope', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('names the profile on every data request, so two tabs cannot share one answer', async () => {
    const fetchMock = vi.fn().mockResolvedValue(json({ data: [] }))
    vi.stubGlobal('fetch', fetchMock)

    await new BffClient('/api', 'garden').packs()

    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(path).toBe('/api/packs')
    expect((init.headers as Record<string, string>)['X-Pantler-Profile']).toBe('garden')
  })

  it('leaves the header off the registry client, which asks the server what is selected', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(json({ available: true, active: 'pantler', profiles: [] }))
    vi.stubGlobal('fetch', fetchMock)

    await new BffClient('/api').profiles()

    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(path).toBe('/api/profiles')
    expect((init.headers as Record<string, string>)['X-Pantler-Profile']).toBeUndefined()
  })

  it('creates a profile with a POST and does NOT retry it', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError('socket hang up'))
    vi.stubGlobal('fetch', fetchMock)

    await expect(
      new BffClient().createProfile({ name: 'garden', display_name: 'Garden' })
    ).rejects.toThrow()
    expect(fetchMock).toHaveBeenCalledTimes(1)

    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(path).toBe('/api/profiles')
    expect(init.method).toBe('POST')
    expect(init.body).toBe('{"name":"garden","display_name":"Garden"}')
  })

  it('encodes a profile id in the path when renaming and deleting', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json({ profile: { name: 'garden' } }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
    vi.stubGlobal('fetch', fetchMock)

    const bff = new BffClient()
    await bff.updateProfile('garden', { new_name: 'smallholding' })
    await bff.deleteProfile('garden')

    expect(fetchMock.mock.calls[0][0]).toBe('/api/profiles/garden')
    expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe('PATCH')
    expect(fetchMock.mock.calls[1][0]).toBe('/api/profiles/garden')
    expect((fetchMock.mock.calls[1][1] as RequestInit).method).toBe('DELETE')
  })

  it('selects the active profile through its own route', async () => {
    const fetchMock = vi.fn().mockResolvedValue(json({ active: 'garden', profile: { name: 'garden' } }))
    vi.stubGlobal('fetch', fetchMock)

    await new BffClient().setActiveProfile('garden')

    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(path).toBe('/api/profiles/active')
    expect(init.method).toBe('POST')
    expect(init.body).toBe('{"name":"garden"}')
  })
  it('reads one type of records with its paging in the query', async () => {
    const fetchMock = vi.fn().mockResolvedValue(json({ data: [{ id: 'APP-0001' }], total: 1 }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(new BffClient().records('application', { limit: 100, offset: 20 })).resolves.toMatchObject({
      total: 1
    })
    expect(fetchMock.mock.calls[0][0]).toBe('/api/records/application?limit=100&offset=20')
  })

  it('encodes the type and id when reading one record', async () => {
    const fetchMock = vi.fn().mockResolvedValue(json({ id: 'APP-0001', type: 'application', data: {} }))
    vi.stubGlobal('fetch', fetchMock)

    await new BffClient().record('application', 'APP-0001')
    expect(fetchMock.mock.calls[0][0]).toBe('/api/records/application/APP-0001')
  })

})
