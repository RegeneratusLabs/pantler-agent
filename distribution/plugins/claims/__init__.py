"""claims — lint marketing copy for claims, before it reaches anybody.

Registers one tool under the `claims` toolset. Pure lookup: no catalogue, no store, no network.
"""
from __future__ import annotations

from . import pantler_kernel  # noqa: F401  (the vendored-kernel fallback)
from . import tools

name = "claims"

__all__ = ["name", "register"]


def register(ctx) -> None:
    tools._CTX = ctx
    for tool_name, schema, handler in tools._TOOLS:
        ctx.register_tool(name=tool_name, toolset=tools.TOOLSET, schema=schema, handler=handler)
