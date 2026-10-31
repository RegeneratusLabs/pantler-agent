"""The studio's five tools: thin adapters over `studio/`, with the workspace boundary enforced.

Nothing here computes a layout. Each handler validates what the model sent, resolves paths against
the active business's own workspace, calls the engine, and returns the result as JSON — including
the checks that failed, because a design the operator cannot read is not a design that succeeded.

The path rule is the product's: a business's designs, photos and brand live in its own workspace,
and a path that resolves outside it is refused, symlinks included.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Callable

from . import schemas
from .studio_engine import audit, brand as brand_kit, layout, pages, photos, raster, render, svg, templates
from .studio_engine.library import Library, LibraryError

TOOLSET = "studio"
CAPABILITY_KEY = "capability_enabled"

_CTX = None
_LIBRARY: Library | None = None

_HREF = re.compile(r"""<image[^>]+(?:href|xlink:href)\s*=\s*["'](?!data:)([^"']+)["']""", re.I)


# ------------------------------------------------------------------ configuration
def _setting(key: str, default: Any = None) -> Any:
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
        return _fail(
            "The design studio is switched off in Capabilities. Switch it back on there and ask "
            "me again."
        )
    return None


def _home() -> Path:
    home = os.environ.get("HERMES_HOME", "").strip()
    return Path(os.path.expanduser(home)) if home else Path.home() / ".hermes"


def _runtime_cwd() -> Path | None:
    """The workspace this request is actually for.

    A host gateway serves several businesses from one process, so `HERMES_HOME` is the *host* home
    and its `workspace/` belongs to nobody. The engine's per-request terminal cwd is the profile's
    own workspace, and it is the only value that is right for the business in front of the operator.
    """
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
    """The named profile's home: the host's active profile, or a single-profile install."""
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
    """`terminal.cwd` from the profile's own config — the stable anchor when no request is live."""
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
    runtime = _runtime_cwd()
    if runtime:
        return runtime
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
            f"{label} is outside this business's workspace. A design writes into output/ in the "
            "workspace; anything else is another business's file or yours, not this one's."
        )
    if must_exist and not resolved.exists():
        raise ValueError(f"{label} does not exist")
    return resolved


def _readable(raw: Any, label: str = "file") -> Path:
    """Photos and brand kits may also come from the operator's uploads."""
    text = str(raw or "").strip()
    candidate = Path(os.path.expanduser(text))
    if candidate.is_absolute() or text.startswith("."):
        roots = [root for root in (_workspace(), _attachments()) if root]
        for root in roots:
            resolved = candidate.resolve(strict=False)
            if resolved == root or root in resolved.parents:
                if resolved.is_file():
                    return resolved
        raise ValueError(
            f"{label} is outside this business's workspace and uploads, so I will not open it. "
            "Attach it and I will use it."
        )
    return _confine(text, label=label, must_exist=True)


def _library() -> Library:
    global _LIBRARY
    if _LIBRARY is None:
        root = Path(__file__).resolve().parent
        fonts = _setting("fonts_dir")
        _LIBRARY = Library(root / "studio_engine" / "library",
                           Path(os.path.expanduser(str(fonts))).resolve() if fonts else None)
    return _LIBRARY


def _fail(message: str, **extra: Any) -> str:
    payload = {"success": False, "error": message}
    payload.update(extra)
    return json.dumps(payload, default=str, ensure_ascii=False)


def _ok(payload: dict) -> str:
    payload = {"success": True, **payload}
    return json.dumps(payload, default=str, ensure_ascii=False)


# ------------------------------------------------------------------ tools
def design_templates(params: dict, **kwargs) -> str:
    if (refusal := _switched_off()) is not None:
        return refusal
    try:
        described = _library().describe()
    except (LibraryError, OSError, ValueError) as exc:
        return _fail(f"the design library could not be read: {exc}")
    section = str((params or {}).get("section") or "all")
    if section != "all":
        key = {"type_pairs": "type_pairs", "fonts": "fonts"}.get(section, section)
        if key not in described:
            return _fail(f"unknown section {section!r}")
        return _ok({key: described[key]})
    return _ok(described)


