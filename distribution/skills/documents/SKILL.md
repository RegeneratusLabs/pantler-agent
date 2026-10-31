---
name: documents
description: Make a document the operator can send, print or keep.
license: MIT
metadata:
  category: pantler
  source: authored in this repository; the render route was measured on the dev host (chromium's headless CLI aborts on a long singleton-socket path)
---

# Documents

Use this when the operator asks for something to send, print, sign, keep or hand to an
inspector: a pack, a checklist, a label sheet, a quote, a report, a letter.

## First: what will they do with it?

- **Send or print** → a PDF. It is the document. Keep the HTML beside it as the source.
- **Edit later** → the HTML is the editable copy. Say plainly that the PDF is the one to send.
- **Look at it in the chat** → an image is a preview, never the document. If the chat can only
  show an image, give the PDF's path beside it.

## Write the HTML first

One self-contained file, A4, no external assets. The page box does the work:

```html
<style>
  @page { size: A4; margin: 16mm 15mm; }
  body { font-family: "DejaVu Sans", Arial, sans-serif; font-size: 10.2pt;
         line-height: 1.42; color: #1c1c1c; }
  h1 { font-size: 17pt; margin: 0 0 2mm; }
  table { width: 100%; border-collapse: collapse; }
  th, td { text-align: left; padding: 2mm; border-bottom: 1px solid #e2e2e2; }
</style>
```

Name it for what it is and the day, in the workspace's `output/` directory:
`organic-audit-pack-2026-10-20.html`.

## Render the PDF

The reliable route on this host is the browser tool and Chrome DevTools Protocol. The chromium
CLI aborts with `Socket path too long` when its profile directory is deep — the singleton
socket has a hard length limit.

```python
import base64, os
new_tab("file:///absolute/path/to/document.html")
wait_for_load()
res = cdp('Page.printToPDF', printBackground=True, preferCSSPageSize=True,
          marginTop=0, marginBottom=0, marginLeft=0, marginRight=0)
data = base64.b64decode(res['data'])
out = "/absolute/path/to/document.pdf"
open(out, "wb").write(data)
print("bytes", len(data), "pages", data.count(b"/Type /Page") - data.count(b"/Type /Pages"))
```

If you use the CLI instead, give it a short profile directory (`--user-data-dir=/tmp/cr`).
There is no reportlab, weasyprint, fpdf, pandoc or wkhtmltopdf on this host; do not plan around
them.

## Check it before you hand it over

- The page count is what you expected.
- The text is really there: read the PDF back. A page that is only an image of text is not a
  document an inspector can search.
- Nothing is cut off at the page edge; tighten the type or add a second page.
- The filename says what it is and the day it was made.

## Hand it over

The PDF is the deliverable. The HTML is the source. An image is a preview. Say which is which
in one line, and put the PDF's path in the reply.
