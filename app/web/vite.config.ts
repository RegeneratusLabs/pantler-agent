import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { networkInterfaces } from 'node:os'
import { fileURLToPath } from 'node:url'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import type { Plugin } from 'vite'
import { defineConfig } from 'vitest/config'

const shared = fileURLToPath(new URL('../shared/src', import.meta.url))
const identity = fileURLToPath(new URL('../identity/identity.mjs', import.meta.url))

/**
 * Where the app listens, and where it forwards the engine's API.
 *
 * Both are environment-driven so that reaching the app from another device is a command,
 * not an edit:
 *
 *   PANTLER_BIND=100.86.176.62   bind the Tailscale address only — reachable from the
 *                                  tailnet, NOT from the LAN this machine also sits on
 *   PANTLER_API_TARGET=…         where the engine actually listens (loopback by default)
 *   PANTLER_ALLOWED_HOSTS=…      extra Host headers Vite will answer to
 *   PANTLER_PROXY_API_KEY=1      let the proxy supply the engine's key, read from the
 *                                  profile's .env (a literal key works too). Off by
 *                                  default: see the note on `resolveEngineKey` below
 *
 * See "Reaching it from another device" in app/README.md.
 */
const bindHost = process.env.PANTLER_BIND ?? '127.0.0.1'
const apiTarget = process.env.PANTLER_API_TARGET ?? 'http://127.0.0.1:8644'
const bffTarget = process.env.PANTLER_BFF_TARGET ?? 'http://127.0.0.1:8650'
const extraHosts = (process.env.PANTLER_ALLOWED_HOSTS ?? '')
  .split(',')
  .map(host => host.trim())
  .filter(Boolean)

/**
 * The engine's API key, held by the DEV SERVER and never by the browser.
 *
 * The obvious way to remove the "paste the key" step is to bake the key into the bundle.
 * This does something strictly better: the proxy adds the Authorization header on the way
 * through, so the key is never sent to, stored in, or readable from a browser. It cannot
 * leak through localStorage, the network tab, a saved page or a screenshot, and it does not
 * end up in a bundle anyone can download.
 *
 * Read from the profile's `.env` rather than from the command line, so the key never
 * appears in `ps` output either.
 *
 * What this trades away is real and worth stating: with the proxy supplying the key,
 * **anyone who can reach this port has full use of the agent.** The network becomes the
 * access control. It used to be on by default — any `npm run dev` handed the agent to whoever
 * could reach :5175, and `PANTLER_BIND` widened that to a tailnet — so it is an explicit opt-in
 * now: `PANTLER_PROXY_API_KEY=1` reads the key from the profile's `.env`, or pass the key itself.
 * Without the opt-in the shell gets the engine's own 401 and says so, which is the honest
 * failure. The proxy also refuses a non-loopback Host unless `PANTLER_BIND` was set
 * (the internal audit WIRE-3). In Phase 1 the Electron shell does this job, and the
 * renderer never holds the key either.
 */
function resolveEngineKey(): string {
  const optIn = process.env.PANTLER_PROXY_API_KEY
  if (!optIn) return ''
  if (optIn !== '1') return optIn.trim()

  const envFile =
    process.env.PANTLER_ENV_FILE ??
    fileURLToPath(new URL('../../.hermes-dev/profiles/pantler/.env', import.meta.url))

  try {
    for (const line of readFileSync(envFile, 'utf8').split('\n')) {
      if (line.startsWith('API_SERVER_KEY=')) return line.slice('API_SERVER_KEY='.length).trim()
    }
  } catch {
    // No profile env: the proxy supplies nothing, and the app finds out the honest way —
    // a request without a key comes back 401 or 403, which is what the shell reports.
  }
  return ''
}

/**
 * A release build must not ship placeholder identifiers (the design notes §8): an app id, bundle id,
 * user-data directory or update-feed channel cannot be changed after release without orphaning
 * user data and breaking updates. The module exported `PLACEHOLDER` for this and nothing read it
 * (the internal audit IDN-1), so the build refuses now — `vite build`, and only a build:
 * `dev` and `test` run against placeholders by design.
 */
function refusePlaceholderIdentity(): Plugin {
  return {
    name: 'pantler-refuse-placeholder-identity',
    apply: 'build',
    async buildStart() {
      const module = await import('../identity/identity.mjs')
      if (module.PLACEHOLDER && process.env.PANTLER_ALLOW_PLACEHOLDER !== '1') {
        this.error(
          'identity.mjs still holds placeholder identifiers (the design notes §8). Set them before ' +
            'building a release, or build with PANTLER_ALLOW_PLACEHOLDER=1 for a throwaway. ' +
            'See the internal audit IDN-1.'
        )
      }
    }
  }
}

