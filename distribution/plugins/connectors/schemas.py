"""The connector tool schema — what the model sees.

The schema carries the policy, not just the parameters: read before write, never invent
arguments, and stop when the result says BLOCKED. The approval hook is the enforcement; this is
the instruction that keeps the model from walking into it by accident.
"""

from __future__ import annotations

CONNECTOR_USE = {
    "name": "connector_use",
    "description": (
        "Use one of the operator's connected apps (Gmail, Google Drive, Google Calendar, Square, "
        "Shopify, Xero, Mailchimp, Facebook or Instagram) through Composio. "
        "Actions: 'status' lists which apps are connected and their state; 'tools' lists the "
        "actions a connected app offers, with a read_only flag; 'schema' returns one tool's "
        "argument names and types; 'run' executes one of those actions with the arguments it "
        "needs. "
        "Work in that order: status, then tools, then schema for the chosen tool, then run. Use "
        "the exact tool slug and argument names the schema returns; never invent an argument or "
        "guess an id. "
        "A read runs directly. A write is stopped for the operator's approval before it is sent; "
        "if the result says BLOCKED or that the user did not approve, stop and tell them — do not "
        "retry the same write. If no app is connected, say so and point at Capabilities → "
        "Connectors; do not claim anything was sent or changed."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["status", "tools", "schema", "run"],
                "description": "What to ask the connector service. Start with status.",
            },
            "connector": {
                "type": "string",
                "description": (
                    "The connector id from the status action — for example gmail, googlesheets "
                    "or quickbooks. Required for tools, schema and run."
                ),
            },
            "tool": {
                "type": "string",
                "description": (
                    "The Composio tool slug from the 'tools' action, e.g. GMAIL_FETCH_EMAILS or "
                    "GMAIL_CREATE_EMAIL_DRAFT. Required for run."
                ),
            },
            "arguments": {
                "type": "object",
                "description": (
                    "The tool's own arguments, exactly as its schema names them. Required for "
                    "run; pass an empty object only when the tool takes none."
                ),
            },
        },
        "required": ["action"],
    },
}
