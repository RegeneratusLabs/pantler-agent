// @vitest-environment jsdom
/**
 * The tab bar's one job: say which panel is showing, and let a keyboard change it.
 *
 * The Capabilities page uses this to split three questions; if the ARIA wiring or the arrow keys
 * rot, the page silently becomes three buttons that only a mouse can use.
 */

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Tabs } from './tabs'

afterEach(cleanup)

const items = [
  { id: 'skills', label: 'Skills & plugins' },
  { id: 'connectors', label: 'Connectors' },
  { id: 'advanced', label: 'Advanced' }
]

describe('Tabs', () => {
  it('marks the selected tab and points it at its panel', () => {
    render(<Tabs items={items} value="connectors" onChange={() => {}} label="Sections" />)

    const tablist = screen.getByRole('tablist', { name: 'Sections' })
    expect(within(tablist).getAllByRole('tab')).toHaveLength(3)

    const selected = screen.getByRole('tab', { name: 'Connectors' })
    expect(selected.getAttribute('aria-selected')).toBe('true')
    expect(selected.getAttribute('aria-controls')).toBe('panel-connectors')
    expect(selected.getAttribute('id')).toBe('tab-connectors')
    expect(selected.getAttribute('tabindex')).toBe('0')

    expect(screen.getByRole('tab', { name: 'Skills & plugins' }).getAttribute('tabindex')).toBe(
      '-1'
    )
  })

  it('changes on click', () => {
    const onChange = vi.fn()
    render(<Tabs items={items} value="skills" onChange={onChange} label="Sections" />)

    fireEvent.click(screen.getByRole('tab', { name: 'Advanced' }))
    expect(onChange).toHaveBeenCalledWith('advanced')
  })

  it('moves with Arrow keys, Home and End', () => {
    const onChange = vi.fn()
    render(<Tabs items={items} value="skills" onChange={onChange} label="Sections" />)

    fireEvent.keyDown(screen.getByRole('tab', { name: 'Skills & plugins' }), {
      key: 'ArrowRight'
    })
    expect(onChange).toHaveBeenLastCalledWith('connectors')

    fireEvent.keyDown(screen.getByRole('tab', { name: 'Connectors' }), { key: 'End' })
    expect(onChange).toHaveBeenLastCalledWith('advanced')

    fireEvent.keyDown(screen.getByRole('tab', { name: 'Advanced' }), { key: 'Home' })
    expect(onChange).toHaveBeenLastCalledWith('skills')
  })

  it('wraps at the ends', () => {
    const onChange = vi.fn()
    render(<Tabs items={items} value="skills" onChange={onChange} label="Sections" />)

    fireEvent.keyDown(screen.getByRole('tab', { name: 'Skills & plugins' }), {
      key: 'ArrowLeft'
    })
    expect(onChange).toHaveBeenLastCalledWith('advanced')
  })
})

function within(element: HTMLElement) {
  // Kept local so the test imports only the component and the DOM testing helpers it uses.
  return {
    getAllByRole: (role: string) =>
      Array.from(element.querySelectorAll(`[role="${role}"]`)) as HTMLElement[]
  }
}
