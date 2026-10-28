"""Profile: every deployment-specific value, loaded from JSON.

The engine (soilengine/) contains agronomic MECHANISM and nothing vendor-specific.
Everything that a deployment would change lives in a profile:

  * the product table (names, analysis %, application ceilings)
  * which product is chosen for each situation
  * ideal soil levels and base-saturation targets
  * typical bulk density per texture class
  * the wording of warnings and notes
  * the report title and disclaimer

That split is deliberate: it keeps the shipped engine free of any one company's
product names and proprietary commentary, and it lets a deployment swap in its own
inputs without touching code.

JSON rather than YAML so the whole package stays dependency-free (stdlib only).
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PROFILE_DIR = os.path.join(os.path.dirname(HERE), "profiles")
DEFAULT_PROFILE = "default"


@dataclass
class Profile:
    """A loaded deployment profile."""
    name: str
    label: str
    raw: dict = field(default_factory=dict)
    path: str | None = None
    warnings: list[str] = field(default_factory=list)

    # ---- convenience accessors -------------------------------------------
    def get(self, key: str, default=None):
        return self.raw.get(key, default)

    @property
    def branding(self) -> dict:
        return self.raw.get("branding", {})

    @property
    def ideal_ppm(self) -> dict:
        return self.raw.get("ideal_ppm", {})

    @property
    def max_rates(self) -> dict:
        """The annual ceilings, `{product: (minimum, maximum)}` in kg/ha/yr.

        Only the ceiling is read anywhere (`recommend.apply_cap`), and it has to be a finite
        number: a profile is a file an operator may hand-edit, and `tuple(300.0)` reaching this
        accessor was an uncaught `TypeError` in the tool while an infinite ceiling would let a
        product through unchecked (the internal security audit A19-PLUG-3). A malformed
        entry is dropped, and a product with no entry is held at zero by `apply_cap` — a refusal,
        not a default.
        """
        raw = self.raw.get("max_kg_ha_yr")
        if not isinstance(raw, dict):
            return {}
        out: dict[str, tuple] = {}
        for key, value in raw.items():
            ceiling = value
            if isinstance(value, (list, tuple)):
                if len(value) < 2:
                    continue
                ceiling = value[1]
            if isinstance(ceiling, bool) or not isinstance(ceiling, (int, float)):
                continue
            if not math.isfinite(float(ceiling)) or ceiling < 0:
                continue
            out[str(key)] = (0.0, float(ceiling))
        return out

    @property
    def selections(self) -> dict:
        return self.raw.get("product_selections", {})

    @property
    def messages(self) -> dict:
        return self.raw.get("messages", {})

    @property
    def thresholds(self) -> dict:
        return self.raw.get("thresholds", {})

    @property
    def bs_table(self) -> list[dict]:
        return self.raw.get("base_saturation_by_tec", [])

    @property
    def high_k_overrides(self) -> dict:
        return self.raw.get("high_k_tec_overrides", {})

    @property
    def bulk_density(self) -> dict:
        return self.raw.get("bulk_density_by_texture", {})

    # ---- message lookup ---------------------------------------------------
    def message(self, code: str, default: str | None = None) -> str | None:
        """Text for a rule code, e.g. 'ca_low_bs'. Deployments supply their own."""
        return self.messages.get("codes", {}).get(code, default)

    def text(self, key: str, default: str = "") -> str:
        """Top-level branded string, e.g. branding.report_title."""
        return self.branding.get(key, default)


def list_profiles(directory: str | None = None) -> list[str]:
    d = directory or DEFAULT_PROFILE_DIR
    if not os.path.isdir(d):
        return []
    return sorted(os.path.splitext(f)[0] for f in os.listdir(d) if f.endswith(".json"))


def load_profile(
    name_or_path: str | None = None,
    directory: str | None = None,
    *,
    allow_path: bool = False,
) -> Profile:
    """Load a profile by *name* from `directory` — the plugin's own `profiles/` by default.

    A name is a bare filename stem: `default` reads `<profiles>/default.json`. It is not a path,
    and a name is all the model may pass. A profile is where the product table and the annual
    application ceilings live, so a caller that can point at any file on the disk can raise every
    ceiling out of the way and still be told the ceilings were applied
    (the internal security audit A19-PLUG-3).

    `allow_path` is the operator's door, not the model's: `cli.py --profile` and the plugin's
    `profile` setting may name a file, because that value comes from the person running the
    installation rather than from a conversation.
    """
    warnings: list[str] = []

    if not name_or_path:
        name_or_path = DEFAULT_PROFILE

    text = str(name_or_path).strip()
    d = directory or DEFAULT_PROFILE_DIR

    if allow_path and os.path.isfile(text):
        path = text
        name = os.path.splitext(os.path.basename(path))[0]
    else:
        name = text
        if not name or os.path.isabs(name) or os.path.basename(name) != name or "/" in name:
            # A separator or an absolute path in a *name* is the finding itself: it is what let
            # `profile: "../../../etc/hostname"` open a file outside the plugin
            # (the internal security audit A19-PLUG-3).
            warnings.append(
                f"profile {name!r} is not a name: profiles are read by name from "
                f"{os.path.basename(d)}/, and a path is not one of them"
            )
            return Profile(name=name, label="(missing)", raw={}, path=None,
                           warnings=warnings)
        path = os.path.join(d, f"{name}.json")
        if not os.path.isfile(path):
            available = list_profiles(d)
            # The directory's basename rather than its absolute path: this warning can reach the
            # transcript, and there an absolute path is a file-existence oracle for model-chosen
            # names (the internal security audit A19-PLUG-12).
            warnings.append(
                f"profile {name!r} not found in {os.path.basename(d)}/; "
                f"available: {', '.join(available) or 'none'}")
            return Profile(name=name, label="(missing)", raw={}, path=None,
                           warnings=warnings)

    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)

    if not isinstance(raw, dict):
        # A JSON array root used to reach `Profile.thresholds` and raise `AttributeError` out of
        # the tool (the internal security audit A19-PLUG-3).
        warnings.append(
            f"profile {name!r} is a JSON {type(raw).__name__}, not an object with a product table "
            f"and ceilings; it was not used")
        return Profile(name=name, label="(invalid)", raw={}, path=path, warnings=warnings)

    profile = Profile(
        name=raw.get("name", name),
        label=raw.get("label", name),
        raw=raw,
        path=path,
        warnings=warnings,
    )
    for required in ("ideal_ppm", "max_kg_ha_yr", "product_selections"):
        if required not in raw:
            warnings.append(f"profile '{name}' is missing '{required}'")
    return profile
