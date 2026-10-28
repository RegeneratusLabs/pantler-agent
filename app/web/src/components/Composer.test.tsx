// @vitest-environment jsdom
/**
 * The composer's one new input: a draft another screen hands over.
 *
 * The rule is "read once, on mount". The conversation is keyed by session, so a new session
 * mounts a new composer; a re-render of the same one must never replace what the operator has
 * typed since — which is exactly the bug a controlled-from-above draft would cause.
 */

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { UseDraftAttachments } from '../state/attachments'
import { Composer } from './Composer'

afterEach(cleanup)

const draft: UseDraftAttachments = {
  attachments: [],
  readyIds: [],
  busy: false,
  addFiles: vi.fn(),
  addBlob: vi.fn(),
  addUrl: vi.fn().mockResolvedValue(undefined),
  remove: vi.fn(),
  take: vi.fn().mockReturnValue([])
} as unknown as UseDraftAttachments

function draw(initialValue?: string) {
  return render(
    <Composer
      disabled={false}
      running={false}
      onStop={vi.fn()}
      draft={draft}
      onSend={vi.fn()}
      initialValue={initialValue}
    />
  )
}

describe('Composer drafts', () => {
  it('starts with the handed-over draft, ready to send', () => {
    draw('Schedule a job for me: ')

    const textarea = screen.getByRole('textbox') as HTMLTextAreaElement
    expect(textarea.value).toBe('Schedule a job for me: ')
    expect((screen.getByRole('button', { name: 'Send' }) as HTMLButtonElement).disabled).toBe(false)
  })

  it('does not overwrite what the operator typed when the prop changes', () => {
    const { rerender } = draw('Schedule a job for me: ')
    const textarea = screen.getByRole('textbox') as HTMLTextAreaElement
    fireEvent.change(textarea, { target: { value: 'Summarise the week' } })

    rerender(
      <Composer
        disabled={false}
        running={false}
        onStop={vi.fn()}
        draft={draft}
        onSend={vi.fn()}
        initialValue={undefined}
      />
    )

    expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('Summarise the week')
  })

  it('is an empty, disabled composer without a draft', () => {
    draw()
    expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('')
    expect((screen.getByRole('button', { name: 'Send' }) as HTMLButtonElement).disabled).toBe(true)
  })
})
