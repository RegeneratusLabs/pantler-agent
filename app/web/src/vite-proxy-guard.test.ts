/**
 * The proxy door.
 *
 * The dev proxy used to strip `Origin`, which made the engine's only cross-site check dead for
 * every request it forwarded, and it only guarded `/seam` — never `/api` — and only while
 * `PANTLER_BIND` was unset. These are the three cases the door now answers, driven through the
 * real middleware rather than a copy of it (`the internal security audit A19-WEB-1/-2`).
 */

import { describe, expect, it, vi } from 'vitest'
import config, {
  guardProxyRequest,
  hostIsThisMachine,
  onProxyPath,
  originVerdict,
  seamProxy,
  seamProxyRequestHandler,
  type GuardedRequest,
  type GuardedResponse,
  type ProxyGuardOptions
} from '../vite.config'

const LOOPBACK: ProxyGuardOptions = {
  bindHost: '127.0.0.1',
  allowedHosts: ['localhost', '127.0.0.1']
}

const TAILNET: ProxyGuardOptions = {
  bindHost: '100.86.176.62',
  allowedHosts: ['localhost', '127.0.0.1', 'machine.tailnet.ts.net']
}

function call(
  url: string,
  headers: Record<string, string> = {},
  options: ProxyGuardOptions = LOOPBACK
) {
  const req: GuardedRequest = { url, headers }
  const res: GuardedResponse = {
    statusCode: 200,
    setHeader: vi.fn(),
    end: vi.fn()
  }
  const next = vi.fn()
  guardProxyRequest(req, res, next, options)
  return { status: res.statusCode, next, res }
}

describe('the proxy door', () => {
  it('refuses a foreign Origin on both proxied prefixes, and does not forward it', () => {
    for (const path of ['/seam/v1/runs', '/api/records']) {
      const result = call(path, { host: '127.0.0.1:5175', origin: 'https://evil.example' })
      expect(result.status, path).toBe(403)
      expect(result.next, path).not.toHaveBeenCalled()
      expect(result.res.end, path).toHaveBeenCalled()
    }
  })

  it('lets a same-origin Origin through — the browser request this app actually makes', () => {
    // Forwarded, not rewritten: the engine's own allow-list still sees the origin, and the BFF
    // sees the same-origin signal its write guard asks for.
    for (const path of ['/seam/v1/runs', '/api/records']) {
      const result = call(path, {
        host: '127.0.0.1:5175',
        origin: 'http://127.0.0.1:5175'
      })
      expect(result.next, path).toHaveBeenCalled()
      expect(result.status, path).toBe(200)
    }
  })

  it('lets a request with no Origin through to the servers’ own guards', () => {
    // curl, a script, and the engine's direct path send none; each server still has its own
    // origin and write guard, and this door refuses only the cross-site browser case.
    expect(call('/seam/v1/runs', { host: '127.0.0.1:5175' }).next).toHaveBeenCalled()
    expect(call('/api/records', { host: '127.0.0.1:5175' }).next).toHaveBeenCalled()
  })

  it('refuses `Origin: null`, which is a sandboxed frame and not this page', () => {
    const result = call('/seam/v1/runs', { host: '127.0.0.1:5175', origin: 'null' })
    expect(result.status).toBe(403)
    expect(result.next).not.toHaveBeenCalled()
  })

  it('refuses a foreign Host on /api too, bound or not', () => {
    expect(call('/api/settings', { host: 'attacker.example' }).status).toBe(403)
    expect(call('/seam/health', { host: 'attacker.example' }).status).toBe(403)
    // A tailnet bind names one address; it does not turn every host into this machine.
    expect(call('/seam/health', { host: 'attacker.example' }, TAILNET).status).toBe(403)
  })

  it('answers the bind address and the names the operator allowed', () => {
    expect(call('/seam/health', { host: '100.86.176.62:5175' }, TAILNET).next).toHaveBeenCalled()
    expect(
      call('/seam/health', { host: 'machine.tailnet.ts.net:5175' }, TAILNET).next
    ).toHaveBeenCalled()
    // Loopback is always this machine.
    expect(call('/seam/health', { host: '127.0.0.1:5175' }, TAILNET).next).toHaveBeenCalled()
    expect(call('/seam/health', { host: '[::1]:5175' }, TAILNET).next).toHaveBeenCalled()
  })

  it('treats a wildcard bind as the addresses the machine actually holds', () => {
    const options: ProxyGuardOptions = {
      bindHost: '0.0.0.0',
      allowedHosts: ['localhost', '127.0.0.1'],
      localAddresses: ['127.0.0.1', '100.86.176.62', '::1']
    }
    expect(call('/seam/health', { host: '100.86.176.62:5175' }, options).next).toHaveBeenCalled()
    expect(call('/seam/health', { host: '198.51.100.7:5175' }, options).status).toBe(403)
  })

  it('leaves a path that only looks like a guarded prefix alone', () => {
    expect(onProxyPath('/seamless')).toBe(false)
    expect(call('/seamless', { host: 'attacker.example' }).next).toHaveBeenCalled()
    // The prefixes themselves are guarded, with a query string or without.
    expect(onProxyPath('/seam')).toBe(true)
    expect(onProxyPath('/api?x=1')).toBe(true)
  })
})

