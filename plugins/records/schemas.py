"""Tool schemas — what the language model sees.

The descriptions have one job beyond describing the arguments: the model must understand that a
record is *validated against the pack that declares it*, so a missing field comes back as a refusal
with the field named, and that it must pass what the operator said rather than a tidied version of
it.
"""
from __future__ import annotations

RECORD_SAVE = {
    "name": "record_save",
    "description": (
        "Save one record of a type this tool writes — a certificate, a block, a harvest, an "
        "input. Pass the record type and the fields exactly as the operator said them; the "
        "store validates them against the pack that declares the type and returns the saved "
        "record with its id, the list of fields it still needs, and `empty_fields` — the declared "
        "fields left blank. Never invent a value to satisfy a required field, and when a "
        "document-backed record is saved (a certificate, a docket), ask where the document itself "
        "lives and put that in the field that says so: a record with no evidence line sends "
        "people looking for the paper, and the answer to that is a question, not a search. Never "
        "state that something is certified, compliant or covered — write the record and let it "
        "say what it says. A consent, a campaign and an invoice are recorded in the app, and a "
        "spray application is computed by the spray tool: this tool refuses them, because a "
        "record the model can author is a record the checks behind it cannot trust. A type the "
        "operator has defined in their own custom pack is writable here."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "type": {
                "type": "string",
                "description": (
                    "The record type: certificate, block, harvest, input, or a custom type the "
                    "operator has approved (check `record_types`)."
                ),
            },
            "fields": {
                "type": "object",
                "description": "The record's fields, as an object. Field names are the pack's, not yours.",
            },
        },
        "required": ["type", "fields"],
    },
}

RECORD_FIND = {
    "name": "record_find",
    "description": (
        "Read back records of one type: the most recent first, optionally filtered by exact field "
        "values or a word they contain. Use this to answer questions about what the operator "
        "holds — 'are we certified?', 'when does it expire?', 'what did I spray on the north "
        "block?' — instead of searching files. If nothing matches, say so; an empty answer is "
        "not permission to answer from memory."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "type": {"type": "string", "description": "The record type to read."},
            "where": {
                "type": "object",
                "description": (
                    "Field values that must match exactly (case-insensitive), for example "
                    "{\"holder\": \"our business\"} or {\"block_name\": \"North block\"}."
                ),
            },
            "contains": {
                "type": "string",
                "description": "A word or phrase the record must contain anywhere in its fields.",
            },
            "limit": {"type": "integer", "description": "How many to return. Default 10."},
        },
        "required": ["type"],
    },
}

RECORD_TYPES = {
    "name": "record_types",
    "description": (
        "List the record types this install declares, with their fields and which are required. "
        "Use it when unsure what can be recorded or what a type is called — never guess a field "
        "name."
    ),
    "parameters": {"type": "object", "properties": {}},
}

_FIELD = {
    "type": "object",
    "description": "One field of the new record type.",
    "properties": {
        "name": {"type": "string", "description": "Machine name, lowercase letters, numbers and underscores."},
        "label": {"type": "string", "description": "The label the operator will read."},
        "kind": {
            "type": "string",
            "enum": ["text", "longtext", "number", "money", "date", "enum", "reference"],
            "description": "The field kind. Default text.",
        },
        "required": {"type": "boolean", "description": "True when the record cannot be saved without it."},
        "options": {
            "type": "array",
            "items": {"type": "string"},
            "description": "For an enum: the allowed values.",
        },
        "reference": {
            "type": "string",
            "description": "For a reference: the record type it points at.",
        },
        "help": {"type": "string", "description": "A short hint shown beside the field."},
    },
    "required": ["name", "label"],
}

_TYPE_PROPERTIES = {
    "type": {
        "type": "string",
        "description": "Machine name for the record type, e.g. cleaning_log. Lowercase letters, numbers and underscores.",
    },
    "label": {"type": "string", "description": "The label the operator will read, e.g. Kitchen cleaning log."},
    "plural": {"type": "string", "description": "Plural label, e.g. Kitchen cleaning logs."},
    "fields": {
        "type": "array",
        "minItems": 1,
        "items": _FIELD,
        "description": "The fields the record holds. Keep it small and useful; the operator can add more later.",
    },
    "columns": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Field names to show in the list, in order. Defaults to the first three fields.",
    },
    "id_prefix": {
        "type": "string",
        "description": "Optional id prefix, e.g. CLN. Defaults to the type's initials. Sequential ids are used.",
    },
}

RECORD_TYPE_PROPOSE = {
    "name": "record_type_propose",
    "description": (
        "Propose a NEW kind of record when the operator asks for one this install does not have "
        "— a cleaning log, a maintenance log, a staff training record. This reads only: it returns "
        "the schema and the fields, and nothing is written. Show the proposal to the operator and "
        "ask them to confirm or change it. A new record kind is a pack type in the same record "
        "store; it is never a skill, a CSV, a spreadsheet or a second database. Once the operator "
        "approves, call record_type_create with the same proposal."
    ),
    "parameters": {"type": "object", "properties": _TYPE_PROPERTIES, "required": ["type", "label", "fields"]},
}

RECORD_TYPE_CREATE = {
    "name": "record_type_create",
    "description": (
        "Create a custom record type in the operator's own custom-packs directory, after they "
        "have approved the proposal. The engine will ask the operator to approve this write. The "
        "new type lands in the SAME store as every other record: do not create a file, a CSV, a "
        "spreadsheet or another database. After it is created, use record_save with the new type."
    ),
    "parameters": {"type": "object", "properties": _TYPE_PROPERTIES, "required": ["type", "label", "fields"]},
}
