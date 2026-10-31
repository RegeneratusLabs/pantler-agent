"""studio — the deterministic half of the design skill.

Registers five tools under the `studio` toolset. The split is the product's own rule: the model
supplies words, choices and the brief; this plugin supplies every measurement. A card the model
composed by hand is a card nobody measured, and an unmeasured card is how text ends up clipped at
the edge of a 1080 px square.

Why a plugin rather than the shell script the `design` skill used to carry: a script depends on an
interpreter that has Pillow, and the shipped `python3` does not always. A tool runs inside the
engine process, where the image library already is, so the capability cannot load, plan and then
fail to run (the 2026-10-19 `social-carousel` session).
"""
from __future__ import annotations

from . import tools

name = "studio"

__all__ = ["name", "register"]


def register(ctx) -> None:
    tools._CTX = ctx
    for tool_name, schema, handler in tools._TOOLS:
        ctx.register_tool(name=tool_name, toolset=tools.TOOLSET, schema=schema, handler=handler)
