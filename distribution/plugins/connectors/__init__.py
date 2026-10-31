"""connectors — use the apps the operator has connected.

One tool, three actions (status · tools · run), one policy: a read through a connection is an
ordinary read, and a write is escalated to the engine's human-approval gate by the
``pre_tool_call`` hook before the handler can send anything.

The connection itself, the Composio key and the operator's opaque ``user_id`` live in the BFF
(``app/server/connectors.py``). This plugin is the model-facing side of that service: it holds no
credential and makes no direct call to Composio, which is why installing it grants no ambient
authority over the operator's accounts.
"""

from __future__ import annotations

from . import tools

name = "connectors"

__all__ = ["name", "register"]


def register(ctx) -> None:
    tools._CTX = ctx
    # The hook is registered before the tool: a tool that could run without its gate is worse
    # than no tool. The handler also refuses writes when this flag has not been set.
    ctx.register_hook("pre_tool_call", tools.pre_tool_call)
    tools._HOOK_REGISTERED = True
    for tool_name, schema, handler in tools._TOOLS:
        ctx.register_tool(name=tool_name, toolset=tools.TOOLSET, schema=schema, handler=handler)
