/**
 * The radiogroup's keyboard rule, as a pure function.
 *
 * There is no component runner in this repository (the internal audit WEB-16), so what is
 * tested is the part that decides: which card an arrow key moves to. The DOM half — focus and
 * click — is three lines around it.
 */

import { describe, expect, it } from 'vitest'
import { nextRadioIndex } from './kit'

describe('nextRadioIndex', () => {
  it('moves down and right, up and left', () => {
    expect(nextRadioIndex(0, 3, 'ArrowDown')).toBe(1)
    expect(nextRadioIndex(0, 3, 'ArrowRight')).toBe(1)
    expect(nextRadioIndex(2, 3, 'ArrowUp')).toBe(1)
    expect(nextRadioIndex(1, 3, 'ArrowLeft')).toBe(0)
  })

  it('wraps at both ends, as the pattern requires', () => {
    expect(nextRadioIndex(2, 3, 'ArrowDown')).toBe(0)
    expect(nextRadioIndex(0, 3, 'ArrowUp')).toBe(2)
  })

  it('ignores every other key', () => {
    for (const key of ['Tab', 'Enter', ' ', 'a', 'Escape']) {
      expect(nextRadioIndex(1, 3, key)).toBeNull()
    }
  })

  it('enters the group from outside it', () => {
    // Focus on the container rather than a card: the first arrow picks an end.
    expect(nextRadioIndex(-1, 3, 'ArrowDown')).toBe(0)
    expect(nextRadioIndex(-1, 3, 'ArrowUp')).toBe(2)
  })

  it('answers nothing for an empty group', () => {
    expect(nextRadioIndex(0, 0, 'ArrowDown')).toBeNull()
  })
})
