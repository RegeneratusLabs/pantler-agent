"""consent — the pre-send gate: who may be written to, and who may not.

Registers one tool under the `consent` toolset. It reads the consent records the app writes and never
decides for itself that a soft opt-in applies.
"""
from __future__ import annotations

from . import pantler_kernel  # noqa: F401  (the vendored-kernel fallback)
from . import tools

name = "consent"

__all__ = ["name", "register"]


def register(ctx) -> None:
    tools._CTX = ctx
    for tool_name, schema, handler in tools._TOOLS:
        ctx.register_tool(name=tool_name, toolset=tools.TOOLSET, schema=schema, handler=handler)