// ------------------------------------------------------------ security headers

/**
 * The shell's Content-Security-Policy.
 *
 * `index.html` has exactly one inline script — the first-paint theme — and a hash names it
 * exactly: `script-src 'self'` alone would refuse it, and `'unsafe-inline'` would refuse
 * nothing. The hash is computed from the file itself (below), so the policy cannot drift from
 * the document it describes; `src/csp.test.ts` recomputes it and checks the string still
 * carries it (the internal security audit A19-WEB-5).
 *
 * `frame-src http: https:` is the website preview's frame. `frame-ancestors 'none'` plus
 * `X-Frame-Options: DENY` is the finding's own answer: the approve, stop and delete controls
 * cannot be clicked through from a page that framed this one.
 *
 * One consequence is accepted rather than worked around: a document rendered in the pane from
 * `srcdoc` inherits this policy, so in the built shell its inline scripts are refused (the frame
 * still renders, and the pane shows the source first). Exempting it would mean `'unsafe-inline'`
 * for this shell's own scripts too, which is the whole thing the hash is for.
 */
export function contentSecurityPolicy(
  scriptHashes: readonly string[],
  options: { dev?: boolean } = {}
): string {
  // Vite's dev server injects `@vitejs/plugin-react`'s Fast Refresh preamble as an inline
  // module script, and there is no nonce to name it by — so `vite dev` relaxes this one
  // directive. `'unsafe-inline'` is ignored whenever a hash is present, so it is one spelling
  // or the other, never both; the built shell (`vite preview`, the BFF's `--static`) keeps the
  // hash. Everything else is identical in both.
  const scriptSrc = options.dev
    ? "script-src 'self' 'unsafe-inline'"
    : `script-src 'self'${scriptHashes.map(hash => ` '${hash}'`).join('')}`

  return [
    "default-src 'self'",
    scriptSrc,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "media-src 'self' blob:",
    "font-src 'self' data:",
    "connect-src 'self'",
    "frame-src http: https:",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'none'",
    "frame-ancestors 'none'"
  ].join('; ')
}

/** Every `<script>` in `index.html` that carries its code inline rather than a `src`. */
export function inlineScripts(html: string): string[] {
  const found: string[] = []
  const tag = /<script\b([^>]*)>([\s\S]*?)<\/script>/gi
  for (let match = tag.exec(html); match !== null; match = tag.exec(html)) {
    if (!/\bsrc\s*=/i.test(match[1])) found.push(match[2])
  }
  return found
}

/** A script's CSP hash, spelled the way a browser compares it: `sha256-` and base64. */
export function scriptHash(script: string): string {
  return `sha256-${createHash('sha256').update(script, 'utf8').digest('base64')}`
}

const indexHtml = readFileSync(fileURLToPath(new URL('index.html', import.meta.url)), 'utf8')
const themeScriptHashes = inlineScripts(indexHtml).map(scriptHash)

/** The headers the built shell is served with — the same set the BFF's `--static` sends. */
export const SHELL_SECURITY_HEADERS: Record<string, string> = {
  'Content-Security-Policy': contentSecurityPolicy(themeScriptHashes),
  'X-Content-Type-Options': 'nosniff',
  'Referrer-Policy': 'no-referrer',
  'X-Frame-Options': 'DENY'
}

/** The same set for `vite dev`, with the one script-src relaxation Fast Refresh forces. */
export const DEV_SECURITY_HEADERS: Record<string, string> = {
  ...SHELL_SECURITY_HEADERS,
  'Content-Security-Policy': contentSecurityPolicy(themeScriptHashes, { dev: true })
}

const engineKey = resolveEngineKey()
const proxySuppliesAuth = engineKey.length > 0

/**
 * The engine's API, forwarded under `/seam`.
 *
 * The proxy exists so that a browser on another device talks to ONE origin. That matters
 * because the engine's tool surface — `terminal`, `code_execution` — must not be reachable
 * from the tailnet directly. Only this dev server is.
 *
 * `Origin` is **forwarded, not dropped**. It used to be dropped, on the argument that the
 * proxied path was gated by the key below — but the key is attached to every request the proxy
 * forwards, so the gate was "can the caller reach this port", and `Origin` is the engine's only
 * cross-site check. A hostile page could reach the port with a CORS-simple `text/plain` POST
 * (no preflight), and the engine parses the body regardless of the declared type, so one page
 * view started an agent run (the internal security audit A19-WEB-1). Now the proxy refuses
 * a request whose `Origin` is not its own `Host` before forwarding it (`guardProxyRequest`
 * below), and forwards the `Origin` it accepted, so the engine's own allow-list still applies.
 * That means the app's origin has to be in `API_SERVER_CORS_ORIGINS` — the tailnet name included
 * when the app is reached by one.
 *
 * `Referer` is still dropped: nothing behind this proxy reads it, and the engine's check is on
 * `Origin`.
 */
