"""A workbook as one page a person can read — the preview, and the source of the PDF.

This is our rendering, not Excel's, and the tool says so. It exists because the app's preview pane
refuses an `.xlsx` with a download button and a reason, so a document the assistant just produced
would arrive looking like something it could not show. A workbook we wrote is a table we already
hold in memory; drawing it as HTML is the honest finished form, and the same page printed by the
browser is the PDF.

Every cell is escaped and there is no script, no stylesheet and no image from anywhere: the page is
served through the app's opaque-origin preview, and it must stay inert.
"""

from __future__ import annotations

from html import escape

_CSS = """
  :root { color-scheme: light; }
  @page { size: A4; margin: 16mm 14mm; }
  * { box-sizing: border-box; }
  body { margin: 0; padding: 24px; background: #fff; color: #1c1c1c;
         font: 11pt/1.45 "Inter", "Segoe UI", system-ui, sans-serif; }
  .doc { max-width: 980px; margin: 0 auto; }
  h1 { font-size: 18pt; margin: 0 0 2mm; letter-spacing: -0.01em; }
  .meta { color: #6b6b6b; font-size: 9.5pt; margin: 0 0 6mm; }
  .sheet + .sheet { margin-top: 10mm; }
  h2 { font-size: 12pt; margin: 0 0 2mm; color: %(accent)s; }
  table { width: 100%%; border-collapse: collapse; font-size: 9.5pt; }
  th { text-align: left; font-weight: 600; background: #f4f4f1; border-bottom: 1px solid #dddddd;
       padding: 5px 8px; }
  td { padding: 4px 8px; border-bottom: 1px solid #eeeeee; vertical-align: top; }
  tr.total td { font-weight: 600; background: #fafaf7; border-top: 1px solid #cccccc; }
  td.num { text-align: right; font-variant-numeric: tabular-nums; }
  .foot { margin-top: 8mm; color: #6b6b6b; font-size: 8.5pt; }
  @media print { body { padding: 0; } }
"""


def workbook_html(built, *, title: str = "", meta: str = "", accent: str = "#3a5a40",
                  footer: str = "") -> str:
    """One self-contained page for a `spec.Built` workbook."""
    heading = escape(title or built.engine.get("title") or "Workbook")
    parts = [f"<h1>{heading}</h1>"]
    if meta:
        parts.append(f'<p class="meta">{escape(meta)}</p>')
    for sheet in built.sheets:
        parts.append('<section class="sheet">')
        if title and sheet.get("title"):
            parts.append(f"<h2>{escape(sheet['title'])}</h2>")
        elif len(built.sheets) > 1:
            parts.append(f"<h2>{escape(sheet['name'])}</h2>")
        parts.append(_table(sheet))
        parts.append("</section>")
    if footer:
        parts.append(f'<p class="foot">{escape(footer)}</p>')
    return _page("\n".join(parts), accent=accent)


def _table(sheet: dict) -> str:
    rows = sheet.get("rows") or []
    total_row = sheet.get("total_row")
    width = max(1, len(sheet.get("columns") or []))
    head = "".join(f"<th>{escape(str(name))}</th>" for name in sheet.get("columns") or [])
    body = []
    for index, row in enumerate(rows):
        classes = ' class="total"' if total_row is not None and index + 1 == total_row else ""
        cells = []
        for value in row:
            cells.append(f"<td>{escape(str(value))}</td>")
        body.append(f"<tr{classes}>{''.join(cells)}</tr>")
    if not rows:
        body.append(f'<tr><td colspan="{width}"></td></tr>')
    return (f"<table><thead><tr>{head}</tr></thead>"
            f"<tbody>{''.join(body)}</tbody></table>")


def _page(body: str, *, accent: str) -> str:
    colour = accent if _is_colour(accent) else "#3a5a40"
    return (
        "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>Pantler workbook preview</title>"
        f"<style>{_CSS % {'accent': colour}}</style></head>"
        f"<body><main class=\"doc\">{body}</main></body></html>\n"
    )


def _is_colour(value: str) -> bool:
    text = str(value or "").strip()
    return bool(text.startswith("#") and len(text) in (4, 7)
                and all(character in "0123456789abcdefABCDEF" for character in text[1:]))
