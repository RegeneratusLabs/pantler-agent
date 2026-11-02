"""The office tools: three doors into the format layer, with the product's rules on this side.

Nothing here formats a document. Each handler validates what the model sent, resolves every path
against the active business's workspace, asks the vendored script to do the format work, and then
does the part the product owns: put the computed total into the file, name it, render the preview,
print the PDF, and return a result that says exactly what was and was not done.

The path rule is the same as the studio's: a business's documents live in its own workspace, a path
that resolves outside it is refused (symlinks included), and a workbook the operator uploaded is
readable from their own `attachments/` but never written to.
"""

from __future__ import annotations

import json
import os
import re
from datetime import date
from pathlib import Path
from typing import Any, Callable

from . import pantler_kernel  # noqa: F401  (the vendored kernel, before `pantler_core` is imported)
from . import schemas
from .office_engine import guard, pdf as pdf_engine, preview, records as records_engine
from .office_engine import runtime, spec as spec_engine
from .office_engine.ooxml import OoxmlError, finalise

TOOLSET = "office"
CAPABILITY_KEY = "capability_enabled"

_CTX = None

_READERS = {".xlsx": "xlsx_read.py", ".docx": "docx_read.py", ".pptx": "pptx_read.py"}
_PARTS = {
    ".xlsx": {"summary": "--sheets", "content": "--json", "formulas": "--formulas",
              "notes": "--notes"},
    ".docx": {"summary": "--structure", "content": "--text", "notes": "--revisions"},
    ".pptx": {"summary": "--outline", "content": "--outline", "notes": "--notes"},
}
_KINDS = {".xlsx": "workbook", ".docx": "word document", ".pptx": "slide deck"}
_REFERENCE = re.compile(r"^[A-Z]{1,3}[1-9][0-9]{0,6}$")
_SLUG = re.compile(r"[^a-z0-9]+")


# ------------------------------------------------------------------ configuration
def _setting(key: str, default: Any = None) -> Any:
    """One key of this plugin's own config, read the way the engine exposes it."""
    getter = getattr(_CTX, "get_config", None)
    if callable(getter):
        try:
            return getter(key, default)
        except TypeError:
            pass
        except Exception:
            return default
        try:
            block = getter()
        except Exception:
            block = None
        if isinstance(block, dict):
            return block.get(key, default)
    block = getattr(_CTX, "config", None)
    if isinstance(block, dict):
        return block.get(key, default)
    return default


def _switched_off() -> str | None:
    value = _setting(CAPABILITY_KEY, True)
    if value is False or (isinstance(value, str) and value.strip().lower() in ("false", "off", "no")):
        return _fail("Office documents are switched off in Capabilities. Switch them back on there "
                     "and ask me again.")
    return None


def _home() -> Path:
    home = os.environ.get("HERMES_HOME", "").strip()
    return Path(os.path.expanduser(home)) if home else Path.home() / ".hermes"


def _runtime_cwd() -> Path | None:
    """The workspace this request is actually for, when a gateway serves several businesses."""
    try:
        from agent.runtime_cwd import scope_terminal_cwd

        raw = str(scope_terminal_cwd() or "").strip()
    except Exception:
        return None
    if not raw:
        return None
    candidate = Path(os.path.expanduser(raw))
    return candidate.resolve() if candidate.is_absolute() and candidate.is_dir() else None


def _profile_home() -> Path | None:
    home = _home()
    try:
        if (home / "profiles").is_dir():
            active = (home / "active_profile").read_text(encoding="utf-8").strip()
            if not active:
                return None
            candidate = (home / "profiles" / active).resolve()
            return candidate if (candidate / "config.yaml").is_file() else None
    except OSError:
        return None
    return home if (home / "config.yaml").is_file() else None


def _configured_cwd(profile: Path) -> Path | None:
    try:
        lines = (profile / "config.yaml").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    section = ""
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line[:1].isspace():
            section = line.partition(":")[0].strip()
            continue
        if section != "terminal":
            continue
        key, _, value = line.strip().partition(":")
        if key.strip() == "cwd":
            raw = value.strip().strip("'\"")
            if raw and os.path.isabs(os.path.expanduser(raw)):
                candidate = Path(os.path.expanduser(raw))
                if candidate.is_dir():
                    return candidate.resolve()
    return None