describe('originVerdict', () => {
  it('compares hosts, not spellings', () => {
    expect(originVerdict('http://127.0.0.1:5175', '127.0.0.1:5175')).toBe('same')
    expect(originVerdict('http://EXAMPLE.com:80', 'example.com')).toBe('same')
    expect(originVerdict('http://example.com:5175', 'example.com:5176')).toBe('foreign')
    expect(originVerdict(undefined, '127.0.0.1:5175')).toBe('absent')
  })
})

describe('hostIsThisMachine', () => {
  it('fails closed on a missing or unparseable Host', () => {
    expect(hostIsThisMachine(undefined, LOOPBACK)).toBe(false)
    expect(hostIsThisMachine('exa mple.com', LOOPBACK)).toBe(false)
  })
})

describe('the seam proxy request', () => {
  it('forwards Origin and drops only Referer', () => {
    const proxyReq = { removeHeader: vi.fn(), setHeader: vi.fn() }
    seamProxyRequestHandler('sk-live')(proxyReq)

    expect(proxyReq.removeHeader).not.toHaveBeenCalledWith('origin')
    expect(proxyReq.removeHeader).toHaveBeenCalledWith('referer')
    expect(proxyReq.setHeader).toHaveBeenCalledWith('authorization', 'Bearer sk-live')
  })

  it('adds no credential when the key opt-in is off', () => {
    const proxyReq = { removeHeader: vi.fn(), setHeader: vi.fn() }
    seamProxyRequestHandler('')(proxyReq)

    expect(proxyReq.setHeader).not.toHaveBeenCalled()
    expect(proxyReq.removeHeader).toHaveBeenCalledWith('referer')
  })

  it('wires that handler into the real `/seam` proxy, not a copy of it', () => {
    type RequestLike = {
      removeHeader: (name: string) => void
      setHeader: (name: string, value: string) => void
    }
    const handlers: ((proxyReq: RequestLike) => void)[] = []
    seamProxy['/seam'].configure({
      on: (_event, handler) => handlers.push(handler)
    })
    expect(handlers).toHaveLength(1)

    const proxyReq = { removeHeader: vi.fn(), setHeader: vi.fn() }
    handlers[0](proxyReq)
    expect(proxyReq.removeHeader).not.toHaveBeenCalledWith('origin')
  })
})

describe('the proxy guard is mounted on both servers the proxies serve', () => {
  it('is a plugin on the dev and the preview server alike', () => {
    const plugins = (config.plugins ?? []) as {
      name?: string
      configureServer?: unknown
      configurePreviewServer?: unknown
    }[]
    const guard = plugins.find(plugin => plugin?.name === 'pantler-guard-proxy')
    expect(guard).toBeDefined()
    expect(guard?.configureServer).toBeTypeOf('function')
    expect(guard?.configurePreviewServer).toBeTypeOf('function')
  })
})
