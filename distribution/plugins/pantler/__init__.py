"""pantler's Hermes plugin: the invoice tools.

Loaded either as a directory plugin (``HERMES_HOME/plugins/pantler/``) or as a pip
package exposing the ``hermes_agent.plugins`` entry point. Both paths land here.

This module is a thin composition root. The business logic lives in ``pantler_core``,
which knows nothing about Hermes (the design notes §1).

**There is no approval gate here, deliberately.** Money handling is not a centred feature
of the product — it belongs in a pack, as a plugin or skill, when we build it. The engine
can still raise an approval for anything, so a gate can come back with that pack; what we
do not do is carry one in the core plugin and let it define the product.
"""

from __future__ import annotations

from typing import Any

# Before anything that imports the kernel: the vendored copy is the fallback when the
# engine's environment does not have it (see pantler_kernel.py).
from . import pantler_kernel  # noqa: F401
from . import scope, tools

name = "pantler"

__all__ = ["name", "register"]


def register(ctx: Any) -> None:
    """Called once by the plugin loader. Registers our tools and the profile boundary."""
    tools.register(ctx)
    register_hook = getattr(ctx, "register_hook", None)
    if callable(register_hook):
        register_hook("pre_tool_call", scope.pre_tool_call)
