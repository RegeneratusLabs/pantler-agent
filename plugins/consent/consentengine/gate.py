"""The three checks a direct-marketing send has to pass, and the one that refuses outright.

The research (the skills and plugins notes §2.5) found the same three-part gate in every jurisdiction
examined: **consent**, **accurate sender identification**, and **a working unsubscribe**. Two of them
are checks on the draft's text and are reported as findings. The first is a lookup over the consent
records and it *refuses*: a send with no consent behind it is not a draft to be improved, it is a
breach waiting for the send button.

What this deliberately does not do: it does not decide that a soft opt-in applies, it does not read a
purchase history to infer consent, and it does not treat "they're a customer" as consent. Those are
judgements about a jurisdiction and a relationship, and the honest answer when the record is missing is
that the record is missing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pantler_core.units import normalize

ALLOWED = "allowed"
NO_RECORD = "no_record"
WITHDRAWN = "withdrawn"
AMBIGUOUS = "ambiguous"

# The words that have to appear somewhere in a send for the other two checks to pass. Deliberately
# loose: this is a presence check, not a legal review, and a false "missing" is a prompt to look
# rather than a finding.
UNSUBSCRIBE_WORDS = ("unsubscribe", "opt out", "opt-out", "stop these emails", "update your preferences")
SENDER_WORDS = ("from ", "regards", "cheers", "thanks", "sincerely", "—", "--", "on behalf of")


@dataclass
class Decision:
    recipient: str
    status: str
    record_id: str = ""
    detail: str = ""
    consent_for: str = ""

    @property
    def allowed(self) -> bool:
        return self.status == ALLOWED

    def as_dict(self) -> dict:
        return {
            "recipient": self.recipient,
            "status": self.status,
            "allowed": self.allowed,
            "record_id": self.record_id,
            "consent_for": self.consent_for,
            "detail": self.detail,
        }


@dataclass
class SendCheck:
    allowed: bool
    decisions: list[Decision] = field(default_factory=list)
    checks: list[dict] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    refusals: list[str] = field(default_factory=list)


def check_recipients(book, recipients: list[str], purpose: str = "") -> list[Decision]:
    """One decision per recipient, from the consent records and nothing else."""
    decisions: list[Decision] = []
    for raw in recipients:
        who = str(raw).strip()
        if not who:
            continue
        decisions.append(_decide(book, who, purpose))
    return decisions


def _decide(book, who: str, purpose: str) -> Decision:
    wanted = normalize(who)
    matches = [
        record
        for record in book.find("consent", limit=500)
        if _matches(record.data or {}, wanted)
    ]
    if not matches:
        return Decision(
            recipient=who,
            status=NO_RECORD,
            detail=(
                "No consent record on file for this person. That is a refusal, not a caution: a "
                "message to somebody with no consent record is the breach the gate exists to stop. "
                "Ask them, then record it — the record is the permission."
            ),
        )
    active = [
        record
        for record in matches
        if not str((record.data or {}).get("withdrawn_on") or "").strip()
    ]
    if not active:
        record = sorted(matches, key=lambda r: r.id)[-1]
        return Decision(
            recipient=who,
            status=WITHDRAWN,
            record_id=record.id,
            consent_for=str((record.data or {}).get("what") or ""),
            detail=(
                f"Consent was withdrawn on {(record.data or {}).get('withdrawn_on')} "
                f"({record.id}). Withdrawal is not a preference to weigh up — it is the end of the "
                f"permission, and the record stays to show it was given and taken back."
            ),
        )
    if len(active) > 1:
        return Decision(
            recipient=who,
            status=AMBIGUOUS,
            record_id=", ".join(record.id for record in active),
            detail=(
                "More than one live consent record for this person. Ask which one applies before "
                "sending — the records may cover different purposes."
            ),
        )
    record = active[0]
    data = record.data or {}
    covers = str(data.get("what") or "")
    where = str(data.get("where_used") or "")
    stated = normalize(purpose)
    place = normalize(where)
    if not stated:
        # The place check used to begin `if purpose and where and …`, so saying nothing skipped it
        # entirely and an omitted argument was the *safe* one — the model chooses the arguments,
        # which makes it the unsafe one (the internal security audit A19-PLUG-9).
        return Decision(
            recipient=who,
            status=NO_RECORD,
            record_id=record.id,
            consent_for=covers,
            detail=(
                f"Consent on file ({record.id}) is for {where or 'one place'}, and this send does "
                f"not say where it is going. Name the place before anything is sent — a consent "
                f"for one place is not a consent for all of them."
            ),
        )
    if not place or stated != place:
        # Identity, not containment: `"letter"` used to pass because it sits inside
        # `"the newsletter"`, which made a consent for one place a consent for every substring of
        # its name (the internal security audit A19-PLUG-9).
        return Decision(
            recipient=who,
            status=NO_RECORD,
            record_id=record.id,
            consent_for=covers,
            detail=(
                f"The consent on file names {where or 'no place'} as the place it may be used, and "
                f"this send is {purpose!r}. A consent for one place is not a consent for all of "
                f"them — ask, or send somewhere the record covers."
            ),
        )
    return Decision(
        recipient=who,
        status=ALLOWED,
        record_id=record.id,
        consent_for=covers,
        detail=f"Consent on file ({record.id}), for {where or 'the place it names'}.",
    )


def _matches(data: dict, wanted: str) -> bool:
    """A person matches on their name, and on nothing else.

    Not on a fuzzy search and not on an email address: a consent record names a *person*, in their own
    spelling, and matching loosely is how one person's permission ends up covering another's address.
    The rule is therefore about *whose name it is*, not about words the two names happen to share:

    * the same name, in any order — "Chen Maria" is "Maria Chen";
    * the same name abbreviated part by part — a record of "M. Chen" covers "Maria Chen";
    * a bare abbreviation — "M." — covers the first name it abbreviates.

    What it deliberately does not do is accept a shared word. A record whose `who` is one token is
    that one name and covers only it, so "Chen" used to permit "Alice Chen", "Bob Chen" *and*
    "Chen Family Trust" — one person's permission covering three
    (the internal audit PLUG-5). A refusal here is a question the operator answers by
    correcting the record, which is the direction this gate must err in.
    """
    name = normalize(str(data.get("who") or ""))
    if not name or not wanted:
        return False
    if name == wanted:
        return True

    ours, theirs = name.split(), wanted.split()

    if len(ours) == len(theirs):
        if sorted(ours) == sorted(theirs):
            return True
        return all(_abbreviates(part, other) for part, other in zip(ours, theirs))

    if len(ours) == 1 and theirs:
        # One token against a longer name may only be a *marked* abbreviation: "M." and "M" are
        # initials, and "Chen" is a surname that says nothing about which Chen
        # (the internal audit PLUG-5).
        return _abbreviates(ours[0], theirs[0], allow_equal=False)

    return False


def _abbreviates(part: str, full: str, *, allow_equal: bool = True) -> bool:
    """Whether `part` is `full` written short: "m." for "maria", "m" for "maria".

    Short and *marked* short — a dot, or a couple of letters. "Maria" is not an abbreviation of
    "Mariah": it is a prefix of it, and the two are different people. The mark is the whole rule,
    and it is what keeps a near-miss name from inheriting a consent
    (the internal audit PLUG-5).
    """
    stem = part.rstrip(".")
    if not stem:
        return False
    if stem == full:
        return allow_equal
    if len(stem) >= len(full):
        return False
    if part.endswith(".") or len(stem) <= 3:
        return full.startswith(stem)
    return False


def check_draft(draft: str) -> list[dict]:
    """The other two checks, as findings on the draft: sender identification and an unsubscribe."""
    text = str(draft or "")
    lowered = text.casefold()
    findings = []
    if text.strip():
        if not any(word in lowered for word in UNSUBSCRIBE_WORDS):
            findings.append(
                {
                    "check": "unsubscribe",
                    "status": "missing",
                    "detail": (
                        "No unsubscribe or opt-out line in the draft. Every jurisdiction examined "
                        "requires a working way out, and 'reply STOP' is not one on email."
                    ),
                }
            )
        if not any(word in lowered for word in SENDER_WORDS):
            findings.append(
                {
                    "check": "sender",
                    "status": "missing",
                    "detail": (
                        "Nothing in the draft identifies who sent it. Accurate sender "
                        "identification is part of the same gate as consent."
                    ),
                }
            )
    return findings


def check_send(book, recipients: list[str], *, purpose: str = "", draft: str = "") -> SendCheck:
    """The gate: who may be written to, what the draft is missing, and what to ask."""
    decisions = check_recipients(book, recipients, purpose)
    checks = check_draft(draft)
    refusals = [d.detail for d in decisions if not d.allowed]
    # A draft missing its sender identification or its unsubscribe line is not ready to send, and
    # `allowed` has to mean "this may be sent as it stands" or the field contradicts the check
    # printed beside it (the internal audit PLUG-16). The missing pieces join the refusals,
    # so the caller sees what to fix rather than only that something is wrong.
    blocking = [check for check in checks if check.get("status") == "missing"]
    refusals += [str(check.get("detail") or check.get("check")) for check in blocking]
    questions = []
    if any(d.status == AMBIGUOUS for d in decisions):
        questions.append("Which consent record applies to the person with more than one?")
    return SendCheck(
        allowed=(
            all(decision.allowed for decision in decisions)
            and bool(decisions)
            and not blocking
        ),
        decisions=decisions,
        checks=checks,
        questions=questions,
        refusals=refusals,
    )
