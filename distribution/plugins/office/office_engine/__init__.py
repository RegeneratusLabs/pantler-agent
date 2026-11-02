"""The office format layer: vendored scripts, and the product rules wrapped around them.

`upstream/` holds five unmodified MIT scripts from the pinned engine (see `../PROVENANCE.md`).
This package never edits them. It runs one, translates the small spec the model is allowed to
write into the script's own spec, puts the computed values back into the workbook, and renders the
preview — so the product's rules (scope, determinism, the honest result) live in our code and the
file-format knowledge lives in theirs.
"""

from __future__ import annotations

__all__ = ["runtime", "spec", "ooxml", "preview", "pdf", "records"]
