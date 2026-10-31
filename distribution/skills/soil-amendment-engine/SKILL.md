---
name: soil-amendment-engine
description: Turn a soil test into an amendment program with rule codes.
license: MIT
metadata:
  category: pantler
  hermes:
    tags: "soil, agronomy, eal, lab-report, amendment, base-saturation"
---

# Soil amendment engine

## When to Use

- A soil test (EAL certificate of analysis, CSV) needs turning into an amendment program.
- Any question about base saturation, cation exchange capacity, mineral deficits, or
  product application rates for a soil test.
- Someone asks why a rate came out the way it did, or wants a soil test read.
- Configuring a deployment's product table or target levels.

## The one rule that matters

**Never calculate these numbers yourself.** Load the test through the `soil_amendment`
tool and narrate what it returns. The engine does the arithmetic and
applies the ceilings; a language model doing this in its head gets it wrong, because
several of the rules are counter-intuitive and one of them is an ordering dependency.

## The way in

| Surface | How | When |
|---|---|---|
| Hermes tool | `soil_amendment` / `soil_test_read` | Normal use inside Hermes |

The tools return JSON: the parsed test, the calculated program, every rule code that
fired, and a `rule_text` map of code to wording. Write the prose from that. The tool
returns data on purpose - the narrative is the model's job.

## When the report is a scan or a photograph

A lab PDF with no text layer, a phone photo of a printout, a scanned fax: `read_file`
returns a `[NEEDS OCR: ...]` warning instead of the table. The numbers are still
recoverable, one image at a time, and the route is short:

1. **Ask the operator to render the pages to images.** This profile has no terminal and no
   code execution — they are removed at install, deliberately — so the conversion is their
   step, not yours: any PDF viewer's "export as image", or `pdftoppm -jpeg -r 150` on a
   machine that has poppler. A photograph is already an image; skip this step.
2. **Read each image with `vision_analyze`, one table band at a time.** Ask for the
   parameter name with its unit and the sample columns in order, and for the raw rows
   only. A whole A4 page at 150 dpi is downscaled until small figures are guesses; five
   or six horizontal bands read accurately.
3. **Transcribe into the certificate's CSV shape** — a `Parameter`/`Unit` header row and
   one column per sample, or one row per sample with the parameters as columns — then load
   *that* with `soil_test_read`.

Three rules for this route:

- **Do not hand-roll OCR.** No terminal script, no direct call to a vision API: the
  engine's `vision_analyze` is the supported path, and a script bypasses the profile's
  configuration, its timeouts and the activity line the operator watches.
- **If `vision_analyze` times out or cannot see the image, say so.** That is the
  profile's missing `auxiliary.vision` route, not a problem with the report, and it is
  a one-line profile setting to fix - never something to work around in this turn.
- **OCR is transcription, not analysis.** Check every figure that came from an image
  (decimal points, thousands separators and `<` signs are what vision models drop), and
  say which numbers were read from an image so the operator can spot-check them. A
  figure you cannot read is a question, not a plausible guess.

## What the engine guarantees

- **Phosphorus before calcium.** A combined P/Ca source carries about 20% calcium, so
  calcium is netted against it. Calculating calcium first over-applies it.
- **Total calcium is capped per year** across all sources. The excess is returned as
  `deferred_ppm` and flagged, never dropped.
- **Per-product annual ceilings** are enforced (lime, gypsum, soft rock, potassium
  sulfate, trace sulfates, and so on). Anything capped is marked `capped: true`.
- **Sulfur and calcium supplied by one input are deducted from the next requirement.**
- **Rule codes are named, not numbered**, and `rule_text` gives the wording.

## Soil-test traps the engine already handles

1. **Two report layouts.** One keys on an internal Report ID, one is method-first with
   a single sample and no Report ID. Both parse.
2. **Parameter names repeat within a file.** `('Calcium','%')` is a base saturation;
   `('Calcium','mg/kg')` is a total acid-extractable reserve. Keys are `(name, unit)`.
   Reading the reserve as the base saturation (or vice versa) is a silent, large error.
3. **`< 2` is not zero.** Below-LOR results are kept with their status; LOR/2 is used
   only for balance arithmetic.
4. **Molybdenum and cobalt on a total-acid pack are reserves**, tens of ppm, not
   comparable with an available-test target. They return `status: reserve_only` and no
   deficit. Do not report them as deficient or adequate.
5. **Sodium and aluminium are excesses**, never deficiencies. They appear in the base
   saturation table, never in the deficit table.
6. **Silicon usually has no product**, so the deficit is reported without a rate.

## The physical basis (do not turn this back into a constant)

The ppm → kg/ha conversion is **derived per sample**, not fixed:

```
kg/ha = ppm x sampling_depth(m) x bulk_density(t/m3) x 10
```

Bulk density **falls as clay content rises** (clay aggregates, so it holds less mass
per unit volume). A light sandy soil therefore needs MORE product per ppm than a clay.
Do not "correct" this in the other direction.

At 15 cm this gives: sand 2.475, sandy soil 2.325, loam 2.250, clay loam 2.175,
clay 2.025. Historical fixed constants were 2.5 and 2.24 (bulk densities 1.67 and
1.49); pass `factor` to reproduce one of those, but do not reinstate it as a default.

Two depth hazards are flagged rather than hidden: a **deep or subsoil sample** gives a
large factor that would badly overstate an amendment to the working layer
(`depth_atypical`), and an **unqualified number** like `150` is interpreted by
magnitude (`depth_unit_inferred`). Both need a human eye.

## Profiles - the deployment layer

Everything a deployment changes lives in a JSON profile, not in code:

```
profiles/default.json
  branding            report title, subtitle, disclaimer
  ideal_ppm           target soil levels
  base_saturation_by_tec   target base saturations per exchange-capacity band
  high_k_tec_overrides     potassium target for high-K crops
  max_kg_ha_yr        per-product annual ceilings
  product_selections  which product is chosen for each situation
  messages.codes      wording for every rule code
  thresholds          pH cut-offs, ratio tolerances, alert levels
  bulk_density_by_texture
```

To rebrand or switch supplier: copy the default profile, change the product names and
analysis percentages under `product_selections` and `max_kg_ha_yr`, add any new
products to both, and edit `messages.codes`. No code changes. Select it with the
`profile` argument or the plugin's `profile` setting.

Profiles are JSON rather than YAML so the package stays dependency-free.

## Provenance and integrity

- The shipped engine and profile contain **no vendor names or trademarks** - enforced
  by a test that scans both for brand strings. Keep it that way: put customer-facing
  product names in a profile, never in the engine.
- Ideal base saturations vary with exchange capacity, which is why a single "68%
  calcium" rule is wrong on a light soil.
- The rule wording in the shipped profile is generic agronomic text. If a deployment
  supplies wording from its own materials, that text is theirs and belongs in their
  profile.

## What this does not do

- No prose generation: it returns codes and wording, and the model writes the text.
- No product program scheduling: no seed treatments, foliar programs, tank-mix order
  or seasonal timing. It stops at the calculated soil requirement.
- No pH or lime-requirement modelling: pH only selects between a carbonate and a
  sulfate calcium source.
- Plant tissue and sap tests are a different problem with different units and targets
  and are refused, not coerced.
