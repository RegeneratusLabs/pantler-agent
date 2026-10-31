/**
 * Delimited data, parsed into rows the preview pane can draw as a table.
 *
 * A CSV opened as comma-separated source is the same failure as a markdown file opened as
 * asterisks: the operator asked to look at the data, not at its punctuation. This is a small,
 * tolerant reader for the files the assistant writes — quoted fields, embedded commas and
 * newlines, escaped quotes, CRLF and a BOM — not a dialect-complete CSV implementation. It does
 * not guess a delimiter, does not type cells, and does not touch the network.
 *
 * The cap is a display cap, not a data cap: the bytes are already fetched (512 KB at most), and
 * the table reports how many rows it left out so the pane can say so.
 */

/** How many data rows the table draws before it asks the operator to download the rest. */
export const CSV_MAX_ROWS = 500

export interface DelimitedTable {
  /** The first row, which is the header in every file we write. */
  header: string[]
  /** The data rows actually drawn, capped at the parser's limit. */
  rows: string[][]
  /** Data rows in the file, header excluded. */
  totalRows: number
  /** True when `rows` stopped at the cap. */
  truncated: boolean
}

/**
 * Read a delimited document. `delimiter` is the file's declared one, never sniffed.
 *
 * The grammar is the one the format actually needs: a field is either bare text up to the
 * delimiter or line ending, or a quoted run in which `""` is a quote and newlines are data. A
 * quote in the middle of a bare field is just a quote. Empty lines and a trailing newline do not
 * become phantom rows.
 */
export function parseDelimited(
  source: string,
  delimiter: ',' | '\t',
  maxRows = CSV_MAX_ROWS
): DelimitedTable {
  const text = (source ?? '').replace(/^\uFEFF/, '')
  const rows: string[][] = []
  let row: string[] = []
  let field = ''
  let quoted = false
  let atFieldStart = true

  const endRow = () => {
    row.push(field)
    field = ''
    // A blank line is not a row, but a line of delimiters is a row of empty fields (`a,,b` keeps
    // its middle cell, and `,,` is three empty cells rather than nothing).
    if (row.length > 1 || row.some(cell => cell.length > 0)) rows.push(row)
    row = []
  }

  for (let i = 0; i < text.length; i += 1) {
    const char = text[i]

    if (quoted) {
      if (char === '"') {
        if (text[i + 1] === '"') {
          field += '"'
          i += 1
        } else {
          quoted = false
        }
      } else {
        field += char
      }
      continue
    }

    if (char === '"' && atFieldStart) {
      quoted = true
      atFieldStart = false
      continue
    }

    if (char === delimiter) {
      row.push(field)
      field = ''
      atFieldStart = true
      continue
    }

    if (char === '\n' || char === '\r') {
      if (char === '\r' && text[i + 1] === '\n') i += 1
      endRow()
      atFieldStart = true
      continue
    }

    field += char
    atFieldStart = false
  }

  // A final row with no trailing newline. `field` alone is enough: a line that ended in a
  // delimiter leaves an empty last field and must still be counted.
  if (field.length > 0 || row.length > 0) endRow()

  const [header = [], ...data] = rows
  return {
    header,
    rows: data.slice(0, Math.max(0, maxRows)),
    totalRows: data.length,
    truncated: data.length > Math.max(0, maxRows)
  }
}
