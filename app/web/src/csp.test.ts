/**
 * The CSP and `index.html` cannot drift.
 *
 * The built shell's script policy is a hash of the inline first-paint theme script: change the
 * script and the hash has to change with it, or the theme silently stops being applied. This
 * test recomputes the hash from the file and asserts the header still carries it — the same
 * check the BFF's own CSP comment promises for the shell it serves with `--static`
 * (`the internal security audit A19-WEB-5`).
 */

import { existsSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import config, {
  DEV_SECURITY_HEADERS,
  inlineScripts,
  scriptHash,
  SHELL_SECURITY_HEADERS
} from '../vite.config'

const here = (relative: string) => fileURLToPath(new URL(relative, import.meta.url))

const shellCsp = SHELL_SECURITY_HEADERS['Content-Security-Policy'] ?? ''
const devCsp = DEV_SECURITY_HEADERS['Content-Security-Policy'] ?? ''

describe('the shell’s Content-Security-Policy', () => {
  it('carries the hash of every inline script in index.html', () => {
    const scripts = inlineScripts(readFileSync(here('../index.html'), 'utf8'))
    expect(scripts.length).toBeGreaterThan(0)
    for (const script of scripts) {
      expect(shellCsp).toContain(`'${scriptHash(script)}'`)
    }
  })

  it('would catch a changed script, because the hash is of the exact text', () => {
    const script = inlineScripts(readFileSync(here('../index.html'), 'utf8'))[0]
    expect(shellCsp).not.toContain(`'${scriptHash(`${script}\n`)}'`)
  })

  it('names the built shell’s inline script too, when there is a build to check', () => {
    // A stale `dist` is the finding A19-WEB-6: the hash is computed from source, so a `dist`
    // that no longer matches source would be served under a policy that does not describe it.
    const dist = here('../dist/index.html')
    if (!existsSync(dist)) return
    for (const script of inlineScripts(readFileSync(dist, 'utf8'))) {
      expect(shellCsp).toContain(`'${scriptHash(script)}'`)
    }
  })

  it('keeps the strict script policy for the built shell and relaxes only dev', () => {
    expect(shellCsp).toContain("script-src 'self' 'sha256-")
    expect(shellCsp).not.toContain("script-src 'self' 'unsafe-inline'")
    // Vite's dev server injects the Fast Refresh preamble inline, so `vite dev` names no hash:
    // `'unsafe-inline'` is ignored when one is present, so it is one or the other.
    expect(devCsp).toContain("script-src 'self' 'unsafe-inline'")
    expect(devCsp).not.toContain('sha256-')
  })

  it('refuses framing in the header as well as the directive', () => {
    for (const headers of [SHELL_SECURITY_HEADERS, DEV_SECURITY_HEADERS]) {
      expect(headers['Content-Security-Policy']).toContain("frame-ancestors 'none'")
      expect(headers['X-Frame-Options']).toBe('DENY')
      expect(headers['X-Content-Type-Options']).toBe('nosniff')
      expect(headers['Referrer-Policy']).toBe('no-referrer')
    }
  })

  it('is wired into both servers the shell is served from', () => {
    expect(config.server?.headers).toEqual(DEV_SECURITY_HEADERS)
    expect(config.preview?.headers).toEqual(SHELL_SECURITY_HEADERS)
  })
})
