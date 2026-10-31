/**
 * Reading delimited data for the preview table.
 *
 * The cases are the ones files the assistant writes actually contain: quoted commas in a
 * description, a quoted newline in a note, escaped quotes, CRLF from a Windows tool, a BOM, a
 * trailing newline that must not become a phantom row, and a file big enough to hit the display
 * cap. The parser is deliberately small, so the edges are tested rather than assumed.
 */

import { describe, expect, it } from 'vitest'
import { CSV_MAX_ROWS, parseDelimited } from './csv'

describe('parseDelimited', () => {
  it('reads a header and rows', () => {
    const table = parseDelimited('name,qty\nBeans,12\nEggs,4\n', ',')
    expect(table.header).toEqual(['name', 'qty'])
    expect(table.rows).toEqual([
      ['Beans', '12'],
      ['Eggs', '4']
    ])
    expect(table.totalRows).toBe(2)
    expect(table.truncated).toBe(false)
  })

  it('keeps a comma inside a quoted field', () => {
    const table = parseDelimited('item,qty\n"Eggs, large",4\n', ',')
    expect(table.rows).toEqual([['Eggs, large', '4']])
  })

  it('keeps a newline inside a quoted field', () => {
    const table = parseDelimited('note,qty\n"first line\nsecond line",2\n', ',')
    expect(table.rows).toEqual([['first line\nsecond line', '2']])
  })

  it('unescapes a doubled quote', () => {
    const table = parseDelimited('note\n"say ""hello"""\n', ',')
    expect(table.rows).toEqual([['say "hello"']])
  })

  it('handles CRLF and a BOM', () => {
    const table = parseDelimited('\uFEFFname,qty\r\nBeans,12\r\nEggs,4\r\n', ',')
    expect(table.header).toEqual(['name', 'qty'])
    expect(table.rows).toEqual([
      ['Beans', '12'],
      ['Eggs', '4']
    ])
  })

  it('does not make a phantom row from a trailing newline or a blank line', () => {
    const table = parseDelimited('a,b\n1,2\n\n3,4\n\n', ',')
    expect(table.rows).toEqual([
      ['1', '2'],
      ['3', '4']
    ])
  })

  it('keeps an empty middle cell but does not invent empty rows', () => {
    const table = parseDelimited('a,b,c\n1,,3\n', ',')
    expect(table.header).toEqual(['a', 'b', 'c'])
    expect(table.rows).toEqual([['1', '', '3']])
  })

  it('keeps a row of empty fields, while a blank line stays blank', () => {
    const table = parseDelimited('a,b,c\n,,\n\n1,,3\n', ',')
    expect(table.rows).toEqual([
      ['', '', ''],
      ['1', '', '3']
    ])
  })

  it('reads a TSV by its declared tab', () => {
    const table = parseDelimited('name\tqty\nBeans\t12\n', '\t')
    expect(table.header).toEqual(['name', 'qty'])
    expect(table.rows).toEqual([['Beans', '12']])
  })

  it('keeps a tab inside a quoted TSV field', () => {
    const table = parseDelimited('note\tqty\n"a\tb"\t2\n', '\t')
    expect(table.rows).toEqual([['a\tb', '2']])
  })

  it('caps the drawn rows and says how many there were', () => {
    const source = ['name']
    for (let i = 0; i < CSV_MAX_ROWS + 3; i += 1) source.push(`row ${i}`)
    const table = parseDelimited(source.join('\n'), ',', CSV_MAX_ROWS)
    expect(table.rows).toHaveLength(CSV_MAX_ROWS)
    expect(table.totalRows).toBe(CSV_MAX_ROWS + 3)
    expect(table.truncated).toBe(true)
  })

  it('reads a header-only file, an empty file and a one-row file', () => {
    expect(parseDelimited('name,qty\n', ',')).toMatchObject({
      header: ['name', 'qty'],
      rows: [],
      totalRows: 0,
      truncated: false
    })
    expect(parseDelimited('', ',')).toEqual({
      header: [],
      rows: [],
      totalRows: 0,
      truncated: false
    })
    expect(parseDelimited('just one line', ',')).toMatchObject({
      header: ['just one line'],
      rows: [],
      totalRows: 0
    })
  })

  it('keeps a quote in an unquoted field as a quote', () => {
    const table = parseDelimited('a,b\n5" pipe,6\n', ',')
    expect(table.rows).toEqual([['5" pipe', '6']])
  })
})
