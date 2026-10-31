"""Build a one-page site from a blueprint and a brand.

A page is not a card at a larger size. It is an argument: what this is, proof, and the one way to
buy. So the blueprint fixes the order and the required parts, the generator refuses a page with no
way to contact the business, and the CSS is written once here rather than by a model that has just
invented a hero carousel.

Everything is local: the fonts are copied beside the page and declared with `@font-face`, there is no
script, and no request leaves the machine. The checks read the generated HTML, so what is reported is
what shipped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html import escape
from pathlib import Path

from . import palette as colour
from .library import Library

PLACEHOLDER = re.compile(r"\[[A-Z0-9$][^\]\n]{1,60}\]")
EXTERNAL = re.compile(r"""(?:href|src)\s*=\s*["'](?:https?:)?//""", re.I)
IMG = re.compile(r"<img\b[^>]*>", re.I)
ALT = re.compile(r"""\balt\s*=\s*["']([^"']*)["']""", re.I)
H1 = re.compile(r"<h1\b", re.I)
H2 = re.compile(r"<h2\b", re.I)
SCRIPT = re.compile(r"<script\b", re.I)
SAFE_HREF = re.compile(r"^(mailto:|tel:|#|/|\./|[\w./-]+$)", re.I)

CONTENT_KEYS = {"name", "tagline", "eyebrow", "opening", "sections", "action", "footer",
                "description", "image"}
SECTION_KEYS = {"kind", "title", "body", "items", "lines"}
SPEC_KEYS = {"blueprint", "brand", "palette", "type", "content", "out", "title"}


class PageError(ValueError):
    """A page the generator will not build: missing content, an unknown section, no way to buy."""


@dataclass
class Page:
    blueprint: str
    html: str
    checks: list[dict] = field(default_factory=list)
    placeholders: list[str] = field(default_factory=list)
    assets: list[Path] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(item["ok"] for item in self.checks if item.get("hard"))


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PageError(message)


def _muted(rgb, ground, amount: float = 0.28) -> str:
    return colour.to_hex(colour.mix(rgb, ground, amount))


def _stylesheet(ground: str, ink: str, accent: str, accent_text: str, muted: str, hair: str,
                faces: dict[str, str], h1_px: float) -> str:
    display, text, label = faces["display"], faces["text"], faces["label"]
    return f"""
:root {{
  --ground: {ground};
  --ink: {ink};
  --accent: {accent};
  --accent-text: {accent_text};
  --muted: {muted};
  --hair: {hair};
  --measure: 64ch;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0; background: var(--ground); color: var(--ink);
  font-family: '{text}', Georgia, serif; font-size: 18px; line-height: 1.6;
}}
.shell {{ max-width: 72rem; margin: 0 auto; padding: 0 clamp(1.2rem, 4vw, 3rem); }}
.skip {{ position: absolute; left: -999px; top: 0; background: var(--ink); color: var(--ground);
  padding: .6rem 1rem; z-index: 10; }}
.skip:focus {{ left: 1rem; top: 1rem; }}
header.site {{ border-bottom: 1px solid var(--hair); padding: clamp(1.3rem, 4vw, 2.4rem) 0 1rem; }}
header.site .shell {{ display: flex; flex-wrap: wrap; gap: .4rem 1.5rem;
  align-items: baseline; justify-content: space-between; }}
.brand {{ font-family: '{label}', system-ui, sans-serif; letter-spacing: .16em;
  text-transform: uppercase; font-size: .78rem; }}
.tag {{ font-family: '{label}', system-ui, sans-serif; font-size: .78rem; color: var(--muted); }}
main {{ padding-bottom: 3rem; }}
section {{ padding: clamp(2.2rem, 6vw, 4.5rem) 0 0; }}
.eyebrow {{ font-family: '{label}', system-ui, sans-serif; font-size: .74rem;
  letter-spacing: .22em; text-transform: uppercase; color: var(--accent-text); margin: 0 0 1rem; }}
h1 {{ font-family: '{display}', Georgia, serif; font-weight: 500;
  font-size: clamp(2.1rem, 5.4vw, {h1_px}px); line-height: 1.04; letter-spacing: -0.015em;
  margin: 0 0 1.6rem; max-width: 18ch; text-wrap: balance; }}
h2 {{ font-family: '{display}', Georgia, serif; font-weight: 500;
  font-size: clamp(1.4rem, 2.6vw, 2rem); line-height: 1.12; letter-spacing: -0.01em;
  margin: 0 0 1.1rem; max-width: 24ch; }}
p {{ margin: 0 0 1rem; max-width: var(--measure); }}
.action {{ display: inline-block; margin-top: .6rem; padding: .85rem 1.4rem;
  background: var(--ink); color: var(--ground); text-decoration: none;
  font-family: '{label}', system-ui, sans-serif; font-size: .82rem; letter-spacing: .12em;
  text-transform: uppercase; border: 1px solid var(--ink); }}
.action:hover, .action:focus {{ background: var(--accent); border-color: var(--accent);
  color: var(--ground); }}
:focus-visible {{ outline: 2px solid var(--accent-text); outline-offset: 3px; }}
ul.list {{ list-style: none; margin: 0; padding: 0; max-width: var(--measure); }}
ul.list li {{ display: flex; justify-content: space-between; gap: 2rem; padding: .9rem 0;
  border-top: 1px solid var(--hair); font-size: 1.02rem; }}
ul.list li:last-child {{ border-bottom: 1px solid var(--hair); }}
ul.list .detail {{ font-family: '{label}', system-ui, sans-serif; font-size: .8rem;
  letter-spacing: .04em; color: var(--accent-text); white-space: nowrap; }}
ol.proof {{ list-style: none; margin: 0; padding: 0; max-width: var(--measure); }}
ol.proof li {{ padding: .8rem 0; border-top: 1px solid var(--hair); font-size: 1rem; }}
.contact p {{ font-size: 1.05rem; margin: 0 0 .4rem; }}
figure {{ margin: 2.4rem 0 0; }}
figure img {{ width: 100%; height: auto; display: block; }}
figcaption {{ font-family: '{label}', system-ui, sans-serif; font-size: .78rem;
  color: var(--muted); padding-top: .6rem; }}
footer.site {{ border-top: 1px solid var(--hair); padding: 1.6rem 0 2.6rem;
  font-family: '{label}', system-ui, sans-serif; font-size: .78rem; color: var(--muted); }}
@media (max-width: 34rem) {{ ul.list li {{ flex-direction: column; gap: .2rem; }} }}
@media (prefers-reduced-motion: reduce) {{ * {{ transition: none !important;
  animation: none !important; }} }}
"""