def design_render(params: dict, **kwargs) -> str:
    if (refusal := _switched_off()) is not None:
        return refusal
    spec = (params or {}).get("spec")
    if not isinstance(spec, dict):
        return _fail("pass the brief as `spec` — an object, not a string")
    library = _library()
    spec = dict(spec)
    brand_dict = None
    brand_ref = spec.get("brand")
    try:
        if isinstance(brand_ref, dict):
            brand_dict = brand_ref
        elif isinstance(brand_ref, str) and brand_ref.strip():
            brand_dict = brand_kit.load(_readable(brand_ref, "brand kit")).to_dict()
    except (ValueError, brand_kit.BrandError) as exc:
        return _fail(str(exc))
    try:
        # Validate the brief before touching the filesystem, so a typo comes back as a sentence
        # about the typo rather than about a directory that was never written.
        layout.resolve(spec, library, brand_dict)
        spec["out"] = str(_confine(spec.get("out"), "the output directory"))
    except ValueError as exc:
        return _fail(str(exc))
    try:
        report = render.job(spec, _workspace(), library, brand_dict)
    except (layout.LayoutError, LibraryError, ValueError, OSError) as exc:
        return _fail(str(exc))
    except Exception as exc:  # a renderer fault should still be a sentence, not a traceback
        return _fail(f"the card could not be rendered: {exc}")
    return _ok(report)


def design_audit(params: dict, **kwargs) -> str:
    if (refusal := _switched_off()) is not None:
        return refusal
    library = _library()
    brief = (params or {}).get("brief")
    if isinstance(brief, dict):
        brand_dict = None
        brand_ref = brief.get("brand")
        try:
            if isinstance(brand_ref, str) and brand_ref.strip():
                brand_dict = brand_kit.load(_readable(brand_ref, "brand kit")).to_dict()
            spec = layout.resolve(brief, library, brand_dict)
            composition = templates.compose(spec, library)
            checks = audit.check(composition, spec)
        except Exception as exc:
            return _fail(str(exc))
        return _ok({"ok": audit.passed(checks), "checks": checks,
                    "failures": [c for c in checks if not c["ok"]],
                    "could_not_check": ["the rendered pixels: read the PNG back with vision"]})

    raw = (params or {}).get("path")
    try:
        path = _confine(raw, "the file to audit", must_exist=True)
    except ValueError as exc:
        return _fail(str(exc))
    checks: list[dict] = []
    size = path.stat().st_size
    checks.append({"id": "file.size", "ok": 0 < size <= audit.INLINE_LIMIT, "hard": False,
                   "value": size, "detail": f"{path.name} is {size / 1024:.0f} KB"})
    could_not = ["type sizes, contrast and margins (they need the brief, not the pixels)"]
    if path.suffix.lower() == ".svg":
        text = path.read_text(encoding="utf-8", errors="replace")
        external = _HREF.findall(text)
        checks.append({"id": "file.self_contained", "ok": not external, "hard": True,
                       "value": len(external),
                       "detail": "the SVG has no external references" if not external
                       else f"external references: {external[:3]}"})
        placeholders = sorted(set(audit.PLACEHOLDER.findall(re.sub(r"<[^>]+>", " ", text))))
        checks.append({"id": "copy.placeholders", "ok": not placeholders, "hard": False,
                       "value": len(placeholders),
                       "detail": "no placeholders left" if not placeholders
                       else f"still to fill: {', '.join(placeholders)}"})
        could_not.append("text clipped by the renderer (the SVG's boxes are authoritative)")
    elif path.suffix.lower() == ".png":
        try:
            raw_bytes = path.read_bytes()[:24]
            width = int.from_bytes(raw_bytes[16:20], "big")
            height = int.from_bytes(raw_bytes[20:24], "big")
            checks.append({"id": "file.dimensions", "ok": width >= 320 and height >= 320,
                           "hard": False, "value": [width, height],
                           "detail": f"{width}×{height}"})
        except Exception:
            could_not.append("the PNG header")
    else:
        could_not.append(f"anything about a {path.suffix or 'bare'} file")
    return _ok({"ok": all(c["ok"] for c in checks if c.get("hard")), "checks": checks,
                "failures": [c for c in checks if not c["ok"]], "could_not_check": could_not})


