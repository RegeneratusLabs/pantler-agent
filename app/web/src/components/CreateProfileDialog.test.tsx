// @vitest-environment jsdom
/**
 * The new-profile form, on its own. The two rules worth pinning: the profile is copied from the
 * installed product, so there is no source to choose; and the form starts clean every time it
 * opens, because the component stays mounted behind the closed dialog.
 */

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CreateProfileDialog } from './CreateProfileDialog'

afterEach(cleanup)

const show = (props: Partial<Parameters<typeof CreateProfileDialog>[0]> = {}) => {
  const onCreate = vi.fn().mockResolvedValue(undefined)
  const onClose = vi.fn()
  const rendered = render(
    <CreateProfileDialog
      open
      onClose={onClose}
      onCreate={onCreate}
      busy={false}
      error={null}
      {...props}
    />
  )
  return { onCreate, onClose, rendered }
}

describe('CreateProfileDialog', () => {
  it('asks for a name, an id and a purpose, and nothing else', () => {
    show()

    expect(screen.getByRole('heading', { name: 'New profile' })).toBeTruthy()
    expect(screen.getByPlaceholderText('Bellview Farm')).toBeTruthy()
    expect(screen.getByPlaceholderText('bellview')).toBeTruthy()
    expect(screen.getByPlaceholderText(/market garden/i)).toBeTruthy()
    expect(screen.queryByText(/start from/i)).toBeNull()
  })

  it('derives the id from the name until the operator edits the id', () => {
    show()
    const displayName = screen.getByPlaceholderText('Bellview Farm')
    const name = screen.getByPlaceholderText('bellview') as HTMLInputElement

    fireEvent.change(displayName, { target: { value: 'Bellview Farm' } })
    expect(name.value).toBe('bellview-farm')

    fireEvent.change(name, { target: { value: 'bellview' } })
    fireEvent.change(displayName, { target: { value: 'Bellview Farm and Shop' } })
    expect(name.value).toBe('bellview')
  })

  it('submits the installed-product default, with no source and no clone_from', async () => {
    const { onCreate } = show()
    fireEvent.change(screen.getByPlaceholderText('Bellview Farm'), {
      target: { value: 'Bellview Farm' }
    })
    fireEvent.change(screen.getByPlaceholderText(/market garden/i), {
      target: { value: 'The market garden and its wholesale customers.' }
    })

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /create profile/i }))
    })

    expect(onCreate).toHaveBeenCalledTimes(1)
    const input = onCreate.mock.calls[0][0] as Record<string, unknown>
    expect(input).toEqual({
      name: 'bellview-farm',
      display_name: 'Bellview Farm',
      description: 'The market garden and its wholesale customers.'
    })
    expect('clone_from' in input).toBe(false)
  })

  it('refuses a reserved name before asking the server', async () => {
    const { onCreate } = show()
    fireEvent.change(screen.getByPlaceholderText('Bellview Farm'), {
      target: { value: 'Default' }
    })

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /create profile/i }))
    })

    expect(onCreate).not.toHaveBeenCalled()
    expect(screen.getByRole('alert').textContent).toMatch(/engine’s own host/i)
  })

  it('shows a refusal from the server in the dialog', () => {
    show({ error: 'a profile named “bellview” already exists' })
    expect(screen.getByRole('alert').textContent).toMatch(/already exists/)
  })

  it('starts clean when it is opened again', () => {
    const { rendered } = show()
    fireEvent.change(screen.getByPlaceholderText('Bellview Farm'), {
      target: { value: 'Bellview Farm' }
    })
    expect((screen.getByPlaceholderText('bellview') as HTMLInputElement).value).toBe('bellview-farm')

    rendered.rerender(
      <CreateProfileDialog
        open={false}
        onClose={vi.fn()}
        onCreate={vi.fn()}
        busy={false}
        error={null}
      />
    )
    rendered.rerender(
      <CreateProfileDialog
        open
        onClose={vi.fn()}
        onCreate={vi.fn()}
        busy={false}
        error={null}
      />
    )

    expect((screen.getByPlaceholderText('bellview') as HTMLInputElement).value).toBe('')
  })
})