def _copy_faces(library: Library, pairing, out_dir: Path) -> tuple[dict[str, str], list[Path], str]:
    """Copy the pairing's faces beside the page and build the `@font-face` rules."""
    names = {"display": "Brand Display", "text": "Brand Text", "label": "Brand Label"}
    targets = {"display": pairing.display, "text": pairing.text, "label": pairing.label}
    faces_dir = out_dir / "assets" / "fonts"
    faces_dir.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    rules: list[str] = []
    families: dict[str, str] = {}
    for role, spec in targets.items():
        face = library.fonts.face_for(spec.family, spec.weight)
        families[role] = names[role]
        if face.path not in copied:
            target = faces_dir / face.path.name
            if not target.is_file():
                target.write_bytes(face.path.read_bytes())
            copied.append(face.path)
        rules.append(
            f"@font-face{{font-family:'{names[role]}';"
            f"src:url('assets/fonts/{face.path.name}') format('truetype');"
            "font-weight:normal;font-style:normal;font-display:swap;}"
        )
    return families, copied, "\n".join(rules)


def _section(kind: str, section: dict, action: dict) -> str:
    title = section.get("title") or ""
    heading = f"<h2>{escape(str(title))}</h2>" if title else ""
    if kind == "list":
        rows = []
        for item in section.get("items") or []:
            left, _, detail = str(item).partition("|")
            left, detail = left.strip(), detail.strip()
            extra = f'<span class="detail">{escape(detail)}</span>' if detail else ""
            rows.append(f"<li><span>{escape(left)}</span>{extra}</li>")
        return (f'<section class="list"><div class="shell">{heading}'
                f'<ul class="list">{"".join(rows)}</ul></div></section>')
    if kind == "text":
        paragraphs = "".join(
            f"<p>{escape(part.strip())}</p>"
            for part in str(section.get("body") or "").split("\n\n") if part.strip()
        )
        return f'<section class="text"><div class="shell">{heading}{paragraphs}</div></section>'
    if kind == "proof":
        rows = "".join(f"<li>{escape(str(item))}</li>" for item in section.get("items") or [])
        return (f'<section class="proof"><div class="shell">{heading}'
                f'<ol class="proof">{rows}</ol></div></section>')
    if kind == "contact":
        lines = "".join(f"<p>{escape(str(line))}</p>" for line in section.get("lines") or [])
        return f'<section class="contact"><div class="shell">{heading}{lines}</div></section>'
    if kind == "action":
        label = escape(str(action.get("label") or "Get in touch"))
        href = escape(str(action.get("href") or "#contact"), quote=True)
        return (f'<section class="closing"><div class="shell">{heading}'
                f'<a class="action" href="{href}">{label}</a></div></section>')
    raise PageError(f"unknown section kind {kind!r}")


