"""Generate SYNTHETIC EAL certificate-of-analysis fixtures for the test suite.

No real client data is used anywhere in this package. These fixtures are invented, but
they reproduce every structural feature the reader must handle, which is what the tests
actually exercise:

  * Layout A (Report ID header) with multiple samples in one file
  * Layout B (method-first) with a single sample and no Report ID
  * parameter names that repeat within a file and are only distinguishable by unit
    (Exchangeable Calcium in cmol+/kg, kg/ha and mg/kg; 'Calcium' as both a base
    saturation % and a total acid-extractable reserve)
  * below-LOR results written as '< 2' and '< 10'
  * sampling depths in several notations, including one atypical (deep) sample
  * a sample with no texture and no depth, to exercise the fallbacks
  * a plant tissue test, which the engine must refuse

Run:  python3 plugins/soil-amendment/scripts/make_fixtures.py
"""
from __future__ import annotations

import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "tests", "fixtures")

EQ = {"Ca": 200.0, "Mg": 120.0, "K": 390.0, "Na": 230.0, "Al": 90.0}

# ---------------------------------------------------------------------------
# Invented samples. Values are chosen to trigger specific engine paths.
# ---------------------------------------------------------------------------
SAMPLES_A = [
    dict(
        name="North Paddock", depth="15cm", texture="Clay Loam", colour="Brownish",
        ph=6.65, ec=0.056, tec=15.5,
        meq={"Ca": 10.4, "Mg": 3.40, "K": 0.54, "Na": 0.14, "Al": 0.07},
        bs={"Ca": 67, "Mg": 22, "K": 3.5, "Na": 0.9, "Al": 0.5, "H": 6.0, "OB": 0.4},
        mehlich_p=44.9, bray_p=87, s=6.0, zn=4.3, mn=11.3, fe=67.8, cu=2.2, b=0.43, si=35,
        no3=5.6, nh4=1.6, c=2.31, n=0.18, om=4.05, paramag=300,
        total={"Mo": 0.49, "Co": 20, "B": 0.8, "S": 247, "Ca": 3200},
    ),
    dict(
        name="South Block", depth="150mm", texture="Clay Loam", colour="Brownish",
        ph=7.57, ec=0.243, tec=32.3,
        meq={"Ca": 23.8, "Mg": 6.13, "K": 1.91, "Na": 0.29, "Al": 0.11},
        bs={"Ca": 74, "Mg": 19, "K": 5.9, "Na": 0.9, "Al": 0.3, "H": 0.0, "OB": 0.3},
        mehlich_p=206, bray_p=310, s=17, zn=24.1, mn=12.8, fe=97.3, cu=4.8, b=0.95, si=61,
        no3=47.8, nh4=3.8, c=8.28, n=0.55, om=14.5, paramag=240,
        total={"Mo": 1.3, "Co": 19, "B": 8.9, "S": 812, "Ca": 11900},
    ),
    dict(
        name="Deep Profile", depth="45cm", texture="Clay", colour="Grey",
        ph=8.10, ec=0.310, tec=28.0,
        meq={"Ca": 24.0, "Mg": 1.20, "K": 0.40, "Na": 1.60, "Al": 0.02},
        bs={"Ca": 86, "Mg": 4.3, "K": 1.4, "Na": 5.7, "Al": 0.1, "H": 2.0, "OB": 0.5},
        mehlich_p=12.0, bray_p=20, s=4.0, zn=1.2, mn=3.0, fe=40.0, cu=0.9, b=0.20, si=20,
        no3=2.0, nh4=9.0, c=0.90, n=0.08, om=1.60, paramag=90,
        total={"Mo": 0.10, "Co": 5, "B": 0.4, "S": 100, "Ca": 9000},
    ),
]


def _fmt(v):
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)


