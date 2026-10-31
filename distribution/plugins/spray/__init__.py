"""spray — record an application against the operator's own spray book.

Registers two tools under the `spray` toolset:

    spray_record   resolve the block and the product, multiply rate by area, and date the
                   earliest safe harvest from the withholding period on file
    spray_inputs   the label facts on file, and which ones are still missing

The engine contains no vendor names and no label data: the blocks and the inputs come from an
operator-maintained JSON file (`spraybook.json`), and every figure on the record is computed in
`sprayengine/`, which imports the kernel and the standard library and nothing else.
"""
from __future__ import annotations

from . import pantler_kernel  # noqa: F401  (the vendored-kernel fallback)
from . import schemas, tools


def register(ctx):
    tools._CTX = ctx
    for name, schema, handler in tools._TOOLS:
        ctx.register_tool(name=name, toolset=tools.TOOLSET, schema=schema, handler=handler)
