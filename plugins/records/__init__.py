"""records — the operator's own records, readable and writable from a conversation.

Registers five tools under the `records` toolset:

    record_save          save a certificate, block, harvest, input or a custom type
    record_find          read records back, optionally filtered
    record_types         what can be recorded, and which fields each type requires
    record_type_propose  propose a new custom record type (read-only)
    record_type_create   create it after the operator's approval

The store is the kernel's (`pantler_core.RecordBook`), the same one the app writes through, so a
record made here and one typed into a screen are the same record. A new kind of record is a type
in that store, never a skill, a CSV or a second database. Standard library and the kernel only;
nothing outbound.
"""
from __future__ import annotations

from . import pantler_kernel  # noqa: F401  (the vendored-kernel fallback)
from . import tools

name = "records"

__all__ = ["name", "register"]


def register(ctx) -> None:
    tools._CTX = ctx
    for name, schema, handler in tools._TOOLS:
        ctx.register_tool(name=name, toolset=tools.TOOLSET, schema=schema, handler=handler)
    register_hook = getattr(ctx, "register_hook", None)
    if callable(register_hook):
        register_hook("pre_tool_call", tools.pre_tool_call)
