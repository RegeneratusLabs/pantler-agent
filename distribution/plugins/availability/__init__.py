"""availability — a spoken field walk becomes an unpriced, customer-facing list.

Registers one tool under the `availability` toolset. The items come from the operator's own
catalogue (the price book the invoicing tool reads); the list carries no prices, and nothing that
failed to match is dropped.
"""
from __future__ import annotations

from . import pantler_kernel  # noqa: F401  (the vendored-kernel fallback)
from . import tools

name = "availability"

__all__ = ["name", "register"]


def register(ctx) -> None:
    tools._CTX = ctx
    for tool_name, schema, handler in tools._TOOLS:
        ctx.register_tool(name=tool_name, toolset=tools.TOOLSET, schema=schema, handler=handler)
