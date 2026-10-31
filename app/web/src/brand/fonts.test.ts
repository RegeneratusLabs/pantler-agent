/**
 * The type pipeline, without a browser.
 *
 * A font that 404s looks exactly like one that did not load, and the brand rules are easy to
 * break by copying a path that is one directory off. These are the two mechanical checks: every
 * declared file exists, and the shell uses the brand token rather than a second, private stack.
 */

import { existsSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const FONTS_CSS = fileURLToPath(new URL('../fonts.css', import.meta.url))
const STYLES_CSS = fileURLToPath(new URL('../styles.css', import.meta.url))

const fonts = readFileSync(FONTS_CSS, 'utf8')
const styles = readFileSync(STYLES_CSS, 'utf8')

describe('fonts.css', () => {
  it('declares both display instances at 400 and 500', () => {
    expect(fonts.match(/font-family: 'Pantler Soft';/g)).toHaveLength(2)
    expect(fonts.match(/font-family: 'Pantler Soft Small';/g)).toHaveLength(2)
    expect(fonts.match(/font-weight: 400;/g)).toHaveLength(2)
    expect(fonts.match(/font-weight: 500;/g)).toHaveLength(2)
  })

  it('points every url at a file that exists in the brand package', () => {
    const urls = [...fonts.matchAll(/url\('([^']+)'\)/g)].map(match => match[1])
    expect(urls.length).toBeGreaterThan(0)
    for (const url of urls) {
      const file = fileURLToPath(new URL(url, new URL('../fonts.css', import.meta.url)))
      expect(existsSync(file), `${url} resolves to ${file}`).toBe(true)
    }
  })

  it('does not drag the unused variable files into the build', () => {
    expect(fonts).not.toContain('fraunces-variable')
    expect(fonts).not.toContain('fraunces-italic')
  })
})

describe('styles.css', () => {
  it('imports the brand tokens and the display faces', () => {
    expect(styles).toContain("@import '../../../brand/tokens/brand-tokens.css';")
    expect(styles).toContain("@import './fonts.css';")
  })

  it('uses the brand UI stack instead of a private one', () => {
    expect(styles).toContain('--font-sans: var(--pl-font-ui);')
    expect(styles).not.toContain('Collapse')
  })

  it('defines both display utilities without a colour of their own', () => {
    expect(styles).toContain('@utility brand-display {')
    expect(styles).toContain('@utility brand-display-sm {')
    expect(styles).toContain('font-synthesis: none;')
  })

  it('uses the brand uppercase tracking, not the old 0.05em', () => {
    const block = styles.match(/@utility text-display \{([\s\S]*?)\n\}/)?.[1] ?? ''
    expect(block).toContain('letter-spacing: 0.26em;')
    expect(block).not.toContain('0.05em;')
  })

  it('sets body copy from the brand scale', () => {
    const body = styles.match(/body \{([\s\S]*?)\n  \}/)?.[1] ?? ''
    expect(body).toContain('font-size: var(--pl-body);')
  })
})
