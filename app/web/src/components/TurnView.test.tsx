// @vitest-environment jsdom
/**
 * One turn, as the operator reads it.
 *
 * The renderer has its own suite; this is the wiring that matters to the product: the assistant's
 * answer goes through the chat markdown scale, while the operator's own message stays the words
 * they typed. A regression here would either show the answer as source or turn a pasted
 * `**asterisk**` in the operator's message into emphasis — two different mistakes.
 */

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createRunState } from '../seam/reducer'
import type { Turn } from '../state/useConversation'
import { TurnView } from './TurnView'

// The media row is a separate component with its own provider; this suite is about the turn's text.
vi.mock('./MediaFigure', () => ({ MediaFigures: () => null }))

afterEach(cleanup)

function turn(output: string, input = ''): Turn {
  return {
    id: 'turn-1',
    input,
    state: { ...createRunState('run-1'), phase: 'completed', output },
    streaming: false
  }
}

const answer = async () => true
const clarify = async () => true
const stop = () => {}

describe('TurnView', () => {
  it('renders the assistant answer as chat markdown', () => {
    const { container } = render(
      <TurnView
        turn={turn(
          '# Weekly totals\n\n**Bellview CSA** owes:\n\n- 12 kg beans\n- 4 dozen eggs\n\n' +
            '| Item | Amount |\n| --- | --- |\n| Beans | $144.00 |'
        )}
        onAnswer={answer}
        onClarify={clarify}
        onStop={stop}
      />
    )

    expect(container.querySelector('h2')?.textContent).toBe('Weekly totals')
    expect(container.querySelectorAll('li')).toHaveLength(2)
    expect(container.querySelectorAll('strong')).toHaveLength(1)
    expect(container.querySelector('table')).not.toBeNull()
    expect(container.textContent).not.toContain('**Bellview')
    expect(container.textContent).not.toContain('| Item |')
  })

  it('leaves the operator’s own message as the words they typed', () => {
    const { container } = render(
      <TurnView
        turn={turn('An answer.', 'What is **this**?')}
        onAnswer={answer}
        onClarify={clarify}
        onStop={stop}
      />
    )

    expect(container.textContent).toContain('What is **this**?')
    expect(container.querySelector('strong')).toBeNull()
  })
})


describe('TurnView copy controls', () => {
  function clipboard(writeText: (text: string) => Promise<void>) {
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
  }

  it('copies the assistant answer as readable text, without media directives', async () => {
    const writeText = vi.fn(async () => undefined)
    clipboard(writeText)
    render(
      <TurnView
        turn={turn('**Two cards are ready.**\n\nMEDIA:/tmp/card.png')}
        onAnswer={answer}
        onClarify={clarify}
        onStop={stop}
      />
    )

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Copy answer' }))
    })

    expect(writeText).toHaveBeenCalledWith('Two cards are ready.')
  })

  it('copies the operator’s own words exactly', async () => {
    const writeText = vi.fn(async () => undefined)
    clipboard(writeText)
    render(
      <TurnView
        turn={turn('An answer.', 'What is **this**?')}
        onAnswer={answer}
        onClarify={clarify}
        onStop={stop}
      />
    )

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Copy your message' }))
    })

    expect(writeText).toHaveBeenCalledWith('What is **this**?')
  })

  it('has no copy control when the turn has no text', () => {
    render(<TurnView turn={turn('')} onAnswer={answer} onClarify={clarify} onStop={stop} />)
    expect(screen.queryByRole('button', { name: 'Copy answer' })).toBeNull()
  })
})
