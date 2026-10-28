// @vitest-environment jsdom
/**
 * The Records page is a read model over the BFF. These tests pin the two things an operator
 * needs: every installed type — custom included — is reachable, and opening a row shows the
 * pack's own fields rather than a summary someone invented.
 */

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router'
import type { Pack, StoredRecord } from '@shared/wire'

const state = vi.hoisted(() => ({
  packs: [] as Pack[],
  records: [] as StoredRecord[],
  record: undefined as StoredRecord | undefined,
  error: null as unknown
}))

vi.mock('../state/profile-context', () => ({
  useProfiles: () => ({
    profiles: [{ name: 'pantler', display_name: 'Bellview Farm' }],
    active: 'pantler'
  })
}))

vi.mock('../state/app-context', () => ({
  usePacks: () => ({
    data: state.packs,
    isPending: false,
    error: state.error,
    refetch: vi.fn(),
    isFetching: false
  }),
  useRecords: () => ({
    data: { data: state.records, total: state.records.length, limit: 100, offset: 0 },
    isPending: false,
    error: state.error,
    refetch: vi.fn(),
    isFetching: false
  }),
  useRecord: () => ({
    data: state.record,
    isPending: false,
    error: state.error,
    refetch: vi.fn()
  })
}))

const { RecordsPage } = await import('./RecordsPage')

const PACKS: Pack[] = [
  {
    id: 'farm',
    name: 'Farm',
    records: [
      {
        type: 'application',
        label: 'Application',
        plural: 'Applications',
        title_field: ['date', 'block'],
        fields: [
          { name: 'date', label: 'Date', kind: 'date', required: true },
          { name: 'block', label: 'Block', kind: 'reference' },
          { name: 'rate', label: 'Rate', kind: 'number' }
        ]
      }
    ],
    screens: [
      { id: 'applications', title: 'Applications', record_type: 'application', columns: ['date', 'block'] }
    ]
  },
  {
    id: 'custom-cleaning',
    name: 'Cleaning',
    custom: true,
    records: [
      {
        type: 'cleaning_log',
        label: 'Kitchen cleaning log',
        plural: 'Kitchen cleaning logs',
        fields: [
          { name: 'date', label: 'Date', kind: 'date', required: true },
          { name: 'task', label: 'Task', kind: 'text', required: true }
        ]
      }
    ]
  }
]

const RECORD: StoredRecord = {
  id: 'APP-0001',
  type: 'application',
  pack: 'farm',
  data: { date: '2026-10-22', block: 'North block', rate: 2.5 },
  updated_at: '2026-10-22T10:00:00+00:00'
}

const show = () =>
  render(
    <MemoryRouter>
      <RecordsPage />
    </MemoryRouter>
  )

afterEach(() => {
  cleanup()
  state.record = undefined
  state.error = null
  vi.restoreAllMocks()
})

describe('RecordsPage', () => {
  it('lists every type, including a custom one, and opens a record with its own fields', () => {
    state.packs = PACKS
    state.records = [RECORD]
    state.record = RECORD
    show()

    expect(screen.getByRole('heading', { name: 'Records' })).toBeTruthy()
    expect(screen.getByRole('button', { name: /Application/i })).toBeTruthy()
    expect(screen.getByRole('button', { name: /Kitchen cleaning log/i })).toBeTruthy()
    expect(screen.getByText('custom')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'APP-0001' }))
    expect(screen.getByText('Rate')).toBeTruthy()
    expect(screen.getByText('2.5')).toBeTruthy()
    expect(screen.getAllByText('North block').length).toBeGreaterThan(0)
  })

  it('says nothing is recorded rather than drawing an empty table', () => {
    state.packs = PACKS
    state.records = []
    show()
    expect(screen.getByText('Nothing recorded yet')).toBeTruthy()
    expect(screen.getAllByRole('button', { name: /Ask in chat/i }).length).toBeGreaterThan(0)
  })

  it('offers Print, and calls the browser only when pressed', () => {
    state.packs = PACKS
    state.records = [RECORD]
    const print = vi.spyOn(window, 'print').mockImplementation(() => {})
    show()
    expect(print).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: /Print/i }))
    expect(print).toHaveBeenCalledTimes(1)
  })

  it('says there are no record types when the install has no packs', () => {
    state.packs = []
    state.records = []
    show()
    expect(screen.getByText('No record types installed')).toBeTruthy()
  })
})
