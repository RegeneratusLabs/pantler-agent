/**
 * The tab icon is a byte copy of the brand's compact favicon.
 *
 * A hand-drawn or hand-exported favicon is the easiest way to end up with a second version of
 * the mark, so the file is a copy and this test is the thing that notices when it stops being
 * one.
 */

import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const favicon = readFileSync(
  fileURLToPath(new URL('../../public/favicon.svg', import.meta.url)),
  'utf8'
)
const brandIcon = readFileSync(
  fileURLToPath(new URL('../../../../brand/logo/pantler-icon-compact-ink.svg', import.meta.url)),
  'utf8'
)
const index = readFileSync(fileURLToPath(new URL('../../index.html', import.meta.url)), 'utf8')

describe('favicon', () => {
  it('is the brand compact icon, unchanged', () => {
    expect(favicon).toBe(brandIcon)
  })

  it('is linked from the document', () => {
    expect(index).toContain('rel="icon"')
    expect(index).toContain('href="/favicon.svg"')
  })
})