interface ProxyRequest {
  removeHeader: (name: string) => void
  setHeader: (name: string, value: string) => void
}
interface ProxyLike {
  on: (event: 'proxyReq', handler: (proxyReq: ProxyRequest) => void) => void
}

/**
 * What the proxy does to each `/seam` request on its way to the engine.
 *
 * Exported for its test, and because the one thing it must never do again is remove `Origin`.
 */
export function seamProxyRequestHandler(key: string): (proxyReq: ProxyRequest) => void {
  return proxyReq => {
    proxyReq.removeHeader('referer')
    if (key) {
      // Replace whatever the browser sent, so a stale or wrong stored key cannot shadow the
      // real one.
      proxyReq.removeHeader('authorization')
      proxyReq.setHeader('authorization', `Bearer ${key}`)
    }
  }
}

export const seamProxy = {
  '/seam': {
    target: apiTarget,
    changeOrigin: false,
    ws: false,
    rewrite: (path: string) => path.replace(/^\/seam/, ''),
    configure: (proxy: ProxyLike) => {
      proxy.on('proxyReq', seamProxyRequestHandler(engineKey))
    }
  }
}

/**
 * The BFF, forwarded under `/api`.
 *
 * This is the shell's own backend, not the engine's — records, packs, and whatever a pack
 * declares. Kept on its own prefix so the two are never confused: `/seam/api/...` reaches
 * the *engine's* `/api` routes (jobs, sessions), while `/api/...` reaches ours.
 *
 * Proxied rather than called cross-origin so the shell has exactly one origin to reason
 * about, which is what makes the phone tier a deployment question rather than a rewrite.
 */
const bffProxy = {
  '/api': {
    target: bffTarget,
    changeOrigin: false
  }
}

/**
 * Host names this dev server answers to.
 *
 * `PANTLER_ALLOWED_HOSTS` is the deliberate escape hatch for the tailnet: the README's Tailscale
 * command passes the machine's `*.ts.net` name here. A blanket `.ts.net` wildcard used to sit in
 * this list, which made every host under that domain "ours"; a name is one environment variable
 * away, so it is named only when it is meant (the internal security audit A19-WEB-2).
 */
const allowedHosts = ['localhost', '127.0.0.1', ...extraHosts]

// ---------------------------------------------------------------- the proxy door

/**
 * The one door both proxied prefixes come through.
 *
 * A browser sends `Origin` on every non-GET it makes, and `Host` names the address the request
 * was addressed to. For a request this app's own page made, the two agree; for a page from
 * somewhere else — which can reach this port with a CORS "simple" request the browser never
 * preflights — they do not. Refusing the mismatch is what keeps the engine's own origin check
 * alive, and applying it to `/api` as well means the BFF is not the only guard on the prefix
 * that carries the record writes (the internal security audit A19-WEB-1/-2).
 *
 * A request with **no** `Origin` is not refused here: curl, a script and some same-origin GETs
 * send none, and each server behind this proxy has its own origin and write guards. This door
 * answers the cross-site browser case and leaves the rest to them.
 */
export interface GuardedRequest {
  url?: string
  headers: {
    host?: string | string[] | undefined
    origin?: string | string[] | undefined
  }
}

export interface GuardedResponse {
  statusCode: number
  setHeader: (name: string, value: string) => void
  end: (body?: string) => void
}

export interface ProxyGuardOptions {
  /** The address this dev server was told to listen on (`PANTLER_BIND`, loopback by default). */
  bindHost: string
  /** Host names this app answers to: the built-ins plus `PANTLER_ALLOWED_HOSTS`. */
  allowedHosts: readonly string[]
  /** Addresses this machine holds. Only consulted for a wildcard bind. */
  localAddresses?: readonly string[]
}

/**
 * The prefixes this dev server forwards. Matching is on a path segment, so `/seamless` is not
 * one of ours.
 */
export const PROXY_PREFIXES = ['/seam', '/api'] as const

export function onProxyPath(url: string): boolean {
  return PROXY_PREFIXES.some(
    prefix => url === prefix || url.startsWith(`${prefix}/`) || url.startsWith(`${prefix}?`)
  )
}

