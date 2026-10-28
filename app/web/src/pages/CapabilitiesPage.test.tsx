// @vitest-environment jsdom
/**
 * The Capabilities page's routing: three tabs, one panel at a time, and no key field.
 *
 * The child sections have their own tests; this one mocks them so it can hold the thing the tabs
 * are responsible for — which panel is showing, that the connector panel is its own tab, and that
 * the page never grows an API-key control.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  bff: {
    saveDisabledToolsets: vi.fn(async (next: string[]) => ({ disabled_toolsets: next })),
    setCapability: vi.fn()
  },
  settings: {
    available: true,
    profile: { agent_editable: true },
    disabled_toolsets: []
  },
  toolsets: [
    { name: 'records', label: 'Records', enabled: true, tools: ['record_save'] }
  ]
}))

vi.mock('../state/app-context', () => ({
  qk: {
    settings: ['settings'],
    toolsets: ['toolsets'],
    capabilityRegistry: ['capability-registry']
  },
  useApp: () => ({ bff: mocks.bff }),
  useEngineSettings: () => ({ data: mocks.settings }),
  useLearning: () => ({ data: null }),
  useToolsets: () => ({ data: mocks.toolsets })
}))

vi.mock('./CapabilityRegistrySection', () => ({
  CapabilityRegistrySection: ({
    title,
    only,
    exclude
  }: {
    title?: string
    only?: string[]
    exclude?: string[]
  }) => (
    <div data-testid="registry">
      <span>{title ?? 'registry'}</span>
      <span>{only?.join(',')}</span>
      <span>{exclude?.join(',')}</span>
    </div>
  )
}))

vi.mock('./ConnectorsSection', () => ({
  ConnectorsSection: () => <div>connectors panel</div>
}))

const { CapabilitiesPage } = await import('./CapabilitiesPage')

const renderPage = () => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } }
  })
  return render(
    <QueryClientProvider client={client}>
      <CapabilitiesPage />
    </QueryClientProvider>
  )
}

/** The one panel testing-library can see; hidden panels are out of the accessibility tree. */
const visiblePanel = (): HTMLElement => screen.getByRole('tabpanel')

afterEach(cleanup)

describe('CapabilitiesPage', () => {
  it('opens on Skills & plugins and shows only that panel', () => {
    renderPage()

    expect(screen.getByRole('tab', { name: 'Skills & plugins' }).getAttribute('aria-selected')).toBe(
      'true'
    )
    expect(within(visiblePanel()).getByTestId('registry').textContent).toContain('skill,plugin')
    expect(within(visiblePanel()).queryByText('connectors panel')).toBeNull()
  })

  it('switches to the Connectors tab', () => {
    renderPage()

    fireEvent.click(screen.getByRole('tab', { name: 'Connectors' }))
    expect(screen.getByRole('tab', { name: 'Connectors' }).getAttribute('aria-selected')).toBe(
      'true'
    )
    expect(within(visiblePanel()).getByText('connectors panel')).toBeTruthy()
  })

  it('puts MCP servers and engine tools in Advanced, not in the skills tab', () => {
    renderPage()

    fireEvent.click(screen.getByRole('tab', { name: 'Advanced' }))
    const panel = visiblePanel()
    expect(within(panel).getByText('MCP servers')).toBeTruthy()
    expect(within(panel).getByText('Engine tools')).toBeTruthy()
    expect(within(panel).getByText('Records')).toBeTruthy()
  })

  it('never renders a key control', () => {
    const { container } = renderPage()
    expect(screen.queryByLabelText(/project key/i)).toBeNull()
    expect(container.querySelector('input[type=password]')).toBeNull()
  })
})
