"""Tool schemas — what the model sees, and the sentences that keep it out of the numbers.

Three rules run through every description here, and they are the product's rather than the format's:

* **The model supplies content, never a computed figure.** A total is a formula the tool writes
  and a value the tool computes; a model-written total is a number nobody can check.
* **A column's type is declared, not guessed.** `money` is dollars, `percent` is a fraction, `date`
  is an ISO string. Guessing is how a 15% rate becomes 1500%.
* **The honest limit is named.** A preview is our rendering, not Excel's; a PDF needs a browser; a
  macro-enabled file is refused rather than opened.
"""

from __future__ import annotations

_READ = {
    "name": "office_read",
    "description": (
        "Read an existing .xlsx, .docx or .pptx file into structure, so you can talk about what is "
        "in it rather than guessing. For a workbook: `content` returns the rows of a sheet, "
        "`formulas` every formula with the value the file last stored, `notes` the cell notes, "
        "`summary` the sheets and their sizes. For a Word document: `summary` the headings and "
        "table shapes, `content` the text and tables, `notes` whether tracked changes or comments "
        "are present. For a deck: `summary` the slide outline, `notes` the speaker notes. Reads "
        "only; it never changes the file. Refuses a macro-enabled, encrypted or legacy binary file "
        "with the reason."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "The file, in this business's workspace or "
                                                      "uploads."},
            "part": {
                "type": "string",
                "enum": ["summary", "content", "notes", "formulas"],
                "description": "What to read. Default `content`.",
            },
            "sheet": {"type": "string", "description": "Workbook only: one sheet's name. Default "
                                                       "the active sheet."},
            "max_rows": {"type": "integer", "minimum": 1, "maximum": 500,
                         "description": "Stop after this many rows. Default 200."},
        },
        "required": ["path"],
    },
}

_CREATE = {
    "name": "xlsx_create",
    "description": (
        "Write an .xlsx workbook from a spec, plus a one-page HTML preview and (when a browser is "
        "present) a PDF of the same page. Pass `spec` with `columns` and `rows`: each column names "
        "a `header`, a `key`, and a `type` of text, number, integer, money, percent or date. Mark a "
        "column `total: true` and the tool writes a SUM formula AND the value it computed — never "
        "supply a total yourself, and never supply a figure you were not given. `money` is dollars "
        "and `percent` is a fraction (0.15 is 15%). For a report over the operator's own records, "
        "pass `source: {kind: \"records\", type: \"spray\"}` instead of rows: the store is read "
        "deterministically and its money fields (stored in cents) are converted for you. The tool "
        "returns where it wrote each file."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "spec": {
                "type": "object",
                "description": "The workbook. Either `sheets: [...]` or one sheet's keys inline.",
                "properties": {
                    "title": {"type": "string", "description": "Shown above the table and used in "
                                                              "the filename."},
                    "sheet": {"type": "string", "description": "Sheet name. Default `Sheet1`."},
                    "columns": {
                        "type": "array",
                        "description": "One object per column, left to right.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "header": {"type": "string"},
                                "key": {"type": "string", "description": "Lowercase identifier "
                                                                        "used by rows. Defaults "
                                                                        "from the header."},
                                "type": {"type": "string",
                                         "enum": ["text", "number", "integer", "money", "percent",
                                                  "date"]},
                                "format": {"type": "string", "description": "An Excel number "
                                                                            "format, when the "
                                                                            "default is wrong."},
                                "width": {"type": "number"},
                                "total": {"type": "boolean", "description": "Sum this column."},
                            },
                            "required": ["header"],
                        },
                    },
                    "rows": {
                        "type": "array",
                        "description": "Objects keyed by column `key`, or lists in column order.",
                    },
                    "totals": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Column keys to sum, when `total: true` is not used.",
                    },
                    "freeze": {"type": "boolean", "description": "Keep the header row visible. "
                                                                 "Default true."},
                    "filter": {"type": "boolean", "description": "Add an autofilter to the table. "
                                                                 "Default true."},
                    "merges": {"type": "array", "items": {"type": "string"},
                               "description": "Extra ranges to merge, like A1:C1."},
                    "sheets": {"type": "array", "description": "Several sheets, each an object of "
                                                               "these keys."},
                },
            },
            "source": {
                "type": "object",
                "description": "Fill `rows` from the operator's record store instead of supplying "
                               "them.",
                "properties": {
                    "kind": {"type": "string", "enum": ["records"]},
                    "type": {"type": "string", "description": "The record type, like `spray` or "
                                                              "`harvest`."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 500,
                              "description": "Rows to take, newest first. Default 200."},
                    "columns": {"type": "array", "items": {"type": "string"},
                                "description": "Only these field names, in this order."},
                    "since": {"type": "string", "description": "Earliest date, YYYY-MM-DD."},
                    "until": {"type": "string", "description": "Latest date, YYYY-MM-DD."},
                },
                "required": ["kind", "type"],
            },
            "out": {"type": "string", "description": "Where to write it, inside the workspace. "
                                                     "Defaults to output/."},
            "preview": {"type": "boolean", "description": "Write the HTML page. Default true."},
            "pdf": {"type": "boolean", "description": "Print the page to PDF. Default true."},
        },
        "required": ["spec"],
    },
}

_EDIT = {
    "name": "xlsx_edit",
    "description": (
        "Change one sheet of an existing .xlsx and write the result to a NEW file — the input is "
        "never modified. Three operations, and nothing else: `set_cells` (a map of cell to value, "
        "like {\"B2\": 12.5}), `append_rows` (lists of values, added after the last row), and "
        "`rename_sheet` (from/to). A value that looks like a number, a date or true/false is stored "
        "as one; the result names any cell where that happened, so you can say so. Formulas already "
        "in the workbook are preserved. Refuses a macro-enabled or encrypted file."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "The workbook to copy and change."},
            "op": {"type": "string", "enum": ["set_cells", "append_rows", "rename_sheet"]},
            "sheet": {"type": "string", "description": "The sheet to change. Default the active "
                                                       "sheet."},
            "cells": {"type": "object", "description": "`set_cells`: cell → value, like "
                                                       "{\"A2\": \"kale\", \"B2\": 12}."},
            "rows": {"type": "array", "description": "`append_rows`: each row a list of values.",
                     "items": {"type": "array"}},
            "from": {"type": "string", "description": "`rename_sheet`: the current name."},
            "to": {"type": "string", "description": "`rename_sheet`: the new name."},
            "out": {"type": "string", "description": "Where to write the copy, inside the "
                                                     "workspace. Defaults to output/."},
        },
        "required": ["path", "op"],
    },
}
