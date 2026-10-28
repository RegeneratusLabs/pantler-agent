import { describe, expect, it } from 'vitest'
import { TOUR } from '../onboarding/tour'
import { COMPOSER_PLACEHOLDER, exampleAsks } from './examples'

const WORKS = ['grow', 'make', 'move', ''] as const

describe('the new-chat examples', () => {
  it('gives each kind of business three finished prompts', () => {
    for (const work of WORKS) {
      const asks = exampleAsks(work)
      expect(asks).toHaveLength(3)
      expect(new Set(asks).size).toBe(3)
      for (const ask of asks) {
        // A sentence the operator could type as it stands, not a fragment or a feature name.
        expect(ask.trim()).toMatch(/[.?]$/)
        expect(ask.length).toBeLessThanOrEqual(100)
      }
    }
  })

  it('keeps a money job and two other jobs in every set', () => {
    for (const work of WORKS) {
      const asks = exampleAsks(work)
      // The first screen is not an invoice demo, but it does still show the money job.
      expect(asks.filter(ask => /^invoice/i.test(ask))).toHaveLength(1)
      expect(asks.filter(ask => !/^invoice/i.test(ask))).toHaveLength(2)
    }
  })

  it('keeps the organic-certification job in the grow set', () => {
    // The card the feature was asked for, not just any third prompt.
    expect(
      exampleAsks('grow').some(ask => ask.startsWith('My organic certification is coming up'))
    ).toBe(true)
  })

  it('does not use the demo customer in the copy', () => {
    for (const work of WORKS) {
      for (const ask of exampleAsks(work)) expect(ask).not.toMatch(/bellview/i)
    }
    expect(COMPOSER_PLACEHOLDER).not.toMatch(/bellview/i)
    for (const card of TOUR) expect(`${card.title} ${card.body}`).not.toMatch(/bellview/i)
  })

  it('has a short placeholder with two examples in it', () => {
    expect(COMPOSER_PLACEHOLDER.length).toBeLessThanOrEqual(80)
    expect(COMPOSER_PLACEHOLDER.match(/“/g)).toHaveLength(2)
    expect(COMPOSER_PLACEHOLDER).toContain('invoice the cafe')
    expect(COMPOSER_PLACEHOLDER).toContain('find the zucchini a home')
  })

  it('keeps the unanswered case non-empty and stable', () => {
    expect(exampleAsks('')).toEqual(exampleAsks(''))
    expect(exampleAsks('')).toHaveLength(3)
  })
})