def build(spec: dict, library: Library, brand: dict | None, out_dir: Path) -> Page:
    """Validate a brief, copy its assets, and return the HTML plus the checks."""
    _require(isinstance(spec, dict), "the page brief must be an object")
    unknown = sorted(set(spec) - SPEC_KEYS)
    _require(not unknown, f"unknown page key(s): {', '.join(unknown)}")

    blueprint_id = str(spec.get("blueprint") or "").strip()
    _require(bool(blueprint_id), "the brief needs a `blueprint`; ask design_templates for the list")
    blueprint = library.page(blueprint_id)

    content = spec.get("content") or {}
    _require(isinstance(content, dict), "`content` must be an object")
    unknown_content = sorted(set(content) - CONTENT_KEYS)
    _require(not unknown_content, f"unknown content key(s): {', '.join(unknown_content)}")
    for key in ("name", "opening"):
        _require(bool(str(content.get(key) or "").strip()), f"a page needs `{key}` — ask for it")

    by_kind: dict[str, dict] = {}
    for section in content.get("sections") or []:
        _require(isinstance(section, dict), "every section is an object")
        unknown_section = sorted(set(section) - SECTION_KEYS)
        _require(not unknown_section, f"unknown section key(s): {', '.join(unknown_section)}")
        kind = str(section.get("kind") or "")
        _require(kind in library.page_kinds, f"unknown section kind {kind!r}")
        _require(kind != "opening", "the opening is `content.opening`, not a section")
        _require(kind not in by_kind, f"two {kind!r} sections on one page")
        by_kind[kind] = section

    action = content.get("action") if isinstance(content.get("action"), dict) else {}
    for required in blueprint["requires"]:
        if required == "opening":
            continue
        if required == "action":
            _require(bool(action), f"blueprint {blueprint_id!r} needs an `action`")
        else:
            _require(required in by_kind, f"blueprint {blueprint_id!r} needs a `{required}` section")
    if action:
        _require(bool(str(action.get("label") or "").strip()), "the action needs a label")
        href = str(action.get("href") or "")
        _require(bool(href), "the action needs a href — a mailto:, a phone number or a page")
        _require(bool(SAFE_HREF.match(href)), f"{href!r} is not a local or mailto/tel link")

    brand = dict(brand or {})
    palette = _palette(spec, brand, library)
    pairing = library.pairing(str(spec.get("type") or brand.get("type") or "young-serif-barlow"))

    ground, ink, accent = palette.ground, palette.ink, palette.accent
    accent_text = (accent if colour.contrast(colour.parse(accent), colour.parse(ground)) >= 4.5
                   else ink)
    muted = _muted(colour.parse(ink), colour.parse(ground))
    hair = colour.to_hex(colour.mix(colour.parse(ink), colour.parse(ground), 0.72))

    families, copied, face_rules = _copy_faces(library, pairing, out_dir)
    styles = face_rules + "\n" + _stylesheet(ground, ink, accent, accent_text, muted, hair,
                                             families, 72)

    blocks = [
        '<section class="opening"><div class="shell">'
        + (f'<p class="eyebrow">{escape(str(content.get("eyebrow")))}</p>'
           if content.get("eyebrow") else "")
        + f'<h1>{escape(str(content["opening"]))}</h1>'
        + (f'<a class="action" href="{escape(str(action.get("href")), quote=True)}">'
           f'{escape(str(action.get("label")))}</a>' if action else "")
        + "</div></section>"
    ]
    image = content.get("image")
    if image:
        _require(isinstance(image, dict), "`image` is an object with path and alt")
        alt = str(image.get("alt") or "").strip()
        _require(bool(alt), "an image needs alt text — describe what is in it")
        source = Path(str(image.get("path")))
        _require(source.is_file(), f"image not found: {source}")
        assets_dir = out_dir / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        target = assets_dir / source.name
        if not target.is_file():
            target.write_bytes(source.read_bytes())
        copied.append(source)
        caption = (f"<figcaption>{escape(str(image.get('caption')))}</figcaption>"
                   if image.get("caption") else "")
        blocks.append(
            f'<div class="shell"><figure><img src="assets/{escape(target.name)}" '
            f'alt="{escape(alt, quote=True)}">{caption}</figure></div>'
        )
    for kind in blueprint["sections"]:
        if kind != "opening" and kind in by_kind:
            blocks.append(_section(kind, by_kind[kind], action))

    name = escape(str(content["name"]))
    title = escape(str(spec.get("title") or f"{content['name']} — food, grown and sold by us"))
    description = escape(str(content.get("description") or content.get("opening") or ""))
    footer = escape(str(content.get("footer") or content["name"]))

    html = (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"<title>{title}</title>\n<meta name=\"description\" content=\"{description}\">\n"
        f"<style>\n{styles}\n</style>\n</head>\n<body>\n"
        '<a class="skip" href="#main">Skip to content</a>\n'
        f'<header class="site"><div class="shell"><span class="brand">{name}</span>'
        + (f'<span class="tag">{escape(str(content.get("tagline")))}</span>'
           if content.get("tagline") else "")
        + "</div></header>\n<main id=\"main\">\n"
        + "\n".join(blocks)
        + f"\n</main>\n<footer class=\"site\"><div class=\"shell\">{footer}</div></footer>\n"
        "</body>\n</html>\n"
    )

    page = Page(blueprint=blueprint_id, html=html, assets=copied)
    page.placeholders = sorted(set(PLACEHOLDER.findall(html)))
    page.checks = check(page, palette, blueprint, bool(action))
    return page


