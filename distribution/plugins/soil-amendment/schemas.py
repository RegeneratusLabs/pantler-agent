"""Tool schemas - what the language model sees.

Descriptions matter here more than in most plugins: the model must understand that
these tools RETURN CALCULATED NUMBERS and that it should not perform any of this
arithmetic itself.
"""
from __future__ import annotations

COA_PATH = {
    "type": "string",
    "description": "Path to an EAL certificate of analysis CSV (soil test).",
}

PROFILE = {
    "type": "string",
    "description": ("Profile name from the plugin's profiles/ directory. Omit to use "
                    "the configured default. A "
                    "profile supplies the product table, application ceilings, target "
                    "levels and rule wording."),
}

SAMPLE = {
    "type": "integer",
    "description": "1-based index of a single sample to process. Omit for all samples.",
}

SOIL_AMENDMENT = {
    "name": "soil_amendment",
    "description": (
        "Read an EAL soil certificate of analysis and return a structured soil amendment "
        "program for every sample: base saturations against exchange-capacity targets, "
        "element deficits in ppm, a product program in kg/ha with annual application "
        "ceilings applied, site flags, ratio imbalances, and named rule codes. "
        "ALL ARITHMETIC IS DONE BY THIS TOOL. Do not calculate, adjust or estimate any "
        "rate yourself - narrate the numbers returned. The order of the program is "
        "meaningful: phosphorus is calculated before calcium so that calcium supplied by "
        "a combined source is netted off, and total calcium for the year is capped. "
        "Rule codes are returned with their wording so you can write the commentary."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "coa_path": COA_PATH,
            "profile": PROFILE,
            "sample": SAMPLE,
            "crop": {"type": "string", "description": "Crop, free text."},
            "crop_class": {
                "type": "string",
                "enum": ["generic", "high_k", "low_k"],
                "description": ("'high_k' raises the potassium base-saturation target for "
                                "crops with a high potassium demand. Default 'generic'."),
            },
            "production_system": {
                "type": "string",
                "enum": ["conventional", "regenerative", "organic", "hydroponic",
                         "biodynamic"],
                "description": "Production system. Default 'conventional'.",
            },
            "certification": {
                "type": "string",
                "description": "Certification scheme if any, e.g. 'organic'.",
            },
            "is_legume": {
                "type": "boolean",
                "description": "True if the crop is a legume, which suppresses nitrogen inputs.",
            },
            "area_ha": {"type": "number", "description": "Area in hectares, if known."},
            "foliar_handles_wettable": {
                "type": "boolean",
                "description": ("False if foliar equipment cannot handle wettable powders, "
                                "which constrains product form."),
            },
            "copper_fungicide_history": {
                "type": "boolean",
                "description": "True if copper fungicides are in use, which suppresses copper inputs.",
            },
            "budget_constrained": {
                "type": "boolean",
                "description": "True to request an ideal program plus a budget alternative.",
            },
            "bulk_density": {
                "type": "number",
                "description": ("Measured bulk density in t/m3 (g/cm3). Overrides the "
                                "texture lookup. Use when a real measurement exists."),
            },
            "depth_cm": {
                "type": "number",
                "description": "Sampling depth in cm. Overrides the value on the report.",
            },
            "factor": {
                "type": "number",
                "description": ("Override the ppm -> kg/ha conversion outright. Only use "
                                "to reproduce a historical constant; normally omit so the "
                                "factor is derived from sampling depth and bulk density."),
            },
        },
        "required": ["coa_path"],
    },
}

SOIL_TEST_READ = {
    "name": "soil_test_read",
    "description": (
        "Parse an EAL soil certificate of analysis WITHOUT producing a program, and "
        "return what was measured: samples, sampling depths, texture, pH, EC, carbon and "
        "organic matter, exchangeable cations, base saturations, exchange capacity, and "
        "available element levels. Use this when you only need to know what the test "
        "reports, or to check a file parses before running a full recommendation."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "coa_path": COA_PATH,
            "profile": PROFILE,
            "sample": SAMPLE,
        },
        "required": ["coa_path"],
    },
}
