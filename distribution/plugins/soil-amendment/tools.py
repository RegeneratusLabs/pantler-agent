"""Tool handlers.

Design note: this layer contains NO agronomic logic. It resolves arguments, calls the
engine, and returns JSON. Everything numeric comes from soilengine, so the language
model receives calculated values and cannot substitute its own.
"""
from __future__ import annotations

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from soilengine import profile as prof                    # noqa: E402
from soilengine.eal import CoATooLarge, read_coa            # noqa: E402
from soilengine.recommend import Context, recommend         # noqa: E402
from soilengine.report import render                        # noqa: E402
from soilengine.soil import analyse_sample                  # noqa: E402

_CTX = None


CAPABILITY_KEY = "capability_enabled"

#: The largest tool result this plugin will put in a transcript. The reader caps its own inputs;
#: this caps what is rendered *after* them, because a certificate inside those caps can still be
#: wide enough that one answer is hundreds of megabytes in the model's context — the audit measured
#: 226 MB (the internal security audit A19-PLUG-7). Normal answers are tens of kilobytes.
MAX_RESULT_CHARS = 2_000_000


def _fail(message: str, **extra) -> str:
    payload = {"success": False, "error": message}
    payload.update(extra)
    return json.dumps(payload, default=str)


def _setting(key: str, default=None):
    """One key of this plugin's own config, read the way the engine exposes it."""
    ctx = _CTX
    getter = getattr(ctx, "get_config", None)
    if callable(getter):
        try:
            return getter(key, default)
        except TypeError:
            pass
        except Exception:
            return default
        try:
            block = getter()
        except Exception:
            block = None
        if isinstance(block, dict):
            return block.get(key, default)
    block = getattr(ctx, "config", None)
    if isinstance(block, dict):
        return block.get(key, default)
    return default


def _switched_off() -> str | None:
    """The refusal when this capability is off, or None when it may act.

    The engine's plugin list is restart-grade ("there is no un-wire primitive"), so the live
    half of the switch is this key, read on every call — otherwise a tool registered before the
    switch stays callable in a conversation that is already open.
    """
    value = _setting(CAPABILITY_KEY, True)
    if value is False or (isinstance(value, str) and value.strip().lower() in ("false", "off", "no")):
        return _fail(
            "Soil amendment is switched off in Capabilities. "
            "Switch it back on there and ask me again."
        )
    return None


def _resolve_profile(params: dict):
    """The model's argument (a name), then the operator's setting, then the packaged default.

    A model-supplied `profile` is resolved by *name* inside the plugin's own `profiles/`
    directory, never as a path: the profile is where the annual application ceilings live, so a
    path the model chooses is the ceiling check gone (the internal security audit
    A19-PLUG-3). The operator's configured value may still be a path — that setting is theirs.
    """
    named = str(params.get("profile") or "").strip()
    if named:
        return prof.load_profile(named)
    configured = _setting("profile")
    return prof.load_profile(
        str(configured).strip() if configured else None, allow_path=True
    )


def _select_samples(coa, params: dict):
    """`(samples, error)` — the sample the caller named, or every one when they named none.

    The read-only tool used to index the list directly, so `sample: 0` returned the *last* sample
    and `-1` the second-to-last, silently answering about a sample nobody asked for. Both tools
    share this validation now (the internal security audit A19-PLUG-10).
    """
    if params.get("sample") is None:
        return coa.samples, None
    wanted, error = _number(params.get("sample"), name="sample", minimum=1)
    if error:
        return None, error
    index = int(wanted) if wanted is not None else 0
    if index < 1 or index > len(coa.samples):
        # A negative index used to select from the end of the list without saying so.
        return None, (
            f"sample has to be between 1 and {len(coa.samples)}, got {params.get('sample')!r}"
        )
    return [coa.samples[index - 1]], None


def _capped_result(payload: dict) -> str:
    """The tool's JSON, or a refusal that names the size when one answer would be too large."""
    text = json.dumps(payload, default=str)
    if len(text) > MAX_RESULT_CHARS:
        return _fail(
            f"that answer came to {len(text):,} characters, more than the "
            f"{MAX_RESULT_CHARS:,} I will put in a transcript. Ask for one sample at a time "
            f"(pass `sample`) and I will answer that."
        )
    return text


