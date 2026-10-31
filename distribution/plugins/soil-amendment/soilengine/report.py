"""Render an analysis and recommendation to plain markdown.

This is a convenience view for a human reading the CLI output or a saved file. The
plugin path returns the structured JSON instead and lets the language model write the
narrative, which is the intended deployment.
"""
from __future__ import annotations

from .soil import SoilAnalysis
from .recommend import Recommendation


def _n(v, dp=1, dash="-"):
    if v is None:
        return dash
    if isinstance(v, float):
        return f"{v:.{dp}f}".rstrip("0").rstrip(".") if dp else f"{v:.0f}"
    return str(v)


def render(a: SoilAnalysis, rec: Recommendation, coa=None, profile=None) -> str:
    L: list[str] = []
    A = L.append

    title = profile.text("report_title", "Soil amendment recommendation") if profile else \
        "Soil amendment recommendation"
    subtitle = profile.text("report_subtitle", "") if profile else ""

    A(f"# {title} - {a.sample_id}")
    if subtitle:
        A(f"\n{subtitle}")
    if coa:
        parts = [f"job {coa.job}" if coa.job else None,
                 f"pack {coa.pack_code}" if coa.pack_code else None,
                 f"source `{coa.path.replace(chr(92), '/').split('/')[-1]}`"]
        A("\n" + " | ".join(p for p in parts if p))
    A(f"\nProfile: `{a.factor_detail.get('profile', rec.profile)}`\n")

    # ---------------- summary ----------------
    A("## 1. Test summary\n")
    A("| Item | Value |")
    A("|---|---|")
    A(f"| Crop | {rec.context.crop or '(not supplied)'} |")
    A(f"| Production system | {rec.context.production_system} |")
    A(f"| Texture / colour | {a.texture or '-'} / {a.colour or '-'} |")
    A(f"| pH (1:5 water) | {_n(a.ph, 2)} |")
    A(f"| EC | {_n(a.ec, 3)} dS/m |")
    A(f"| Total exchange capacity | {_n(a.tec, 1)} cmol+/kg |")
    A(f"| Cation sum | {_n(a.cec_measured, 2)} cmol+/kg |")
    A(f"| Organic carbon | {_n(a.organic_c, 2)} % |")
    A(f"| Organic matter | {_n(a.organic_matter, 2)} % |")
    A(f"| Paramagnetism | {_n(a.paramagnetism, 0)} |")
    fd = a.factor_detail or {}
    A(f"| Sampling depth | {_n(fd.get('depth_cm'), 0)} cm"
      f"{'' if fd.get('depth_is_explicit') else ' *(assumed)*'} |")
    A(f"| Bulk density used | {_n(fd.get('bulk_density'), 2)} t/m3"
      f"{' *(default)*' if fd.get('bulk_density_is_default') else ''} |")
    A(f"| **ppm -> kg/ha factor** | **{_n(a.ppm_to_kgha, 3)}** "
      f"({fd.get('source', 'unknown')}) |")

    # ---------------- base saturation ----------------
    A("\n## 2. Base saturation against target\n")
    band = a.bs_band
    if band:
        tmax = band.get("tec_max")
        tmax_disp = "up" if tmax is None else _n(float(tmax), 0)
        A(f"Exchange-capacity band {_n(float(band['tec_min']), 0)}-{tmax_disp} "
          f"(target Ca/Mg ratio {band.get('ca_mg_label')}).\n")
        A("| Cation | ppm | meq | BS % (calculated) | BS % (reported) | Target BS max | "
          "Target ppm max |")
        A("|---|---|---|---|---|---|---|")
        for e in ("Ca", "Mg", "K", "Na", "Al"):
            c = a.cations[e]
            A(f"| {e} | {_n(c.ppm, 0)} | {_n(c.meq, 2)} | {_n(c.bs_pct, 1)} | "
              f"{_n(c.bs_pct_lab, 1)} | {_n(c.ideal_bs_max, 1)} | {_n(c.ideal_ppm_max, 0)} |")
    else:
        A("_No exchange-capacity band matched, so base saturation targets are "
          "unavailable._")

    A("\n### Ratios\n")
    A("| Ratio | Actual | Target |")
    A("|---|---|---|")
    A(f"| Ca/Mg (base sat) | {_n(a.ratios.get('Ca_Mg_bs'), 2)} | "
      f"{band.get('ca_mg_label') if band else '-'} |")
    p_act, zn_act = a.elements.get("P", {}).get("actual"), a.elements.get("Zn", {}).get("actual")
    A(f"| P/Zn (ppm) | {_n(p_act / zn_act, 1) if (p_act and zn_act) else '-'} | 10 |")
    mg, k = a.cations["Mg"].ppm, a.cations["K"].ppm
    A(f"| Mg/K (ppm) | {_n(mg / k, 2) if (mg and k) else '-'} | 1 |")
    fe, mn_ = a.elements.get("Fe", {}).get("actual"), a.elements.get("Mn", {}).get("actual")
    A(f"| Fe/Mn (ppm) | {_n(fe / mn_, 2) if (fe and mn_) else '-'} | 1.1 |")
    na = a.cations["Na"].ppm
    A(f"| K/Na (ppm) | {_n(k / na, 2) if (k and na) else '-'} | 5 |")

    # ---------------- requirements ----------------
    A("\n## 3. Element requirements\n")
    A("| Element | Actual ppm | Target ppm | Deficit ppm | Element kg/ha | Status |")
    A("|---|---|---|---|---|---|")
    for key in ("P", "S", "Ca", "Mg", "K", "Fe", "Mn", "Cu", "Zn", "B", "Mo", "Co",
                "Si", "NO3_N", "NH4_N"):
        d = rec.element_requirements.get(key)
        if not d:
            continue
        ideal = d.get("ideal_ppm", d.get("ideal_ppm_max"))
        A(f"| {key} | {_n(d.get('actual_ppm'), 2)} | {_n(ideal, 2)} | "
          f"{_n(d.get('deficit_ppm'), 2)} | {_n(d.get('element_kg_ha'), 1)} | "
          f"{d.get('status', '-')} |")

    # ---------------- program ----------------
    A("\n## 4. Amendment program\n")
    if not rec.amendments:
        A("_No amendment inputs triggered._")
    for am in rec.amendments:
        star = " **[CAPPED]**" if am.capped else ""
        A(f"### Step {am.step}: {am.product} - {am.product_kg_ha:.0f} kg/ha{star}")
        A(f"- Element: {am.element} ({am.element_pct}%)")
        A(f"- Deficit addressed: {am.deficit_ppm:.1f} ppm = {am.element_kg_ha:.1f} kg/ha "
          f"of {am.element}")
        A(f"- Product required: {am.product_kg_ha:.0f} kg/ha "
          f"(uncapped {am.product_kg_ha_uncapped:.0f})")
        if am.ca_ppm_supplied > 0.01:
            A(f"- Calcium contributed: {am.ca_ppm_supplied:.0f} ppm")
        if am.deferred_ppm > 0.5:
            A(f"- Deferred to future seasons: {am.deferred_ppm:.0f} ppm")
        for nt in am.notes:
            if nt:
                A(f"- {nt}")
        A(f"- Rule codes: {', '.join(am.rule_codes)}")
        A("")

    # ---------------- flags ----------------
    if rec.flags:
        A("## 5. Flags and required checks\n")
        for f in rec.flags:
            A(f"- **[{f['severity'].upper()}] {f['code']}** - {f['text']}")
        A("")
    if rec.ratio_flags:
        A("## 6. Ratio imbalances\n")
        for f in rec.ratio_flags:
            A(f"- **{f['code']}** ({f['ratio']} = {f['actual']} vs target {f['ideal']}) - "
              f"{f['text']}")
        A("")

    # ---------------- method ----------------
    A("## 7. Method and assumptions\n")
    A(f"- **kg/ha conversion:** {_n(a.ppm_to_kgha, 3)} kg/ha per ppm, derived as "
      f"depth x bulk density / 10 ({_n(fd.get('depth_cm'), 0)} cm x "
      f"{_n(fd.get('bulk_density'), 2)} t/m3 / 10). Bulk density is not a constant: it "
      "falls as clay content rises, so a light sandy soil needs more product per ppm "
      "than a clay. Densities are typical for the texture class, not measured.")
    for n in fd.get("notes", []):
        A(f"  - {n}")
    for s in rec.assumptions:
        if s:
            A(f"- {s}")
    A("")
    if profile is not None:
        A(profile.text("disclaimer", ""))
    return "\n".join(L)
