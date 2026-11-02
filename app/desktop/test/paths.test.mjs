import assert from 'node:assert/strict'
import { mkdirSync, mkdtempSync, readFileSync, statSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import test from 'node:test'

import {
  desktopPaths,
  ensureDirectories,
  engineEnvironment,
  ensureEngineKey,
  freePort,
  installProfile,
  readEnvValue,
  waitForJson
} from '../src/paths.mjs'

test('the packaged layout keeps user data out of resources', () => {
  const paths = desktopPaths({
    userData: '/home/op/.config/pantler',
    resources: '/opt/pantler/resources',
    platform: 'linux',
    env: {}
  })
  assert.equal(paths.engineHome, '/home/op/.config/pantler/engine')
  assert.equal(paths.profileDir, '/home/op/.config/pantler/engine/profiles/pantler')
  assert.equal(paths.envFile, '/home/op/.config/pantler/engine/profiles/pantler/.env')
  assert.equal(paths.store, '/home/op/.config/pantler/engine/profiles/pantler/records.db')
  assert.equal(paths.shell, '/opt/pantler/resources/shell')
  assert.equal(paths.server, '/opt/pantler/resources/server')
  assert.equal(paths.packs, '/opt/pantler/resources/packs')
  assert.equal(paths.python, '/opt/pantler/resources/runtime/bin/python3')
  assert.equal(paths.engineBin, '/opt/pantler/resources/runtime/engine/.hermes/bin/hermes')
})

test('the platform picks the Windows executables and separators', () => {
  const paths = desktopPaths({
    userData: 'C:\\Users\\op\\AppData\\Roaming\\pantler',
    resources: 'C:\\Program Files\\pantler\\resources',
    platform: 'win32',
    env: {}
  })
  assert.ok(paths.python.endsWith('runtime\\python\\python.exe'))
  assert.ok(paths.engineBin.endsWith('hermes.exe'))
  assert.ok(paths.profileDir.includes('\\profiles\\pantler'))
})

test('environment overrides win, so development can point at the checkout', () => {
  const paths = desktopPaths({
    userData: '/u',
    resources: '/r',
    env: {
      PANTLER_ENGINE_HOME: '/repo/.hermes-dev',
      PANTLER_PYTHON: '/repo/python3',
      PANTLER_SERVER: '/repo/app/server',
      PANTLER_SHELL: '/repo/app/web/dist',
      PANTLER_PACKS: '/repo/packs',
      PANTLER_ENGINE_BIN: '/repo/.hermes-dev/src/hermes-agent/.hermes/bin/hermes'
    }
  })
  assert.equal(paths.engineHome, '/repo/.hermes-dev')
  assert.equal(paths.python, '/repo/python3')
  assert.equal(paths.server, '/repo/app/server')
  assert.equal(paths.shell, '/repo/app/web/dist')
  assert.equal(paths.packs, '/repo/packs')
  assert.equal(paths.engineBin, '/repo/.hermes-dev/src/hermes-agent/.hermes/bin/hermes')
})

test('ensureDirectories creates the profile and log directories', () => {
  const userData = mkdtempSync(path.join(tmpdir(), 'pantler-desktop-'))
  const paths = desktopPaths({ userData, resources: '/r', env: {} })
  ensureDirectories(paths)
  assert.ok(statSync(paths.profileDir).isDirectory())
  assert.ok(statSync(paths.logs).isDirectory())
})

test('the engine key is created once, 0600, and never duplicated', () => {
  const userData = mkdtempSync(path.join(tmpdir(), 'pantler-desktop-'))
  const paths = ensureDirectories(desktopPaths({ userData, resources: '/r', env: {} }))

  const first = ensureEngineKey(paths.envFile)
  assert.match(first, /^[A-Za-z0-9_-]{32,}$/)
  assert.equal(readEnvValue(paths.envFile, 'API_SERVER_KEY'), first)
  // POSIX permission bits are not a Windows concept; the file is still created owner-only by the
  // OS's own rules, and asserting 0600 there would fail for a reason that is not a defect.
  if (process.platform !== 'win32') {
    assert.equal(statSync(paths.envFile).mode & 0o777, 0o600)
  }

  const second = ensureEngineKey(paths.envFile)
  assert.equal(second, first)
  const lines = readFileSync(paths.envFile, 'utf8')
    .split('\n')
    .filter(line => line.startsWith('API_SERVER_KEY='))
  assert.equal(lines.length, 1)
})

test('an existing key in the profile is used as it is', () => {
  const userData = mkdtempSync(path.join(tmpdir(), 'pantler-desktop-'))
  const paths = ensureDirectories(desktopPaths({ userData, resources: '/r', env: {} }))
  ensureEngineKey(paths.envFile, { generate: () => 'fixed-key-for-a-test' })
  assert.equal(readEnvValue(paths.envFile, 'API_SERVER_KEY'), 'fixed-key-for-a-test')
})

test('freePort returns a port the OS accepted', async () => {
  const port = await freePort()
  assert.ok(Number.isInteger(port) && port > 0)
})

test('waitForJson resolves on the first 2xx answer', async () => {
  const calls = []
  const fetchImpl = async url => {
    calls.push(url)
    return calls.length < 3
      ? { ok: false, status: 503 }
      : { ok: true, json: async () => ({ ready: true }) }
  }
  const body = await waitForJson('http://127.0.0.1:1/api/health', {
    fetchImpl,
    intervalMs: 1,
    timeoutMs: 1_000
  })
  assert.deepEqual(body, { ready: true })
  assert.equal(calls.length, 3)
})

test('waitForJson times out with the last failure in the message', async () => {
  const fetchImpl = async () => {
    throw new Error('connection refused')
  }
  await assert.rejects(
    waitForJson('http://127.0.0.1:1/api/health', { fetchImpl, intervalMs: 1, timeoutMs: 20 }),
    /timed out waiting for .*connection refused/
  )
})

test('installProfile copies the template once and never overwrites the operator', () => {
  const userData = mkdtempSync(path.join(tmpdir(), 'pantler-desktop-'))
  const template = path.join(userData, 'template')
  const paths = ensureDirectories(
    desktopPaths({ userData, resources: '/r', env: { PANTLER_PROFILE_TEMPLATE: template } })
  )

  // No payload template yet: nothing to install, and that is not an error.
  assert.equal(installProfile(paths), false)

  mkdirSync(template, { recursive: true })
  writeFileSync(path.join(template, 'config.yaml'), 'name: pantler\n')
  assert.equal(installProfile(paths), true)
  assert.equal(readFileSync(path.join(paths.profileDir, 'config.yaml'), 'utf8'), 'name: pantler\n')

  // A second run is a no-op: an existing profile belongs to the operator.
  writeFileSync(path.join(paths.profileDir, 'config.yaml'), 'name: theirs\n')
  assert.equal(installProfile(paths), false)
  assert.equal(readFileSync(path.join(paths.profileDir, 'config.yaml'), 'utf8'), 'name: theirs\n')
})

test('the engine is told its home and its API port', () => {
  const paths = desktopPaths({ userData: '/u', resources: '/r', env: {} })
  const env = engineEnvironment(paths, { PATH: '/usr/bin' }, 4321)
  assert.equal(env.HERMES_HOME, paths.engineHome)
  assert.equal(env.API_SERVER_PORT, '4321')
  assert.ok(env.PATH.includes('/usr/bin'), 'the inherited PATH is kept after the python dir')
})
