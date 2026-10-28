"""Physical context: sampling depth and soil bulk density.

The ppm -> kg/ha conversion is not a constant:

    kg/ha = ppm x depth(m) x bulk_density(t/m3) x 10

so it depends on how deep the sample was taken and how dense the soil is.

The counter-intuitive part, and the reason a constant is wrong: bulk density goes
DOWN as clay content goes UP. Clay soils have better aggregation and more pore space
than sands, so they hold less mass per unit volume. Raising a nutrient by 1 ppm in a
light sandy soil therefore takes MORE product than in a clay, not less.

Density values come from the active profile. The defaults shipped with the package
are typical central values per texture class (Zeri et al. 2018, as reproduced in
extension literature), cross-checked against published root-growth thresholds which
agree on the direction. They are typical, not measured - compaction and cultivation
raise real densities well above these figures. Pass a measured bulk density when one
is available; it overrides the table.
"""
from __future__ import annotations

import re

from . import constants as K

# Fallbacks used only when no profile is supplied.
_FALLBACK_BD = {
    "sand": 1.65, "loamy sand": 1.60, "sandy loam": 1.55, "sandy soil": 1.55,
    "sandy clay loam": 1.50, "loam": 1.50, "silt loam": 1.50, "silty loam": 1.50,
    "silt": 1.50, "silty clay loam": 1.50, "clay loam": 1.45, "silty clay": 1.45,
    "sandy clay": 1.40, "clay": 1.35, "clayey": 1.35,
}
_FALLBACK_DEFAULT_BD = 1.50
_FALLBACK_DEFAULT_DEPTH_CM = 15.0
_FALLBACK_APPROXIMATE = {"sandy soil"}

_NUM = re.compile(r"\d+(?:\.\d+)?")


def _tables(profile=None):
    if profile is None:
        return (_FALLBACK_BD, _FALLBACK_DEFAULT_BD, _FALLBACK_DEFAULT_DEPTH_CM,
                _FALLBACK_APPROXIMATE, 5.0, 30.0)
    t = profile.thresholds
    return (profile.bulk_density or _FALLBACK_BD,
            profile.get("default_bulk_density", _FALLBACK_DEFAULT_BD),
            profile.get("default_depth_cm", _FALLBACK_DEFAULT_DEPTH_CM),
            set(profile.get("approximate_textures", _FALLBACK_APPROXIMATE)),
            t.get("typical_depth_min_cm", 5.0),
            t.get("typical_depth_max_cm", 30.0))


def normalise_texture(raw: str | None) -> str | None:
    if not raw:
        return None
    s = str(raw).strip().lower()
    s = s.replace("_", " ").replace("-", " ")
    s = re.sub(r"\s+", " ", s)
    s = s.replace("silt clay", "silty clay").replace("silty loam", "silt loam")
    if s in ("", "---", "n/a", "na", "-", "none"):
        return None
    return s


def bulk_density_for_texture(raw: str | None, profile=None) -> tuple[float | None, str]:
    """(bulk_density, note). bulk_density is None when the texture is unknown."""
    table, default_bd, _depth, approximate, _tmin, _tmax = _tables(profile)
    key = normalise_texture(raw)
    if key is None:
        return None, f"no texture reported; using {default_bd} g/cm3 as the default"
    if key in table:
        bd = float(table[key])
        note = f"texture '{str(raw).strip()}' -> {bd} g/cm3"
        if key in approximate:
            note += " (broad bucket, mapped to a central value)"
        return bd, note
    return None, f"unrecognised texture '{str(raw).strip()}'"


