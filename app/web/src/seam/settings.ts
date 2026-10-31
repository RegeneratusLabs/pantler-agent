/**
 * Where the engine is and how we authenticate to it.
 *
 * Read by the shell's footer, the capabilities page and every query hook. **Nothing in the UI
 * writes it any more**: Settings → Connection is gone, because the address is `/seam` — forwarded
 * by the app's own server — and the key is that server's (`vite.config.ts` reads it from the
 * profile's `.env`), so neither is the browser's to set. What is still read here is a value a
 * previous build stored, and the default below, so an install that was pointed somewhere once
 * keeps working.
 *
 * **A stored key is not read, and a stored address is not trusted.** `loadSettings` used to
 * spread whatever JSON was in `localStorage` over these defaults, and `client.ts` attached
 * `Bearer <apiKey>` to whatever address came out — so a stored
 * `{"baseUrl":"https://attacker.example","apiKey":"…"}` posted the key to that host. Nothing in
 * this build writes one; the shape is still read, so it is read carefully
 * (the internal security audit A19-WEB-4).
 */

export interface SeamSettings {
  baseUrl: string
  /**
   * A key the app may hold **in memory** — the Electron shell tier is where a secret is allowed
   * to live (the desktop notes). It is never read from, or written to, `localStorage` here.
   */
  apiKey: string
}

/**
 * Same-origin by default: the app forwards `/seam` to the engine itself, so a browser on
 * another device needs no CORS configuration and the engine stays bound to loopback.
 * An absolute URL here talks to a gateway directly instead — which does need CORS, and which
 * nothing in this build offers a way to type.
 */
export const DEFAULT_SETTINGS: SeamSettings = {
  baseUrl: '/seam',
  apiKey: ''
}

const SETTINGS_KEY = 'pantler.seam.settings'

/**
 * Whether a base URL is one a key may travel to: this document's own origin, or this machine's
 * loopback. Anything else is a host that has no business holding the credential, whatever wrote
 * the setting (the internal security audit A19-WEB-4).
 *
 * `ownOrigin` is passed in rather than reached for, so this is testable without a browser.
 */
export function isTrustedBaseUrl(baseUrl: string, ownOrigin?: string): boolean {
  const value = (baseUrl ?? '').trim()
  if (!value) return false

  // A path is on this document's own origin. `//host` is protocol-relative — a URL, not a path.
  if (value.startsWith('/')) return !value.startsWith('//') && !/[\s\\]/.test(value)

  try {
    const parsed = new URL(value)
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return false
    // `fetch` refuses a URL carrying credentials anyway; treat it as not an address of ours.
    if (parsed.username || parsed.password) return false
    if (ownOrigin && parsed.origin === ownOrigin) return true
    return (
      parsed.hostname === 'localhost' ||
      parsed.hostname === '127.0.0.1' ||
      parsed.hostname === '[::1]'
    )
  } catch {
    return false
  }
}

/**
 * Read what an earlier build stored, and believe none of it.
 *
 * Every failure — absent, malformed JSON, the wrong shape, an address that is not ours — is the
 * default, because the alternative is a client pointed somewhere the operator did not choose.
 * The key is dropped even when the address is fine: nothing here has a use for a persisted one.
 */
export function loadSettings(): SeamSettings {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY)
    if (!raw) return DEFAULT_SETTINGS

    const parsed: unknown = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return DEFAULT_SETTINGS

    const baseUrl = (parsed as { baseUrl?: unknown }).baseUrl
    if (typeof baseUrl !== 'string' || !isTrustedBaseUrl(baseUrl)) return DEFAULT_SETTINGS
    return { baseUrl: baseUrl.trim(), apiKey: '' }
  } catch {
    return DEFAULT_SETTINGS
  }
}

/** Persists the address only. A key is not this store's to keep (the internal security audit A19-WEB-4). */
export function saveSettings(settings: SeamSettings): void {
  try {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify({ baseUrl: settings.baseUrl }))
  } catch {
    // A browser refusing storage must not block connecting.
  }
}