def _workspace() -> Path:
    configured = _setting("workspace_dir")
    if configured:
        return Path(os.path.expanduser(str(configured))).resolve()
    env = os.environ.get("PANTLER_WORKSPACE", "").strip()
    if env:
        return Path(os.path.expanduser(env)).resolve()
    runtime_cwd = _runtime_cwd()
    if runtime_cwd:
        return runtime_cwd
    profile = _profile_home()
    if profile:
        configured_cwd = _configured_cwd(profile)
        if configured_cwd:
            return configured_cwd
        own = profile / "workspace" / profile.name
        return own.resolve() if own.is_dir() else (profile / "workspace").resolve()
    home = _home()
    shared = home / "workspace"
    own = shared / home.name
    return own.resolve() if own.is_dir() else shared.resolve()


def _attachments() -> Path | None:
    configured = _setting("attachments_dir")
    if configured:
        return Path(os.path.expanduser(str(configured))).resolve()
    profile = _profile_home()
    roots = [profile] if profile else []
    roots.append(_home())
    for root in roots:
        for candidate in (root / "attachments", root.parent / ".data" / "attachments"):
            if candidate.is_dir():
                return candidate.resolve()
    return None


def _confine(raw: Any, label: str = "path", must_exist: bool = False) -> Path:
    """One door from a caller's string to a path inside this business's workspace."""
    text = str(raw or "").strip()
    if not text:
        raise ValueError(f"{label} is empty")
    if "\x00" in text:
        raise ValueError(f"{label} is not a path")
    root = _workspace()
    candidate = Path(os.path.expanduser(text))
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve(strict=False)
    if not (resolved == root or root in resolved.parents):
        raise ValueError(
            f"{label} is outside this business's workspace. Documents are written into output/ in "
            f"the workspace; anything else is another business's file or yours, not this one's."
        )
    if must_exist and not resolved.exists():
        raise ValueError(f"{label} does not exist")
    return resolved


def _readable(raw: Any, label: str = "file") -> Path:
    """The operator's uploads are readable; anything else must be in the workspace."""
    text = str(raw or "").strip()
    candidate = Path(os.path.expanduser(text))
    if candidate.is_absolute() or text.startswith("."):
        roots = [root for root in (_workspace(), _attachments()) if root]
        resolved = candidate.resolve(strict=False)
        for root in roots:
            if resolved == root or root in resolved.parents:
                if resolved.is_file():
                    return resolved
                raise ValueError(f"{label} does not exist")
        raise ValueError(
            f"{label} is outside this business's workspace and uploads, so I will not open it. "
            f"Attach it and I will use it."
        )
    return _confine(text, label=label, must_exist=True)


def _profile_home_for_store() -> Path | None:
    return _profile_home()


def _store_paths() -> tuple[Path, Path, Path | None] | None:
    """`(store, packs, custom_packs)` — the same resolution the records plugin uses."""
    store = str(_setting("store_path") or os.environ.get("PANTLER_STORE") or "").strip()
    packs = str(_setting("packs_dir") or os.environ.get("PANTLER_PACKS") or "").strip()
    custom = str(_setting("custom_packs_dir") or os.environ.get("PANTLER_CUSTOM_PACKS") or "").strip()
    home = _home()
    profile = _profile_home_for_store()
    if not store and profile is not None:
        store = str(profile / "records.db")
    if not packs and profile is not None and (profile / "packs").is_dir():
        packs = str(profile / "packs")
    if not custom and profile is not None:
        custom = str(profile / "custom-packs")
    if not store and home:
        store = str(home / "records.db")
    if not packs and home:
        packs = str(home / "packs")
    if not custom and home:
        custom = str(home / "custom-packs")
    if not store or not packs:
        return None
    return (Path(os.path.expanduser(store)), Path(os.path.expanduser(packs)),
            Path(os.path.expanduser(custom)) if custom else None)


def _business() -> str:
    return str(_setting("business_name") or "").strip()


def _currency() -> str:
    return str(_setting("currency") or "$").strip() or "$"


def _fail(message: str, **extra: Any) -> str:
    payload = {"success": False, "error": message}
    payload.update(extra)
    return json.dumps(payload, default=str, ensure_ascii=False)


def _ok(payload: dict) -> str:
    payload = {"success": True, **payload}
    return json.dumps(payload, default=str, ensure_ascii=False)


def _today() -> str:
    return date.today().isoformat()


