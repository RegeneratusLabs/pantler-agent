"""Agronomic constants that are the same for every deployment.

Anything a deployment would change - product names, analysis percentages, application
ceilings, ideal levels, warning text - lives in a profile (see profile.py), not here.
What remains here is chemistry and physics.
"""

# ---------------------------------------------------------------------------
# ppm <-> meq/100g conversion divisors.
#     meq = ppm / divisor        ppm = meq * divisor
#
# These are equivalent weights x 10, using the ROUNDED atomic weights that the
# standard published tables use (Ca 40, Mg 24, K 39, Na 23, Al 27):
#   Ca 40/2*10 = 200   Mg 24/2*10 = 120   K 39/1*10 = 390
#   Na 23/1*10 = 230   Al 27/3*10 = 90
# The exact values are 200.4 / 121.5 / 391.0 / 229.9 / 89.9. The rounded set is the
# convention and the error is under 1.3% for every element; do not change these to
# "fix" a decimal place.
# ---------------------------------------------------------------------------
EQ_PPM = {
    "Ca": 200.0,
    "Mg": 120.0,
    "K": 390.0,
    "Na": 230.0,
    "Al": 90.0,
}

# Which exchangeable cation maps to which parameter name in an EAL Certificate of
# Analysis. Note aluminium is named differently, and that sodium appears under
# 'Sodium - ESP' in the calculated base-saturation block.
EXCHANGEABLE_PARAM = {
    "Ca": "Exchangeable Calcium",
    "Mg": "Exchangeable Magnesium",
    "K": "Exchangeable Potassium",
    "Na": "Exchangeable Sodium",
    "Al": "Aluminium - Exchangeable",
}

LAB_BS_PARAM = {
    "Ca": "Calcium",
    "Mg": "Magnesium",
    "K": "Potassium",
    "Na": "Sodium - ESP",
    "Al": "Aluminium",
    "H": "Hydrogen",
    "OtherBases": "Other Bases",
}

# ---------------------------------------------------------------------------
# A worked example of why the factor is derived and not fixed: older output used one assumed
# bulk density for every soil — 2.5 kg/ha per ppm is 1.67 t/m3 at 15 cm, and 2.24 is 1.49 —
# which is what the CLI's `--factor` reproduces when someone needs an old number. Neither is a
# live default.
# Neutral fallback for the dataclass field only - always overwritten by the derived
# factor, so it is never used in a calculation.
DEFAULT_FACTOR = 2.25  # 15 cm at bulk density 1.50

# ---------------------------------------------------------------------------
# Physical constants
# ---------------------------------------------------------------------------
# kg/ha of element per 1 ppm = depth_cm / 100 * bulk_density * 10.
FACTOR_DEPTH_DIVISOR = 10.0

