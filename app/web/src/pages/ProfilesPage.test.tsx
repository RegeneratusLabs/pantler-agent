// @vitest-environment jsdom
/**
 * The Profiles screen draws from the registry context, not from a fetch of its own. These tests
 * mock that context and assert the two things an operator must be able to see: which business is
 * selected, and whether the engine is actually serving the others.
 */

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router'
import type { ProfileScope } from '../state/profile-context'

const mocks = vi.hoisted(() => ({
  activate: vi.fn().mockResolvedValue(undefined),
  create: vi.fn().mockResolvedValue(undefined),
  update: vi.fn().mockResolvedValue(undefined),
  remove: vi.fn().mockResolvedValue(undefined),
  scope: null as unknown as ProfileScope
}))

vi.mock('../state/profile-context', () => ({
  useProfiles: () => mocks.scope
}))

const { ProfilesPage } = await import('./ProfilesPage')

const baseScope = (overrides: Partial<ProfileScope> = {}): ProfileScope => ({
  profiles: [
    {
      name: 'pantler',
      display_name: 'Bellview Farm',
      description: 'The market garden.',
      is_install: true,
      active: true,
      provider: 'opencode-go',
      model: 'deepseek-v4.1-flash',
      has_env: true,
      served: true
    },
    {
      name: 'garden',
      display_name: 'Second Farm',
      description: '',
      is_install: false,
      active: false,
      provider: 'opencode-go',
      model: 'deepseek-v4.1-flash',
      has_env: true,
      served: false
    }
  ],
  active: 'pantler',
  install: 'pantler',
  available: true,
  reason: null,
  gateway: { multiplex: false, served: ['pantler'], live: true },
  restartRequired: true,
  loading: false,
  error: null,
  refresh: vi.fn(),
  activate: mocks.activate,
  create: mocks.create,
  update: mocks.update,
  remove: mocks.remove,
  ...overrides
})

const show = (scope: ProfileScope) => {
  mocks.scope = scope
  return render(
    <MemoryRouter>
      <ProfilesPage />
    </MemoryRouter>
  )
}

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('ProfilesPage', () => {
  it('lists every business, marks the selected one, and warns that a restart is needed', () => {
    show(baseScope())

    expect(screen.getByText('Bellview Farm')).toBeTruthy()
    expect(screen.getByText('Second Farm')).toBeTruthy()
    expect(screen.getByText('selected')).toBeTruthy()
    expect(screen.getByText('engine restart')).toBeTruthy()
    expect(screen.getAllByText(/multi-profile/i).length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: /use this profile/i })).toBeTruthy()
  })

  it('selects a profile and starts a conversation under it', async () => {
    show(baseScope())
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /use this profile/i }))
    })
    expect(mocks.activate).toHaveBeenCalledWith('garden')
  })

  it('does not offer to delete the installed or selected profile', () => {
    show(baseScope())
    const deleteButtons = screen.getAllByRole('button', { name: /^delete$/i })
    // Installed first: never deletable. The second profile is neither installed nor selected,
    // so it may be deleted — after the confirmation dialog.
    expect(deleteButtons[0]).toHaveProperty('disabled', true)
    expect(deleteButtons[1]).toHaveProperty('disabled', false)
  })

  it('says why profiles are unavailable instead of drawing a dead button', () => {
    show(
      baseScope({
        available: false,
        reason: 'No engine profile is configured for this server.',
        profiles: []
      })
    )
    expect(screen.getByText(/Profiles are not available/)).toBeTruthy()
    expect(screen.getByText(/No engine profile is configured/)).toBeTruthy()
    expect(screen.getByRole('button', { name: /new profile/i })).toHaveProperty('disabled', true)
  })

  it('opens the new-profile form without asking where to copy it from', async () => {
    show(baseScope())
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /new profile/i }))
    })

    expect(screen.getByRole('heading', { name: 'New profile' })).toBeTruthy()
    expect(screen.getByPlaceholderText('Bellview Farm')).toBeTruthy()
    expect(screen.getByPlaceholderText('bellview')).toBeTruthy()
    expect(screen.queryByText(/start from/i)).toBeNull()
  })
})