def _slug(text: str) -> str:
    cleaned = _SLUG.sub("-", str(text or "").lower()).strip("-")
    return (cleaned or "workbook")[:48]


def _output_path(raw: Any, *, stem: str, suffix: str) -> Path:
    """Where a produced file goes: the caller's path, or a dated name under output/."""
    if raw:
        target = _confine(raw, "the output path")
        if target.suffix.lower() != suffix:
            raise ValueError(f"the output path must end in {suffix}")
        target.parent.mkdir(parents=True, exist_ok=True)
        return target
    directory = _confine("output", "the output directory")
    directory.mkdir(parents=True, exist_ok=True)
    base = f"{_slug(stem)}-{_today()}"
    candidate = directory / f"{base}{suffix}"
    index = 2
    while candidate.exists():
        candidate = directory / f"{base}-{index}{suffix}"
        index += 1
    return candidate


def _checked(path: Path) -> dict:
    return guard.check(path)


# ------------------------------------------------------------------ tools
def office_read(params: dict, **kwargs) -> str:
    if (refusal := _switched_off()) is not None:
        return refusal
    try:
        path = _readable((params or {}).get("path"), "the file")
    except ValueError as exc:
        return _fail(str(exc))
    suffix = path.suffix.lower()
    if suffix not in _READERS:
        return _fail(
            f"{suffix or 'that file'} is not something this tool reads. It reads .xlsx, .docx and "
            f".pptx; a PDF is opened with the documents route, and a .csv as a table."
        )
    part = str((params or {}).get("part") or "content").strip().lower()
    if part not in _PARTS[suffix]:
        return _fail(f"a {_KINDS[suffix]} can be read as {', '.join(sorted(_PARTS[suffix]))} — "
                     f"not {part!r}.")
    try:
        _checked(path)
    except guard.GuardError as exc:
        return _fail(str(exc))
    arguments = [_PARTS[suffix][part]]
    sheet = str((params or {}).get("sheet") or "").strip()
    if suffix == ".xlsx" and sheet:
        arguments.extend(["--sheet", sheet])
    try:
        payload = runtime.run(_READERS[suffix], [str(path), *arguments])
    except runtime.OfficeError as exc:
        return _fail(str(exc))
    result = dict(payload)
    note = ""
    limit = (params or {}).get("max_rows")
    if suffix == ".xlsx" and isinstance(result.get("rows"), list) and limit not in (None, ""):
        try:
            capped = max(1, min(500, int(limit)))
        except (TypeError, ValueError):
            capped = 200
        if len(result["rows"]) > capped:
            result["rows"] = result["rows"][:capped]
            note = f"showing the first {capped} rows; the sheet has more"
    return _ok({
        "path": str(path),
        "kind": _KINDS[suffix],
        "part": part,
        "result": result,
        "note": note,
    })