def design_brand(params: dict, **kwargs) -> str:
    if (refusal := _switched_off()) is not None:
        return refusal
    library = _library()
    stage = str((params or {}).get("stage") or "").strip()
    if stage == "directions":
        answers = (params or {}).get("answers") or {}
        if not isinstance(answers, dict):
            return _fail("`answers` must be an object")
        name = str(answers.get("name") or "").strip()
        if not name:
            return _fail(
                "I need the business's name, spelled the way it should appear, before I can build "
                "a board. Ask for it — do not use the profile name."
            )
        try:
            candidates = brand_kit.derive(answers, library)
        except Exception as exc:
            return _fail(str(exc))
        try:
            out = _confine(params.get("out") or "output/brand/directions")
        except ValueError as exc:
            return _fail(str(exc))
        out.mkdir(parents=True, exist_ok=True)
        files = []
        for index, candidate in enumerate(candidates, start=1):
            composition = brand_kit.board(
                candidate, library, name, str(answers.get("tagline") or ""), index
            )
            faces = {face_id: library.fonts.face(face_id).path
                     for face_id in {op.face_id for op in composition.texts()}}
            stem = out / f"{index:02d}-{candidate.direction.id}"
            stem.with_suffix(".svg").write_text(
                svg.render(composition, faces, title=f"{name} — {candidate.direction.name}"),
                encoding="utf-8",
            )
            png = ""
            if raster.available():
                try:
                    raster.draw(composition, faces, stem.with_suffix(".png"))
                    png = str(stem.with_suffix(".png"))
                except Exception:
                    png = ""
            files.append({"direction": candidate.direction.id, "svg": str(stem.with_suffix(".svg")),
                          "png": png})
        return _ok({
            "stage": stage,
            "candidates": [candidate.as_dict() for candidate in candidates],
            "files": files,
            "next": "Show the operator the three boards and ask which one is theirs. Do not pick "
                    "for them, and do not blend two.",
        })
    if stage == "save":
        block = (params or {}).get("brand")
        if not isinstance(block, dict):
            return _fail("`brand` must be the full kit object")
        try:
            kit = brand_kit.Brand.from_dict(block)
        except brand_kit.BrandError as exc:
            return _fail(str(exc))
        problems = brand_kit.validate(kit, library)
        if problems:
            return _fail("this brand kit cannot be used yet: " + "; ".join(problems))
        try:
            out = _confine(params.get("out") or "output/brand")
        except ValueError as exc:
            return _fail(str(exc))
        out.mkdir(parents=True, exist_ok=True)
        brand_path = brand_kit.save(kit, out / "brand.json")
        sheet_comp = brand_kit.sheet(kit, library)
        lockups = {}
        for layout_name in ("horizontal", "stacked", "monogram"):
            composition = brand_kit.lockup(kit, library, layout_name)
            faces = {face_id: library.fonts.face(face_id).path
                     for face_id in {op.face_id for op in composition.texts()}}
            stem = out / f"wordmark-{layout_name}"
            stem.with_suffix(".svg").write_text(
                svg.render(composition, faces, title=f"{kit.name} — {layout_name}"),
                encoding="utf-8",
            )
            png = ""
            if raster.available():
                try:
                    raster.draw(composition, faces, stem.with_suffix(".png"))
                    png = str(stem.with_suffix(".png"))
                except Exception:
                    png = ""
            lockups[layout_name] = {"svg": str(stem.with_suffix(".svg")), "png": png}
        sheet_faces = {face_id: library.fonts.face(face_id).path
                       for face_id in {op.face_id for op in sheet_comp.texts()}}
        sheet_svg = out / "brand-sheet.svg"
        sheet_svg.write_text(svg.render(sheet_comp, sheet_faces, title=f"{kit.name} — brand sheet"),
                             encoding="utf-8")
        sheet_png = ""
        if raster.available():
            try:
                raster.draw(sheet_comp, sheet_faces, out / "brand-sheet.png")
                sheet_png = str(out / "brand-sheet.png")
            except Exception:
                sheet_png = ""
        icons = {}
        if raster.available():
            try:
                from PIL import Image

                monogram = out / "wordmark-monogram.png"
                if monogram.is_file():
                    with Image.open(monogram) as source:
                        for size in (1024, 180, 32, 16):
                            icon = out / f"icon-{size}.png"
                            source.resize((size, size), Image.LANCZOS).save(icon, "PNG",
                                                                           optimize=True)
                            icons[str(size)] = str(icon)
            except Exception:
                icons = {}
        return _ok({
            "stage": stage,
            "brand": kit.to_dict(),
            "files": {"brand": str(brand_path), "sheet_svg": str(sheet_svg),
                      "sheet_png": sheet_png, "lockups": lockups, "icons": icons},
            "caveats": [
                "This is a wordmark and a palette, not a full identity system. A designer should "
                "review it before it goes on packaging or a sign.",
                "Pantler has not run a trademark search.",
            ],
        })
    return _fail("`stage` must be `directions` or `save`")


