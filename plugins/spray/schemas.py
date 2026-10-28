"""Tool schemas — what the language model sees.

The descriptions carry the same instruction the soil engine's do, for the same reason: the model
must understand that these tools RETURN COMPUTED NUMBERS and that it must not do this arithmetic
itself. A withholding period is the sharpest case — it comes off a label, and the tool says plainly
when it does not have one.
"""
from __future__ import annotations

SPRAY_RECORD = {
    "name": "spray_record",
    "description": (
        "Record one application: what was applied, to which block, at what rate, on what date. "
        "The tool resolves the block and the product against the operator's own spray book, "
        "multiplies the rate by the area to give the product used, and dates the earliest safe "
        "harvest from the withholding period on file. ALL ARITHMETIC IS DONE HERE — do not "
        "multiply, convert, count days or estimate a withholding period yourself; narrate what "
        "is returned. If the tool has no withholding period on file it leaves the field empty "
        "and says so: read it off the label with the operator rather than supplying one. If the "
        "result carries questions, ask them; if it carries warnings, say them in one line."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "applied": {
                "type": "string",
                "description": "The date it was applied, as YYYY-MM-DD.",
            },
            "block": {
                "type": "string",
                "description": "The block or paddock, as the operator named it.",
            },
            "product": {
                "type": "string",
                "description": "The product applied, as the operator named it.",
            },
            "rate": {
                "type": "number",
                "description": "The rate applied, as a number, with `rate_unit` beside it.",
            },
            "rate_unit": {
                "type": "string",
                "description": (
                    "One of: L/ha, mL/ha, kg/ha, g/ha (an area rate) or mL/100L, g/100L (a "
                    "concentration rate). Pass the unit the operator used; do not convert it."
                ),
            },
            "area_ha": {
                "type": "number",
                "description": (
                    "Hectares treated, when it differs from the block's area on file or the "
                    "operator said it. Omit to use the block's own area."
                ),
            },
            "operator": {"type": "string", "description": "Who did the spraying, if said."},
            "notes": {"type": "string", "description": "Anything else worth keeping on the record."},
            "dry_run": {
                "type": "boolean",
                "description": (
                    "Set true to work the application out WITHOUT writing it — the figures, the "
                    "questions and any label-maximum warning come back and nothing is recorded. "
                    "Use it when the rate is uncertain or above the maximum on file: ask the "
                    "operator first, then call again with dry_run false to write it once they "
                    "have confirmed. A spray record is a compliance record; it should not say "
                    "'recorded' while a question about it is still open."
                ),
            },
        },
        "required": ["applied", "block", "product", "rate", "rate_unit"],
    },
}

SPRAY_INPUTS = {
    "name": "spray_inputs",
    "description": (
        "List the products in the operator's spray book with the label facts on file for each: "
        "the unit it is sold in, the withholding period, the re-entry period, the label "
        "reference and the maximum rate. Use this to answer 'what do you have on file for X?' "
        "and to check which label facts are still missing — never to supply one from memory."
    ),
    "parameters": {"type": "object", "properties": {}},
}