def layout_a(samples, path):
    """Report-ID-first layout, one column per sample."""
    n = len(samples)
    pad = [""] * n
    rows = []
    rows.append(["Report ID", "E26-00-9999_EALT1_1"] + pad)
    rows.append(["Client Sample ID:"] + [""] * 3 + [s["name"] for s in samples])
    rows.append(["Sample Depth:"] + [""] * 3 + [s["depth"] for s in samples])
    rows.append(["Crop ID:"] + [""] * 3 + ["Example crop" for _ in samples])
    rows.append(["Sample Date:"] + [""] * 3 + ["1 Jan 2026" for _ in samples])
    rows.append(["Sampled By:"] + [""] * 3 + ["Synthetic" for _ in samples])
    rows.append(["Your Client:"] + [""] * 3 + ["EXAMPLE FARM" for _ in samples])
    rows.append(["EAL Sample ID: "] + [""] * 3 +
                [f"E26-00-9999-{i+1:04d}" for i in range(n)])
    rows.append(["Parameter", "Unit", "Method Reference", "LOR"] + ["---"] * n)

    def add(param, unit, method, lor, values):
        rows.append([param, unit, method, lor] + [values[i] for i in range(n)])

    add("Soluble Calcium", "mg/kg", "** Inhouse S10", "<10", [2020, 5450, 1500])
    add("Soluble Magnesium", "mg/kg", "** Inhouse S10", "<1", [382, 719, 150])
    add("Soluble Potassium", "mg/kg", "** Inhouse S10", "<25", [168, 520, 90])
    add("Soluble Phosphorus", "mg/kg", "** Inhouse S10", "<1", [6.3, 86, 3.0])
    add("Nitrate-N - KCl extractable", "mg/kg", "** Inhouse S37", "<0.1",
        [s["no3"] for s in samples])
    add("Ammonium-N - KCl extractable", "mg/kg", "** Inhouse S37", "<0.1",
        [s["nh4"] for s in samples])
    add("Mehlich Phosphorus", "mg/kg", "** Rayment & Lyons 18F1", "<0.1",
        [s["mehlich_p"] for s in samples])
    add("Phosphorus - Bray 2", "mg/kg", "** Inhouse S3A", "<1",
        [s["bray_p"] for s in samples])
    add("Sulfur - KCl extractable", "mg/kg", "** Inhouse S37", "<1",
        [s["s"] for s in samples])
    add("pH (H2O)", "units", "Rayment & Lyons 4A1", "---", [s["ph"] for s in samples])
    add("Electrical Conductivity", "dS/m", "Rayment & Lyons 3A1", "<0.005",
        [s["ec"] for s in samples])
    add("Maximum Soil Chloride Estimate", "mg/kg", "** Calculation", "---",
        [36, 156, 198])

    # exchangeable cations: the SAME parameter name in three units. The key is
    # (name, unit); matching on name alone reads a ppm as a meq or vice versa.
    for elem, key in (("Calcium", "Ca"), ("Magnesium", "Mg"),
                      ("Potassium", "K"), ("Sodium", "Na")):
        add(f"Exchangeable {elem}", "cmol+/kg", "** Rayment & Lyons 18F1", "<0.05",
            [s["meq"][key] for s in samples])
        # kg/ha is unpadded above 9999, which is what real reports do
        add(f"Exchangeable {elem}", "kg/ha", "** Rayment & Lyons 18F1", "<22",
            [round(s["meq"][key] * EQ[key] * 2.5, 1) for s in samples])
        add(f"Exchangeable {elem}", "mg/kg", "** Rayment & Lyons 18F1", "<10",
            [round(s["meq"][key] * EQ[key]) for s in samples])
    add("Aluminium - Exchangeable", "cmol+/kg", "** Calculations", "<0.01",
        [s["meq"]["Al"] for s in samples])

    # calculated base saturation - names collide with the total-acid block below,
    # disambiguated only by the '%' unit
    add("Calcium", "%", "** Calculation", "<0.01", [s["bs"]["Ca"] for s in samples])
    add("Magnesium", "%", "** Calculation", "<0.01", [s["bs"]["Mg"] for s in samples])
    add("Potassium", "%", "** Calculation", "<0.01", [s["bs"]["K"] for s in samples])
    add("Sodium - ESP", "%", "** Calculation", "<0.01", [s["bs"]["Na"] for s in samples])
    add("Hydrogen", "%", "** Calculation", "---", [s["bs"]["H"] for s in samples])
    add("Other Bases", "%", "** Calculation", "<0.01", [s["bs"]["OB"] for s in samples])
    add("Calcium/Magnesium Ratio", "Ratio", "** Calculation", "<0.01",
        [round(s["bs"]["Ca"] / s["bs"]["Mg"], 1) for s in samples])
    add("Total Cation Exchange Capacity", "cmol+/kg", "** Calculation", "---",
        [s["tec"] for s in samples])

    add("Zinc - DTPA", "mg/kg", "Rayment & Lyons 12A1", "<0.5", [s["zn"] for s in samples])
    add("Manganese - DTPA", "mg/kg", "Rayment & Lyons 12A1", "<0.1", [s["mn"] for s in samples])
    add("Iron - DTPA", "mg/kg", "Rayment & Lyons 12A1", "<0.5", [s["fe"] for s in samples])
    add("Copper - DTPA", "mg/kg", "Rayment & Lyons 12A1", "<0.1", [s["cu"] for s in samples])
    # below-LOR written the way real reports write it
    add("Boron - CaCl2 extractable", "mg/kg", "** Rayment & Lyons 12C2", "<0.1",
        [s["b"] if s["b"] >= 0.1 else "< 0.1" for s in samples])
    add("Silicon - CaCl2 extractable", "mg/kg", "** Inhouse S11", "<1",
        [s["si"] for s in samples])
    add("Carbon - Total", "%", "Inhouse S4a", "<0.03", [s["c"] for s in samples])
    add("Nitrogen - Total", "%", "Inhouse S4a", "<0.02", [s["n"] for s in samples])
    add("Estimated Organic Matter", "%", "Inhouse S4a", "<0.04", [s["om"] for s in samples])
    add("Paramagnetism", "uCGS", "** Paramagnetic Count Soil Meter", "---",
        [s["paramag"] for s in samples])
    add("Basic Texture", "---", "** Inhouse S65", "---", [s["texture"] for s in samples])
    add("Basic Colour", "---", "** Inhouse S65", "---", [s["colour"] for s in samples])

    # total acid extractable reserves - the same names again, different units.
    # Molybdenum/Cobalt here are reserves, two orders of magnitude above an
    # available-test target, so no deficit may be derived from them.
    total_block = [
        ("Calcium", "mg/kg", "<50", [s["total"]["Ca"] for s in samples]),
        ("Magnesium", "mg/kg", "<50", [5850, 4390, 3990]),
        ("Phosphorus", "mg/kg", "<50", [582, 1620, 900]),
        ("Molybdenum", "mg/kg", "<0.2", [s["total"]["Mo"] for s in samples]),
        ("Cobalt", "mg/kg", "<0.05", [s["total"]["Co"] for s in samples]),
        ("Boron", "mg/kg", "<2", [s["total"]["B"] for s in samples]),
        ("Sulfur", "mg/kg", "<50", [s["total"]["S"] for s in samples]),
        ("Zinc", "mg/kg", "<1", [70, 122, 45]),
    ]
    for elem, unit, lor, vals in total_block:
        add(elem, unit, "1:3 Nitric:HCl - ICPMS", lor, vals)

    with open(path, "w", encoding="utf-8", newline="") as fh:
        for r in rows:
            fh.write(",".join(_fmt(x) for x in r) + "\n")