/**
 * A host as a URL spells it — lower case, default port dropped, an IPv6 literal bracketed — or
 * `undefined` when it is not a host at all, so a missing or malformed header fails closed.
 */
export function hostKey(value: unknown): string | undefined {
  const raw = String(value ?? '').trim()
  if (!raw) return undefined
  for (const spelling of raw.startsWith('[') ? [raw] : [raw, `[${raw}]`]) {
    try {
      // Parse it the way the browser did: this strips a default port and folds case. The second
      // spelling is a bare IPv6 literal (`::1`), which a URL needs bracketed.
      return new URL(`http://${spelling}`).host.toLowerCase()
    } catch {
      // Try the next spelling; a value that parses as neither is not a host.
    }
  }
  return undefined
}

/** The name part of a `hostKey`: no port, no IPv6 brackets. */
function hostName(key: string): string {
  return key.replace(/:\d+$/, '').replace(/^\[|\]$/g, '')
}

/** A bind of `0.0.0.0` or `::` is every interface, which is not a name any Host will carry. */
function isWildcardBind(name: string): boolean {
  return name === '0.0.0.0' || name === '::'
}

/** Every address this machine holds — what "this machine" means when the bind was a wildcard. */
function machineAddresses(): string[] {
  const addresses = new Set<string>()
  for (const entries of Object.values(networkInterfaces())) {
    for (const entry of entries ?? []) addresses.add(entry.address)
  }
  return [...addresses]
}

/** Vite's own wildcard spelling: a leading dot means that domain and everything under it. */
function hostPatternMatches(pattern: string, name: string): boolean {
  const candidate = pattern.trim().toLowerCase()
  if (!candidate) return false
  if (candidate.startsWith('.')) return name === candidate.slice(1) || name.endsWith(candidate)
  return name === candidate
}

/**
 * Whether a request's `Host` names this machine.
 *
 * The bind address is what `PANTLER_BIND` asked for, so a deliberate tailnet bind answers its own
 * address; loopback always answers; a wildcard bind answers the addresses the machine actually
 * holds. `PANTLER_ALLOWED_HOSTS` names anything else, which is how the tailnet name is admitted.
 * A host that is none of those is someone else's name for this port — DNS rebinding, or a proxy
 * in front of it — and is refused.
 */
export function hostIsThisMachine(host: string | undefined, options: ProxyGuardOptions): boolean {
  const key = hostKey(host)
  if (!key) return false
  const name = hostName(key)
  if (name === 'localhost' || name === '127.0.0.1' || name === '::1') return true

  const bind = hostKey(options.bindHost)
  const bindName = bind ? hostName(bind) : ''
  if (bind && isWildcardBind(bindName)) {
    const addresses = options.localAddresses ?? machineAddresses()
    if (addresses.some(address => hostName(hostKey(address) ?? '') === name)) return true
  } else if (bindName && name === bindName) {
    return true
  }

  return options.allowedHosts.some(pattern => hostPatternMatches(pattern, name))
}

export type OriginVerdict = 'absent' | 'same' | 'foreign'

/**
 * Whether a request's `Origin` names the same host as its `Host` header.
 *
 * `absent` is not a pass for the servers behind the proxy — it is a pass *to* them. `null` and
 * anything unparseable are `foreign`: a sandboxed frame sends `Origin: null`, and a browser that
 * cannot spell its own origin is not this page.
 */
