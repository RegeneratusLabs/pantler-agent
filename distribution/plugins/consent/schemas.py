"""Tool schema — what the language model sees.

The rule the description has to carry: **a refusal is final, not a caution**. An assistant that treats
"no consent record" as something to work around is the failure mode this tool exists for, and it is
the one place where being helpful is the harm.
"""
from __future__ import annotations

CONSENT_CHECK = {
    "name": "consent_check",
    "description": (
        "Before any message goes to anybody — a newsletter, a text, a market reminder — check who "
        "may be written to. Give the recipients as they are named, and the draft if there is one. "
        "Returns one decision per recipient: `allowed` (with the consent record), `no_record`, "
        "`withdrawn`, or `ambiguous`; plus any missing unsubscribe line or sender identification. "
        "A `no_record` or `withdrawn` decision is A REFUSAL, NOT A CAUTION: do not send, do not "
        "offer to send, and do not treat 'they're a customer' or a past purchase as consent — say "
        "what is missing and how to record it. Never decide for yourself that a soft opt-in applies. "
        "If everyone is allowed, say who the consent came from before the send happens."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "recipients": {
                "type": "array",
                "items": {"type": "string"},
                "description": "The people the message would go to, named as the operator names them.",
            },
            "purpose": {
                "type": "string",
                "description": (
                    "Where it would be sent — 'the newsletter', 'Instagram', 'a text reminder'. A "
                    "consent naming one place does not cover another, so this is checked against it."
                ),
            },
            "draft": {
                "type": "string",
                "description": "The message itself, if it exists, for the unsubscribe and sender checks.",
            },
        },
        # `purpose` is required here as well as in the gate: a purpose the caller leaves out
        # used to skip the place check entirely (the internal security audit A19-PLUG-9).
        "required": ["recipients", "purpose"],
    },
}
