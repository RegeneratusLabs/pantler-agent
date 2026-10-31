"""Scanning copy for claims: what was said, where, and what would have to stand behind it.

The lint does one thing and refuses to do another. It **finds** claims, names the category, and says
what each one needs. It does **not** rewrite: a lint that silently softens a sentence teaches the
operator nothing and produces copy nobody asked for. The finding is the product; the skill decides
what happens next, and the operator decides whether the claim stays.

Overlapping phrases are resolved by preferring the longest match at a position — "certified organic"
is one finding, not a `certified` and an `organic` — because a report that lists the same words three
times is a report nobody reads.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .vocabulary import RULES, Rule

# What the operator can do about a finding, in the order the tool reports it. "refuse" is not advice
# to consider: it is the answer, because the research behind health claims was never done.
VERDICTS = {
    "health": "refuse",
    "environmental": "needs_evidence",
    "certification": "needs_evidence",
    "provenance": "needs_evidence",
    "comparative": "needs_substantiation",
}

_INDEX: dict[str, list[Rule]] = {}
for _rule in RULES:
    _INDEX.setdefault(_rule.phrase.casefold(), []).append(_rule)

#: The inflections a phrase's final word may take. English does this with a suffix, not a new
#: word, so a list of them is a list that loses: the health vocabulary carried `boosts`,
#: `immunity` and `prevents` while a draft said "boost your immune system and prevent disease",
#: and the lint answered "clear" — the one output a health claim must never get
#: (the internal audit PLUG-4).
_FAMILY = r"(?:e?s|e?d|ing|ion|ions|if(?:y|ies|ied))?"


def _phrase_pattern(phrase: str) -> re.Pattern[str]:
    """One phrase, tolerant of how it is spelt rather than which word was listed.

    A space in the phrase also matches a hyphen (`anti-inflammatory`), and **each** word may
    carry an inflection — so the vocabulary can list `prevent disease` and `boost` once, and
    still catch "prevents disease" and "boosting". Both are spelling, not meaning, and a lint
    that misses a health claim over an `s` is worse than one that reports a near miss.
    """
    parts = [part for part in re.split(r"[\s-]+", phrase) if part]
    words = [re.escape(part) + _FAMILY for part in parts]
    body = r"[\s-]+".join(words)
    return re.compile(rf"(?<![A-Za-z]){body}(?![A-Za-z])", re.I)


_PATTERNS = [
    (phrase, _phrase_pattern(phrase)) for phrase in sorted(_INDEX, key=len, reverse=True)
]

#: What a lookalike folds to before matching. NFKC normalises compatibility forms — a full-width
#: `－`, a ligature — but it does *not* fold Cyrillic or Greek homoglyphs, and `immуne` written
#: with a Cyrillic `у` is the same claim to every reader that will ever see it
#: (the internal security audit A19-PLUG-8). This is the set of lookalikes for the letters
#: the vocabulary's own words use, in both cases; a spoofed sentence beyond it is a spoof, not a
#: claim, and this lint is a checklist rather than a spoofing detector.
_CONFUSABLES = str.maketrans({
    # Cyrillic
    "а": "a", "А": "A", "В": "B", "е": "e", "Е": "E", "К": "K", "М": "M", "Н": "H",
    "о": "o", "О": "O", "р": "p", "Р": "P", "с": "c", "С": "C", "Т": "T", "у": "y",
    "У": "Y", "х": "x", "Х": "X", "ѕ": "s", "Ѕ": "S", "і": "i", "І": "I", "ј": "j",
    "Ј": "J", "ԁ": "d", "һ": "h", "ӏ": "l", "ԛ": "q", "ԝ": "w",
    # Greek
    "α": "a", "Α": "A", "ε": "e", "Ε": "E", "ι": "i", "Ι": "I", "κ": "k", "Κ": "K",
    "μ": "m", "Μ": "M", "ν": "v", "Ν": "N", "ο": "o", "Ο": "O", "ρ": "p", "Ρ": "P",
    "τ": "t", "Τ": "T", "υ": "u", "Υ": "Y", "χ": "x", "Χ": "X", "ϲ": "c",
    # Latin lookalikes outside ASCII
    "ɡ": "g", "ɪ": "i", "ʟ": "l", "ɴ": "n", "ᴏ": "o", "ᴘ": "p", "ʀ": "r", "ᴜ": "u",
})


def _fold(text: str) -> tuple[str, list[int]]:
    """The copy the patterns run against, and where each of its characters came from.

    Four normalisations, in this order: NFKC (compatibility forms — a full-width hyphen, a
    ligature), the removal of `Cf` characters (the soft hyphen and zero-width space that sit
    *inside* a word and are invisible in every rendering), the dash family (a non-breaking hyphen
    is a hyphen), and the homoglyph table above. Without them the lint answered `clear` for
    `imm\\u00adune system`, `imm\\u200bune system`, `immune s\\u0443stem` and
    `anti\\u2011inflammatory` (the internal security audit A19-PLUG-8).

    The index map points every folded character back at the character it was folded from, so a
    finding's offsets stay offsets into the text the caller passed — the operator's own copy —
    even though the matching ran on the folded one. An obfuscated claim is therefore reported
    under its plain spelling, in the sentence it was actually written in.
    """
    folded: list[str] = []
    origin: list[int] = []
    for index, char in enumerate(text):
        if unicodedata.category(char) == "Cf":
            continue
        for piece in unicodedata.normalize("NFKC", char):
            if unicodedata.category(piece) == "Cf":
                continue
            if unicodedata.category(piece) == "Pd":
                piece = "-"
            folded.append(piece.translate(_CONFUSABLES))
            origin.append(index)
    return "".join(folded), origin


@dataclass(frozen=True)
class Finding:
    phrase: str
    category: str
    confidence: str
    start: int
    end: int
    needs: str

    @property
    def verdict(self) -> str:
        return VERDICTS.get(self.category, "needs_evidence")

    def as_dict(self, text: str) -> dict:
        context = text[max(0, self.start - 40) : self.end + 40].strip()
        return {
            "phrase": self.phrase,
            "category": self.category,
            "confidence": self.confidence,
            "verdict": self.verdict,
            "needs": self.needs,
            "in_context": f"…{context}…" if context != text.strip() else self.phrase,
        }


def check(text: str) -> list[Finding]:
    """Every claim in the copy, longest phrase first at any given position.

    The scan runs on a folded copy (`_fold`), so a spelling cannot hide a claim, and the offsets
    come back mapped onto the text that was passed.
    """
    string, origin = _fold(str(text or ""))
    found: list[Finding] = []
    taken: list[tuple[int, int]] = []
    for phrase, pattern in _PATTERNS:
        for match in pattern.finditer(string):
            span = (match.start(), match.end())
            if any(span[0] < end and start < span[1] for start, end in taken):
                continue  # a longer phrase already covers these words
            taken.append(span)
            rule = _INDEX[phrase.casefold()][0]
            found.append(
                Finding(
                    phrase=match.group(0),
                    category=rule.category,
                    confidence=rule.confidence,
                    start=origin[span[0]],
                    end=origin[span[1] - 1] + 1,
                    needs=rule.needs,
                )
            )
    found.sort(key=lambda finding: (finding.start, finding.end))
    return found


def report(text: str) -> dict:
    """The tool's answer: the findings, the verdict that matters, and what to do next."""
    findings = check(text)
    # The verdict is about the claims a reviewer would act on. A low-confidence flag — "natural",
    # "fresh", "seasonal" — is there for the assistant to read in context, which is what the
    # vocabulary's own design note says (`vocabulary.py`), so it does not decide the verdict
    # (the internal audit PLUG-16).
    decided = [finding for finding in findings if finding.confidence != "low"]
    categories = {finding.category for finding in decided}
    if "health" in categories:
        verdict = "refuse"
    elif "environmental" in categories or "certification" in categories or "provenance" in categories:
        verdict = "needs_evidence"
    elif "comparative" in categories:
        verdict = "needs_substantiation"
    else:
        verdict = "clear"

    return {
        "success": True,
        "verdict": verdict,
        "clear": not findings,
        "findings": [finding.as_dict(str(text)) for finding in findings],
        "counts": {
            category: len([f for f in findings if f.category == category])
            for category in sorted(categories)
        },
        "note": _note(verdict) + (
            " Some words were flagged as possibly a claim and nothing more — read them in "
            "context rather than rewriting on their word alone."
            if findings and not decided
            else ""
        ),
        "not_legal_advice": (
            "A checklist with reasons, not legal advice. The operator's regulator is the authority, "
            "and the categories above name what would have to stand behind each claim."
        ),
    }


def _note(verdict: str) -> str:
    if verdict == "clear":
        return (
            "Nothing in this copy reads as a claim from the list this tool carries. That is not a "
            "guarantee: the list is a checklist, and a sentence can mislead without using any of "
            "its words."
        )
    if verdict == "refuse":
        return (
            "A health claim is present. Take it out rather than qualify it: no record and no "
            "wording settles one until the health-claims research is done, and an assistant that "
            "emits one is guessing with the operator's name on it."
        )
    if verdict == "needs_evidence":
        return (
            "Each finding names what would settle it. Look for that record with `record_find`; if "
            "it is not there, the claim comes out — not softened, not qualified, out."
        )
    return (
        "A comparative claim needs its comparison stated and substantiated. Ask what it is better "
        "than; 'best' on its own cannot be answered."
    )
