import { describe, expect, it } from 'vitest'
import type { Pack, StoredRecord } from '@shared/wire'
import {
  columnsFor,
  formatFieldValue,
  recordTitle,
  recordTypeOptions,
  recordsFilename,
  recordsToCsv
} from './records'

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
          { name: 'block', label: 'Block', kind: 'reference', reference: 'block' },
          { name: 'rate', label: 'Rate', kind: 'number' },
          { name: 'notes', label: 'Notes', kind: 'longtext' }
        ]
      }
    ],
    screens: [
      {
        id: 'applications',
        title: 'Applications',
        kind: 'list',
        record_type: 'application',
        columns: ['date', 'block']
      }
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
          { name: 'task', label: 'Task', kind: 'text', required: true },
          { name: 'cost', label: 'Cost', kind: 'money' }
        ]
      }
    ]
  }
]

const RECORD: StoredRecord = {
  id: 'APP-0001',
  type: 'application',
  pack: 'farm',
  data: { date: '2026-10-22', block: 'North block', rate: 2.5, notes: 'Floors, benches' },
  created_at: '2026-10-22T10:00:00+00:00',
  updated_at: '2026-10-22T10:00:00+00:00'
}

describe('recordTypeOptions', () => {
  it('reads the pack screen and the custom flag', () => {
    const options = recordTypeOptions(PACKS)
    expect(options.map(option => option.record.type)).toEqual(['application', 'cleaning_log'])
    expect(options[0].columns.map(column => column.name)).toEqual(['date', 'block'])
    expect(options[1].pack.custom).toBe(true)
    // No screen: the first three fields are the columns, and the first names the row.
    expect(options[1].columns.map(column => column.name)).toEqual(['date', 'task', 'cost'])
    expect(options[1].titleField).toEqual(['date'])
  })

  it('drops a column the type does not declare', () => {
    const record = PACKS[0].records![0]
    expect(columnsFor(record, { id: 'x', title: 'x', record_type: 'application', columns: ['date', 'nope'] }).map(c => c.name)).toEqual(['date'])
  })
})

describe('formatFieldValue', () => {
  it('shows an empty field as an em dash, never a blank', () => {
    expect(formatFieldValue({ name: 'x', label: 'X', kind: 'text' }, '')).toBe('—')
    expect(formatFieldValue({ name: 'x', label: 'X', kind: 'text' }, null)).toBe('—')
  })

  it('renders money in cents as a decimal', () => {
    expect(formatFieldValue({ name: 'cost', label: 'Cost', kind: 'money' }, 1234)).toBe('12.34')
  })

  it('renders arrays and booleans readably', () => {
    expect(formatFieldValue({ name: 'x', label: 'X', kind: 'text' }, ['a', 'b'])).toBe('a, b')
    expect(formatFieldValue({ name: 'x', label: 'X', kind: 'text' }, true)).toBe('yes')
  })
})

describe('recordsToCsv', () => {
  it('exports every declared field, not only the visible columns, and quotes commas', () => {
    const record = PACKS[0].records![0]
    const csv = recordsToCsv(record, [
      RECORD,
      { ...RECORD, id: 'APP-0002', data: { ...RECORD.data, notes: 'Floors, benches\nand sinks' } }
    ])
    expect(csv.split('\n')[0]).toBe('ID,Date,Block,Rate,Notes,Updated')
    expect(csv).toContain('APP-0001,2026-10-22,North block,2.5,"Floors, benches"')
    expect(csv).toContain('"Floors, benches')
  })

  it('formats a money field as a decimal', () => {
    const record = PACKS[1].records![0]
    const csv = recordsToCsv(record, [
      {
        id: 'CLE-0001',
        type: 'cleaning_log',
        pack: 'custom-cleaning',
        data: { date: '2026-10-22', task: 'Benches', cost: 450 },
        updated_at: '2026-10-22T10:00:00+00:00'
      }
    ])
    expect(csv).toContain('CLE-0001,2026-10-22,Benches,4.50')
  })
})

describe('recordTitle and filename', () => {
  it('uses the title fields and falls back to the id', () => {
    const option = recordTypeOptions(PACKS)[0]
    expect(recordTitle(option, RECORD)).toBe('2026-10-22 · North block')
    expect(recordTitle(option, { ...RECORD, data: {} })).toBe('APP-0001')
  })

  it('makes a stable filename', () => {
    expect(recordsFilename('cleaning_log', new Date('2026-10-22T10:00:00Z'))).toBe(
      'records-cleaning_log-2026-10-22.csv'
    )
  })
})
