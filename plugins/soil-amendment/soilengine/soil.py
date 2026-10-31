"""Soil arithmetic: base saturations, ratios, exchange-capacity-relative targets and
element deficits.

Deterministic functions rather than a live spreadsheet with manual override cells and
iterative calculation.

Where the lab already reports a derived figure (base saturation %, cation exchange
capacity, calcium/magnesium ratio) that figure is used as the primary value and the
computed one is kept beside it for cross-checking. Disagreements are surfaced in
`warnings`, never silently resolved one way or the other.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import constants as K
from . import physical
from .eal import Sample


@dataclass
class CationState:
    """One exchangeable cation, in every unit the sources use."""
    element: str
    meq: float | None
    ppm: float | None
    kg_ha: float | None
    bs_pct: float | None          # % of total exchange capacity, computed
    bs_pct_lab: float | None      # % as reported by the laboratory
    ideal_ppm_min: float | None
    ideal_ppm_max: float | None
    ideal_bs_min: float | None
    ideal_bs_max: float | None


@dataclass
class SoilAnalysis:
    sample: Sample
    sample_id: str
    tec: float | None
    cec_measured: float | None
    ph: float | None
    ec: float | None
    organic_c: float | None
    organic_matter: float | None
    texture: str | None
    colour: str | None
    paramagnetism: float | None
    cations: dict[str, CationState]
    ratios: dict[str, float | None]
    ratio_ideals: dict[str, object]
    elements: dict[str, dict]
    bs_band: dict | None
    ppm_to_kgha: float = K.DEFAULT_FACTOR
    factor_detail: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Target lookup
# ---------------------------------------------------------------------------

def ideal_bs_row(tec: float | None, crop_class: str = "generic", profile=None) -> dict | None:
    """The target base-saturation row for a total exchange capacity.

    Returns a row dict: {tec_min, tec_max, ca_mg_label, elements:{el:[min,max]}}.
    A profile may raise the potassium target for a high-potassium crop class.
    """
    if tec is None:
        return None
    table = profile.bs_table if profile is not None else None
    if not table:
        return None
    for row in table:
        tmin = float(row["tec_min"])
        tmax = row["tec_max"]
        tmax = float("inf") if tmax is None else float(tmax)
        if tmin <= tec < tmax:
            out = dict(row)
            out["elements"] = {k: tuple(v) for k, v in row["elements"].items()}
            if profile is not None and crop_class == "high_k":
                overrides = profile.high_k_overrides
                key = str(tmin)
                if key in overrides and "K" in out["elements"]:
                    out["elements"]["K"] = tuple(overrides[key])
            return out
    return None


def ideal_ppm_for(tec: float | None, element: str, bs_pct: float) -> float | None:
    """Ideal ppm = TEC x BS% x (equivalent weight / 10)."""
    if tec is None:
        return None
    eq = K.EQ_PPM.get(element)
    if eq is None:
        return None
    return tec * bs_pct * (eq / 100.0)


def lab_bs_pct(sample: Sample, element: str) -> float | None:
    """Laboratory-reported base saturation %, using the parameter names the lab uses.

    Note these are DIFFERENT rows from the same-named total-acid-extractable rows,
    which is why matching on (name, unit) rather than name alone matters.
    """
    name = K.LAB_BS_PARAM.get(element, element)
    return sample.value(name, "%")


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

def analyse_sample(sample: Sample, profile=None, crop_class: str = "generic",
                   ppm_to_kgha: float | None = None,
                   override_bd: float | None = None,
                   override_depth_cm: float | None = None) -> SoilAnalysis:
    """Compute the full soil state for one certificate-of-analysis sample.

    The ppm -> kg/ha factor is derived from the sample's own texture and sampling
    depth unless `ppm_to_kgha` is given explicitly, which reproduces a fixed
    historical constant. How the factor was arrived at is recorded in
    `factor_detail` and surfaced in the report.
    """
    warnings: list[str] = []
    wr = sample.value_or_lor_half   # below-LOR -> LOR/2, for balance arithmetic

    # --- physical context --------------------------------------------------
    texture_r = sample.get("Basic Texture")
    colour_r = sample.get("Basic Colour")
    # The known labels first, in order, and a warning if the report carries more than one: a
    # dict's insertion order is the CSV's row order, so "whichever depth-like label came first"
    # was how a depth was chosen (the internal audit PLUG-16).
    depth_keys = [k for k in sample.meta if "depth" in str(k).lower()]
    preferred = [k for k in ("Sample Depth", "Depth", "Sampling Depth") if k in depth_keys]
    chosen = (preferred or depth_keys or [None])[0]
    if len(depth_keys) > 1:
        warnings.append(
            f"more than one depth label in this report ({', '.join(map(str, depth_keys))}); "
            f"using {chosen!r}"
        )
    depth_raw = sample.meta.get(chosen) if chosen is not None else None

    ppm_to_kgha, factor_detail = physical.resolve_factor(
        texture_r.raw if texture_r else None, depth_raw, profile,
        override_bd=override_bd, override_depth_cm=override_depth_cm,
        override_factor=ppm_to_kgha)
    if factor_detail.get("bulk_density_is_default"):
        warnings.append("bulk density defaulted - texture not usable, so the kg/ha "
                        "factor is an estimate")

    # --- exchangeable cations ---------------------------------------------
    cations: dict[str, CationState] = {}
    meq_values: dict[str, float | None] = {}

    for el, param in K.EXCHANGEABLE_PARAM.items():
        meq = wr(param, "cmol+/kg")
        ppm = wr(param, "mg/kg")
        kg_ha = wr(param, "kg/ha")

        if meq is None and ppm is not None:
            meq = ppm / K.EQ_PPM[el]
            warnings.append(f"{el}: meq derived from ppm / {K.EQ_PPM[el]:.0f}")
        if ppm is None and meq is not None:
            ppm = meq * K.EQ_PPM[el]
        if kg_ha is None and meq is not None:
            kg_ha = meq * K.EQ_PPM[el] * ppm_to_kgha

        meq_values[el] = meq
        cations[el] = CationState(
            element=el, meq=meq, ppm=ppm, kg_ha=kg_ha,
            bs_pct=None, bs_pct_lab=lab_bs_pct(sample, el),
            ideal_ppm_min=None, ideal_ppm_max=None,
            ideal_bs_min=None, ideal_bs_max=None,
        )
        if meq is None and ppm is None:
            warnings.append(f"{el}: exchangeable value not present in the report")

    # --- pH, EC, carbon ----------------------------------------------------
    ph = sample.value("pH (H2O)")
    ec = sample.value("Electrical Conductivity")
    organic_c = sample.value("Carbon - Total")
    if organic_c is None:
        organic_c = sample.value("Total Carbon")
    organic_matter = sample.value("Estimated Organic Matter")
    if organic_matter is None and organic_c is not None:
        organic_matter = organic_c * 1.75
        warnings.append("organic matter estimated as carbon x 1.75")
    texture = texture_r.raw if texture_r else None
    colour = colour_r.raw if colour_r else None
    paramag = sample.value("Paramagnetism")

    # --- exchange capacity -------------------------------------------------
    cec_measured = None
    if all(v is not None for v in (meq_values["Ca"], meq_values["Mg"],
                                   meq_values["K"], meq_values["Na"])):
        cec_measured = (sum(meq_values[e] for e in ("Ca", "Mg", "K", "Na"))
                        + (meq_values["Al"] or 0.0))

    tec = sample.value("Total Cation Exchange Capacity")
    tec_was_reported = tec is not None
    if tec is None:
        h_pct = lab_bs_pct(sample, "H")
        if cec_measured is not None and h_pct is not None and h_pct < 100:
            tec = cec_measured / (1 - h_pct / 100.0)
            warnings.append("exchange capacity derived from the cation sum and the "
                            "reported hydrogen percentage")
        else:
            tec = cec_measured
            warnings.append("exchange capacity fell back to the sum of exchangeable "
                            "cations")
    # Only a *reported* exchange capacity can disagree with the cation sum. When TEC was derived
    # from that sum, the comparison was against itself and fired on every sample with more than
    # 25% hydrogen — a warning about arithmetic this module had just done
    # (the internal audit PLUG-16).
    if tec_was_reported and cec_measured is not None and tec is not None:
        if abs(cec_measured - tec) > max(0.25 * tec, 0.5):
            warnings.append(
                f"cation sum ({cec_measured:.2f}) and reported exchange capacity "
                f"({tec:.2f}) disagree by more than 25%")

    # --- base saturation and targets --------------------------------------
    band = ideal_bs_row(tec, crop_class, profile)
    bs_table = {}
    ca_mg_label = None
    if band:
        bs_table = band["elements"]
        ca_mg_label = band.get("ca_mg_label")
    else:
        warnings.append("no exchange-capacity band matched; base saturation targets "
                        "unavailable")

    for el, cs in cations.items():
        if tec and tec > 0 and cs.meq is not None:
            cs.bs_pct = cs.meq / tec * 100.0
        lim = bs_table.get(el)
        if lim:
            cs.ideal_bs_min, cs.ideal_bs_max = lim
            if cs.ideal_bs_max is not None:
                cs.ideal_ppm_max = ideal_ppm_for(tec, el, cs.ideal_bs_max)
            if cs.ideal_bs_min is not None:
                cs.ideal_ppm_min = ideal_ppm_for(tec, el, cs.ideal_bs_min)
        if cs.bs_pct is not None and cs.bs_pct_lab is not None:
            if abs(cs.bs_pct - cs.bs_pct_lab) > 2.0:
                warnings.append(
                    f"{el} base saturation: computed {cs.bs_pct:.1f}% vs reported "
                    f"{cs.bs_pct_lab:.1f}% (>2 points apart)")

    # --- ratios ------------------------------------------------------------
    c = cations

    def safe(num, den):
        if num is None or den in (None, 0):
            return None
        return num / den

    ratios = {
        "Ca_Mg_bs": safe(c["Ca"].bs_pct, c["Mg"].bs_pct),
        "Ca_Mg_ppm": safe(c["Ca"].ppm, c["Mg"].ppm),
        "Mg_K": safe(c["Mg"].ppm, c["K"].ppm),
        "K_Na": safe(c["K"].ppm, c["Na"].ppm),
        "Ca_K": safe(c["Ca"].ppm, c["K"].ppm),
    }
    ratio_lab = sample.value("Calcium/Magnesium Ratio")
    if ratio_lab is not None:
        ratios["Ca_Mg_lab_ratio"] = ratio_lab

    # --- other elements ----------------------------------------------------
    ideal_ppm = (profile.ideal_ppm if profile is not None else {})
    elements: dict[str, dict] = {}

    def add_element(key: str, actual: float | None, ideal: float | None, source: str):
        if actual is None:
            elements[key] = {"actual": None, "ideal": ideal, "deficit": None,
                             "kg_ha_element": None, "source": source,
                             "status": "not_reported"}
            return
        if ideal is None:
            elements[key] = {"actual": actual, "ideal": None, "deficit": None,
                             "kg_ha_element": None, "source": source,
                             "status": "no_target"}
            return
        deficit = max(0.0, ideal - actual)
        elements[key] = {
            "actual": actual, "ideal": ideal, "deficit": deficit,
            "kg_ha_element": deficit * ppm_to_kgha, "source": source,
            "status": "deficient" if deficit > 0 else "adequate",
        }

    add_element("P", wr("Mehlich Phosphorus", "mg/kg"), ideal_ppm.get("P"), "Mehlich 3")
    add_element("S", wr("Sulfur - KCl extractable", "mg/kg"), ideal_ppm.get("S"), "KCl extractable")
    add_element("Zn", wr("Zinc - DTPA", "mg/kg"), ideal_ppm.get("Zn"), "DTPA")
    add_element("Mn", wr("Manganese - DTPA", "mg/kg"), ideal_ppm.get("Mn"), "DTPA")
    add_element("Fe", wr("Iron - DTPA", "mg/kg"), ideal_ppm.get("Fe"), "DTPA")
    add_element("Cu", wr("Copper - DTPA", "mg/kg"), ideal_ppm.get("Cu"), "DTPA")
    add_element("B", wr("Boron - CaCl2 extractable", "mg/kg"), ideal_ppm.get("B"), "CaCl2")
    add_element("Si", wr("Silicon - CaCl2 extractable", "mg/kg"), ideal_ppm.get("Si"), "CaCl2")
    add_element("NO3_N", wr("Nitrate-N - KCl extractable", "mg/kg"), ideal_ppm.get("NO3_N"), "KCl")
    add_element("NH4_N", wr("Ammonium-N - KCl extractable", "mg/kg"), ideal_ppm.get("NH4_N"), "KCl")

    # Molybdenum and cobalt are reported on two incompatible scales: an AVAILABLE
    # test (DTPA / Mehlich, comparable with the ppm target) and a TOTAL
    # ACID-EXTRACTABLE reserve (tens of ppm, two orders of magnitude larger). Using
    # the reserve against an available-test target would hide a real deficiency, so
    # the reserve is recorded but no deficit is derived from it.
    for label, sym in (("Molybdenum", "Mo"), ("Cobalt", "Co")):
        r = sample.get(label, "mg/kg")
        ideal = ideal_ppm.get(sym)
        if r is not None and any(t in (r.method or "").lower()
                                 for t in ("dtpa", "mehlich", "cacl2", "morgan")):
            add_element(sym, r.value if r.status == "ok" else None, ideal, r.method)
        else:
            reserve = r.value if (r is not None and r.status == "ok") else None
            if reserve is None:
                add_element(sym, None, ideal,
                            r.method if r is not None else "not reported in this pack")
            else:
                elements[sym] = {
                    "actual": None, "ideal": ideal, "deficit": None,
                    "kg_ha_element": None,
                    "source": r.method or "total acid extractable",
                    "status": "reserve_only", "reserve_ppm": reserve,
                }

    return SoilAnalysis(
        sample=sample, sample_id=sample.sample_id, tec=tec, cec_measured=cec_measured,
        ph=ph, ec=ec, organic_c=organic_c, organic_matter=organic_matter,
        texture=texture, colour=colour, paramagnetism=paramag,
        cations=cations, ratios=ratios,
        ratio_ideals={"Ca_Mg_label": ca_mg_label},
        elements=elements, bs_band=band, ppm_to_kgha=ppm_to_kgha,
        factor_detail=factor_detail, warnings=warnings,
    )
