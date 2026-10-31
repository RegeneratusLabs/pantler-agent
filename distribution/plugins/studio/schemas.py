"""Tool schemas — what the model sees, and the sentences that stop it drawing by hand.

Every description here does three jobs: it says what the tool computes, it forbids the model from
supplying geometry or inventing a fact, and it names the honest limit. The model writes the words
and makes the choices; the tool writes the coordinates.
"""
from __future__ import annotations

_TEMPLATES = {
    "name": "design_templates",
    "description": (
        "List the studio's design library: 16 directions, 12 artboard templates, 3 page "
        "blueprints, 24 palettes and the type pairings, each in one line. Call this before designing so you choose a direction "
        "instead of inventing one, and so you use a template id that exists. Pass `section` to "
        "narrow it (directions, templates, palettes, type_pairs, fonts). This returns names and "
        "one-line descriptions only — it is cheap, and it is the difference between a card that "
        "looks decided and one that looks averaged."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "section": {
                "type": "string",
                "enum": ["all", "directions", "templates", "palettes", "type_pairs", "pages", "page_sections", "fonts"],
                "description": "Which part of the library to return. Default `all`.",
            }
        },
        "required": [],
    },
}

_RENDER = {
    "name": "design_render",
    "description": (
        "Compose and render a card from a written brief. You supply the words, the template id, "
        "the direction and the palette; the tool computes every margin, type size, line break, "
        "safe zone and contrast ratio, writes card.svg, card.png and a preview page, and returns "
        "the checks it ran. NEVER supply coordinates, and never write a price, date, name, "
        "certification, quantity or photo the operator did not give you — leave a `[PLACEHOLDER]` "
        "and it will be reported back. If a hard check fails, the card is not finished: fix the "
        "brief and render again, or tell the operator what is missing. Pass `brand` as a path to "
        "the business's brand.json so every later design uses the same colours and type."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "spec": {
                "type": "object",
                "description": (
                    "The brief. Keys: template, direction, palette (an id, or an object with "
                    "ground/ink/accent), type (a pairing id), brand (path to brand.json), "
                    "content (eyebrow, headline, items[], day, footer, quote, attribution, "
                    "venue, time, number, price_note, note), image ({path, fit, focus, "
                    "treatment}), size ([w,h] to override the template), out (a directory in "
                    "this workspace, e.g. output/design/2026-10-31-veg-boxes)."
                ),
                "additionalProperties": False,
                "properties": {
                    "template": {"type": "string"},
                    "direction": {"type": "string"},
                    "palette": {"type": ["string", "object"]},
                    "type": {"type": "string"},
                    "brand": {"type": ["string", "object"]},
                    "content": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "eyebrow": {"type": "string"},
                            "headline": {"type": "string"},
                            "items": {"type": "array", "items": {"type": "string"}},
                            "day": {"type": "string"},
                            "footer": {"type": "string"},
                            "quote": {"type": "string"},
                            "attribution": {"type": "string"},
                            "venue": {"type": "string"},
                            "time": {"type": "string"},
                            "price": {"type": "string"},
                            "price_note": {"type": "string"},
                            "note": {"type": "string"},
                            "kicker": {"type": "string"},
                            "number": {"type": "string"},
                        },
                    },
                    "image": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "path": {"type": "string"},
                            "fit": {"type": "string"},
                            "focus": {"type": "array", "items": {"type": "number"}},
                            "treatment": {"type": "string"},
                        },
                    },
                    "size": {"type": "array", "items": {"type": "number"}},
                    "out": {"type": "string"},
                    "title": {"type": "string"},
                },
                "required": ["template", "direction", "content", "out"],
            }
        },
        "required": ["spec"],
    },
}

_AUDIT = {
    "name": "design_audit",
    "description": (
        "Re-run the checks on a design: pass the brief and it audits the composition without "
        "writing anything, or pass a file and it reports what can honestly be measured about "
        "that file (dimensions, size, placeholders in an SVG). Use it before you hand a design "
        "over, and when the operator asks whether something is ready. It reports numbers; it "
        "does not taste, so read the PNG back with the vision tool as well. Say plainly which "
        "checks could not be made."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "A file in this workspace to audit."},
            "brief": {
                "type": "object",
                "description": "The same spec you would pass to design_render; audits the layout.",
            },
        },
        "required": ["path"],
    },
}