def _palette(spec: dict, brand: dict, library: Library):
    block = spec.get("palette")
    colours = brand.get("colours") if isinstance(brand.get("colours"), dict) else {}
    if isinstance(block, dict) or colours:
        source = block if isinstance(block, dict) else colours
        base = library.palette(str(brand.get("palette") or "neutral-stone"))
        palette = type(base)(
            id=base.id, name=base.name, group=base.group,
            ground=str(source.get("ground") or base.ground),
            ink=str(source.get("ink") or base.ink),
            accent=str(source.get("accent") or base.accent),
            accent2=str(source.get("accent2") or base.accent2),
            note=base.note,
        )
        for role in ("ground", "ink", "accent", "accent2"):
            colour.parse(getattr(palette, role))
        if colour.contrast(colour.parse(palette.ink), colour.parse(palette.ground)) < 4.5:
            raise PageError("ink on ground is below 4.5:1; the page would be unreadable")
        return palette
    return library.palette(str(brand.get("palette") or "neutral-stone"))


def check(page: Page, palette, blueprint: dict, has_action: bool) -> list[dict]:
    html = page.html

    def item(check_id: str, ok: bool, detail: str, hard: bool = True, value=None) -> dict:
        return {"id": check_id, "ok": bool(ok), "hard": hard, "detail": detail,
                "value": value if value is not None else ""}

    checks = [
        item("page.lang", 'lang="en"' in html, "the page declares its language"),
        item("page.viewport", 'name="viewport"' in html, "the page sets a viewport"),
        item("page.title", "<title>" in html and "</title>" in html, "the page has a title"),
        item("page.description", 'name="description"' in html, "the page has a description"),
        item("page.h1", len(H1.findall(html)) == 1, f"{len(H1.findall(html))} h1 element(s)"),
        item("page.static", not SCRIPT.search(html),
             "the page carries no script" if not SCRIPT.search(html)
             else "the page carries a script"),
        item("page.external", not EXTERNAL.search(html),
             "no external request" if not EXTERNAL.search(html)
             else "the page loads something from the network"),
        item("page.placeholders", not page.placeholders,
             "no placeholders left" if not page.placeholders
             else f"still to fill: {', '.join(page.placeholders)}",
             hard=False, value=len(page.placeholders)),
    ]
    images = IMG.findall(html)
    missing_alt = [tag for tag in images if not ALT.search(tag) or not ALT.search(tag).group(1).strip()]
    checks.append(item("page.alt", not missing_alt,
                       "every image has alt text" if not missing_alt
                       else f"{len(missing_alt)} image(s) without alt"))

    for required in blueprint["requires"]:
        if required == "action":
            checks.append(item("page.required.action", has_action, "the page has a way to act"))
        elif required != "opening":
            present = f'class="{required}"' in html
            checks.append(item(f"page.required.{required}", present,
                               f"the page has its {required} section" if present
                               else f"the page is missing its {required} section"))

    ratio = colour.contrast(colour.parse(palette.ink), colour.parse(palette.ground))
    checks.append(item("page.contrast", ratio >= 4.5, f"ink on ground is {ratio:.2f}:1",
                       value=round(ratio, 2)))
    checks.append(item("page.size", len(html.encode()) < 400_000,
                       f"the page is {len(html.encode()) / 1024:.0f} KB",
                       hard=False, value=len(html.encode())))
    return checks