def xlsx_create(params: dict, **kwargs) -> str:
    if (refusal := _switched_off()) is not None:
        return refusal
    spec = (params or {}).get("spec")
    if not isinstance(spec, dict):
        return _fail("pass the workbook as `spec` — an object with `columns` and `rows`, not a string")
    spec = dict(spec)
    source = (params or {}).get("source")
    if source:
        try:
            spec = _from_records(spec, source)
        except (records_engine.RecordsError, OSError, ValueError) as exc:
            return _fail(str(exc))
    try:
        built = spec_engine.build(spec, currency=_currency())
    except spec_engine.SpecError as exc:
        return _fail(str(exc))

    title = str(spec.get("title") or (spec.get("sheets") or [{}])[0].get("title") or "").strip()
    stem = title or str(spec.get("sheet") or (spec.get("sheets") or [{}])[0].get("name") or "workbook")
    try:
        out = _output_path((params or {}).get("out"), stem=stem, suffix=".xlsx")
    except ValueError as exc:
        return _fail(str(exc))

    try:
        runtime.run("xlsx_create.py", [str(out)], spec=built.engine)
    except runtime.OfficeError as exc:
        return _fail(str(exc))
    if not out.is_file():
        return _fail("the workbook was not written, though the script reported success; nothing to "
                     "hand over")

    not_done: list[str] = []
    checks = list(built.checks)
    try:
        finalised = finalise(out, cached=built.cached, creator=_business(), title=title,
                             application="Pantler", stamp=f"{_today()}T00:00:00Z")
        if finalised["missed"]:
            not_done.append("no cached value was written for " + ", ".join(finalised["missed"]))
        if finalised["skipped"]:
            not_done.append("a value was already stored for " + ", ".join(finalised["skipped"])
                            + ", so it was left as it was")
        if built.cached and not finalised["missed"]:
            checks.append(f"{len(built.cached)} total(s) written as a formula and its value")
    except OoxmlError as exc:
        not_done.append(str(exc))

    files = [str(out)]
    preview_path = ""
    if (params or {}).get("preview", True) is not False:
        try:
            preview_path = str(out.with_suffix(".html"))
            Path(preview_path).write_text(
                preview.workbook_html(built, title=title or stem, meta=_meta(built),
                                      accent=_accent()),
                encoding="utf-8",
            )
            files.append(preview_path)
        except OSError as exc:
            preview_path = ""
            not_done.append(f"the preview page could not be written: {exc}")

    pdf_path = ""
    if (params or {}).get("pdf", True) is not False:
        if not preview_path:
            not_done.append("no PDF was printed because there is no preview page to print")
        else:
            try:
                printed = pdf_engine.print_pdf(Path(preview_path), out.with_suffix(".pdf"))
                pdf_path = printed["path"]
                files.append(pdf_path)
            except pdf_engine.PdfError as exc:
                not_done.append(str(exc))

    payload: dict[str, Any] = {
        "resolved_path": str(out),
        "files_written": files,
        "bytes": out.stat().st_size,
        "sheets": [sheet["name"] for sheet in built.sheets],
        "checks": checks,
        "not_done": not_done,
        "note": ("The .xlsx is the deliverable; the .html is the same table as a page (and the "
                 "source of the PDF), rendered here rather than by Excel."),
    }
    if preview_path:
        payload["preview_path"] = preview_path
    if pdf_path:
        payload["pdf_path"] = pdf_path
    return _ok(payload)


def xlsx_edit(params: dict, **kwargs) -> str:
    if (refusal := _switched_off()) is not None:
        return refusal
    try:
        source = _readable((params or {}).get("path"), "the workbook")
    except ValueError as exc:
        return _fail(str(exc))
    if source.suffix.lower() != ".xlsx":
        return _fail(f"this tool edits .xlsx workbooks; {source.name} is not one")
    try:
        _checked(source)
    except guard.GuardError as exc:
        return _fail(str(exc))

    operation = str((params or {}).get("op") or "").strip()
    try:
        arguments, planned = _edit_arguments(operation, params or {}, source)
    except ValueError as exc:
        return _fail(str(exc))

    try:
        out = _output_path((params or {}).get("out"), stem=f"{source.stem}-edited", suffix=".xlsx")
    except ValueError as exc:
        return _fail(str(exc))
    if out == source:
        return _fail("the edited workbook would overwrite the original. Pass `out` somewhere else; "
                     "this tool always writes a copy.")
    arguments.extend(["--out", str(out)])
    try:
        result = runtime.run("xlsx_edit.py", [str(source), *arguments])
    except runtime.OfficeError as exc:
        return _fail(str(exc))
    if not out.is_file():
        return _fail("the edited workbook was not written; the original is untouched")

    not_done: list[str] = []
    if operation == "append_rows":
        # The vendored `--recalc` asks the reader to recalculate on open; the totals that follow
        # from new rows are Excel's to compute, and this tool does not pretend to have them.
        not_done.append("totals in the workbook recalculate when it is opened in Excel; they are "
                        "not recomputed here")
    return _ok({
        "resolved_path": str(out),
        "files_written": [str(out)],
        "source": str(source),
        "bytes": out.stat().st_size,
        "changes": planned,
        "result": result,
        "not_done": not_done,
        "note": "The original is untouched; the edited copy is the deliverable.",
    })


