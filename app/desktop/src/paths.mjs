/**
 * The desktop shell's paths, key handling and readiness probes.
 *
 * Everything here is Electron-free on purpose: the parts that decide *where* things live and
 * *when* a child is ready are the parts worth testing, and they are testable on the machine that
 * builds the installer rather than only on a Windows VM.
 *
 * The packaged layout is a contract with `scripts/build-windows-payload.ps1`:
 *
 *   <resources>/shell/          the built web bundle
 *   <resources>/server/         the BFF
 *   <resources>/packs/          the pack declarations
 *   <resources>/runtime/        CPython, the engine source at the pin, its site-packages, launcher
 *   <userData>/engine/          HERMES_HOME — the profile, sessions, records, credentials
 *   <userData>/logs/            child output, rotated by the supervisor
 *
 * User data never lives under resources: an update replaces the payload, and the operator's
 * business must survive it (the desktop notes §3).
 */

import { createServer } from 'node:net'
import { appendFileSync, cpSync, existsSync, mkdirSync, readFileSync } from 'node:fs'
import { randomBytes } from 'node:crypto'
import path from 'node:path'

export const PROFILE_NAME = 'pantler'

/** Where every file the shell touches lives. Overridable for development and for tests. */
export function desktopPaths({ userData, resources, platform = process.platform, env = process.env }) {
  // The separator follows the *target* platform, not the host: the tests for the Windows layout
  // run on Linux, and a Windows build must not inherit a POSIX path because a developer was on
  // macOS when the installer was assembled.
  const p = platform === 'win32' ? path.win32 : path.posix
  const engineHome = env.PANTLER_ENGINE_HOME || p.join(userData, 'engine')
  const profileDir = p.join(engineHome, 'profiles', PROFILE_NAME)
  const runtime = env.PANTLER_RUNTIME || p.join(resources, 'runtime')
  return {
    userData,
    resources,
    engineHome,
    profileDir,
    profile: PROFILE_NAME,
    envFile: p.join(profileDir, '.env'),
    store: env.PANTLER_STORE || p.join(profileDir, 'records.db'),
    logs: p.join(userData, 'logs'),
    shell: env.PANTLER_SHELL || p.join(resources, 'shell'),
    server: env.PANTLER_SERVER || p.join(resources, 'server'),
    packs: env.PANTLER_PACKS || p.join(resources, 'packs'),
    // The payload stages the interpreter as `runtime/python/python.exe` (the whole uv
    // standalone directory); the POSIX source build keeps its interpreter at `bin/python3`.
    python:
      env.PANTLER_PYTHON ||
      (platform === 'win32'
        ? p.join(runtime, 'python', 'python.exe')
        : p.join(runtime, 'bin', 'python3')),
    // The payload launches the bundled interpreter with this shim, never a venv executable:
    // Windows refuses a venv's redirector under a packaged interpreter (BUILDING.md).
    launcher: env.PANTLER_LAUNCHER || p.join(runtime, 'launcher.py'),
    // A profile as it came out of `profile install`, copied on first run. Copying is what keeps
    // first run offline and immediate; the engine's own installer is not invoked on the
    // operator's machine.
    profileTemplate:
      env.PANTLER_PROFILE_TEMPLATE || p.join(runtime, 'profile-template'),
    engineBin:
      env.PANTLER_ENGINE_BIN ||
      p.join(runtime, 'engine', '.hermes', 'bin', platform === 'win32' ? 'hermes.exe' : 'hermes')
  }
}

/**
 * Give the profile directory the template on first run.
 *
 * Nothing is merged and nothing is overwritten: a directory that already has a `config.yaml` is
 * the operator's, and an update never touches it. Returns true when it copied.
 */
export function installProfile(paths) {
  if (existsSync(path.join(paths.profileDir, 'config.yaml'))) return false
  if (!existsSync(paths.profileTemplate)) return false
  mkdirSync(paths.profileDir, { recursive: true })
  cpSync(paths.profileTemplate, paths.profileDir, { recursive: true })
  return true
}

/** Create the directories a first run needs. Idempotent; returns the paths for convenience. */
export function ensureDirectories(paths) {
  for (const directory of [paths.userData, paths.engineHome, paths.profileDir, paths.logs]) {
    mkdirSync(directory, { recursive: true })
  }
  return paths
}

