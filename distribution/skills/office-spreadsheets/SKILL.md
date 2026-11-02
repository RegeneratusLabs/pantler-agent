---
name: office-spreadsheets
description: A workbook of the records, that adds up.
license: MIT
metadata:
  category: pantler
  source: authored in this repository; the format layer is the pinned engine's MIT office scripts (plugins/office/PROVENANCE.md)
---

# Spreadsheets

Use this when the deliverable is a spreadsheet: the accountant wants the quarter, the inspector
wants a sortable list, the market wants a price sheet, or the operator wants their own workbook
updated. A PDF is for reading and a Word file is for signing; a workbook is for counting, and it is
the only form where the reader can check the arithmetic themselves.

## First: is a workbook the right thing?

- **The reader will add, sort or filter it** → a workbook. That is the test.
- **It is going to be read once and filed** → a PDF (`documents`).
- **It is going to be signed or sent on letterhead** → a Word document (`office-documents`).
- **It is a list of what is available this week** → the availability skill produces the list; ask
  whether they want the table as well.

## Say what each column is

A column is a promise about what is in it. Get the type wrong once and every total under it is
wrong.

| Type | What you pass | How it reads |
|---|---|---|
| `text` | the words as given | as they are |
| `number` | a number | `2.5` |
| `integer` | a whole number | `12` |
| `money` | dollars, not cents | `$120.50` |
| `percent` | a fraction: `0.15` is 15% | `15.0%` |
| `date` | `YYYY-MM-DD` | a real date, sortable |

Records store money in **cents**; the tool converts when the rows come from the store. Never pass
cents into a `money` column, and never pass `15` for fifteen percent.

## Never supply a number the code should compute

Mark a column `total: true` and the tool writes the `SUM` formula **and** the value it computed.
That number is checkable by the reader and by you; a total you typed is neither.

- If the operator gives you a total, treat it as a **check**: build the rows, then compare. If they
  disagree, say so and ask which is right — do not "fix" the rows to match.
- Never carry a figure across from another document by hand. If it is in the records, read it; if it
  is on a label, the operator quotes it and you say who gave it.

## Rows that are already in the records

Over roughly fifty rows, or anything that is a ledger (invoices, spray applications, harvests),
pass `source` instead of `rows`:

```
{"kind": "records", "type": "spray", "since": "2026-07-01", "until": "2026-09-30"}
```

The store is read deterministically, the columns come from the record type's own fields, and money
is converted for you. Say which type and which dates you used, because that is what makes the
workbook reproducible.

## Check it before you hand it over

1. **The preview is the file.** Open `preview_path` (the tool returns it) and look at the table: the
   header row, the number of rows, the totals row.
2. **It adds up.** Read the workbook back with `office_read` `part: "formulas"`; every total must
   have a cached value, and it must equal the sum you expect.
3. **The dates read as dates.** A date column that shows `46309` was typed as a number.
4. **Nothing is invented.** Every row is something the operator said or a record that exists.

## Editing a workbook they already have

`xlsx_edit` writes a **copy** — the input is never changed. Say that in one line, and name the new
file.

- `set_cells` for a handful of values, `append_rows` for a week's rows, `rename_sheet` for a tidy-up.
- If a value you passed as text was stored as a number or a date (the result names any), say so: a
  product code `007` that became `7` is a mistake the operator must see.
- Totals already in the workbook recalculate when it opens; you do not have a recomputed figure, and
  you must not claim one.
- Do not restructure somebody else's workbook in this version. If it needs columns moved, inserts or
  deletes, say what you would change and ask first.

## What not to do

- No charts, merged-cell artwork, hidden sheets, colours for decoration or password protection. The
  tool writes a clean table and nothing else; a workbook that looks designed is a workbook the
  accountant reformats.
- No formula you wrote yourself, and no cell containing a number you calculated in your head.
- No `.xlsm`, `.xls` or password-protected file: those are refused, and the answer is to re-save it
  as `.xlsx` first.

## Hand it over

The `.xlsx` is the deliverable. The `.html` is the same table as a page (and the source of the
PDF), rendered here rather than by Excel — say "preview" when you mean it. The `.pdf` is for sending
to somebody who should not edit it. One line on which is which, and the workbook's path in the
reply.
