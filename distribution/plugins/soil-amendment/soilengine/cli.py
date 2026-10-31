"""Command line interface: one certificate of analysis in, analysis and draft out.

    python -m soilengine.cli <coa.csv> [options]

The plugin path calls the library directly and returns JSON; this CLI exists for
batch runs, testing, and human inspection.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import profile as prof
from .eal import read_coa
from .physical import parse_depth_cm, bulk_density_for_texture
from .recommend import Context, recommend
from .report import render
from .soil import analyse_sample


def build_parser():
    p = argparse.ArgumentParser(
        prog="soil-amendment",
        description="Read an EAL certificate of analysis and produce a soil amendment "
                    "program.")
    p.add_argument("coa", help="path to an EAL certificate of analysis CSV")
    p.add_argument("--profile", default=prof.DEFAULT_PROFILE,
                   help=f"profile name or path (default: {prof.DEFAULT_PROFILE}). "
                        f"Available: {', '.join(prof.list_profiles()) or 'none'}")
    p.add_argument("--crop", default="", help="crop, free text")
    p.add_argument("--crop-class", default="generic",
                   choices=["generic", "high_k", "low_k"],
                   help="crop class; 'high_k' lifts the potassium base-saturation target")
    p.add_argument("--system", default="conventional",
                   choices=["conventional", "regenerative", "organic", "hydroponic",
                            "biodynamic"])
    p.add_argument("--certification", default="", help="e.g. organic, biodynamic")
    p.add_argument("--legume", action="store_true", help="crop is a legume (omits nitrogen)")
    p.add_argument("--area-ha", type=float)
    p.add_argument("--fertigation", action="store_true")
    p.add_argument("--foliar", action="store_true")
    p.add_argument("--no-foliar-wettable", dest="foliar_wettable", action="store_false",
                   help="foliar equipment cannot handle wettable powders (default: it can, "
                        "which is what the tool and the library assume)")
    p.add_argument("--cu-fungicide", action="store_true",
                   help="copper fungicides in use (omits copper)")
    p.add_argument("--compost", action="store_true")
    p.add_argument("--budget", action="store_true")
    p.add_argument("--factor", type=float, default=None,
                   help="override the ppm -> kg/ha factor outright, e.g. 2.5 or 2.24 to "
                        "reproduce a historical constant. Default: derived from sampling "
                        "depth and bulk density.")
    p.add_argument("--bd", type=float, default=None,
                   help="measured bulk density in t/m3 (g/cm3); overrides the texture table")
    p.add_argument("--depth-cm", type=float, default=None,
                   help="sampling depth in cm; overrides the value on the report")
    p.add_argument("--sample", type=int, default=None,
                   help="1-based sample index; default is all samples")
    p.add_argument("--json", action="store_true", help="emit JSON instead of markdown")
    p.add_argument("--out", default=None, help="write output files into this directory")
    p.add_argument("--list-profiles", action="store_true")
    p.add_argument("--inspect", action="store_true",
                   help="print the parsed test without producing a program")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)

    if args.list_profiles:
        for name in prof.list_profiles():
            pr = prof.load_profile(name)
            print(f"{name:<20} {pr.label}")
        return 0

    # A human at a terminal may point at their own file; the tool's `profile` argument may not
    # (the internal security audit A19-PLUG-3).
    profile = prof.load_profile(args.profile, allow_path=True)
    for w in profile.warnings:
        print(f"!! {w}", file=sys.stderr)
    if not profile.raw:
        return 2

    coa = read_coa(args.coa)

    if coa.test_type == "plant":
        print(f"!! {os.path.basename(args.coa)} is a plant tissue test, not a soil test. "
              "This engine handles soil tests only.", file=sys.stderr)
        return 2

    ctx = Context(
        crop=args.crop, crop_class=args.crop_class, production_system=args.system,
        certification=args.certification, is_legume=args.legume, area_ha=args.area_ha,
        has_fertigation=args.fertigation, has_foliar=args.foliar,
        foliar_handles_wettable=args.foliar_wettable,
        copper_fungicide_history=args.cu_fungicide,
        compost_available=args.compost, budget_constrained=args.budget,
    )

    selected = coa.samples
    if args.sample is not None:
        if not 1 <= args.sample <= len(coa.samples):
            print(f"cli: --sample has to be between 1 and {len(coa.samples)}", file=sys.stderr)
            return 2
        selected = [coa.samples[args.sample - 1]]

    results = []
    for s in selected:
        a = analyse_sample(s, profile, crop_class=ctx.crop_class,
                           ppm_to_kgha=args.factor, override_bd=args.bd,
                           override_depth_cm=args.depth_cm)
        if args.inspect:
            results.append((a, None, None))
        else:
            rec = recommend(a, ctx, profile)
            results.append((a, rec, render(a, rec, coa, profile)))

    if args.out:
        os.makedirs(args.out, exist_ok=True)
        for a, rec, md in results:
            safe = "".join(c if c.isalnum() or c in "-_ " else "_"
                           for c in a.sample_id).strip().replace(" ", "_") or "sample"
            stem = os.path.join(args.out, f"{coa.job or 'coa'}_{safe}")
            # `--inspect` has neither a recommendation nor a rendered report: it prints the
            # parsed analysis and writes nothing, rather than writing "None" into a file
            # (the internal audit PLUG-16).
            if rec is None or md is None:
                print(f"inspected {a.sample_id}: nothing to write (--inspect prints only)")
                continue
            # A recommendation names the client, their blocks and their rates, so the report is
            # written 0600 rather than at the process umask: a bare `open(..., "w")` under the
            # default umask left a customer's soil report world-readable, which is how the one on
            # this machine got that way (the internal security audit A19-DATA-5).
            for suffix, text in ((".md", md), (".json", json.dumps(rec.to_dict(), indent=1, default=str))):
                descriptor = os.open(stem + suffix, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(descriptor, "w", encoding="utf-8") as fh:
                    fh.write(text)
            print(f"wrote {stem}.md and .json")
        return 0

    if args.json:
        payload = []
        for a, rec, _ in results:
            entry = {"sample": a.sample_id, "test_type": coa.test_type}
            if rec is not None:
                entry["recommendation"] = rec.to_dict()
            payload.append(entry)
        print(json.dumps(payload, indent=1, default=str))
        return 0

    for a, rec, md in results:
        if args.inspect:
            print(json.dumps({
                "sample": a.sample_id, "texture": a.texture, "tec": a.tec,
                "ph": a.ph, "factor": a.ppm_to_kgha,
                "base_saturation": {e: a.cations[e].bs_pct for e in a.cations},
                "elements": {k: v.get("actual") for k, v in a.elements.items()},
            }, indent=1, default=str))
        else:
            print(md)
            print("\n" + "=" * 100 + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