_BRAND = {
    "name": "design_brand",
    "description": (
        "Derive, board and save a business's brand kit. Stage `directions` takes the operator's "
        "answers and renders three genuinely different boards (palette, type, wordmark) so they "
        "can choose; stage `save` writes output/brand/brand.json plus a usage sheet, six lockups "
        "and four icon tiles. NEVER invent a name, a tagline or a colour — take them from the "
        "operator, and if something is missing ask. A kit is saved as `starter` unless the "
        "operator has confirmed it; say so, and say that Pantler has not run a trademark search."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "stage": {
                "type": "string",
                "enum": ["directions", "save"],
                "description": "`directions` to explore, `save` to write the kit.",
            },
            "answers": {
                "type": "object",
                "description": (
                    "For stage=directions: name, tagline, posture (warm|clean|bold|quiet|"
                    "playful), kind (what the business does), avoid_directions (ids to skip)."
                ),
            },
            "brand": {
                "type": "object",
                "description": (
                    "For stage=save: the full kit — name, tagline, posture, direction, palette, "
                    "type, colours{ground,ink,accent,accent2}, logo{case,monogram,path}, never[], "
                    "notes, sources, status (starter|confirmed)."
                ),
            },
            "out": {
                "type": "string",
                "description": "Directory for the kit. Default output/brand.",
            },
        },
        "required": ["stage"],
    },
}

_PHOTOS = {
    "name": "photo_prepare",
    "description": (
        "Prepare the operator's own photographs: `clean` fixes orientation, size and metadata; "
        "`social-crops` makes a 1080 square and a 1080x1350 portrait from each; `contact-sheet` "
        "lays them out with their file names so the operator can choose. It never generates an "
        "image, never invents a product shot and never removes a person's face: a photo of a "
        "person still needs a consent record before it goes on a public card."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "inputs": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Paths to the operator's photos, inside this workspace.",
            },
            "mode": {
                "type": "string",
                "enum": ["clean", "social-crops", "contact-sheet"],
                "description": "What to do. Default `clean`.",
            },
            "out": {
                "type": "string",
                "description": "Directory for the results. Default output/photos.",
            },
            "focus": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Where the crop should centre, 0..1 in x and y. Default [0.5,0.5].",
            },
        },
        "required": ["inputs"],
    },
}


_PAGE = {
    "name": "design_page",
    "description": (
        "Build a one-page website from a blueprint, a brand and the operator's own words. The "
        "blueprint fixes the section order and the parts a page cannot ship without (an opening, "
        "and a way to contact or buy); the tool writes index.html, copies the licensed fonts "
        "beside it, checks the headings, alt text, contrast, placeholders and external requests, "
        "and photographs the first screen at desktop and phone width when a browser is present. "
        "NEVER invent a price, a phone number, an address, a review or a certification: a blank is "
        "a [PLACEHOLDER] and the report names it. Use `content.sections` with kinds list, text, "
        "proof, contact and action; the opening is `content.opening`."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "spec": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "blueprint": {"type": "string", "enum": ["producer", "order", "stall"]},
                    "brand": {"type": ["string", "object"]},
                    "palette": {"type": "object"},
                    "type": {"type": "string"},
                    "title": {"type": "string"},
                    "out": {"type": "string"},
                    "content": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "name": {"type": "string"},
                            "tagline": {"type": "string"},
                            "opening": {"type": "string"},
                            "description": {"type": "string"},
                            "footer": {"type": "string"},
                            "action": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "label": {"type": "string"},
                                    "href": {"type": "string"},
                                },
                            },
                            "image": {"type": "object"},
                            "sections": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "properties": {
                                        "kind": {
                                            "type": "string",
                                            "enum": ["list", "text", "proof", "contact", "action"],
                                        },
                                        "title": {"type": "string"},
                                        "body": {"type": "string"},
                                        "items": {"type": "array", "items": {"type": "string"}},
                                        "lines": {"type": "array", "items": {"type": "string"}},
                                    },
                                    "required": ["kind"],
                                },
                            },
                        },
                        "required": ["name", "opening"],
                    },
                },
                "required": ["blueprint", "content", "out"],
            },
            "previews": {
                "type": "boolean",
                "description": "Draw desktop and phone previews when a browser is available.",
            },
        },
        "required": ["spec"],
    },
}
