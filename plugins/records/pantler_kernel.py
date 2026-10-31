"""Make the kernel importable, from the copy this plugin shipped with.

`pantler_core` is not installed into the engine's Python environment by anything the engine knows
about. On a dev machine `scripts/dev-sync.sh` puts it there by hand; an engine update then builds a
*fresh* dependency environment that does not have it, which is why the dev script has to be re-run
after one. On a customer's machine there is no dev script at all, and the failure is silent until a
tool is called: the plugin simply does not import.

So each plugin that needs the kernel carries the kernel, in `vendor/`, generated from
`core/src/pantler_core` by `scripts/check-distribution.py --sync-plugins` and asserted
byte-identical by the same script.

**The vendored copy wins** (`insert`, not `append`). It used to be the fallback — "an installed
kernel wins" — and that turned a stale install into the kernel the tools actually ran: on this
machine both installed copies were two days behind, so `load_packs` raised on the current packs,
the store was still created world-readable, and every kernel fix after that date was silently
bypassed (the internal security audit A19-KERN-1). The copy that ships with the plugin is
the copy the plugin was tested with; an install elsewhere is not more authoritative than that.
`SOURCE` says which one this process got, and `scripts/tests/test_vendored_kernel.py` asserts it.
"""

from __future__ import annotations

import sys
from pathlib import Path

_VENDOR = Path(__file__).resolve().parent / "vendor"


def ensure_kernel() -> str:
    """Put the vendored kernel first on the path, and say which copy is in use."""
    already = sys.modules.get("pantler_core")
    if already is not None:
        # Too late to choose: something imported the kernel before this shim ran. Report what it
        # got rather than pretending this plugin's copy is in use. Another plugin's vendored copy
        # is the same kernel, so it counts as vendored; anything else is an install.
        loaded = Path(getattr(already, "__file__", "") or "")
        vendored = loaded.parent.name == "pantler_core" and loaded.parent.parent.name == "vendor"
        return "vendored" if vendored else "installed"
    if not (_VENDOR / "pantler_core").is_dir():
        return "installed"
    path = str(_VENDOR)
    if path in sys.path:
        sys.path.remove(path)
    sys.path.insert(0, path)
    return "vendored"


SOURCE = ensure_kernel()
