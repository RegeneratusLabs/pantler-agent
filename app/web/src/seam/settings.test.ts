/**
 * What the app reads back from `localStorage`.
 *
 * The settings shape is legacy — nothing in this build writes a key — which is exactly why it is
 * read defensively: a stored `{"baseUrl":"https://attacker.example","apiKey":"…"}` used to point
 * the client at that host and post the key to it
 * (the internal security audit A19-WEB-4). The storage is stubbed, so this runs in the
 * node environment the rest of the suite uses.
 */

import { afterEach, describe, expect, it, vi } from 'vitest'
import { DEFAULT_SETTINGS, isTrustedBaseUrl, loadSettings, saveSettings } from './settings'

const SETTINGS_KEY = 'pantler.seam.settings'

function stubStorage(initial: Record<string, string> = {}) {
  const values = new Map(Object.entries(initial))
  const storage = {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => void values.set(key, value),
    removeItem: (key: string) => void values.delete(key),
    clear: () => values.clear(),
    key: (index: number) => [...values.keys()][index] ?? null,
    get length() {
      return values.size
    }
  }
  vi.stubGlobal('localStorage', storage)
  return { storage, values }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('loadSettings', () => {
  it('is the default when nothing was stored', () => {
    stubStorage()
    expect(loadSettings()).toEqual(DEFAULT_SETTINGS)
  })

  it('is the default for anything that is not the shape it expects', () => {
    for (const raw of ['not json', 'null', '42', '"a string"', '[]', '{"baseUrl":42}', '{}']) {
      stubStorage({ [SETTINGS_KEY]: raw })
      expect(loadSettings(), raw).toEqual(DEFAULT_SETTINGS)
    }
  })

  it('honours a same-origin path and a loopback address', () => {
    stubStorage({ [SETTINGS_KEY]: '{"baseUrl":"/seam"}' })
    expect(loadSettings().baseUrl).toBe('/seam')

    stubStorage({ [SETTINGS_KEY]: '{"baseUrl":"http://127.0.0.1:8644"}' })
    expect(loadSettings().baseUrl).toBe('http://127.0.0.1:8644')
  })

  it('refuses an address that is not this origin or loopback', () => {
    for (const baseUrl of [
      'https://attacker.example',
      '//attacker.example/seam',
      'file:///etc/passwd',
      'seam',
      ''
    ]) {
      stubStorage({ [SETTINGS_KEY]: JSON.stringify({ baseUrl }) })
      expect(loadSettings(), baseUrl).toEqual(DEFAULT_SETTINGS)
    }
  })

  it('never returns a stored key, even when the address is ours', () => {
    stubStorage({ [SETTINGS_KEY]: '{"baseUrl":"/seam","apiKey":"sk-secret"}' })
    expect(loadSettings()).toEqual({ baseUrl: '/seam', apiKey: '' })

    // The exact shape the audit executed: an absolute address beside a key.
    stubStorage({
      [SETTINGS_KEY]: '{"baseUrl":"https://attacker.example","apiKey":"sk-secret"}'
    })
    expect(loadSettings()).toEqual(DEFAULT_SETTINGS)
  })
})

describe('saveSettings', () => {
  it('writes the address only', () => {
    const { values } = stubStorage()
    saveSettings({ baseUrl: '/seam', apiKey: 'sk-secret' })

    expect(JSON.parse(values.get(SETTINGS_KEY) ?? '')).toEqual({ baseUrl: '/seam' })
    expect(values.get(SETTINGS_KEY)).not.toContain('sk-secret')
  })
})

describe('isTrustedBaseUrl', () => {
  it('accepts a path on this origin and this machine’s loopback', () => {
    expect(isTrustedBaseUrl('/seam')).toBe(true)
    expect(isTrustedBaseUrl('  /seam  ')).toBe(true)
    expect(isTrustedBaseUrl('http://127.0.0.1:8644')).toBe(true)
    expect(isTrustedBaseUrl('http://localhost:8644')).toBe(true)
    expect(isTrustedBaseUrl('http://[::1]:8644')).toBe(true)
    expect(isTrustedBaseUrl('http://127.0.0.1:8644', 'http://127.0.0.1:8644')).toBe(true)
  })

  it('refuses everything else, protocol-relative paths included', () => {
    for (const baseUrl of [
      'https://attacker.example',
      '//attacker.example',
      '/se am',
      '/seam\\..',
      'seam',
      '',
      'javascript:alert(1)',
      'http://user:pw@127.0.0.1:8644'
    ]) {
      expect(isTrustedBaseUrl(baseUrl), baseUrl).toBe(false)
    }
  })

  it('accepts this document’s own origin whatever it is', () => {
    expect(isTrustedBaseUrl('http://192.168.1.20:5175', 'http://192.168.1.20:5175')).toBe(true)
    expect(isTrustedBaseUrl('http://192.168.1.21:5175', 'http://192.168.1.20:5175')).toBe(false)
  })
})
