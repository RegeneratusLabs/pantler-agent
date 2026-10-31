import { describe, expect, it } from 'vitest'
import { CONNECTORS } from '../pages/connectors'
import { CONNECTORS_SHOWN, connectorsToShow } from './apps'
import { STEPS, needsSetup, nextStep, previousStep, progressOf, stepIndex } from './flow'
import { DEFAULT_VOICE_ID, VOICES, instructions, isVoiceId, turnInstructions, voiceById } from './personalities'
import { TOUR } from './tour'
import { exampleAsks } from '../chat/examples'

describe('the first run', () => {
  it('asks six questions in a fixed order', () => {
    expect(STEPS.map(step => step.id)).toEqual(['welcome', 'business', 'voice', 'apps', 'tour', 'done'])
  })

  it('walks forward to the end and then stops', () => {
    let step = STEPS[0].id
    const walked: string[] = [step]
    for (let guard = 0; guard < 10 && step !== 'done'; guard += 1) {
      const next = nextStep(step)
      expect(next).not.toBeNull()
      step = next as (typeof STEPS)[number]['id']
      walked.push(step)
    }
    expect(walked).toEqual(STEPS.map(entry => entry.id))
    // The end is an end: nothing follows `done`, and the page finishes rather than looping.
    expect(nextStep('done')).toBeNull()
  })

  it('goes back the way it came, and the first step has nowhere to go back to', () => {
    expect(previousStep('welcome')).toBeNull()
    expect(previousStep('business')).toBe('welcome')
    expect(previousStep('done')).toBe('tour')
  })

  it('counts progress from one, for the people reading it', () => {
    expect(progressOf('welcome')).toEqual({ index: 1, total: 6 })
    expect(progressOf('done')).toEqual({ index: 6, total: 6 })
    expect(stepIndex('voice')).toBe(2)
  })

  it('gates on the one field that means finished', () => {
    expect(needsSetup({ complete: false })).toBe(true)
    expect(needsSetup({ complete: true })).toBe(false)
  })
})

describe('the voices', () => {
  it('offers exactly three, in a settled order, with unique ids', () => {
    expect(VOICES.map(voice => voice.id)).toEqual(['warm', 'brief', 'patient'])
    expect(new Set(VOICES.map(voice => voice.id)).size).toBe(3)
  })

  it('keeps the engine preset each one stands for', () => {
    // These are real Hermes built-ins (`hermes_cli/personality.py`); if upstream renames one, this
    // is where we find out rather than in a voice that quietly does nothing.
    expect(VOICES.map(voice => voice.preset)).toEqual(['helpful', 'concise', 'teacher'])
  })

  it('sends a different overlay for each, and none for no voice', () => {
    const texts = VOICES.map(voice => instructions(voice.id))
    for (const text of texts) expect(text.length).toBeGreaterThan(40)
    expect(new Set(texts).size).toBe(3)
    expect(instructions('')).toBe('')
    expect(instructions('pirate')).toBe('')
  })

  it('asks every turn for the markdown this window renders, even with no voice', () => {
    for (const voice of VOICES) {
      const text = turnInstructions(voice.id)
      expect(text).toContain(instructions(voice.id))
      expect(text).toContain('markdown')
    }
    // A turn with no stored voice still needs the surface instruction; the voice itself stays
    // empty, which is what "no overlay" means for the voice data.
    expect(turnInstructions('')).toContain('markdown')
    expect(turnInstructions('')).toContain('table')
    expect(instructions('')).toBe('')
  })

  it('shows a sample that is an answer, not a description of one', () => {
    for (const voice of VOICES) {
      expect(voice.sample.length).toBeGreaterThan(10)
      expect(voice.sample).toMatch(/[$.]|\d/)
    }
    expect(new Set(VOICES.map(voice => voice.sample)).size).toBe(3)
  })

  it('falls back to the default rather than throwing on a stale id', () => {
    expect(voiceById('nonsense').id).toBe(DEFAULT_VOICE_ID)
    expect(voiceById(null).id).toBe(DEFAULT_VOICE_ID)
    expect(isVoiceId('brief')).toBe(true)
    expect(isVoiceId('pirate')).toBe(false)
  })
})

describe('the apps step', () => {
  it('shows six, whatever the answer', () => {
    for (const work of ['grow', 'make', 'move', ''] as const) {
      expect(connectorsToShow(work)).toHaveLength(CONNECTORS_SHOWN)
      expect(connectorsToShow(work)).toHaveLength(6)
    }
  })

  it('leads with what that kind of work reaches for first', () => {
    // A grower's day starts in the inbox and the calendar; someone moving boxes starts with the till.
    expect(connectorsToShow('grow')[0].id).toBe('gmail')
    expect(connectorsToShow('move')[0].id).toBe('square')
    expect(connectorsToShow('make').map(c => c.id)).toContain('mailchimp')
  })

  it('never repeats an app, and never invents one', () => {
    const known = new Set(CONNECTORS.map(connector => connector.id))
    for (const work of ['grow', 'make', 'move', ''] as const) {
      const shown = connectorsToShow(work)
      expect(new Set(shown.map(c => c.id)).size).toBe(shown.length)
      for (const connector of shown) expect(known.has(connector.id)).toBe(true)
    }
  })

  it('still leads with the inbox when the question was not answered', () => {
    // No answer is not a reason for a different kind of first impression: email is the one app
    // every one of these businesses has, so it opens the step either way.
    expect(connectorsToShow('')[0].id).toBe('gmail')
    expect(connectorsToShow('grow')[0].id).toBe('gmail')
  })
})

describe('the tour', () => {
  it('has four cards, each naming the place it is about', () => {
    expect(TOUR.map(card => card.where)).toEqual(['Chat', 'Capabilities', 'Scheduled jobs', 'Settings'])
    expect(new Set(TOUR.map(card => card.id)).size).toBe(TOUR.length)
    for (const card of TOUR) expect(card.body.length).toBeGreaterThan(40)
  })

  it('suggests things to try for the work they said they do', () => {
    for (const work of ['grow', 'make', 'move', ''] as const) {
      const asks = exampleAsks(work)
      expect(asks).toHaveLength(3)
      // Each one is a sentence the operator could type as-is — a statement or a question, finished.
      for (const ask of asks) expect(ask.trim()).toMatch(/[.?]$/)
    }
    // The three kinds get three different openings; the unanswered case is not empty.
    expect(new Set([exampleAsks('grow')[0], exampleAsks('make')[0], exampleAsks('move')[0]]).size).toBe(3)
    expect(exampleAsks('')).toEqual(exampleAsks(''))
    expect(exampleAsks('').length).toBe(3)
  })
})
