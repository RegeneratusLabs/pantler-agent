// @vitest-environment jsdom
/**
 * Settings is five tabs, and the model form is one of them.
 *
 * The form's own behaviour is `model/ModelForm.test.tsx`; this holds the page's wiring — the tab
 * order and panels, that the model form is the Assistant panel's content, and that `available:
 * false` is a sentence rather than an empty card or a crash.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { EngineSettings } from '@shared/wire'

const mocks = vi.hoisted(() => ({
  settings: { available: true, model: {}, keys: [] } as EngineSettings,
  bff: {
    saveModel: vi.fn(),
    saveKey: vi.fn(),
    clearKey: vi.fn()
  }
}))

vi.mock('../state/app-context', () => ({
  qk: { settings: ['settings'] },
  useApp: () => ({ bff: mocks.bff }),
  useEngineSettings: () => ({ data: mocks.settings, isPending: false })
}))

vi.mock('../components/LearningPanel', () => ({
  LearningPanel: () => <div>learning panel</div>,
  LearningChangeLog: () => <div>learning change log</div>
}))

vi.mock('./PersonalitySection', () => ({
  PersonalitySection: () => <div>voice section</div>
}))

vi.mock('../onboarding/profile', () => ({
  WORK_KINDS: [],
  operatorProfile: { update: vi.fn() },
  useOperatorProfile: () => ({ name: '', business: '', work: '' })
}))

import { SettingsPage } from './SettingsPage'

function show(entry = '/settings') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[entry]}>
        <LocationProbe />
        <SettingsPage />
      </MemoryRouter>
    </QueryClientProvider>
  )
}

/** The tab is a URL, and more than one screen links to it; this is the assertion that it is. */
function LocationProbe() {
  const location = useLocation()
  return <output data-testid="location">{`${location.pathname}${location.search}`}</output>
}

afterEach(() => {
  cleanup()
  mocks.settings = { available: true, model: {}, keys: [] }
})

describe('the settings page', () => {
  const panel = (id: string) => document.getElementById(`panel-${id}`)

  it('opens on Business, with the model form kept behind Advanced', () => {
    show()
    expect(screen.getByRole('tablist', { name: 'Settings sections' })).toBeTruthy()
    expect(screen.getAllByRole('tab').map(tab => tab.textContent)).toEqual([
      'Business',
      'Voice',
      'Learning',
      'Advanced',
      'About'
    ])
    expect(screen.getByRole('tab', { name: 'Business' }).getAttribute('aria-selected')).toBe('true')
    expect(panel('business')?.hidden).toBe(false)
    expect(panel('advanced')?.hidden).toBe(true)

    // The advanced panel is mounted but out of the accessibility tree, so its form is not on
    // the general operator's screen.
    expect(screen.queryByRole('button', { name: 'Connect' })).toBeNull()
  })

  it('opens Advanced from a link, with the provider form', () => {
    show('/settings?tab=advanced')
    expect(panel('advanced')?.hidden).toBe(false)
    expect(screen.getByText('For advanced users')).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Model' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Connect' })).toBeTruthy()
    // The learning change log lives here now, not under the Learning tab.
    expect(screen.getByText('Learning change log')).toBeTruthy()
    expect(screen.getByText('learning change log')).toBeTruthy()
  })

  it('treats an unknown tab as the default rather than an empty page', () => {
    show('/settings?tab=nonsense')
    expect(screen.getByRole('tab', { name: 'Business' }).getAttribute('aria-selected')).toBe('true')
    expect(panel('business')?.hidden).toBe(false)
  })

  it('puts the selected tab in the URL and keeps the other panels mounted', () => {
    show()
    fireEvent.click(screen.getByRole('tab', { name: 'Advanced' }))
    expect(screen.getByTestId('location').textContent).toBe('/settings?tab=advanced')
    expect(panel('advanced')?.hidden).toBe(false)
    expect(panel('business')?.hidden).toBe(true)
    // Mounted, hidden: a half-typed key and a chosen voice survive the switch.
    expect(screen.getByText('voice section')).toBeTruthy()
    expect(screen.getByText('learning panel')).toBeTruthy()

    fireEvent.click(screen.getByRole('tab', { name: 'Business' }))
    expect(screen.getByTestId('location').textContent).toBe('/settings')
  })

  it('names the version and the update channel on About', () => {
    show()
    fireEvent.click(screen.getByRole('tab', { name: 'About' }))
    expect(panel('about')?.hidden).toBe(false)
    expect(screen.getByText('Version')).toBeTruthy()
    expect(screen.getByText(__PANTLER_VERSION__)).toBeTruthy()
    // A real version from distribution.yaml, not the config's `dev` fallback.
    expect(__PANTLER_VERSION__).toMatch(/^\d+\.\d+\.\d+$/)
    expect(screen.getByText('Update channel')).toBeTruthy()
    // The browser build has no host updater; About says so rather than offering a dead button.
    expect(screen.getByText('Not available here')).toBeTruthy()
  })

  it('explains a read-only server instead of rendering a form that cannot write', () => {
    mocks.settings = {
      available: false,
      reason: 'Start the BFF with --profile-dir <profiles/NAME>.'
    }
    show('/settings?tab=advanced')
    expect(screen.getByText(/--profile-dir/)).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Connect' })).toBeNull()
  })
})
