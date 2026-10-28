"""The words that turn a sentence into a claim, and what each one needs before it can stand.

This is the pack's clearest case of prose describing a decision code makes
(the internal capability plan §6, rule 2): whether a sentence is a claim
is a lookup, not a judgement, and the lookup belongs here where it can be tested and read rather
than in a model's recollection.

Where the vocabulary comes from, and where it deliberately stops:

* The **shape** — accurate, evidenced, nothing important hidden — is the ACCC's environmental-claims
  guidance, re-stated in our own words (the skills and plugins notes §2.5 records that the ACCC's own
  reuse terms could not be verified, so nothing is quoted and the link is the citation).
* **Health claims are refused outright** rather than advised on, and that is a deliberate hole: the
  health-and-nutrition research (FSANZ Standard 1.2.7, FDA, Reg (EC) 1924/2006) was never reached, and
  §2.5 says a marketing assistant must emit **no** health claim until it is. A lint that said "check
  this one carefully" would be worse than one that says no.
* **Certification marks are not ours to give.** "Certified organic" is licensed wording that belongs
  to the certifier, and a certificate record is the only thing that can stand behind it.

Nothing here is legal advice, and the tool says so. It is a checklist with reasons.
"""

from __future__ import annotations

from dataclasses import dataclass

# `confidence` is not decoration. "Natural" and "green" are ordinary product words as often as they
# are claims — "natural yoghurt", "green beans" — so they are flagged low and the assistant is told
# to judge them in context rather than strip them. A lint that cannot say "this might be nothing" gets
# switched off by the first person it annoys.
LOW = "low"
HIGH = "high"


@dataclass(frozen=True)
class Rule:
    phrase: str
    category: str
    confidence: str
    needs: str


def _rules(category: str, needs: str, high: tuple[str, ...], low: tuple[str, ...] = ()) -> list[Rule]:
    return [Rule(phrase, category, HIGH, needs) for phrase in high] + [
        Rule(phrase, category, LOW, needs) for phrase in low
    ]


HEALTH_NEEDS = (
    "nothing can settle this. Health and nutrition claims are refused outright until the "
    "health-claims research is done: take the claim out, or say what the food is and let the "
    "customer decide."
)
ENVIRONMENTAL_NEEDS = (
    "evidence for the specific claim, not the general feeling: what was measured, by whom, over "
    "what, and what was left out. A generic environmental claim is the exact thing EmpCo "
    "((EU) 2024/825, applying 27 September 2026) treats as an unfair commercial practice, and a "
    "true-but-misleading claim is still misleading under the ACCC's guidance."
)
CERTIFICATION_NEEDS = (
    "the certificate record: a `record_find` on the certificate type for the scheme and the scope. "
    "Certification wording and marks are licensed by the certifier — an assistant cannot award one, "
    "and a certificate that does not name the thing being sold does not cover it."
)
PROVENANCE_NEEDS = (
    "the record that says where it came from — a supplier, a block, a batch — and the place named "
    "as the customer will read it. 'Local' with no boundary is a claim nobody can check."
)
COMPARATIVE_NEEDS = (
    "what it is better than, and on what measure. A comparative claim needs the comparison stated "
    "and substantiated; 'best' with nothing after it cannot be substantiated at all."
)

RULES: tuple[Rule, ...] = tuple(
    # Base forms, and the matcher (`lint._phrase_pattern`) carries the inflections: `cure` finds
    # "cures" and "cured", `prevent disease` finds "prevents disease", `boost` finds "boosting".
    # The list used to spell out each inflection, which is how it came to carry `boosts` while
    # missing `boost` — and a health claim went out with a "clear" verdict
    # (the internal audit PLUG-4).
    _rules("health", HEALTH_NEEDS, (
        # A bare verb is broad on purpose: "prevents colds" is a health claim, and a lint that
        # only caught "prevents disease" would miss it. The report says what was said and what
        # the operator must do; it never rewrites, so a near miss costs a sentence, not a draft.
        "cure", "heal", "prevent", "prevent disease", "prevent cancer",
        "boost immunity", "immune boosting",
        "immune system", "immunity", "detox", "superfood",
        "clinically proven", "medicinal", "therapeutic", "anti-inflammatory", "antioxidant",
        "lower cholesterol", "blood pressure", "aid digestion", "good for your gut",
        "treat", "remedy", "kill bacteria", "antibacterial", "boost",
        "help you lose weight", "sugar free", "keto friendly", "doctor recommended",
    ))
    + _rules("environmental", ENVIRONMENTAL_NEEDS, (
        "eco-friendly", "eco friendly", "environmentally friendly", "planet friendly",
        "carbon neutral", "net zero", "zero carbon", "climate positive", "carbon negative",
        "chemical free", "chemical-free", "pesticide free", "pesticide-free", "spray free",
        "biodegradable", "compostable", "recyclable", "sustainable", "sustainably grown",
        "low carbon", "carbon footprint", "food miles", "zero waste",
        "plastic free", "plastic-free", "beyond organic",
    ), low=("natural", "green", "clean", "pure", "gentle on the planet"))
    + _rules("certification", CERTIFICATION_NEEDS, (
        "certified organic", "certified biodynamic", "usda organic", "certified",
        "organic", "biodynamic", "bio-dynamic", "free range", "free-range",
        "rspca approved", "pasture raised", "grass fed", "grass-fed", "halal", "kosher",
    ), low=("regenerative",))
    + _rules("provenance", PROVENANCE_NEEDS, (
        "local", "locally grown", "australian made", "australian owned", "made in australia",
        "grown in australia", "farm fresh", "farm-fresh", "estate grown", "single origin",
        "artisan", "artisanal", "hand made", "handmade", "home made", "homemade",
        "small batch", "vine ripened", "vine-ripened", "picked today", "market fresh",
    ), low=("fresh", "seasonal", "locally", "local produce", "sourced locally"))
    + _rules("comparative", COMPARATIVE_NEEDS, (
        "best", "the best", "finest", "freshest", "cheapest", "number one", "#1", "no. 1",
        "award winning", "award-winning", "world class", "world-class", "premium",
        "the only", "unbeatable", "restaurant quality", "restaurant-quality",
    ))
)
