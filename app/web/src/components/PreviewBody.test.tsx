// @vitest-environment jsdom
/**
 * The preview bodies open on the finished thing.
 *
 * The plan tests decide the mode; this one decides what the operator sees when the mode is
 * `html` or `csv`: the rendered page or table first, the source one click away. The BFF is the
 * only dependency mocked — the fetch itself is tested at the seam.
 */

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fileTarget } from './preview'

const { textPreview } = vi.hoisted(() => ({ textPreview: vi.fn() }))

vi.mock('../state/app-context', () => ({
  useApp: () => ({ bff: { textPreview } })
}))

import { CsvBody, HtmlBody } from './PreviewSidebar'

const HTML = '<!DOCTYPE html><html><body><h1>Compost batch log</h1></body></html>'
const target = (name: string) => fileTarget(`/w/${name}`)

beforeEach(() => {
  textPreview.mockReset()
  textPreview.mockResolvedValue(HTML)
})

afterEach(cleanup)

describe('HtmlBody', () => {
  it('opens on the rendered page, not the source', async () => {
    const { container } = render(
      <HtmlBody target={target('batch-log.html')} reason="Rendered in a sandboxed frame." note="note" />
    )

    await waitFor(() => expect(container.querySelector('iframe')).not.toBeNull())

    const frame = container.querySelector('iframe')
    expect(frame?.getAttribute('srcdoc')).toContain('Compost batch log')
    expect(frame?.getAttribute('sandbox')).not.toContain('allow-same-origin')
    expect(container.querySelector('pre')).toBeNull()
    expect(screen.getByRole('button', { name: 'Show the source' })).toBeTruthy()
  })

  it('shows the source on request and the page again on the way back', async () => {
    const { container } = render(
      <HtmlBody target={target('batch-log.html')} reason="Rendered in a sandboxed frame." />
    )
    await waitFor(() => expect(container.querySelector('iframe')).not.toBeNull())

    fireEvent.click(screen.getByRole('button', { name: 'Show the source' }))

    await waitFor(() => expect(container.querySelector('pre')).not.toBeNull())
    expect(container.querySelector('iframe')).toBeNull()
    expect(container.querySelector('pre')?.textContent).toContain('Compost batch log')

    fireEvent.click(screen.getByRole('button', { name: 'Show the rendered page' }))
    await waitFor(() => expect(container.querySelector('iframe')).not.toBeNull())
  })
})

describe('CsvBody', () => {
  it('opens on a table with a header row and keeps the source one click away', async () => {
    textPreview.mockResolvedValue('name,qty\n"Eggs, large",4\nBeans,12\n')
    const { container } = render(<CsvBody target={target('order.csv')} delimiter="," note="note" />)

    await waitFor(() => expect(container.querySelector('table')).not.toBeNull())

    expect(container.querySelectorAll('thead th')).toHaveLength(2)
    expect(container.querySelectorAll('tbody tr')).toHaveLength(2)
    expect(container.textContent).toContain('Eggs, large')
    // The table shows the value, not the quoting around it.
    expect(container.textContent).not.toContain('"Eggs, large"')

    fireEvent.click(screen.getByRole('button', { name: 'Show the source' }))
    await waitFor(() => expect(container.querySelector('pre')).not.toBeNull())
    expect(container.querySelector('table')).toBeNull()
    expect(container.querySelector('pre')?.textContent).toContain('name,qty')
  })

  it('says when a file has a header but no data rows', async () => {
    textPreview.mockResolvedValue('name,qty\n')
    const { container } = render(<CsvBody target={target('empty.csv')} delimiter="," />)

    await waitFor(() => expect(container.querySelector('table')).not.toBeNull())
    expect(container.textContent).toContain('header but no data rows')
  })
})
