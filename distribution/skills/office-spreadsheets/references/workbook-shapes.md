# Workbook shapes that come up

Four shapes cover most of the work. Each is a spec you can adapt; the tool's schema is the
authority on the keys.

## The accountant's quarter

Everything that moved, one sheet per kind, totals at the bottom, one row per record.

```json
{
  "title": "Quarter to 30 September 2026",
  "sheets": [
    {
      "name": "Invoices",
      "columns": [
        {"header": "Invoice", "key": "number"},
        {"header": "Date", "key": "issued_on", "type": "date"},
        {"header": "Customer", "key": "customer"},
        {"header": "Subtotal", "key": "subtotal", "type": "money", "total": true},
        {"header": "Tax", "key": "tax", "type": "money", "total": true},
        {"header": "Total", "key": "total", "type": "money", "total": true}
      ],
      "rows": []
    }
  ]
}
```

Rows come from the store (`source: {"kind": "records", "type": "invoice", "since": "...",
"until": "..."}`), not from your transcription. If the accountant also wants the list of payments,
that is a second sheet, not a second file.

## The spray summary an inspector reads

One row per application, the product and rate as recorded, the withholding period as it was on the
day, and the earliest safe date. Those last two are copied from the record, never recomputed — the
record is what the operator attested to.

```
Block · Date · Product · Rate · Area · Operator · Withholding (days) · Earliest safe
```

## The price sheet the market sees

No costs, no margins, no customer names. Product, unit, price, and the day it was set. Prices come
from the operator or the price book; a price you invented is the worst possible error in this file.

## The traceability export (FSMA 204 shape)

An "electronic sortable spreadsheet" is a normal workbook with the right columns: the lot code, the
critical tracking event, the key data elements, the date, and who held it. Keep it one sheet, one
header row, no merged cells and no blank rows — the point is that a regulator can sort and filter it.

The rule that matters more than the shape: **the enforcement date has moved more than once**. Do not
state a deadline in the workbook or the reply. Cite the current one from the compliance skill, and
print the date the file was made.
