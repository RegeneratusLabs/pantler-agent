#!/usr/bin/env python3
"""Assert that the kernel imports the standard library and itself, nothing else.

the design notes §1 claims the kernel survives a change of engine, and `core/pyproject.toml` states the
mechanical half of it as `dependencies = []` with a comment. This script is the same claim as a
build failure, because a comment in a manifest fails nothing: it walks every module under
`core/src/pantler_core/`, resolves every import, and reports the ones that leave the package.

It parses rather than searches, so "hermes" in a docstring is not a violation. Relative imports
are resolved against the package — the kernel is flat, so one dot is a sibling and two dots
leave it. It does not pretend to be complete: a module loaded by name at runtime
(`importlib.import_module("pantler_server")`) is a blind spot, and closing it would mean
running the kernel rather than reading it.

Usage:
    scripts/check-seam.py          exit 1 on any import that leaves the kernel
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KERNEL = ROOT / "core" / "src" / "pantler_core"
PACKAGE = KERNEL.name


def neighbouring_modules() -> frozenset[str]:
    """Every module name inside the kernel, for resolving relative imports."""
    return frozenset(
        path.stem if path.is_file() else path.name
        for path in KERNEL.iterdir()
        if path.suffix == ".py" or (path.is_dir() and (path / "__init__.py").is_file())
    )


def forbidden_roots() -> frozenset[str]:
    """The top-level names the kernel may not import, other than the standard library.

    Read from the trees rather than listed here, so a module that appears tomorrow is
    forbidden the day it lands rather than the day someone remembers this file. The
    engine is `hermes*` because the kernel must not know the name of the thing running
    it; the plugins and the BFF are today `pantler`, `soil_amendment`, `soilengine` and
    `pantler_server`, `engine_settings`, `previews`, `skills_index`, `learning`,
    `capabilities`, `attachments`.
    """
    plugins = ROOT / "plugins"
    names: set[str] = set()
    if plugins.is_dir():
        for directory in plugins.iterdir():
            if not (directory / "plugin.yaml").is_file():
                continue
            # A plugin directory name is not always an identifier: soil-amendment is
            # imported as soil_amendment. Its inner packages travel with it.
            names.add(directory.name.replace("-", "_"))
            names.update(
                inner.parent.name
                for inner in directory.glob("*/__init__.py")
                if inner.parent.name != "tests"
            )
    server = ROOT / "app" / "server"
    if server.is_dir():
        names.update(path.stem for path in server.glob("*.py"))
    return frozenset(names)


def imports_of(tree: ast.Module) -> list[tuple[int, str]]:
    """Every module a parsed file imports, as (line number, dotted name)."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            # Both halves matter: the level says which package the name is relative
            # to, and a bare `from . import x` has no module part at all.
            found.append((node.lineno, "." * node.level + (node.module or "")))
    return found


def offence(name: str, neighbours: frozenset[str], forbidden: frozenset[str]) -> str | None:
    """The module as it is written when the kernel may not import it, or None when it may."""
    if not name:
        return None
    if name.startswith("."):
        # A relative import is how a flat package refers to itself: one dot is the package,
        # so `.store` resolves to pantler_core.store and `.` to the package itself. Two dots
        # climb out of a top-level package, where nothing exists to import, and a single dot
        # naming no module in the package is an import that cannot resolve at all.
        if name == "." or (not name.startswith("..") and name[1:] in neighbours):
            return None
        return name
    top = name.split(".", 1)[0]
    if top == PACKAGE:
        return None
    if top.startswith("hermes") or top in forbidden or top not in sys.stdlib_module_names:
        return name
    return None


def main() -> int:
    if not (KERNEL / "__init__.py").is_file():
        print(f"check-seam: no kernel package at {KERNEL.relative_to(ROOT)}", file=sys.stderr)
        return 1

    neighbours = neighbouring_modules()
    forbidden = forbidden_roots()
    modules = sorted(KERNEL.rglob("*.py"))
    imports = 0
    violations: list[tuple[Path, int, str]] = []

    for path in modules:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for line, name in imports_of(tree):
            imports += 1
            if bad := offence(name, neighbours, forbidden):
                violations.append((path, line, bad))

    for path, line, bad in sorted(violations, key=lambda item: (item[0], item[1])):
        print(f"{path.relative_to(ROOT)}:{line}: {bad}")

    if violations:
        print(
            f"check-seam: {len(violations)} import(s) leave the kernel — "
            f"{KERNEL.relative_to(ROOT)} may import the standard library and itself, nothing else "
            "(the design notes §1)",
            file=sys.stderr,
        )
        return 1

    print(f"check-seam: {len(modules)} modules, {imports} imports — standard library and the kernel only")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
