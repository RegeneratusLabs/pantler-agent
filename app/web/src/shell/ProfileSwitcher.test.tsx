// @vitest-environment jsdom
/**
 * The rail's profile dropdown. Three behaviours matter: it still switches profiles, it offers
 * a create action inside the dropdown, and what happens after a create follows the engine's
 * answer rather than assuming the new business is already served.
 */

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ProfileSummary, ProfileWriteResponse } from '../seam/bff'
import type { ProfileScope } from '../state/profile-context'

const mocks = vi.hoisted(() => ({
  navigate: vi.fn(),
  create: vi.fn(),
  activate: vi.fn(),
  scope: null as unknown as ProfileScope
}))

vi.mock('react-router', () => ({ useNavigate: () => mocks.navigate }))
vi.mock('../state/profile-context', () => ({ useProfiles: () => mocks.scope }))

const { ProfileSwitcher } = await import('./ProfileSwitcher')

const pantler: ProfileSummary = {
  name: 'pantler',
  display_name: 'Bellview Farm',
  description: '',
  is_install: true,
  active: true,
  provider: 'opencode-go',
  model: 'deepseek-v4.1-flash',
  has_env: true,
  served: true
}

const bellview: ProfileSummary = {
  ...pantler,
  name: 'bellview',
  display_name: 'Bellview Market Garden',
  is_install: false,
  active: false,
  served: true
}

const scope = (overrides: Partial<ProfileScope> = {}): ProfileScope => ({
  profiles: [pantler],
  active: 'pantler',
  install: 'pantler',
  available: true,
  reason: null,
  gateway: { multiplex: true, served: ['pantler'], live: true },
  restartRequired: false,
  loading: false,
  error: null,
  refresh: vi.fn(),
  activate: mocks.activate,
  create: mocks.create,
  update: vi.fn(),
  remove: vi.fn(),
  ...overrides
})

const show = (overrides: Partial<ProfileScope> = {}) => {
  mocks.scope = scope(overrides)
  render(<ProfileSwitcher />)
  return screen.getByLabelText('Profile') as HTMLSelectElement
}

const written = (profile: ProfileSummary, restart = false): ProfileWriteResponse => ({
  profile,
  gateway: { multiplex: !restart, served: ['pantler'], live: true },
  restart_required: restart
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('ProfileSwitcher', () => {
  it('offers every business and the create action', () => {
    show({ profiles: [pantler, bellview] })
    const options = [...(screen.getByLabelText('Profile') as HTMLSelectElement).options].map(
      option => option.textContent
    )
    expect(options).toContain('Bellview Farm')
    expect(options).toContain('Bellview Market Garden')
    expect(options).toContain('New profile…')
  })

  it('opens the create dialog from the dropdown without switching', async () => {
    const select = show()
    await act(async () => {
      fireEvent.change(select, { target: { value: '__new__' } })
    })

    expect(screen.getByRole('heading', { name: 'New profile' })).toBeTruthy()
    expect(mocks.activate).not.toHaveBeenCalled()
    // The control snaps back to the business the app is actually in.
    expect(select.value).toBe('pantler')
  })

  it('creates, selects the new business and starts a conversation', async () => {
    mocks.create.mockResolvedValue(written(bellview))
    mocks.activate.mockResolvedValue(undefined)
    const select = show()

    await act(async () => {
      fireEvent.change(select, { target: { value: '__new__' } })
    })
    fireEvent.change(screen.getByPlaceholderText('Bellview Farm'), {
      target: { value: 'Bellview Market Garden' }
    })
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /create profile/i }))
    })

    expect(mocks.create).toHaveBeenCalledWith({
      name: 'bellview-market-garden',
      display_name: 'Bellview Market Garden',
      description: undefined
    })
    expect(mocks.activate).toHaveBeenCalledWith('bellview')
    expect(mocks.navigate).toHaveBeenCalledWith('/chat')
    expect(screen.queryByRole('heading', { name: 'New profile' })).toBeNull()
  })

  it('does not switch when the engine is serving one profile at a time', async () => {
    mocks.create.mockResolvedValue(written(bellview, true))
    const select = show()

    await act(async () => {
      fireEvent.change(select, { target: { value: '__new__' } })
    })
    fireEvent.change(screen.getByPlaceholderText('Bellview Farm'), {
      target: { value: 'Bellview Market Garden' }
    })
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /create profile/i }))
    })

    expect(mocks.activate).not.toHaveBeenCalled()
    expect(mocks.navigate).not.toHaveBeenCalled()
    expect(screen.getByText(/serving one business at a time/i)).toBeTruthy()
  })

  it('says the engine is starting a business that is not served yet', async () => {
    mocks.create.mockResolvedValue(written({ ...bellview, served: false }))
    mocks.activate.mockResolvedValue(undefined)
    const select = show()

    await act(async () => {
      fireEvent.change(select, { target: { value: '__new__' } })
    })
    fireEvent.change(screen.getByPlaceholderText('Bellview Farm'), {
      target: { value: 'Bellview Market Garden' }
    })
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /create profile/i }))
    })

    expect(mocks.activate).toHaveBeenCalledWith('bellview')
    expect(screen.getByText(/engine is starting/i)).toBeTruthy()
  })

  it('keeps the form open and shows the server’s refusal', async () => {
    mocks.create.mockRejectedValue(new Error('a profile named “bellview” already exists'))
    const select = show()

    await act(async () => {
      fireEvent.change(select, { target: { value: '__new__' } })
    })
    fireEvent.change(screen.getByPlaceholderText('Bellview Farm'), {
      target: { value: 'Bellview Market Garden' }
    })
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /create profile/i }))
    })

    expect(mocks.activate).not.toHaveBeenCalled()
    expect(screen.getByRole('alert').textContent).toMatch(/already exists/)
    expect(screen.getByRole('heading', { name: 'New profile' })).toBeTruthy()
  })
})
