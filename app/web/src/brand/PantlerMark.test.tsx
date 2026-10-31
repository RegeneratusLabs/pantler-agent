/**
 * What the mark draws, and the promise that it is still the brand's mark.
 *
 * There is no DOM in the default environment, so these render with `react-dom/server`: no
 * effects, no events, just the markup. That is enough to pin the two things that would be easy
 * to break by accident — the canonical geometry, and the true holes that make the face work on
 * any surface.
 */

import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { PantlerMark } from './PantlerMark'

const asset = readFileSync(
  fileURLToPath(new URL('../../../../brand/logo/pantler-mark-ink.svg', import.meta.url)),
  'utf8'
)

const draw = (props: Parameters<typeof PantlerMark>[0] = {}) =>
  renderToStaticMarkup(<PantlerMark {...props} />)

const HIDDEN_STEM = 'M0,-214 L0,-240'

/** Every path in the shipped mark except the invisible construction stub. */
const canonicalPaths = [
  ...new Set([...asset.matchAll(/\sd="([^"]+)"/g)].map(match => match[1]))
].filter(path => path !== HIDDEN_STEM)

describe('PantlerMark', () => {
  it('draws every canonical path from the brand asset, verbatim', () => {
    const html = draw()
    expect(canonicalPaths.length).toBeGreaterThanOrEqual(4)
    for (const path of canonicalPaths) expect(html).toContain(path)
    expect(html).not.toContain(HIDDEN_STEM)
  })

  it('keeps the feet, stem and leaves exactly where the asset puts them', () => {
    const html = draw()
    for (const fragment of [
      'x="-118.0" y="6" width="52.0" height="18" rx="9"',
      'x="66.0" y="6" width="52.0" height="18" rx="9"',
      'translate(-24,-268) rotate(-52)',
      'translate(24,-268) rotate(52)',
      'stroke-width="15"',
      'stroke-width="6.6"'
    ]) {
      expect(asset).toContain(fragment)
      expect(html).toContain(fragment)
    }
  })

  it('idles with the brand eyes and smile, as true holes', () => {
    const html = draw()
    expect(html).toContain('M-26.0,-60 C-13.0,-47 13.0,-47 26.0,-60')
    expect(html).toContain('cx="-52" cy="-86" rx="13" ry="13"')
    expect(html).toContain('cx="52" cy="-86" rx="13" ry="13"')
    // A mask, not a white face: the eyes are black shapes in the mask and the body is filled.
    expect(html).toContain('<mask')
    expect(html).toContain('maskUnits="userSpaceOnUse"')
    expect(html).toMatch(/mask="url\(#pl-mark-/)
  })

  it('works with half-lidded eyes and a flat mouth, not the smile', () => {
    const html = draw({ state: 'working' })
    expect(html).toContain('rx="22" ry="5"')
    expect(html).toContain('ry="5"')
    expect(html).not.toContain('M-26.0,-60 C-13.0,-47 13.0,-47 26.0,-60')
  })

  it('listens with a small round mouth and the one permitted tilt', () => {
    const html = draw({ state: 'listening' })
    expect(html).toContain('rotate(-7 0 60)')
    expect(html).toContain('rx="9" ry="9"')
    expect(html).toContain('rx="14.5"')
  })

  it('grins with a wider smile and two wheat cheeks', () => {
    const html = draw({ state: 'done' })
    expect(html).toContain('translate(0 -60) scale(1.15 1.25) translate(0 60)')
    expect(html).toContain('var(--pl-wheat)')
    expect(html).toContain('rx="5" ry="5"')
  })

  it('frowns, dimmed, when a run fails', () => {
    const html = draw({ state: 'cant' })
    expect(html).toContain('translate(0 -60) scale(1 -1) translate(0 60)')
    expect(html).toContain('opacity="0.55"')
  })

  it('wears the monocle without moving the loaf', () => {
    const html = draw({ outfit: 'monocle' })
    expect(html).toContain('data-outfit="monocle"')
    expect(html).toContain('stroke="var(--pl-cut)"')
    expect(html).toContain('r="26"')
    for (const path of canonicalPaths) expect(html).toContain(path)
  })

  it('is a bare loaf unless a costume is asked for', () => {
    expect(draw()).not.toContain('data-outfit')
    expect(draw({ outfit: 'none' })).not.toContain('data-outfit')
  })

  it('fattens the chain for a small mark and thins it for a large one', () => {
    expect(draw({ outfit: 'monocle', size: 32 })).toContain('stroke-width="9"')
    expect(draw({ outfit: 'monocle', size: 64 })).toContain('stroke-width="5"')
  })

  it('uses the brand tokens rather than hard-coded brand hexes', () => {
    const html = draw({ state: 'done' })
    expect(html).toContain('var(--pl-mark)')
    expect(html).toContain('var(--pl-cream)')
    expect(html).toContain('var(--pl-wheat)')
    for (const hex of ['#1B2420', '#F7EFDF', '#C9922E']) expect(html).not.toContain(hex)
  })

  it('has no type in the artwork', () => {
    expect(draw()).not.toMatch(/<text[\s>]/)
  })

  it('gives every instance its own mask', () => {
    const html = renderToStaticMarkup(
      <>
        <PantlerMark />
        <PantlerMark state="working" />
      </>
    )
    const ids = [...html.matchAll(/id="(pl-mark-[^"]+)"/g)].map(match => match[1])
    expect(ids).toHaveLength(2)
    expect(new Set(ids).size).toBe(2)
  })

  it('animates the working face and leaves the resting faces still', () => {
    expect(draw({ state: 'working' })).toContain('mascot-thinking')
    for (const state of ['idle', 'listening', 'done', 'cant'] as const) {
      expect(draw({ state })).not.toContain('mascot-thinking')
    }
  })

  it('is a labelled button when interactive and decorative when not', () => {
    const button = draw({ interactive: true, state: 'working' })
    expect(button).toContain('<button')
    expect(button).toContain('type="button"')
    expect(button).toContain('aria-label="Pantler — working"')

    const art = draw()
    expect(art).not.toContain('<button')
    expect(art).toContain('aria-hidden="true"')
  })
})
