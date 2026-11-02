#!/usr/bin/env node
/**
 * The identity module's two files must agree.
 *
 * `app/identity/identity.d.mts` declares `Identity`, `PLACEHOLDER` and the default export by hand
 * beside `identity.mjs`, and nothing checked the pair — so a field could be added to the object
 * and never to the type, or declared in the type and never set
 * (the internal audit IDN-3). This is the check, and `scripts/test.sh web` runs it.
 *
 * It also asserts the one thing the module's own docstring claims: that the placeholder flag is
 * still true while the identifiers are placeholders. A release build refusing on a *stale* flag
 * would be worse than no guard.
 */
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const MODULE = path.join(HERE, '..', 'app', 'identity')
// A bare Windows path is not a valid ESM specifier; the URL form is.
const { identity, PLACEHOLDER } = await import(
  pathToFileURL(path.join(MODULE, 'identity.mjs')).href
)

const declared = readFileSync(path.join(MODULE, 'identity.d.mts'), 'utf8')
const interfaceBody = declared.match(/export interface Identity \{([\s\S]*?)\n\}/)
if (!interfaceBody) {
  console.error('identity-check: identity.d.mts declares no Identity interface')
  process.exit(1)
}
const fields = [...interfaceBody[1].matchAll(/^\s{2}([A-Za-z_][A-Za-z0-9_]*)\??:/gm)].map(m => m[1])
const actual = Object.keys(identity)

const missingFromType = actual.filter(key => !fields.includes(key))
const missingFromObject = fields.filter(key => !actual.includes(key))
const problems = []
if (missingFromType.length) {
  problems.push(`set in identity.mjs but not declared in Identity: ${missingFromType.join(', ')}`)
}
if (missingFromObject.length) {
  problems.push(`declared in Identity but not set in identity.mjs: ${missingFromObject.join(', ')}`)
}
if (!declared.includes('export declare const PLACEHOLDER: boolean')) {
  problems.push('identity.d.mts does not declare PLACEHOLDER')
}
if (problems.length) {
  for (const problem of problems) console.error(`identity-check: ${problem}`)
  process.exit(1)
}

const placeholders = Object.entries(identity).filter(
  ([, value]) => typeof value === 'string' && value.includes('placeholder')
)
if (placeholders.length > 0 && !PLACEHOLDER) {
  console.error(
    `identity-check: PLACEHOLDER is false while ${placeholders.length} identifier(s) still say ` +
      `"placeholder" (${placeholders.map(([key]) => key).join(', ')}) — a release build would pass`
  )
  process.exit(1)
}
console.log(
  `identity-check: ${actual.length} fields agree with identity.d.mts, PLACEHOLDER=${PLACEHOLDER}` +
    (placeholders.length ? ` (${placeholders.length} still placeholders)` : '')
)
