// @vitest-environment jsdom
/**
 * The clarifying-question card, from its props.
 *
 * The answer is the product: a choice's exact label, a JSON array for multi-select, or free
 * text. A wrong encoding would be accepted by the engine and mean something else, so the test
 * asserts the string that crosses the seam — not just that a button was clicked.
 */

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ClarifyPrompt } from '../seam/reducer'
import { ClarifyCard, multiAnswer, questionText } from './ClarifyCard'

afterEach(cleanup)

const prompt = (fields: Partial<ClarifyPrompt> = {}): ClarifyPrompt => ({
  key: 'q-1',
  promptId: 'prompt-1',
  executionGeneration: 2,
  question: 'Which do you want?\nReply "skip" to skip this question.',
  choices: ['Apples (Recommended)', 'Pears'],
  multiSelect: false,
  ...fields
})

const draw = (fields: Partial<ClarifyPrompt> = {}, onAnswer = vi.fn(async () => true)) => {
  render(<ClarifyCard prompt={prompt(fields)} onAnswer={onAnswer} />)
  return onAnswer
}

describe('clarifyQuestion', () => {
  it('removes the engine’s plain-text skip hint, which a card does not need', () => {
    expect(questionText('Which one?\nReply "skip" to skip this question.')).toBe('Which one?')
    expect(questionText('Which one?')).toBe('Which one?')
  })
})

describe('multiAnswer', () => {
  it('encodes the labels as the JSON array the tool parses', () => {
    expect(multiAnswer(['Apples', 'Pears'])).toBe('["Apples","Pears"]')
  })
})

describe('ClarifyCard', () => {
  it('shows the question without the skip hint and offers the engine’s choices', () => {
    draw()
    expect(screen.getByText('Which do you want?')).toBeTruthy()
    expect(screen.queryByText(/skip this question/)).toBeNull()
    expect(screen.getByText('Apples (Recommended)')).toBeTruthy()
    expect(screen.getByText('Pears')).toBeTruthy()
  })

  it('sends a single choice as its exact label', async () => {
    const onAnswer = draw()
    fireEvent.click(screen.getByText('Pears'))
    await waitFor(() => expect(onAnswer).toHaveBeenCalledWith('Pears'))
  })

  it('sends a multi-select answer as a JSON array', async () => {
    const onAnswer = draw({ multiSelect: true })
    fireEvent.click(screen.getByText('Apples (Recommended)'))
    fireEvent.click(screen.getByText('Pears'))
    fireEvent.click(screen.getByText('Send answer'))
    await waitFor(() => expect(onAnswer).toHaveBeenCalledWith('["Apples (Recommended)","Pears"]'))
  })

  it('adds typed free text to a multi-select answer', async () => {
    const onAnswer = draw({ multiSelect: true })
    fireEvent.click(screen.getByText('Pears'))
    fireEvent.change(screen.getByLabelText('Your answer'), { target: { value: 'Or a quince' } })
    fireEvent.click(screen.getByText('Send answer'))
    await waitFor(() => expect(onAnswer).toHaveBeenCalledWith('["Pears","Or a quince"]'))
  })

  it('sends an open-ended answer as the typed text', async () => {
    const onAnswer = draw({ choices: [] })
    fireEvent.change(screen.getByLabelText('Your answer'), { target: { value: '  A quince  ' } })
    fireEvent.click(screen.getByText('Send answer'))
    await waitFor(() => expect(onAnswer).toHaveBeenCalledWith('A quince'))
  })

  it('does not send an empty answer', () => {
    const onAnswer = draw({ choices: [] })
    expect(screen.getByText('Send answer')).toHaveProperty('disabled', true)
    expect(onAnswer).not.toHaveBeenCalled()
  })

  it('records the answer once the engine settles it', async () => {
    const onAnswer = vi.fn(async () => true)
    const { rerender } = render(<ClarifyCard prompt={prompt()} onAnswer={onAnswer} />)
    fireEvent.click(screen.getByText('Pears'))
    await waitFor(() => expect(onAnswer).toHaveBeenCalled())
    await waitFor(() => expect(screen.getByText(/Answer sent/)).toBeTruthy())
    rerender(<ClarifyCard prompt={prompt({ settled: true })} onAnswer={onAnswer} />)
    expect(screen.getByText('You answered: Pears')).toBeTruthy()
  })

  it('says the run moved on when the engine settled it unanswered', () => {
    draw({ settled: true })
    expect(screen.getByText(/moved on without an answer/)).toBeTruthy()
    expect(screen.queryByRole('button')).toBeNull()
  })

  it('says the run ended when it expired, and offers nothing to click', () => {
    draw({ expired: true })
    expect(screen.getByText(/run ended before this was answered/)).toBeTruthy()
    expect(screen.queryByRole('button')).toBeNull()
  })

  it('refuses to answer a prompt that carries no id', () => {
    draw({ promptId: null, executionGeneration: null })
    expect(screen.getByText(/cannot be answered from here/)).toBeTruthy()
    expect(screen.queryByText('Send answer')).toBeNull()
  })
})