def _context_from(params: dict) -> Context:
    return Context(
        crop=params.get("crop", "") or "",
        crop_class=params.get("crop_class", "generic") or "generic",
        production_system=params.get("production_system", "conventional") or "conventional",
        certification=params.get("certification", "") or "",
        is_legume=bool(params.get("is_legume", False)),
        area_ha=params.get("area_ha"),
        foliar_handles_wettable=params.get("foliar_handles_wettable", True),
        copper_fungicide_history=bool(params.get("copper_fungicide_history", False)),
        budget_constrained=bool(params.get("budget_constrained", False)),
    )


def _analysis_summary(a) -> dict:
    fd = a.factor_detail or {}
    return {
        "sample_id": a.sample_id,
        "texture": a.texture,
        "colour": a.colour,
        "ph": a.ph,
        "ec_ds_m": a.ec,
        "exchange_capacity_cmol_kg": a.tec,
        "cation_sum_cmol_kg": a.cec_measured,
        "organic_carbon_pct": a.organic_c,
        "organic_matter_pct": a.organic_matter,
        "paramagnetism": a.paramagnetism,
        "sampling_depth_cm": fd.get("depth_cm"),
        "sampling_depth_is_explicit": fd.get("depth_is_explicit"),
        "bulk_density_t_m3": fd.get("bulk_density"),
        "bulk_density_is_default": fd.get("bulk_density_is_default"),
        "ppm_to_kgha_factor": a.ppm_to_kgha,
        "ppm_to_kgha_source": fd.get("source"),
        "base_saturation_target_band": (a.bs_band or {}).get("ca_mg_label"),
        "cations": {
            e: {
                "ppm": c.ppm, "meq_per_100g": c.meq,
                "base_saturation_pct": round(c.bs_pct, 2) if c.bs_pct is not None else None,
                "base_saturation_pct_reported": c.bs_pct_lab,
                "target_base_saturation_max_pct": c.ideal_bs_max,
                "target_ppm_max": (round(c.ideal_ppm_max, 1)
                                   if c.ideal_ppm_max is not None else None),
            }
            for e, c in a.cations.items()
        },
        "ratios": {k: (round(v, 3) if isinstance(v, float) else v)
                   for k, v in a.ratios.items()},
        "elements": {
            k: {kk: (round(vv, 4) if isinstance(vv, float) else vv)
                for kk, vv in v.items()}
            for k, v in a.elements.items()
        },
        "data_quality_notes": a.warnings,
    }


def _code_text_map(rec, profile) -> dict:
    """Every rule code that fired, with the wording a narrative layer should use."""
    out: dict[str, str] = {}
    for f in rec.flags + rec.ratio_flags:
        out[f["code"]] = f["text"]
    for am in rec.amendments:
        for code in am.rule_codes:
            if code in out:
                continue
            text = profile.message(code) if profile is not None else None
            if text:
                out[code] = text
            else:
                # No profile wording for the code; the amendment notes carry the reason.
                out[code] = "; ".join(n for n in am.notes if n) or \
                    f"{am.element}: {am.product} required for this element."
    return out


def _number(value, *, name: str, minimum: float, maximum: float | None = None):
    """A finite number in range, or a sentence saying why not. (value, error)."""
    if value is None:
        return None, None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        try:
            value = float(value)
        except (TypeError, ValueError):
            return None, f"{name} has to be a number, got {value!r}"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None, f"{name} has to be a number, got {value!r}"
    if number != number or number in (float("inf"), float("-inf")):
        return None, f"{name} has to be a real number, got {value!r}"
    if number < minimum:
        return None, f"{name} has to be at least {minimum:g}, got {number:g}"
    if maximum is not None and number > maximum:
        return None, f"{name} has to be at most {maximum:g}, got {number:g}"
    return number, None


