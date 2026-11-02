# Provenance

What this plugin ships, where it came from, and what is ours. Read this before editing anything in
`office_engine/upstream/`.

## The format layer

`office_engine/upstream/` holds five scripts copied **unmodified** from the pinned engine's own
office skills. They are MIT, authored by Nous Research, and part of the artefact Pantler already
runs: the engine is pinned at `bf0203a794a07aac3ff764972ab9087baa4e4f4e` (`v0.22.5`) and its
`LICENSE` ships beside them as `LICENSE.engine`.

| Upstream path | Here | Upstream hash (sha256) |
|---|---|---|
| `skills/productivity/xlsx/scripts/xlsx_create.py` | `office_engine/upstream/xlsx_create.py` | `f6be8af8…b5f7eed417` (see `UPSTREAM.sha256`) |
| `skills/productivity/xlsx/scripts/xlsx_edit.py` | `office_engine/upstream/xlsx_edit.py` | `f689b1c3…fa4c4a9cc` |
| `skills/productivity/xlsx/scripts/xlsx_read.py` | `office_engine/upstream/xlsx_read.py` | `5ab31b1b…fa0ca0916` |
| `skills/productivity/docx/scripts/docx_read.py` | `office_engine/upstream/docx_read.py` | `4760617e…f9129de` |
| `skills/productivity/powerpoint/scripts/pptx_read.py` | `office_engine/upstream/pptx_read.py` | `b2a6e246…fdbc71` |

`UPSTREAM.sha256` carries the exact hashes, and `tests/test_upstream.py` asserts the shipped files
still match them: an edit to a vendored script must be deliberate, and must update both files and
this table. the engine-update notes carries the re-diff step for every engine re-pin.

**Nothing is patched.** Each script is a self-contained argparse CLI that takes a JSON spec and
prints JSON, so the wrapper in `../spec.py`, `../runtime.py` and `../tools.py` does the product's
work around them: path scope, the small spec the model is allowed to write, cached formula values,
the preview, the envelope.

## What was refused, and why

| Upstream | Why it is not here |
|---|---|
| `skills/productivity/pdf` | its OCR path depends on **PyMuPDF (AGPL-3.0)** and marker — copyleft in the shipped path, which invariant 5 forbids. The `documents` skill already owns the PDF route through Chromium. |
| `skills/productivity/docx/scripts/docx_create.py` and the docx edit/template/comments/revisions scripts | Phase B. Vendored with the tool that exposes them, not before — an unreferenced script is surface nobody reviewed. |
| the catalogue's `office-desk` plugin | third-party, community tier, depends on three forked libraries and the operator's LibreOffice, and runs in-process with full app authority. Invariant 2: the install carries first-party code only, and this is code we did not read and cannot patch. See `docs/office-suite.md`. |

## The rest

Everything else in this plugin — the spec translator, the OOXML cached-value pass, the preview
renderer, the Chromium PDF route, the tools, the schemas and the skill text — is authored here
under the MIT licence, like every other first-party plugin. The PDF route follows the pattern
`plugins/studio/studio_engine/screenshot.py` established (find the browser the machine already has,
run it headless once, and say so honestly when it is absent); the two modules are deliberately
separate copies rather than a shared package, because a plugin is loaded on its own.

## Dependencies

`requirements.txt` pins the libraries the scripts import, exactly. Licences: python-docx MIT,
openpyxl MIT, python-pptx MIT, lxml BSD-3, XlsxWriter BSD-2, et-xmlfile MIT, typing_extensions
PSF-2.0, Pillow MIT-CMU. All inside the repository's allowlist, and the `licences` job in CI scans
the file so a moved licence is a build failure.

**`defusedxml` is deliberately absent.** openpyxl's documentation recommends it, but its licence is
not mapped by the scanner's database, so it would have to be waved through as "non-standard" — a
gate nobody can trust. Its job is done before it: `office_engine/guard.py` reads every XML part in
full (to a hard cap) and refuses any that declares a document type, which is the construct that
turns a small part into a large parse. `tests/test_guard.py` pins that, including the padded prolog.

Pillow is pinned rather than left to the resolver: `python-pptx` asks for `>=3.3.2`, and a
requirements-only resolution picks a 2021 release with a wall of published CVEs. The engine already
ships 13.0.0, so naming it keeps the closure equal to what runs.
