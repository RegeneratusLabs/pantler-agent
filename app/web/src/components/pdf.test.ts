import { describe, expect, it } from 'vitest'
import { PAGE_RENDER_CAP, backingScale, canRenderPage, capNote, fitScale } from './pdf'

describe('fitScale', () => {
  it('fits a page to the column it is in', () => {
    expect(fitScale(600, 900)).toBeCloseTo(1.5)
    expect(fitScale(600, 300)).toBeCloseTo(0.5)
  })

  it('refuses to magnify a page past the cap', () => {
    expect(fitScale(100, 1000)).toBe(2)
    expect(fitScale(100, 1000, 3)).toBe(3)
  })

  it('refuses to shrink a page into a sliver', () => {
    expect(fitScale(10000, 10)).toBe(0.15)
  })

  it('answers something drawable before layout has happened', () => {
    expect(fitScale(600, 0)).toBe(0.15)
    expect(fitScale(0, 900)).toBe(1)
    expect(fitScale(Number.NaN, 900)).toBe(1)
  })
})

describe('backingScale', () => {
  it('multiplies the backing store for a dense screen, and clamps it', () => {
    expect(backingScale(1, 2)).toBe(2)
    expect(backingScale(1.5, 1)).toBe(1.5)
    expect(backingScale(1, 4)).toBe(3)
    expect(backingScale(1, 0)).toBe(1)
    expect(backingScale(1, Number.NaN)).toBe(1)
  })
})

describe('canRenderPage', () => {
  it('draws any page of a document that fits under the cap', () => {
    expect(canRenderPage(0, 10, false)).toBe(true)
    expect(canRenderPage(9, 10, false)).toBe(true)
  })

  it('stops at the cap, and keeps going when asked', () => {
    const total = PAGE_RENDER_CAP + 40
    expect(canRenderPage(PAGE_RENDER_CAP - 1, total, false)).toBe(true)
    expect(canRenderPage(PAGE_RENDER_CAP, total, false)).toBe(false)
    expect(canRenderPage(PAGE_RENDER_CAP, total, true)).toBe(true)
  })
})

describe('capNote', () => {
  it('says nothing about a document that is not capped', () => {
    expect(capNote(10)).toBeUndefined()
    expect(capNote(PAGE_RENDER_CAP)).toBeUndefined()
  })

  it('says what is happening, and the number, when it is', () => {
    const note = capNote(PAGE_RENDER_CAP + 5)
    expect(note).toContain(String(PAGE_RENDER_CAP))
    expect(note).toContain(String(PAGE_RENDER_CAP + 5))
  })
})
