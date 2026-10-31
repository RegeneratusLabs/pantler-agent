/**
 * The Records page's reading of a pack.
 *
 * The page must not know what a spray or an invoice is (the design notes architecture rule 9): the pack
 * declares the fields, the screen declares the columns, and this module turns those declarations
 * into the table, the detail and the CSV. The three pure functions are separated from the page so
 * the formatting rules — especially money and CSV quoting — can be tested without a browser.
 */

import type { Pack, PackField, PackRecordType, PackScreen, StoredRecord } from '@shared/wire'

export interface RecordTypeOption {
  pack: Pack
  record: PackRecordType
  screen?: PackScreen
  /** The fields shown as columns, in the pack's declared order. */
  columns: PackField[]
  /** The field(s) that name a row; the first field when the pack does not choose. */
  titleField: string[]
}

/** Every record type in every installed pack, with its list screen resolved. */
export function recordTypeOptions(packs: readonly Pack[]): RecordTypeOption[] {
  return packs.flatMap(pack =>
    (pack.records ?? []).map(record => {
      const screen = (pack.screens ?? []).find(candidate => candidate.record_type === record.type)
      return {
        pack,
        record,
        screen,
        columns: columnsFor(record, screen),
        titleField: record.title_field?.length
          ? record.title_field.filter(name => record.fields.some(field => field.name === name))
          : record.fields.slice(0, 1).map(field => field.name)
      }
    })
  )
}

/**
 * The list columns: the screen's own choice, else the first three declared fields.
 *
 * A column the type does not declare is dropped rather than drawn as a blank header; the pack
 * loader already refuses that shape, so this is defence in depth, not a second validator.
 */
export function columnsFor(record: PackRecordType, screen?: PackScreen): PackField[] {
  const names = screen?.columns?.length
    ? screen.columns
    : record.fields.slice(0, 3).map(field => field.name)
  return names
    .map(name => record.fields.find(field => field.name === name))
    .filter((field): field is PackField => Boolean(field))
}

/** The label for a field name, or the name itself when a pack is mid-edit. */
export function fieldLabel(record: PackRecordType, name: string): string {
  return record.fields.find(field => field.name === name)?.label ?? name
}

/** A value as the operator reads it. Empty is an em dash, never a blank that looks like zero. */
export function formatFieldValue(field: PackField | undefined, value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (Array.isArray(value)) {
    return value.map(item => formatScalar(field, item)).join(', ') || '—'
  }
  if (typeof value === 'object') {
    try {
      return JSON.stringify(value)
    } catch {
      return String(value)
    }
  }
  return formatScalar(field, value)
}

function formatScalar(field: PackField | undefined, value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (field?.kind === 'money' && typeof value === 'number' && Number.isFinite(value)) {
    return (value / 100).toFixed(2)
  }
  if (typeof value === 'boolean') return value ? 'yes' : 'no'
  return String(value)
}

/** A record's name in a list: the pack's title field(s), joined, else its id. */
export function recordTitle(option: RecordTypeOption, record: StoredRecord): string {
  const title = option.titleField
    .map(name => formatFieldValue(option.record.fields.find(field => field.name === name), record.data?.[name]))
    .filter(value => value !== '—')
    .join(' · ')
  return title || record.id
}

function csvCell(value: string): string {
  return /[",\n\r]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value
}

/**
 * The current type's records as CSV. Every declared field is exported, not only the visible
 * columns, so the file is a record dump rather than a screenshot of the table.
 */
export function recordsToCsv(record: PackRecordType, rows: readonly StoredRecord[]): string {
  const header = ['ID', ...record.fields.map(field => field.label), 'Updated']
  const lines = [header.map(csvCell).join(',')]
  for (const row of rows) {
    const cells = [
      row.id,
      ...record.fields.map(field => formatFieldValue(field, row.data?.[field.name])),
      row.updated_at ?? ''
    ]
    lines.push(cells.map(csvCell).join(','))
  }
  return `${lines.join('\n')}\n`
}

/** A stable filename an operator can find again: the type and the day. */
export function recordsFilename(type: string, day = new Date()): string {
  return `records-${type.replace(/[^a-z0-9_-]+/gi, '-')}-${day.toISOString().slice(0, 10)}.csv`
}
