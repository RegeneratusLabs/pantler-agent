// @vitest-environment jsdom
/**
 * The rail footer's one rule: it reports whether the engine is answering, not which model is
 * behind it. The model name is an implementation detail the operator cannot act on, and showing
 * it bottom-left was the thing the new-user feedback asked to remove.
 */

import { cleanup, render } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  health: { data: undefined as unknown, isError: false }
}))

vi.mock('../state/app-context', () => ({
  useHealth: () => mocks.health
}))

const { SidebarFooter } = await import('./SidebarFooter')

afterEach(cleanup)

describe('SidebarFooter', () => {
  it('says connected and never names the model', () => {
    mocks.health = { data: { version: 'v0.22.5' } as unknown, isError: false }
    const { container } = render(<SidebarFooter />)

    expect(container.textContent).toContain('Connected')
    expect(container.textContent).toContain('v0.22.5')
    expect(container.textContent).not.toContain('deepseek')
    expect(container.textContent).not.toContain('glm')
  })

  it('says the engine is unreachable when the health check fails', () => {
    mocks.health = { data: undefined, isError: true }
    const { container } = render(<SidebarFooter />)

    expect(container.textContent).toContain('engine unreachable')
    expect(container.textContent).not.toContain('Connected')
  })
})