def photo_prepare(params: dict, **kwargs) -> str:
    if (refusal := _switched_off()) is not None:
        return refusal
    raw = (params or {}).get("inputs")
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list) or not raw:
        return _fail("name the photographs as `inputs`: one path per photo")
    inputs = []
    for entry in raw:
        try:
            inputs.append(_readable(entry, "photograph"))
        except ValueError as exc:
            return _fail(str(exc))
    try:
        out = _confine(params.get("out") or "output/photos")
    except ValueError as exc:
        return _fail(str(exc))
    focus = params.get("focus") or (0.5, 0.5)
    try:
        result = photos.prepare(inputs, out, str(params.get("mode") or "clean"),
                                tuple(float(value) for value in focus))
    except (photos.PhotoError, ValueError, OSError) as exc:
        return _fail(str(exc))
    return _ok(result)


def design_page(params: dict, **kwargs) -> str:
    if (refusal := _switched_off()) is not None:
        return refusal
    spec = (params or {}).get("spec")
    if not isinstance(spec, dict):
        return _fail("pass the page brief as `spec` — an object, not a string")
    library = _library()
    spec = dict(spec)
    brand_dict = None
    brand_ref = spec.get("brand")
    try:
        if isinstance(brand_ref, dict):
            brand_dict = brand_ref
        elif isinstance(brand_ref, str) and brand_ref.strip():
            brand_dict = brand_kit.load(_readable(brand_ref, "brand kit")).to_dict()
    except (ValueError, brand_kit.BrandError) as exc:
        return _fail(str(exc))
    try:
        spec["out"] = str(_confine(spec.get("out"), "the page directory"))
    except ValueError as exc:
        return _fail(str(exc))
    try:
        report = render.page_job(spec, _workspace(), library, brand_dict,
                                 previews=bool((params or {}).get("previews", True)))
    except (pages.PageError, ValueError, OSError) as exc:
        return _fail(str(exc))
    except Exception as exc:
        return _fail(f"the page could not be built: {exc}")
    return _ok(report)


_TOOLS: tuple[tuple[str, dict, Callable[..., str]], ...] = (
    ("design_templates", schemas._TEMPLATES, design_templates),
    ("design_render", schemas._RENDER, design_render),
    ("design_audit", schemas._AUDIT, design_audit),
    ("design_brand", schemas._BRAND, design_brand),
    ("photo_prepare", schemas._PHOTOS, photo_prepare),
    ("design_page", schemas._PAGE, design_page),
)
