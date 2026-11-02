"""office — Word, Excel and PowerPoint documents, made and read inside Pantler.

Registers three tools under the `office` toolset:

    office_read   read a workbook, a Word document or a deck into structure
    xlsx_create   a workbook from a spec, plus its preview page and a PDF
    xlsx_edit     change a copy of a workbook: cells, appended rows, a renamed sheet

Why a plugin rather than a skill full of scripts: a skill's script runs under whatever `python3`
the operator has, which is the failure the studio plugin already fixed for design. A plugin runs in
the engine process, whose environment the payload stages, so the capability cannot load, plan and
then fail to run. The format work itself is the pinned engine's own MIT office scripts, vendored
unmodified in `office_engine/upstream/` — see `PROVENANCE.md`.
"""
from __future__ import annotations

from . import pantler_kernel  # noqa: F401  (the vendored kernel, before anything imports it)
from . import tools

name = "office"

__all__ = ["name", "register"]


def register(ctx) -> None:
    tools._CTX = ctx
    for tool_name, schema, handler in tools._TOOLS:
        ctx.register_tool(name=tool_name, toolset=tools.TOOLSET, schema=schema, handler=handler)
