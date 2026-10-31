"""One job, end to end: validate the brief, compose, write the artefacts, audit, report.

The order matters. The audit reads the composition, not the PNG, so a hard failure is known before
anything is handed over. The PNG is written even when a soft check fails — the operator can see what
is wrong — but the report says `ok: false` and the skill's rule is that it is not done.

Every path is resolved by the caller against the active workspace; this module trusts the paths it
is given and never reaches outside them.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import audit, layout, pages, raster, svg, templates
from .library import Library


def _html(composition, svg_text: str) -> str:
    return (
        "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<title>Design preview</title>"
        "<style>html,body{margin:0;background:#111;display:grid;place-items:center;"
        "min-height:100vh}svg{max-width:96vw;height:auto;box-shadow:0 20px 60px rgba(0,0,0,.5)}"
        "</style></head><body>\n" + svg_text + "\n</body></html>\n"
    )


def _faces_for(composition, library: Library) -> dict[str, Path]:
    return {face_id: library.fonts.face(face_id).path for face_id in
            {op.face_id for op in composition.texts()}}


def job(spec_dict: dict, workspace: Path, library: Library, brand: dict | None = None) -> dict:
    spec = layout.resolve(spec_dict, library, brand)
    # A card for a business with a kit signs itself. The name comes from the brand file, never from
    # the model's idea of who the operator is; a card with no brand still gets no footer.
    if not spec.content.get("footer") and (brand or {}).get("name"):
        spec.content["footer"] = str(brand["name"])
    out = Path(spec.out)
    if not out.is_absolute():
        out = Path(workspace) / out
    out.mkdir(parents=True, exist_ok=True)

    composition = templates.compose(spec, library)
    faces = _faces_for(composition, library)

    svg_path = out / "card.svg"
    svg_text = svg.render(composition, faces, title=spec.title or spec.content.get("headline", ""),
                          physical=spec.physical)
    svg_path.write_text(svg_text, encoding="utf-8")

    png_path = out / "card.png"
    rendered_with = "svg"
    if raster.available():
        try:
            raster.draw(composition, faces, png_path)
            rendered_with = "pillow"
        except Exception as exc:  # a broken font or image should not lose the SVG
            composition.notes.append(f"the PNG could not be drawn: {exc}")
    else:
        composition.notes.append(
            "this machine has no image library, so the PNG was not drawn; the SVG is the "
            "deliverable and the operator should be told"
        )

    html_path = out / "card.html"
    html_path.write_text(_html(composition, svg_text), encoding="utf-8")

    checks = audit.check(composition, spec)
    checks += audit.check_files(png_path if rendered_with == "pillow" else None, svg_path)
    ok = audit.passed(checks)

    report = {
        "ok": ok,
        "template": spec.template,
        "direction": spec.direction.id,
        "palette": spec.palette.id,
        "type": spec.pairing.id,
        "size": [composition.width, composition.height],
        "physical_mm": list(spec.physical) if spec.physical else None,
        "rendered_with": rendered_with,
        "files": {
            "svg": str(svg_path),
            "png": str(png_path) if rendered_with == "pillow" else "",
            "html": str(html_path),
            "brief": str(out / "brief.json"),
            "report": str(out / "report.json"),
        },
        "checks": checks,
        "failures": [item for item in checks if not item["ok"]],
        "content": dict(spec.content),
        "notes": composition.notes,
        "placeholders": sorted({match for op in composition.texts()
                                for match in audit.PLACEHOLDER.findall(op.text)}),
    }
    (out / "brief.json").write_text(
        json.dumps(spec_dict, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (out / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return report


def page_job(spec_dict: dict, workspace: Path, library: Library, brand: dict | None = None,
             previews: bool = True) -> dict:
    """Build a one-page site into the workspace and report what it checked and photographed."""
    out = Path(str(spec_dict.get("out") or "")).expanduser()
    if not str(out):
        raise pages.PageError("the brief needs an `out` directory")
    if not out.is_absolute():
        out = Path(workspace) / out
    out.mkdir(parents=True, exist_ok=True)

    page = pages.build(spec_dict, library, brand, out)
    html_path = out / "index.html"
    html_path.write_text(page.html, encoding="utf-8")

    previews_made: list[dict] = []
    preview_note = ""
    if previews:
        try:
            from .screenshot import capture

            for name, width, height in (("desktop", 1280, 900), ("phone", 390, 844)):
                previews_made.append(
                    capture(html_path, out / f"preview-{name}.png", width, height)
                )
        except Exception as exc:  # no browser is a sentence in the report, not a failed page
            preview_note = str(exc)

    report = {
        "ok": page.ok,
        "blueprint": page.blueprint,
        "size": [len(page.html.encode()), 0],
        "files": {
            "html": str(html_path),
            "brief": str(out / "brief.json"),
            "report": str(out / "report.json"),
            "previews": [entry["path"] for entry in previews_made],
        },
        "checks": page.checks,
        "failures": [item for item in page.checks if not item["ok"]],
        "placeholders": page.placeholders,
        "preview_note": preview_note,
        "assets": [str(path) for path in page.assets],
    }
    (out / "brief.json").write_text(json.dumps(spec_dict, indent=2, ensure_ascii=False) + "\n",
                                    encoding="utf-8")
    (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                                     encoding="utf-8")
    return report
