/**
 * The update feed is configuration, and configuration drifts silently.
 *
 * `electron-builder.yml` owns the URL the app reads `latest.yml` from; `package.json` owns the
 * updater dependency. Neither is exercised by the unit tests (the updater needs a packaged app and
 * a live feed), so the contract that can be checked cheaply — the feed is the public releases
 * page, and the dependency exists — is checked here.
 */

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const builder = readFileSync(new URL('../electron-builder.yml', import.meta.url), 'utf8')
const pkg = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8'))
const main = readFileSync(new URL('../src/main.mjs', import.meta.url), 'utf8')

test('the update feed is the public releases page', () => {
  assert.match(builder, /provider:\s*generic/)
  assert.match(
    builder,
    /url:\s*https:\/\/github\.com\/RegeneratusLabs\/pantler-agent\/releases\/latest\/download/
  )
})

test('the updater is a runtime dependency, not a dev one', () => {
  assert.ok(pkg.dependencies?.['electron-updater'], 'electron-updater must ship in the app')
  assert.ok(!pkg.devDependencies?.['electron-updater'], 'a dev dependency is pruned from the build')
})

test('the updater is loaded as CommonJS, lazily, not as a named export', () => {
  // electron-updater 6.x defines `autoUpdater` with Object.defineProperty on module.exports.
  // Node's ESM loader cannot see that as a named export, so `import { autoUpdater } from
  // 'electron-updater'` throws while the module graph links — before `boot` — and the installed
  // app never opens. v0.0.3 shipped exactly that. Two rules follow: the dependency is read
  // through its CommonJS default, and it is imported inside `startUpdates`, never at the top,
  // so a broken updater cannot take the window with it.
  assert.doesNotMatch(
    main,
    /from\s+['"]electron-updater['"]/,
    'a static import puts the updater in the link-time boot path'
  )
  assert.match(
    main,
    /const\s*\{\s*autoUpdater\s*\}\s*=\s*\(await import\(['"]electron-updater['"]\)\)\.default/
  )
})

test('a failed update load does not fail the boot', () => {
  assert.match(main, /await startUpdates\(\)\.catch\(/)
})

test('the installer build never publishes by itself', () => {
  // The release workflow uploads the assets it generated; a builder that also tried to publish
  // would race it and could overwrite a release from a developer's machine.
  assert.match(pkg.scripts['build:win'], /--publish never/)
})