def parse_depth_cm(raw: str | None, profile=None) -> tuple[float, bool, str]:
    """Parse a depth string to centimetres: (depth_cm, unit_was_explicit, note).

    Ranges use the LOWER boundary of the sampled layer, since that is the depth the
    reported concentration averages over.

    Real CoAs carry a mess of formats: '15cm', '150mm', '0-15', '0.0-0.15', '150',
    'Sub 1m', '30-120', '50-250mm'. Unitless values are inferred from magnitude, and
    that inference is always reported so a human can catch a wrong guess.
    """
    _bd, _dbd, default_depth, _ap, tmin, tmax = _tables(profile)

    if raw is None or not str(raw).strip() or str(raw).strip() in ("---", "-"):
        return default_depth, False, (
            f"no sampling depth on the report; assumed {default_depth:.0f} cm")

    s = str(raw).strip().lower()

    if "sub" in s and "m" in s:
        return 100.0, True, f"depth '{str(raw).strip()}' read as 100 cm (below 1 m)"

    nums = [float(n) for n in _NUM.findall(s)]
    if not nums:
        return default_depth, False, (
            f"could not read depth '{str(raw).strip()}'; assumed {default_depth:.0f} cm")

    value = max(nums)
    if "mm" in s:
        depth, explicit = value / 10.0, True
        note = f"depth '{str(raw).strip()}'"
    elif "cm" in s:
        depth, explicit = value, True
        note = f"depth '{str(raw).strip()}'"
    elif re.search(r"\d\s*m\b", s) or s.strip().endswith("m"):
        # Metres, which used to fall through to the no-unit branch: "2m" read as 2 cm and "0-2m"
        # as 2 cm, so a metre-deep sample was treated as a 2 cm one and every kg/ha figure came
        # out 50× light (the internal audit PLUG-10). `mm` and `cm` are matched above, so a
        # trailing `m` here can only be metres.
        depth, explicit = value * 100.0, True
        note = f"depth '{str(raw).strip()}' read as metres"
    else:
        explicit = False
        if value > 40:
            depth = value / 10.0
            note = (f"depth '{str(raw).strip()}' had no unit; read as {value:.0f} mm "
                    "given the magnitude")
        else:
            depth = value
            note = (f"depth '{str(raw).strip()}' had no unit; read as {value:.0f} cm "
                    "given the magnitude")

    # A decimal-fraction form like '0.0-0.15' is metres.
    if max(nums) <= 1.0 and depth < 5.0:
        depth = max(nums) * 100.0
        note = f"depth '{str(raw).strip()}' read as metres"

    if not (2.0 <= depth <= 200.0):
        return default_depth, False, (
            f"depth '{str(raw).strip()}' parsed to {depth:.1f} cm which is out of range; "
            f"assumed {default_depth:.0f} cm")

    return depth, explicit, note


def ppm_to_kgha_factor(depth_cm: float, bulk_density: float) -> float:
    """kg/ha of element per 1 ppm: 15 cm at BD 1.50 gives 2.25."""
    # kg/ha of element per 1 ppm = depth_cm / 100 × bulk_density × the divisor.
    return depth_cm / 100.0 * bulk_density * K.FACTOR_DEPTH_DIVISOR


def resolve_factor(texture_raw: str | None, depth_raw: str | None,
                   profile=None,
                   override_bd: float | None = None,
                   override_depth_cm: float | None = None,
                   override_factor: float | None = None) -> tuple[float, dict]:
    """Derive the ppm -> kg/ha factor and explain how.

    Precedence: an explicit factor wins outright (reproducing a fixed historical
    constant), then an explicit bulk density, then the texture table.
    """
    _bd_t, default_bd, default_depth, _ap, tmin, tmax = _tables(profile)
    detail: dict = {"texture_raw": texture_raw, "depth_raw": depth_raw, "notes": []}

    if override_factor is not None:
        detail.update(factor=override_factor, source="operator override",
                      bulk_density=override_bd, depth_cm=override_depth_cm,
                      depth_raw=depth_raw, depth_is_typical=True,
                      depth_as_given=False, depth_is_explicit=True,
                      bulk_density_is_default=False)
        detail["notes"].append(
            f"factor fixed at {override_factor} by explicit override - no physical "
            "derivation applied")
        return override_factor, detail

    depth_cm, depth_explicit, depth_note = parse_depth_cm(depth_raw, profile)
    if override_depth_cm is not None:
        depth_cm, depth_explicit = override_depth_cm, True
        depth_note = f"depth fixed at {override_depth_cm} cm by override"

    bd, bd_note = bulk_density_for_texture(texture_raw, profile)
    bd_is_default = bd is None
    if bd is None:
        bd = float(default_bd)
    if override_bd is not None:
        bd, bd_is_default = override_bd, False
        bd_note = f"bulk density fixed at {override_bd} t/m3 by override"

    factor = ppm_to_kgha_factor(depth_cm, bd)
    typical = tmin <= depth_cm <= tmax
    detail.update(factor=factor, source="texture and depth",
                  bulk_density=bd, bulk_density_is_default=bd_is_default,
                  depth_cm=depth_cm, depth_is_explicit=depth_explicit,
                  depth_as_given=bool(depth_raw and str(depth_raw).strip()
                                      and str(depth_raw).strip() != "---"),
                  depth_is_typical=typical)
    detail["notes"].extend([depth_note, bd_note])
    detail["notes"].append(
        f"factor {factor:.3f} kg/ha per ppm = {depth_cm:.0f} cm x {bd:.2f} t/m3 "
        f"/ {K.FACTOR_DEPTH_DIVISOR:.0f}")
    if not typical:
        detail["notes"].append(
            f"DEPTH CHECK: {depth_cm:.0f} cm is outside the typical {tmin:.0f}-{tmax:.0f} "
            "cm sampling layer. The rate is arithmetically right for that depth but "
            "would overstate an amendment to the working layer.")
    return factor, detail
