"""The amendment algorithm, as code.

Five steps, in this order:

    Step 1  Phosphorus
    Step 2  Magnesium
    Step 3  Calcium      - NET of the calcium already supplied in steps 1 and 2
    Step 4  Nitrogen, potassium, sulfur
    Step 5  Trace elements

Two rules that a language model will not infer and that must never be skipped:

  * **Phosphorus must be calculated before calcium.** A combined phosphorus and
    calcium source (soft rock phosphate) carries roughly 20% calcium, so calculating
    calcium first and then phosphorus over-applies calcium. The calcium requirement
    in step 3 is netted against what steps 1 and 2 already supply.
  * **Total calcium from all forms is capped for the year.** Anything above the cap
    is deferred, reported, and never silently dropped.

The engine emits rule CODES plus the numbers. It does not write prose: the wording
for each code comes from the active profile, and the narrative that reaches a reader
is written by the language model on top. That is what keeps the arithmetic out of the
model's hands.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

from . import physical
from .soil import SoilAnalysis


@dataclass
class Context:
    """Site context that changes the answer but is not in the laboratory report."""
    crop: str = ""
    crop_class: str = "generic"          # 'generic' | 'high_k' | 'low_k'
    production_system: str = "conventional"
    is_legume: bool = False
    area_ha: float | None = None
    has_fertigation: bool = False
    has_foliar: bool = False
    foliar_handles_wettable: bool = True
    copper_fungicide_history: bool = False
    compost_available: bool = False
    budget_constrained: bool = False
    certification: str = ""              # e.g. 'organic', 'biodynamic'


@dataclass
class Amendment:
    """One product line in the amendment program."""
    step: int
    product: str
    element: str
    element_pct: float
    deficit_ppm: float
    element_kg_ha: float
    product_kg_ha: float
    product_kg_ha_uncapped: float
    capped: bool
    ca_ppm_supplied: float = 0.0
    s_ppm_supplied: float = 0.0
    deferred_ppm: float = 0.0
    rule_codes: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class Recommendation:
    sample_id: str
    profile: str
    amendments: list[Amendment]
    element_requirements: dict[str, dict]
    flags: list[dict]
    ratio_flags: list[dict]
    context: Context
    assumptions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def codes(self) -> list[str]:
        """Every rule code that fired, for a narrative layer to work from."""
        out = [c for am in self.amendments for c in am.rule_codes]
        out += [f["code"] for f in self.flags]
        out += [f["code"] for f in self.ratio_flags]
        return sorted(set(out))


def _rate(element_ppm: float, pct: float, factor: float) -> tuple[float, float]:
    """(element kg/ha, product kg/ha) for a required ppm of an element."""
    element_kg = element_ppm * factor
    product_kg = element_kg / (pct / 100.0) if pct else 0.0
    return element_kg, product_kg


def _selected_products(sel: dict) -> list[str]:
    """Every product named anywhere in `product_selections`.

    The structure is nested — `phosphorus.with_calcium_need`, `calcium.high_ph`, `trace.Cu` — so
    the walk is recursive and picks up `product` keys only. These are the products the profile
    itself chooses, and therefore the set it has to carry an annual ceiling for
    (the internal security audit A19-PLUG-3).
    """
    found: list[str] = []

    def walk(node) -> None:
        if isinstance(node, dict):
            product = node.get("product")
            if isinstance(product, str) and product.strip():
                found.append(product.strip())
            for value in node.values():
                walk(value)
        elif isinstance(node, (list, tuple)):
            for value in node:
                walk(value)

    walk(sel)
    return found


def _missing_ceiling_text(product: str) -> str:
    return (
        f"{product} is named in this profile's product_selections but has no max_kg_ha_yr "
        f"entry, so its rate is held at 0 kg/ha rather than applied without a ceiling. Add the "
        f"ceiling to the profile and ask again."
    )


def recommend(a: SoilAnalysis, ctx: Context | None = None, profile=None,
              factor: float | None = None) -> Recommendation:
    ctx = ctx or Context()
    factor = a.ppm_to_kgha if factor is None else factor

    amendments: list[Amendment] = []
    flags: list[dict] = []
    ratio_flags: list[dict] = []

    el = a.elements
    cat = a.cations
    ph = a.ph
    tec = a.tec
    t = profile.thresholds if profile is not None else {}
    sel = profile.selections if profile is not None else {}
    max_rates = profile.max_rates if profile is not None else {}
    max_ca_ppm = (profile.get("max_ca_ppm_per_year", 800.0)
                  if profile is not None else 800.0)
    ideal_ppm = profile.ideal_ppm if profile is not None else {}

    def msg(code: str, fallback: str = "") -> str:
        return (profile.message(code) if profile is not None else None) or fallback

    def flag(code: str, severity: str, text: str | None = None, **fmt):
        body = text if text is not None else msg(code)
        if fmt and body:
            try:
                body = body.format(**fmt)
            except (KeyError, IndexError):
                pass
        flags.append({"code": code, "severity": severity, "text": body or code})

    # ---------------------------------------------------------------- deficits
    def cation_deficit(el_name: str) -> float:
        c = cat[el_name]
        if c.ideal_ppm_max is None or c.ppm is None:
            return 0.0
        return max(0.0, c.ideal_ppm_max - c.ppm)

    #: Product → kg/ha this program has already committed. One product can serve two steps —
    #: gypsum is the high-pH calcium source *and* the sulfur source — and capping each line
    #: against the full annual maximum let the two add up past it: 2000 + 217.5 kg/ha against a
    #: 2000 kg/ha ceiling, which the per-line test could not see
    #: (the internal audit PLUG-6).
    used: dict[str, float] = {}

    # A product with no `max_kg_ha_yr` entry used to be treated as if its ceiling were 1e9 kg/ha,
    # which is no ceiling at all: the audit's crafted sample asked for 10,227,978 kg/ha of MAP and
    # the result still said the annual ceilings had been applied
    # (the internal security audit A19-PLUG-3). Every product the profile itself names has
    # to carry a ceiling, and a missing one is named here — once per product, not once per line,
    # because gypsum can be the calcium source and the sulfur source in one program.
    for product in dict.fromkeys(_selected_products(sel)):
        if product not in max_rates:
            flag("ceiling_missing", "action", _missing_ceiling_text(product))

    def apply_cap(product: str, rate: float) -> tuple[float, bool, float]:
        """The rate the year may still take of `product`, whether that capped it, and the ceiling.

        A product with no ceiling entry is held at zero — the safe direction, and the one that
        makes the sentence about applied ceilings true (the internal security audit
        A19-PLUG-3). The flag raised above says which product and why.
        """
        entry = max_rates.get(product)
        ceiling = float(entry[1]) if entry and entry[1] is not None else 0.0
        remaining = max(0.0, ceiling - used.get(product, 0.0))
        final = min(rate, remaining)
        used[product] = used.get(product, 0.0) + final
        return final, rate > remaining, ceiling

    ca_def_ppm = cation_deficit("Ca")
    mg_def_ppm = cation_deficit("Mg")
    k_def_ppm = cation_deficit("K")
    ca_supplied_ppm = 0.0

    # ================================================================ STEP 1 - P
    p = sel.get("phosphorus", {})
    p_def = el.get("P", {}).get("deficit") or 0.0
    if p_def > 0:
        pick = (p.get("with_calcium_need") if ca_def_ppm > 0 else p.get("without_calcium"))
        if pick:
            prod, pct = pick["product"], float(pick["element_pct"])
            e_kg, wanted = _rate(p_def, pct, factor)
            pr, capped, cap = apply_cap(prod, wanted)
            ca_from = pr * float(pick.get("ca_pct", 0.0)) / 100.0
            ca_supplied_ppm += ca_from / factor
            amendments.append(Amendment(
                step=1, product=prod, element="P", element_pct=pct,
                deficit_ppm=p_def, element_kg_ha=p_def * factor,
                product_kg_ha=pr, product_kg_ha_uncapped=e_kg / (pct / 100.0),
                capped=capped,
                ca_ppm_supplied=ca_from / factor,
                rule_codes=["p_from_combined_source" if ca_def_ppm > 0
                            else "p_from_fast_release"] + (["rate_capped"] if capped else []),
                notes=[pick.get("note", "")] + (
                    [f"Capped at the {cap:.0f} kg/ha/yr maximum."] if capped else []),
            ))

    # ================================================================ STEP 2 - Mg
    mg = sel.get("magnesium", {})
    mg_excess = (cat["Mg"].bs_pct is not None and cat["Mg"].ideal_bs_max is not None
                 and cat["Mg"].bs_pct > cat["Mg"].ideal_bs_max)
    alkaline = ph is not None and ph > t.get("ph_use_gypsum_above", 7.0)

    if mg_def_ppm > 0 and not alkaline:
        pick = (mg.get("with_calcium_need") if ca_def_ppm > 0
                else mg.get("without_calcium"))
        if pick:
            prod, pct = pick["product"], float(pick["element_pct"])
            e_kg, wanted = _rate(mg_def_ppm, pct, factor)
            pr, capped, cap = apply_cap(prod, wanted)
            ca_from = pr * float(pick.get("ca_pct", 0.0)) / 100.0
            ca_supplied_ppm += ca_from / factor
            amendments.append(Amendment(
                step=2, product=prod, element="Mg", element_pct=pct,
                deficit_ppm=mg_def_ppm, element_kg_ha=mg_def_ppm * factor,
                product_kg_ha=pr, product_kg_ha_uncapped=e_kg / (pct / 100.0),
                capped=capped, ca_ppm_supplied=ca_from / factor,
                rule_codes=["mg_from_combined_source" if ca_def_ppm > 0
                            else "mg_from_high_analysis"] + (["rate_capped"] if capped else []),
                notes=[pick.get("note", "")] + (
                    [f"Capped at {cap:.0f} kg/ha/yr."] if capped else []),
            ))
    elif mg_def_ppm > 0 and alkaline:
        flag("mg_deficit_needs_ph_check", "warn")
        flag("mg_alkalising", "warn")
    elif mg_excess:
        if cat["Ca"].bs_pct is not None and cat["Ca"].bs_pct < 60:
            flag("mg_excess_with_low_ca", "action")
        else:
            flag("mg_excess", "warn")

    # ================================================================ STEP 3 - Ca
    ca_remaining = max(0.0, ca_def_ppm - ca_supplied_ppm)
    ca_sel = sel.get("calcium", {})
    if ca_remaining > 1e-4:
        pick = ca_sel.get("high_ph" if alkaline else "low_ph")
        if pick:
            prod, pct = pick["product"], float(pick["element_pct"])
            s_from_calcium_pct = float(pick.get("s_pct", 0.0))
            notes = [pick.get("note", "")] + [msg("ordering")]
            codes = ["ca_from_gypsum" if alkaline else "ca_from_lime"]
            if ca_supplied_ppm > 0.5:
                notes.append(f"{msg('ca_netted')} ({ca_supplied_ppm:.0f} ppm Ca from "
                             "earlier inputs)")

            addressed, deferred, ca_capped_flag = ca_remaining, 0.0, False
            total_ca = ca_supplied_ppm + ca_remaining
            if total_ca > max_ca_ppm:
                addressed = max(0.0, max_ca_ppm - ca_supplied_ppm)
                deferred = ca_remaining - addressed
                ca_capped_flag = True
                flag("ca_annual_ceiling", "warn", **{
                    "total": f"{total_ca:.0f}", "addressed": f"{addressed:.0f}",
                    "deferred": f"{deferred:.0f}", "ceiling": f"{max_ca_ppm:.0f}"})
                codes.append("ca_annual_ceiling")
            e_kg, wanted = _rate(addressed, pct, factor)
            pr, rate_capped, cap = apply_cap(prod, wanted)
            if rate_capped:
                addressed = pr * (pct / 100.0) / factor
                deferred += wanted * (pct / 100.0) / factor - addressed
                flag("ca_max_rate", "warn")
                codes.append("ca_max_rate")
            if deferred > 0.5:
                codes.append("ca_deferred")
                notes.append(f"{deferred:.0f} ppm of the calcium requirement is deferred "
                             "to future seasons.")
            amendments.append(Amendment(
                step=3, product=prod, element="Ca", element_pct=pct,
                deficit_ppm=addressed, element_kg_ha=addressed * factor,
                product_kg_ha=pr, product_kg_ha_uncapped=e_kg / (pct / 100.0),
                capped=rate_capped or ca_capped_flag, deferred_ppm=deferred,
                ca_ppm_supplied=addressed,
                # Gypsum is 15% sulfur: the sulfur step nets against what every earlier input
                # brought, and this one used to bring nothing as far as it could see.
                s_ppm_supplied=(addressed * factor / (pct / 100.0) * s_from_calcium_pct / 100.0
                                / factor) if pct else 0.0,
                rule_codes=codes, notes=notes,
            ))
    elif ca_def_ppm > 0:
        amendments.append(Amendment(
            step=3, product="(none)", element="Ca", element_pct=0.0,
            deficit_ppm=ca_def_ppm, element_kg_ha=0.0, product_kg_ha=0.0,
            product_kg_ha_uncapped=0.0, capped=False,
            ca_ppm_supplied=ca_supplied_ppm,
            rule_codes=["ca_covered_by_earlier_inputs"],
            notes=[f"The calcium requirement ({ca_def_ppm:.0f} ppm) is fully covered by "
                   f"{ca_supplied_ppm:.0f} ppm of calcium supplied by the phosphorus and "
                   "magnesium inputs. No separate calcium input is required this season."],
        ))

    if cat["Ca"].bs_pct is not None and cat["Ca"].bs_pct > t.get("ca_bs_crowded", 80.0):
        flag("ca_excess_crowding", "warn")

    # ================================================================ STEP 4 - N,K,S
    if k_def_ppm > 0:
        pick = sel.get("potassium", {})
        prod = pick.get("product", "Potassium sulfate")
        pct = float(pick.get("element_pct", 42.0))
        e_kg, wanted = _rate(k_def_ppm, pct, factor)
        uncapped = wanted
        pr, capped, cap = apply_cap(prod, wanted)
        notes = [pick.get("note", "")]
        codes = ["k_from_sulfate"]
        crowded = (cat["Ca"].bs_pct is not None and cat["Mg"].bs_pct is not None
                   and cat["Ca"].bs_pct + cat["Mg"].bs_pct > 85)
        if crowded:
            codes.append("k_colloid_crowded")
            flag("k_colloid_crowded", "warn")
        if capped:
            notes.append("The full deficit is far above the maximum annual application "
                         "rate, so it is split across seasons rather than applied at once.")
            flag("k_split_across_seasons", "warn")
            codes.append("k_split_across_seasons")
            # `pr` is already the clamped rate — `apply_cap` sets it to what the *year* has left
            # of this product, not to the product's ceiling. Restoring `cap` here put the full
            # ceiling back and let a second line of the same product take it again.
        amendments.append(Amendment(
            step=4, product=prod, element="K", element_pct=pct,
            deficit_ppm=k_def_ppm, element_kg_ha=k_def_ppm * factor,
            product_kg_ha=pr, product_kg_ha_uncapped=uncapped,
            capped=capped, rule_codes=codes, notes=notes,
        ))

    no3_def = el.get("NO3_N", {}).get("deficit") or 0.0
    nh4_def = el.get("NH4_N", {}).get("deficit") or 0.0
    n_def = no3_def + nh4_def
    if n_def > 0:
        if ctx.is_legume:
            flag("legume_omit_n", "info")
        else:
            pick = sel.get("nitrogen", {})
            prod = pick.get("product", "Ammonium sulfate")
            pct = float(pick.get("element_pct", 21.0))
            s_pct = float(pick.get("s_pct", 0.0))
            e_kg, wanted = _rate(n_def, pct, factor)
            pr, capped, cap = apply_cap(prod, wanted)
            s_supplied = pr * s_pct / 100.0 / factor
            amendments.append(Amendment(
                step=4, product=prod, element="N", element_pct=pct,
                deficit_ppm=n_def, element_kg_ha=n_def * factor,
                product_kg_ha=pr, product_kg_ha_uncapped=e_kg / (pct / 100.0),
                capped=capped, s_ppm_supplied=s_supplied,
                rule_codes=["n_from_ammonium_sulfate"] + (["rate_capped"] if capped else []),
                notes=[pick.get("note", ""),
                       "The nitrogen requirement is the sum of the nitrate and ammonium "
                       "deficits, which the report carries as separate targets."],
            ))

    s_def = el.get("S", {}).get("deficit") or 0.0
    s_supplied = sum(x.s_ppm_supplied for x in amendments)
    s_remaining = max(0.0, s_def - s_supplied)
    if s_remaining > 0.5:
        pick = sel.get("sulfur", {})
        prod = pick.get("product", "Gypsum")
        pct = float(pick.get("element_pct", 15.0))
        e_kg, wanted = _rate(s_remaining, pct, factor)
        pr, capped, cap = apply_cap(prod, wanted)
        # Recorded so the year's calcium total can see it: gypsum supplies calcium as well as
        # sulfur, and a program already at the calcium ceiling takes this on top
        # (the internal audit PLUG-7).
        ca_from_sulfur = pr * float(pick.get("ca_pct", 0.0)) / 100.0 / factor
        amendments.append(Amendment(
            step=4, product=prod, element="S", element_pct=pct,
            deficit_ppm=s_remaining, element_kg_ha=s_remaining * factor,
            product_kg_ha=pr, product_kg_ha_uncapped=e_kg / (pct / 100.0),
            capped=capped, ca_ppm_supplied=ca_from_sulfur,
            rule_codes=["s_from_gypsum"] + (["rate_capped"] if capped else []),
            notes=[pick.get("note", ""), "Netted against sulfur supplied by the nitrogen "
                                         "input, where one was used."],
        ))

    # ================================================================ STEP 5 - traces
    for sym, pick in (sel.get("trace", {}) or {}).items():
        d = el.get(sym, {})
        if not d.get("deficit"):
            continue
        if sym == "Cu" and ctx.copper_fungicide_history:
            flag("copper_history", "info")
            continue
        prod = pick.get("product")
        if not prod:
            continue
        pct = float(pick.get("element_pct", 0.0))
        e_kg, wanted = _rate(d["deficit"], pct, factor)
        pr, capped, cap = apply_cap(prod, wanted)
        notes = [pick.get("note", "")] if pick.get("note") else []
        if capped:
            notes.append(f"Maximum {cap:.0f} kg/ha/yr of {prod}. One maximum application "
                         f"raises the level by roughly {cap * pct / 100.0 / factor:.1f} ppm, "
                         "so the full deficit takes more than one season.")
        amendments.append(Amendment(
            step=5, product=prod, element=sym, element_pct=pct,
            deficit_ppm=d["deficit"], element_kg_ha=d["deficit"] * factor,
            product_kg_ha=pr, product_kg_ha_uncapped=e_kg / (pct / 100.0),
            capped=capped, rule_codes=[f"trace_{sym.lower()}"] + (["rate_capped"] if capped else []),
            notes=notes,
        ))

    # Si has a target but typically no discrete product (supplied as an amendment).
    if (el.get("Si", {}).get("deficit") or 0) and "Si" not in (sel.get("trace", {}) or {}):
        flag("silicon_no_product", "info")

    # ============================================== the year's calcium, as a total
    #
    # The ceiling is a total over every form of calcium, and it has to be checked once the
    # program is complete: gypsum appears twice in a high-pH program — as the calcium source and
    # as the sulfur source — and a check that only looked at the calcium step let the two
    # together pass 800 ppm (818.7 in the audit's synthetic sample,
    # the internal audit PLUG-7). Every line that supplies calcium records it in
    # `ca_ppm_supplied`, so the sum is the total.
    total_ca_ppm = sum(a.ca_ppm_supplied for a in amendments)
    if total_ca_ppm > max_ca_ppm + 0.5:
        # Trim the *calcium* line first: its requirement is the one the module already documents
        # as deferred to a later season. Only if that cannot absorb the excess do the incidental
        # contributors give some up, and each line keeps its own record consistent — the element
        # it exists for is reduced by exactly what its product rate loses.
        order = [x for x in amendments if x.element == "Ca" and x.ca_ppm_supplied > 0] + [
            x for x in amendments if x.element != "Ca" and x.ca_ppm_supplied > 0
        ]
        excess = total_ca_ppm - max_ca_ppm
        deferred = excess
        # `line`, not `a`: the analysis object is `a` throughout this function, and a loop
        # variable of that name shadows it for everything below.
        for line in order:
            if excess <= 0.5 or line.product_kg_ha <= 0:
                continue
            ca_per_kg = line.ca_ppm_supplied / line.product_kg_ha
            if ca_per_kg <= 0:
                continue
            removed_kg = min(line.product_kg_ha, excess / ca_per_kg)
            removed_ca = removed_kg * ca_per_kg
            removed_element = removed_kg * (line.element_pct / 100.0) / factor
            line.product_kg_ha = max(0.0, line.product_kg_ha - removed_kg)
            line.ca_ppm_supplied = max(0.0, line.ca_ppm_supplied - removed_ca)
            line.deficit_ppm = max(0.0, line.deficit_ppm - removed_element)
            line.element_kg_ha = max(0.0, line.element_kg_ha - removed_kg * (line.element_pct / 100.0))
            line.deferred_ppm += removed_ca
            line.capped = True
            if "ca_annual_ceiling" not in line.rule_codes:
                line.rule_codes.append("ca_annual_ceiling")
                line.rule_codes.append("ca_deferred")
            line.notes.append(
                f"{removed_ca:.0f} ppm of calcium was deferred at the {max_ca_ppm:.0f} ppm "
                f"annual ceiling, which is {removed_kg:.0f} kg/ha less {line.product}."
            )
            excess -= removed_ca
        flag("ca_program_ceiling", "warn", **{
            "total": f"{total_ca_ppm:.0f}", "addressed": f"{total_ca_ppm - deferred:.0f}",
            "deferred": f"{deferred:.0f}", "ceiling": f"{max_ca_ppm:.0f}"})

    # ================================================================ ratio checks
    def ratio_flag(code, name, actual, ideal, extra=""):
        ratio_flags.append({"code": code, "ratio": name, "actual": actual, "ideal": ideal,
                            "text": (msg(code) or code) + ((" " + extra) if extra else "")})

    tol = t.get("ratio_tolerance", 0.20)
    p_act, zn_act = el.get("P", {}).get("actual"), el.get("Zn", {}).get("actual")
    if p_act and zn_act:
        pzn = p_act / zn_act
        ideal_ratio = t.get("ppm_zn_ratio_ideal", 10.0)
        if abs(pzn - ideal_ratio) / ideal_ratio > tol:
            ratio_flag("p_zn_ratio_high" if pzn > ideal_ratio else "p_zn_ratio_low",
                       "P/Zn", round(pzn, 2), ideal_ratio)
    fe_act, mn_act = el.get("Fe", {}).get("actual"), el.get("Mn", {}).get("actual")
    if fe_act and mn_act:
        femn = fe_act / mn_act
        if femn < t.get("fe_mn_ratio_ideal", 1.1):
            ratio_flag("fe_mn_inverted", "Fe/Mn", round(femn, 2),
                       t.get("fe_mn_ratio_ideal", 1.1))
    k_act, na_act = cat["K"].ppm, cat["Na"].ppm
    if k_act and na_act and na_act > k_act:
        ratio_flag("k_na_inverted", "K/Na", round(k_act / na_act, 2),
                   t.get("k_na_ratio_ideal", 5.0))
    label = (a.bs_band or {}).get("ca_mg_label")
    if label and a.ratios.get("Ca_Mg_bs") is not None:
        try:
            ideal_ratio = float(str(label).split(":")[0])
        except (ValueError, IndexError):
            ideal_ratio = None
        if ideal_ratio and abs(a.ratios["Ca_Mg_bs"] - ideal_ratio) / ideal_ratio > tol:
            ratio_flag("ca_mg_ratio_low" if a.ratios["Ca_Mg_bs"] < ideal_ratio
                       else "ca_mg_ratio_high", "Ca/Mg (base sat)",
                       round(a.ratios["Ca_Mg_bs"], 2), ideal_ratio)

    # ================================================================ context flags
    if tec is not None and tec < t.get("tec_bs_irrelevant_below", 5.0):
        flag("tec_below_5", "info")

    fd = a.factor_detail or {}
    if fd and fd.get("depth_is_typical") is False:
        flag("depth_atypical", "action",
             depth=f"{fd.get('depth_cm'):.0f}",
             min=f"{t.get('typical_depth_min_cm', 5):.0f}",
             max=f"{t.get('typical_depth_max_cm', 30):.0f}",
             factor=f"{a.ppm_to_kgha:.2f}")
    if fd.get("depth_as_given") and not fd.get("depth_is_explicit"):
        flag("depth_unit_inferred", "warn",
             raw=fd.get("depth_raw"), depth=f"{fd.get('depth_cm'):.0f}")
    if fd.get("bulk_density_is_default"):
        flag("density_defaulted", "warn", bd=fd.get("bulk_density"))

    if ctx.certification in ("organic", "biodynamic") or \
            ctx.production_system in ("organic", "biodynamic"):
        flag("certification_check", "action")

    if ctx.has_foliar and not ctx.foliar_handles_wettable:
        flag("equipment_constraint", "action")

    om = a.organic_matter
    if om is not None and om < t.get("organic_matter_min_pct", 4.0):
        flag("organic_matter_low", "action")
    organic_c_min = t.get("organic_carbon_min_pct", 2.0)
    if a.organic_c is not None and a.organic_c < organic_c_min:
        # The profile's own minimum, which a trailing `and a.organic_c < 1.0` made unreachable
        # for every threshold at or above 1: the configured 2.0 never fired and the shipped
        # message repeated the hardcoded figure (the internal audit PLUG-10).
        flag("organic_carbon_very_low", "warn", min=f"{organic_c_min:g}")
    if a.paramagnetism is not None and a.paramagnetism < t.get("paramagnetism_min", 200.0):
        flag("paramagnetism_low", "info")
    if a.ec is not None and a.ec > t.get("ec_salinity_threshold", 0.6):
        flag("salinity_check", "warn")

    no3, nh4 = el.get("NO3_N", {}).get("actual"), el.get("NH4_N", {}).get("actual")
    if no3 and nh4 is not None and no3 > 0 and (nh4 / no3) < t.get("nh4_no3_min_ratio", 0.5):
        flag("ammonium_nitrate_imbalance", "action")

    for sym in ("Mo", "Co"):
        if el.get(sym, {}).get("status") == "reserve_only":
            flags.append({"code": "reserve_only", "severity": "info",
                          "text": (f"{sym}: " + (msg("reserve_only") or ""))})

    if ctx.budget_constrained:
        flag("budget_option", "info")

    for w in a.warnings:
        flags.append({"code": "data_quality", "severity": "warn", "text": w})

    # ================================================================ requirements
    required = {}
    for k, d in el.items():
        required[k] = {"actual_ppm": d.get("actual"), "ideal_ppm": d.get("ideal"),
                       "deficit_ppm": d.get("deficit"),
                       "element_kg_ha": d.get("kg_ha_element"),
                       "status": d.get("status")}
    for e in ("Ca", "Mg", "K"):
        c = cat[e]
        required[e] = {
            "actual_ppm": c.ppm, "ideal_ppm_max": c.ideal_ppm_max,
            "actual_bs_pct": c.bs_pct, "ideal_bs_max": c.ideal_bs_max,
            "deficit_ppm": (max(0.0, c.ideal_ppm_max - c.ppm)
                            if (c.ideal_ppm_max is not None and c.ppm is not None) else None),
        }

    fd_src = (a.factor_detail or {}).get("source")
    assumptions = [
        (f"ppm -> kg/ha factor = {factor:.3f} (operator override - not derived from the "
         "sample's physical context)" if fd_src == "operator override" else
         f"ppm -> kg/ha factor = {factor:.3f} (derived from sampling depth and soil bulk "
         "density; see the method section)"),
        "Direct application rates are the calculated soil requirement, capped at the "
        "maximum annual application for each product. They are not an application "
        "schedule.",
        msg("ordering"),
    ]

    return Recommendation(
        sample_id=a.sample_id, profile=(profile.name if profile is not None else "none"),
        amendments=amendments, element_requirements=required, flags=flags,
        ratio_flags=ratio_flags, context=ctx, assumptions=assumptions,
    )
