// @vitest-environment jsdom
/**
 * The no-model strip points at the Advanced tab, and only goes quiet where that form is visible.
 *
 * Settings now opens on Business, so a link to `/settings` would drop the operator on a page that
 * says nothing about the missing model. The tab is a URL for exactly this reason.
 */

import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { EngineSettings } from '@shared/wire'

const mocks = vi.hoisted(() => ({
  settings: { available: true, model: {} } as EngineSettings
}))

vi.mock('../state/app-context', () => ({
  useEngineSettings: () => ({ data: mocks.settings })
}))

import { ModelNotice } from './ModelNotice'

function show(entry: string) {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <ModelNotice />
    </MemoryRouter>
  )
}

afterEach(() => {
  cleanup()
  mocks.settings = { available: true, model: {} }
})

describe('the no-model notice', () => {
  it('links a fresh install straight to the Advanced tab', () => {
    show('/chat')
    expect(screen.getByRole('link', { name: 'Connect one' }).getAttribute('href')).toBe(
      '/settings?tab=advanced'
    )
  })

  it('stays on Settings’ other tabs, where the form is not on screen', () => {
    show('/settings')
    expect(screen.getByRole('link', { name: 'Connect one' })).toBeTruthy()
    cleanup()
    show('/settings?tab=business')
    expect(screen.getByRole('link', { name: 'Connect one' })).toBeTruthy()
  })

  it('hides on the Advanced tab itself', () => {
    show('/settings?tab=advanced')
    expect(screen.queryByText(/No model is connected/)).toBeNull()
  })

  it('stays quiet once a model is configured or the profile is unavailable', () => {
    mocks.settings = { available: true, model: { default: 'deepseek-chat' } }
    show('/chat')
    expect(screen.queryByText(/No model is connected/)).toBeNull()

    cleanup()
    mocks.settings = { available: false }
    show('/chat')
    expect(screen.queryByText(/No model is connected/)).toBeNull()
  })
})