# ------------------------------------------------------------------ helpers
def _edit_arguments(operation: str, params: dict, source: Path) -> tuple[list[str], list[str]]:
    sheet = str(params.get("sheet") or "").strip()
    arguments: list[str] = []
    planned: list[str] = []
    if sheet:
        arguments.extend(["--sheet", sheet])
    if operation == "set_cells":
        cells = params.get("cells")
        if not isinstance(cells, dict) or not cells:
            raise ValueError("`set_cells` needs `cells`: an object of cell → value")
        for reference, value in cells.items():
            if not isinstance(reference, str) or not _REFERENCE.match(reference.upper()):
                raise ValueError(f"{reference!r} is not a cell reference like A1 or C12")
            text = _cell_text(value)
            arguments.extend(["--set", f"{reference.upper()}={text}"])
            if isinstance(value, str) and _would_coerce(value):
                planned.append(f"{reference.upper()} {value!r} is stored as a "
                               f"{_would_coerce(value)}")
            else:
                planned.append(f"{reference.upper()}")
    elif operation == "append_rows":
        rows = params.get("rows")
        if not isinstance(rows, list) or not rows:
            raise ValueError("`append_rows` needs `rows`: a list of lists")
        for row in rows:
            if not isinstance(row, list):
                raise ValueError("each appended row must be a list of values")
            arguments.extend(["--append", json.dumps(row, ensure_ascii=False)])
        arguments.append("--recalc")
        planned.append(f"{len(rows)} row(s) appended")
    elif operation == "rename_sheet":
        old = str(params.get("from") or "").strip()
        new = str(params.get("to") or "").strip()
        if not old or not new:
            raise ValueError("`rename_sheet` needs `from` and `to`")
        if ":" in old or ":" in new:
            raise ValueError("a sheet name with ':' cannot be renamed through this tool")
        arguments.extend(["--rename-sheet", f"{old}:{new}"])
        planned.append(f"renamed {old!r} to {new!r}")
    else:
        raise ValueError("`op` must be set_cells, append_rows or rename_sheet")
    return arguments, planned


def _cell_text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value
    raise ValueError(f"{value!r} is not a cell value; use text, a number, true/false or null")


def _would_coerce(text: str) -> str:
    """Would `xlsx_edit.py`'s inference store something other than the string it was given?"""
    if not text:
        return ""
    lowered = text.strip().lower()
    if lowered in ("true", "false"):
        return "true/false value"
    try:
        int(text)
        return "number"
    except ValueError:
        pass
    try:
        float(text)
        return "number"
    except ValueError:
        pass
    try:
        date.fromisoformat(text)
        return "date"
    except ValueError:
        return ""


def _from_records(spec: dict, source: dict) -> dict:
    """Rows from the operator's own store, replacing whatever rows the spec carried."""
    if not isinstance(source, dict):
        raise ValueError("`source` must be an object")
    if str(source.get("kind") or "") != "records":
        raise ValueError("`source.kind` is `records`; that is the only source this version reads")
    paths = _store_paths()
    if paths is None:
        raise ValueError("no record store is configured on this machine")
    store, packs, custom = paths
    if not packs.is_dir():
        raise ValueError(f"no packs directory named {packs.name!r} at the configured place")
    try:
        from pantler_core import RecordBook, RecordBookError

        book = RecordBook(store, packs, custom)
    except Exception as exc:  # RecordBookError, PackError, OSError
        raise ValueError(f"the record store could not be opened: {exc}") from exc
    try:
        table = records_engine.rows(
            book,
            str(source.get("type") or ""),
            limit=int(source.get("limit") or 200),
            columns=source.get("columns") if isinstance(source.get("columns"), list) else None,
            since=str(source.get("since") or ""),
            until=str(source.get("until") or ""),
        )
    finally:
        try:
            book.close()
        except Exception:
            pass
    merged = dict(spec)
    merged["columns"] = table["columns"]
    merged["rows"] = table["rows"]
    merged.setdefault("sheet", table["label"])
    merged.setdefault("title", f"{table['label']} — {table['count']} records")
    return merged


def _meta(built) -> str:
    detail = " · ".join(checks for checks in built.checks)
    business = _business()
    return f"{business} · {detail}" if business else detail


def _accent() -> str:
    """The brand accent, when the studio has written one for this business."""
    brand = _workspace() / "output" / "brand" / "brand.json"
    try:
        data = json.loads(brand.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "#3a5a40"
    palette = data.get("palette") if isinstance(data, dict) else None
    candidate = ""
    if isinstance(palette, dict):
        candidate = str(palette.get("primary") or palette.get("accent") or "")
    elif isinstance(palette, list) and palette:
        candidate = str(palette[0])
    return candidate if re.fullmatch(r"#[0-9a-fA-F]{6}", candidate or "") else "#3a5a40"


_TOOLS: tuple[tuple[str, dict, Callable[..., str]], ...] = (
    ("office_read", schemas._READ, office_read),
    ("xlsx_create", schemas._CREATE, xlsx_create),
    ("xlsx_edit", schemas._EDIT, xlsx_edit),
)
