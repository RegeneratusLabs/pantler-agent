"""Tool schemas — what the language model sees.

The important sentence is the one about prices. An assistant that helpfully adds "…at $12/kg" to an
availability list has turned it into a quotation, and the operator's list is a different document
with a different audience.
"""
from __future__ import annotations

AVAILABILITY_LIST = {
    "name": "availability_list",
    "description": (
        "Turn what the operator says they have into an unpriced, customer-facing availability "
        "list. Pass one line per item, as they said it ('twelve kilos of beans', 'four dozen "
        "eggs', 'a few punnets of rocket'). The tool reads the quantity and unit in code, "
        "resolves the item against the operator's own catalogue, and returns the list. "
        "THE LIST CARRIES NO PRICES and you must not add any: availability is what they have, "
        "not what it costs — a price beside a line makes it a quotation. Nothing is dropped: "
        "items that did not match are kept as spoken, and anything without a quantity comes "
        "back flagged so you can ask instead of guessing. Do not do the matching, the counting "
        "or the unit conversion yourself; narrate what is returned."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "lines": {
                "type": "array",
                "items": {"type": "string"},
                "description": "One entry per item, exactly as the operator said it.",
            },
            "title": {
                "type": "string",
                "description": "What to call the list — 'This week's boxes', 'Saturday market'.",
            },
            "include_unmatched": {
                "type": "boolean",
                "description": (
                    "Whether items that do not match the catalogue appear in the list. Default "
                    "true: dropping them is how a customer arrives for something that is not "
                    "there. Set false only when the operator asks for a catalogue-only list."
                ),
            },
        },
        "required": ["lines"],
    },
}