def soil_amendment(params: dict, **kwargs) -> str:
    if (refusal := _switched_off()) is not None:
        return refusal
    path = params.get("coa_path")
    if not path:
        return _fail("coa_path is required")
    if not os.path.isfile(path):
        # The basename, not the path: this sentence reaches the transcript, and an absolute path
        # there is a file-existence oracle for model-chosen paths
        # (the internal security audit A19-PLUG-12).
        return _fail(f"no such file: {os.path.basename(str(path))}")

    try:
        profile = _resolve_profile(params)
    except (OSError, ValueError) as exc:
        return _fail(f"could not read the profile: {exc}")
    if not profile.raw:
        return _fail("; ".join(profile.warnings) or "profile could not be loaded")

    try:
        coa = read_coa(path)
    except CoATooLarge as exc:
        # A named refusal, not "could not parse": the count is the useful half
        # (the internal security audit A19-PLUG-7).
        return _fail(str(exc))
    except Exception as exc:  # noqa: BLE001
        return _fail(f"could not parse certificate of analysis: {exc}")

    if coa.test_type == "plant":
        return _fail(
            "this is a plant tissue test, not a soil test; the soil amendment tool "
            "handles soil tests only")

    overrides: dict[str, float | None] = {}
    for key, minimum, maximum, label in (
        ("factor", 0.1, 100.0, "factor"),
        ("bulk_density", 0.2, 2.5, "bulk_density"),
        ("depth_cm", 2.0, 200.0, "depth_cm"),
        ("area_ha", 0.0001, 1_000_000.0, "area_ha"),
    ):
        number, error = _number(params.get(key), name=label, minimum=minimum, maximum=maximum)
        if error:
            return _fail(error)
        overrides[key] = number

    ctx = _context_from(params)
    if overrides["area_ha"] is not None:
        ctx.area_ha = overrides["area_ha"]
    selected, error = _select_samples(coa, params)
    if error:
        return _fail(error)

    results = []
    for s in selected:
        a = analyse_sample(s, profile, crop_class=ctx.crop_class,
                           ppm_to_kgha=overrides["factor"],
                           override_bd=overrides["bulk_density"],
                           override_depth_cm=overrides["depth_cm"])
        rec = recommend(a, ctx, profile)
        entry = {
            "sample_id": a.sample_id,
            "analysis": _analysis_summary(a),
            "recommendation": rec.to_dict(),
            "rule_codes": rec.codes(),
            "rule_text": _code_text_map(rec, profile),
        }
        results.append(entry)

    return _capped_result({
        "success": True,
        "profile": profile.name,
        "job": coa.job,
        "pack_code": coa.pack_code,
        "test_type": coa.test_type,
        "samples": results,
        "instructions": (
            "All figures are calculated. Do not recalculate, adjust or estimate any rate. "
            "Write the narrative from these numbers and from rule_text. Amendment rates are "
            "the calculated soil requirement with annual ceilings already applied; they are "
            "not an application schedule. The order of the program matters: phosphorus "
            "before calcium, with calcium supplied by an earlier input deducted."
        ),
    })


def soil_test_read(params: dict, **kwargs) -> str:
    if (refusal := _switched_off()) is not None:
        return refusal
    path = params.get("coa_path")
    if not path:
        return _fail("coa_path is required")
    if not os.path.isfile(path):
        return _fail(f"no such file: {os.path.basename(str(path))}")

    try:
        profile = _resolve_profile(params)
    except (OSError, ValueError) as exc:
        return _fail(f"could not read the profile: {exc}")
    try:
        coa = read_coa(path)
    except CoATooLarge as exc:
        return _fail(str(exc))
    except Exception as exc:  # noqa: BLE001
        return _fail(f"could not parse certificate of analysis: {exc}")

    selected, error = _select_samples(coa, params)
    if error:
        return _fail(error)

    samples = []
    for s in selected:
        a = analyse_sample(s, profile)
        samples.append({
            "sample_id": s.sample_id,
            "metadata": dict(s.meta),
            "analysis": _analysis_summary(a),
            "parameters_reported": sorted({p for (p, _u) in s.results}),
        })

    return _capped_result({
        "success": True,
        "job": coa.job,
        "pack_code": coa.pack_code,
        "test_type": coa.test_type,
        "warnings": coa.warnings,
        "samples": samples,
    })
