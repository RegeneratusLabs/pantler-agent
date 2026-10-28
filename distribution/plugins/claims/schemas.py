"""Tool schema — what the language model sees.

The two sentences that matter: **call this before any marketing copy is offered**, and **do not
rewrite the copy yourself**. A lint that quietly softens a sentence teaches nobody anything, and the
operator is the one whose name goes on the claim.
"""
from __future__ import annotations

CLAIM_CHECK = {
    "name": "claim_check",
    "description": (
        "Check marketing copy — a post, a product page, a newsletter line, a label — for claims, "
        "before it is offered to the operator. Returns every finding with its category, whether it "
        "was a confident match or an ordinary word that might be nothing, and what would have to "
        "stand behind it. "
        "HEALTH CLAIMS ARE REFUSED, not qualified: if the verdict is `refuse`, take the claim out. "
        "For `needs_evidence`, look for the record the finding names (`record_find` on the "
        "certificate type, the input record, the harvest lot); if there is no such record, the "
        "claim comes out. "
        "DO NOT REWRITE THE COPY YOURSELF and do not treat a clean result as permission — this is "
        "a checklist, not a clearance. Report the findings to the operator and let them decide; "
        "they are the one making the claim."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "The copy to check, as it would be published.",
            }
        },
        "required": ["text"],
    },
}
