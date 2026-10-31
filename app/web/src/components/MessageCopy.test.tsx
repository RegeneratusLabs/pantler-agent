// @vitest-environment jsdom
/**
 * The copy control's contract: the clipboard gets the readable text, a refusal is said out loud,
 * and the plain-HTTP fallback is real. The fallback matters because the app is reached over the
 * tailnet on HTTP, where `navigator.clipboard` is not available.
 */

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MessageCopy } from './MessageCopy'

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.restoreAllMocks()
})

function defineClipboard(writeText: (text: string) => Promise<void>) {
  Object.defineProperty(navigator, 'clipboard', {
    configurable: true,
    value: { writeText }
  })
}

function defineExecCommand(result: boolean) {
  Object.defineProperty(document, 'execCommand', {
    configurable: true,
    value: vi.fn(() => result)
  })
}

describe('MessageCopy', () => {
  it('copies the text and reports it', async () => {
    const writeText = vi.fn(async () => undefined)
    defineClipboard(writeText)
    render(<MessageCopy text="A week of beans." label="Copy answer" />)

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Copy answer' }))
    })

    expect(writeText).toHaveBeenCalledWith('A week of beans.')
    expect(screen.getByText('Copied')).toBeTruthy()
  })

  it('returns to Copy after the confirmation', async () => {
    vi.useFakeTimers()
    defineClipboard(vi.fn(async () => undefined))
    render(<MessageCopy text="A week of beans." label="Copy answer" />)

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Copy answer' }))
      await Promise.resolve()
    })
    expect(screen.getByText('Copied')).toBeTruthy()

    act(() => vi.advanceTimersByTime(2000))
    expect(screen.getByText('Copy')).toBeTruthy()
  })

  it('falls back to execCommand when the clipboard API is refused', async () => {
    defineClipboard(vi.fn(async () => Promise.reject(new Error('denied'))))
    const exec = vi.fn(() => true)
    Object.defineProperty(document, 'execCommand', { configurable: true, value: exec })
    render(<MessageCopy text="Plain HTTP still copies." label="Copy answer" />)

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Copy answer' }))
    })

    expect(exec).toHaveBeenCalledWith('copy')
    expect(screen.getByText('Copied')).toBeTruthy()
  })

  it('says the copy failed when both routes fail', async () => {
    defineClipboard(vi.fn(async () => Promise.reject(new Error('denied'))))
    defineExecCommand(false)
    render(<MessageCopy text="Nothing works." label="Copy answer" />)

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Copy answer' }))
    })

    expect(screen.getAllByText('Copy failed').length).toBeGreaterThan(0)
  })

  it('renders nothing when there is no text to copy', () => {
    const { container } = render(<MessageCopy text="   " label="Copy answer" />)
    expect(container.textContent).toBe('')
  })
})
