// @vitest-environment jsdom
/**
 * One turn, as the operator reads it.
 *
 * The renderer has its own suite; this is the wiring that matters to the product: the assistant's
 * answer goes through the chat markdown scale, while the operator's own message stays the words
 * they typed. A regression here would either show the answer as source or turn a pasted
 * `**asterisk**` in the operator's message into emphasis — two different mistakes.
 */

import { cleanup, render } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { createRunState } from '../seam/reducer'
import type { Turn } from '../state/useConversation'
import { TurnView } from './TurnView'

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