/** One `KEY=value` from an env file, or "". Never prints the value. */
export function readEnvValue(file, name) {
  if (!existsSync(file)) return ''
  for (const line of readFileSync(file, 'utf8').split(/\r?\n/)) {
    if (line.startsWith(`${name}=`)) return line.slice(name.length + 1).trim()
  }
  return ''
}

/**
 * The engine's API key, created on first run if the profile has none.
 *
 * The shell owns secrets, not the renderer and not the BFF's arguments (`desktop-app.md` §3, item
 * 2): the key is written to the profile's `.env`, which is where the engine reads it, and the BFF
 * reads the same file on the way through `/seam`.
 */
export function ensureEngineKey(envFile, { generate = defaultKey } = {}) {
  const existing = readEnvValue(envFile, 'API_SERVER_KEY')
  if (existing) return existing
  const key = generate()
  mkdirSync(path.dirname(envFile), { recursive: true })
  appendFileSync(envFile, `API_SERVER_KEY=${key}\n`, { mode: 0o600 })
  return key
}

function defaultKey() {
  return randomBytes(32).toString('base64url')
}

/** A port the OS says is free right now. */
export function freePort(host = '127.0.0.1') {
  return new Promise((resolve, reject) => {
    const server = createServer()
    server.unref()
    server.once('error', reject)
    server.listen(0, host, () => {
      const { port } = server.address()
      server.close(() => resolve(port))
    })
  })
}

/**
 * Poll a JSON endpoint until it answers 2xx, the deadline passes, or the caller gives up.
 *
 * Readiness is a positive answer from the child, not "the process exists": an engine that has not
 * loaded its profile yet, and a BFF that has not built its registry, both accept a socket before
 * they can answer, and a window that opens against that shows an error the operator caused
 * nothing of.
 */
export async function waitForJson(
  url,
  { fetchImpl = fetch, timeoutMs = 120_000, intervalMs = 400, headers = {}, signal } = {}
) {
  const deadline = Date.now() + timeoutMs
  let lastError = null
  while (Date.now() < deadline) {
    if (signal?.aborted) throw new Error('readiness check aborted')
    try {
      const response = await fetchImpl(url, { headers, signal })
      if (response.ok) return await response.json()
      lastError = new Error(`${url} answered ${response.status}`)
    } catch (error) {
      lastError = error
    }
    await new Promise(resolve => setTimeout(resolve, intervalMs))
  }
  throw new Error(`timed out waiting for ${url}: ${lastError?.message ?? 'no answer'}`)
}

/**
 * The environment the engine child needs: its own home, the profile selectable by name, and the
 * API server's port.
 *
 * The port is explicit because the engine's API server defaults to 8642 while the dev box's
 * multiplexer listens on 8644 — a packaged app that assumed the dev number waits forever for a
 * server that is fine, just elsewhere.
 */
export function engineEnvironment(paths, base = process.env, port = null) {
  const env = { ...base, HERMES_HOME: paths.engineHome }
  if (port) env.API_SERVER_PORT = String(port)
  // A Windows console is cp1252 by default, and the engine and BFF print characters it cannot
  // encode (a warning sign is enough); the child dies on its own startup banner. UTF-8 mode is
  // Python's own answer and costs nothing.
  env.PYTHONUTF8 = '1'
  env.PYTHONIOENCODING = 'utf-8'
  const separator = process.platform === 'win32' ? ';' : ':'
  const pythonDir = path.dirname(paths.python)
  env.PATH = [pythonDir, env.PATH || ''].filter(Boolean).join(separator)
  return env
}

/**
 * The BFF's environment: the payload's site-packages, so `import pantler_core` works.
 *
 * The BFF is run as a script (`python pantler_server.py`), so its own directory is already on
 * `sys.path`; the kernel is not, and the payload ships it in the shared dependency tree.
 */
export function bffEnvironment(paths, base = process.env) {
  const separator = process.platform === 'win32' ? ';' : ':'
  const site = path.join(paths.resources, 'runtime', 'site-packages')
  return {
    ...base,
    PYTHONPATH: [site, base.PYTHONPATH].filter(Boolean).join(separator),
    // See engineEnvironment: a cp1252 console turns one warning sign into a dead process.
    PYTHONUTF8: '1',
    PYTHONIOENCODING: 'utf-8'
  }
}