export function originVerdict(
  origin: string | string[] | undefined,
  host: string | string[] | undefined
): OriginVerdict {
  if (Array.isArray(origin) || Array.isArray(host)) return 'foreign'
  const value = String(origin ?? '').trim()
  if (!value) return 'absent'

  let parsed: URL
  try {
    parsed = new URL(value)
  } catch {
    return 'foreign'
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return 'foreign'

  const target = hostKey(host)
  return target && parsed.host.toLowerCase() === target ? 'same' : 'foreign'
}

function refuse(res: GuardedResponse, message: string): void {
  res.statusCode = 403
  res.setHeader('Content-Type', 'text/plain; charset=utf-8')
  res.end(message)
}

/**
 * The middleware itself, exported so it can be driven in a test without a socket.
 *
 * Order matters: the `Origin` check first, because a foreign origin is the cross-site case this
 * exists for, then the host check, which is the DNS-rebinding case.
 */
export function guardProxyRequest(
  req: GuardedRequest,
  res: GuardedResponse,
  next: () => void,
  options: ProxyGuardOptions
): void {
  if (!req.url || !onProxyPath(req.url)) return next()

  if (originVerdict(req.headers.origin, req.headers.host) === 'foreign') {
    refuse(
      res,
      'This proxy only forwards requests whose Origin is its own host. ' +
        'A page from another site cannot reach the engine or the app’s records through it.\n'
    )
    return
  }

  if (!hostIsThisMachine(Array.isArray(req.headers.host) ? undefined : req.headers.host, options)) {
    refuse(
      res,
      'The /seam and /api proxies serve this machine only. ' +
        'Set PANTLER_BIND to the address you want it reachable on, and PANTLER_ALLOWED_HOSTS ' +
        'to the name you will reach it by.\n'
    )
    return
  }

  return next()
}

/**
 * Mount the door on `vite dev` and `vite preview` alike: `preview` serves the built shell and
 * forwards the same two prefixes, so it needs the same guard.
 */
export function guardProxy(options: ProxyGuardOptions): Plugin {
  const middleware = (req: GuardedRequest, res: GuardedResponse, next: () => void): void => {
    guardProxyRequest(req, res, next, options)
  }
  return {
    name: 'pantler-guard-proxy',
    configureServer(server) {
      server.middlewares.use(middleware)
    },
    configurePreviewServer(server) {
      server.middlewares.use(middleware)
    }
  }
}

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    refusePlaceholderIdentity(),
    guardProxy({ bindHost, allowedHosts })
  ],
  resolve: {
    alias: {
      // The pack and the wire contract are source-only packages: no build step, consumed
      // directly. They move to app/shared as a real workspace package when the Electron
      // shell arrives in Phase 1 and needs them too.
      '@shared': shared,
      '@identity': identity
    }
  },
  server: {
    host: bindHost,
    port: 5175,
    // Fail loudly rather than silently moving ports: the address is given to a person.
    strictPort: true,
    // The dev server serves the brand package's fonts and wordmark SVGs straight from
    // `brand/`, outside this package root. Allowing the repository root keeps one copy of the
    // assets rather than a duplicated public tree; the build reads the same files through the
    // CSS and module graph.
    fs: {
      allow: [fileURLToPath(new URL('../../..', import.meta.url))]
    },
    // Vite refuses unknown Host headers (DNS-rebinding protection). The tailnet name is
    // not localhost, so it has to be named in PANTLER_ALLOWED_HOSTS.
    allowedHosts,
    // The shell's headers (the internal security audit A19-WEB-5). `dev` because the dev
    // server injects the Fast Refresh preamble as an inline script; the built shell keeps the
    // strict script policy.
    headers: DEV_SECURITY_HEADERS,
    proxy: { ...seamProxy, ...bffProxy }
  },
  preview: {
    host: bindHost,
    port: 5175,
    strictPort: true,
    allowedHosts,
    // `vite preview` serves `dist`, which is the built shell the BFF's `--static` serves too, so
    // it gets the strict policy.
    headers: SHELL_SECURITY_HEADERS,
    proxy: { ...seamProxy, ...bffProxy }
  },
  build: {
    outDir: 'dist',
    // Source maps are 4.2 MB of the original TypeScript (the internal audit WEB-15).
    // That is a reasonable thing to want while debugging and a poor thing to hand the phone
    // tier on every load, so it is opt-in: `PANTLER_SOURCEMAP=1 npm run build`.
    sourcemap: process.env.PANTLER_SOURCEMAP === '1'
  },
  test: {
    // The reducer is pure — it needs no DOM, so the default environment stays honest.
    // `node`, because there is no DOM here — but component tests are possible: React renders to
    // a string with `react-dom/server`, which is enough to assert what a component *draws* from
    // its props. Effects do not run in that mode, so a hook's own logic is tested as the pure
    // functions it was extracted into (`state/stream.ts`, `seam/reducer.ts`,
    // `state/transcript.ts`) and a DOM-rendering suite still needs a `jsdom` dependency the
    // repository does not have (the internal audit WEB-16).
    environment: 'node',
    include: ['src/**/*.test.{ts,tsx}'],
    setupFiles: ['src/test-setup.ts']
  }
})

if (proxySuppliesAuth && bindHost !== '127.0.0.1' && bindHost !== 'localhost') {
  console.warn(
    `\n  ⚠  ${bindHost} is serving the engine's key to every request.\n` +
      `     Anyone who can reach this port has full use of the agent — including its\n` +
      `     terminal and code-execution tools. Keep the bind to your tailnet, and\n` +
      `     restrict the port with a Tailscale ACL if the tailnet is not all yours.\n` +
      `     Keep PANTLER_PROXY_API_KEY unset to serve no key at all.\n`
  )
}