def layout_b(path, no_texture=False, no_depth=False):
    """Method-first layout, one sample per file, no Report ID."""
    rows = []
    rows.append(["Client Sample ID:", "", "", "", "Whole Paddock"])
    rows.append(["Sample Depth:", "", "", "",
                 "" if no_depth else "0-15"])
    rows.append(["Sample Date:", "", "", "", "2 Feb 2026"])
    rows.append(["Your Client:", "", "", "", "EXAMPLE FARM"])
    rows.append(["Method Reference", "Parameter", "Unit", "LOR", "E26-00-8888-0001"])

    def add(method, param, unit, lor, value):
        rows.append([method, param, unit, lor, value])

    add("** Inhouse S37", "Nitrate-N - KCl extractable", "mg/kg", "<0.1", "3.6")
    add("** Inhouse S37", "Ammonium-N - KCl extractable", "mg/kg", "<0.1", "2.3")
    add("** Inhouse S37", "Sulfur - KCl extractable", "mg/kg", "<1", "26")
    add("** Rayment & Lyons 18F1", "Mehlich Phosphorus", "mg/kg", "<0.1", "9.7")
    add("Rayment & Lyons 4A1", "pH (H2O)", "units", "---", "6.98")
    add("Rayment & Lyons 3A1", "Electrical Conductivity", "dS/m", "<0.005", "0.110")
    add("** Rayment & Lyons 18F1", "Exchangeable Calcium", "cmol+/kg", "<0.05", "9.48")
    add("** Rayment & Lyons 18F1", "Exchangeable Calcium", "kg/ha", "<22", "4260")
    add("** Rayment & Lyons 18F1", "Exchangeable Calcium", "mg/kg", "<10", "1900")
    add("** Rayment & Lyons 18F1", "Exchangeable Magnesium", "cmol+/kg", "<0.01", "7.29")
    add("** Rayment & Lyons 18F1", "Exchangeable Magnesium", "kg/ha", "<2", "1990")
    add("** Rayment & Lyons 18F1", "Exchangeable Magnesium", "mg/kg", "<1", "887")
    add("** Rayment & Lyons 18F1", "Exchangeable Potassium", "cmol+/kg", "<0.12", "0.18")
    add("** Rayment & Lyons 18F1", "Exchangeable Potassium", "kg/ha", "<112", "160")
    add("** Rayment & Lyons 18F1", "Exchangeable Potassium", "mg/kg", "<50", "71.6")
    add("** Rayment & Lyons 18F1", "Exchangeable Sodium", "cmol+/kg", "<0.065", "0.72")
    add("** Rayment & Lyons 18F1", "Exchangeable Sodium", "kg/ha", "<33", "372")
    add("** Rayment & Lyons 18F1", "Exchangeable Sodium", "mg/kg", "<15", "166")
    add("** Inhouse S37", "Aluminium - Exchangeable", "cmol+/kg", "---", "0.03")
    add("** Calculation", "Calcium", "%", "<0.01", "53")
    add("** Calculation", "Magnesium", "%", "<0.01", "41")
    add("** Calculation", "Potassium", "%", "<0.01", "1.0")
    add("** Calculation", "Sodium - ESP", "%", "<0.01", "4.0")
    add("** Calculation", "Hydrogen", "%", "---", "1.5")
    add("** Calculation", "Total Cation Exchange Capacity", "cmol+/kg", "---", "18.0")
    add("Rayment & Lyons 12A1", "Zinc - DTPA", "mg/kg", "<0.5", "1.3")
    add("Rayment & Lyons 12A1", "Manganese - DTPA", "mg/kg", "<0.1", "25.3")
    add("Rayment & Lyons 12A1", "Iron - DTPA", "mg/kg", "<0.5", "29.0")
    add("Rayment & Lyons 12A1", "Copper - DTPA", "mg/kg", "<0.1", "3.3")
    add("** Rayment & Lyons 12C2", "Boron - CaCl2 extractable", "mg/kg", "<0.1", "< 0.1")
    add("** Inhouse S11", "Silicon - CaCl2 extractable", "mg/kg", "<1", "67")
    add("Inhouse S4a", "Carbon - Total", "%", "<0.02", "1.6")
    add("Inhouse S4a", "Nitrogen - Total", "%", "<0.02", "0.13")
    add("Inhouse S4a", "Estimated Organic Matter", "%", "<0.04", "2.8")
    add("** Paramagnetic Count Soil Meter", "Paramagnetism", "uCGS", "---", "140")
    add("** Inhouse S65", "Basic Texture", "---", "---",
        "---" if no_texture else "Sandy Soil")
    add("** Inhouse S65", "Basic Colour", "---", "---", "Pale")

    with open(path, "w", encoding="utf-8", newline="") as fh:
        for r in rows:
            fh.write(",".join(_fmt(x) for x in r) + "\n")


