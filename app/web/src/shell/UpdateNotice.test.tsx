// @vitest-environment jsdom
/**
 * The ready-to-install strip: it appears when the host has a downloaded update, installs only on
 * click, and can be put off without losing the update.
 */

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { UpdateState } from '../pantler'
import { UpdateNotice } from './UpdateNotice'

const downloaded: UpdateState = {
  status: 'downloaded',
  currentVersion: '0.0.4',
  version: '0.0.5',
  percent: 100,
  error: null,
  checkedAt: 1
}

function bridge(state: UpdateState) {
  return {
    state: vi.fn(async () => state),
    check: vi.fn(async () => state),
    install: vi.fn(async () => ({ ok: true })),
    subscribe: vi.fn(() => () => {})
  }
}

afterEach(() => {
  cleanup()
  delete window.pantler
})

describe('the update notice', () => {
  it('offers a restart when a version is downloaded', async () => {
    const updates = bridge(downloaded)
    window.pantler = { updates }
    render(<UpdateNotice />)

    expect(await screen.findByText(/Pantler 0\.0\.5 is ready/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Restart and install' }))
    await waitFor(() => expect(updates.install).toHaveBeenCalledTimes(1))
  })

  it('says nothing while there is nothing to install', async () => {
    const updates = bridge({ ...downloaded, status: 'idle', version: null, percent: null })
    window.pantler = { updates }
    render(<UpdateNotice />)

    await waitFor(() => expect(updates.state).toHaveBeenCalled())
    expect(screen.queryByText(/is ready/)).toBeNull()
  })

  it('says nothing at all in a browser with no host bridge', () => {
    render(<UpdateNotice />)
    expect(screen.queryByText(/is ready/)).toBeNull()
  })

  it('can be put off for the session without cancelling the download', async () => {
    window.pantler = { updates: bridge(downloaded) }
    render(<UpdateNotice />)

    await screen.findByText(/is ready/)
    fireEvent.click(screen.getByRole('button', { name: 'Later' }))
    expect(screen.queryByText(/is ready/)).toBeNull()
  })
})
