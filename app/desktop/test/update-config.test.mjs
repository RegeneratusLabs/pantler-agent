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

test('the installer build never publishes by itself', () => {
  // The release workflow uploads the assets it generated; a builder that also tried to publish
  // would race it and could overwrite a release from a developer's machine.
  assert.match(pkg.scripts['build:win'], /--publish never/)
})