def plant_fixture(path):
    rows = [
        ["Report ID", "E26-00-7777_EALP1_1", "", ""],
        ["Client Sample ID:", "", "", "Leaf Block 1"],
        ["Plant Part:", "", "", "Leaf"],
        ["Sample Date:", "", "", "3 Mar 2026"],
        ["Parameter", "Unit", "Method Reference", "LOR", "---"],
        ["Total Carbon", "%", "Inhouse S4a", "<0.02", "46.8"],
        ["Total Nitrogen", "%", "Inhouse S4a", "<0.02", "3.56"],
        ["Crude Protein", "%", "Inhouse S4a", "<0.13", "22.3"],
        ["Potassium", "%", "** Nitric Acid digest", "<0.005", "3.70"],
        ["Calcium", "%", "** Nitric Acid digest", "<0.005", "2.24"],
        ["Magnesium", "%", "** Nitric Acid digest", "<0.005", "0.53"],
        ["Copper", "mg/kg", "** Nitric Acid digest", "<1", "7.5"],
        ["Zinc", "mg/kg", "** Nitric Acid digest", "<1", "50"],
    ]
    with open(path, "w", encoding="utf-8", newline="") as fh:
        for r in rows:
            fh.write(",".join(_fmt(x) for x in r) + "\n")


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    layout_a(SAMPLES_A, os.path.join(OUT, "example-soil-multi-sample.csv"))
    layout_b(os.path.join(OUT, "example-soil-single-sample.csv"))
    layout_b(os.path.join(OUT, "example-soil-no-texture-no-depth.csv"),
             no_texture=True, no_depth=True)
    plant_fixture(os.path.join(OUT, "example-plant-tissue.csv"))
    print("wrote fixtures to", OUT)
    for f in sorted(os.listdir(OUT)):
        print("  ", f)
