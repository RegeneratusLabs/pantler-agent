# soil-amendment

Reads an EAL soil certificate of analysis and returns a structured soil amendment
program. Ships as a Hermes plugin (two tools) plus a skill.

**The engine does the arithmetic. The model writes the narrative.** That split is the
whole design: several of the rules are counter-intuitive and one is an ordering
dependency, so they belong in code, not in a language model's head.

Whitelabel by construction: the engine and the shipped profile contain no vendor
product names, no trademarks and no proprietary commentary. Product tables, application
ceilings, target levels and rule wording all come from a profile.

## Where this sits in pantler

This is the `farm` pack's agronomy capability: a **first-party plugin** under
`plugins/soil-amendment/`, with its skill shipped by the distribution at
`distribution/skills/soil-amendment-engine/`. It is vendored, not installed — the repo is
the source of truth, and nothing here is third-party at runtime (the design notes invariant 2). It
is MIT (invariant 5), and every figure it returns is computed by `soilengine`, never by
the model (invariant 1). See the skills and plugins notes
§4.1 for why the agronomy layer is the first thing built for this market.

The engine is standard library only, so it needs no dependency environment of its own.

## Layout

```
soilengine/
  eal.py          certificate-of-analysis reader - two real layouts, below-LOR,
                  parameters that repeat and are only distinguishable by unit
  physical.py     sampling depth + bulk density -> the kg/ha factor
  soil.py         base saturations, ratios, exchange-capacity-relative targets, deficits
  recommend.py    the five-step amendment algorithm, caps, ordering, rule codes
  report.py       markdown view for a human
  profile.py      profile loading (JSON, so the package stays dependency-free)
  constants.py    chemistry and physics only - nothing deployment-specific
  cli.py          command line entry point
profiles/
  default.json    the shipped profile: products, ceilings, targets, wording
skills/
  soil-amendment-engine/SKILL.md   bundled copy; the distribution ships the discoverable one
tests/
  fixtures/       SYNTHETIC certificates of analysis (no real client data)
scripts/
  make_fixtures.py     regenerate the synthetic fixtures
```

## Install

The plugin is loaded from the profile's `plugins/` directory, which in the dev environment
is a symlink into this repo (the developer setup notes step 4). Registering it there and
enabling it in the profile is the whole install:

```bash
export HERMES_HOME="$PWD/.hermes-dev"
ln -sfn "$PWD/plugins/soil-amendment" "$HERMES_HOME/profiles/pantler/plugins/soil-amendment"
hermes -p pantler plugins enable soil-amendment
hermes -p pantler plugins validate "$PWD/plugins/soil-amendment"
```

The discoverable skill is installed by the distribution, not by the plugin: a skill bundled
by a plugin is namespaced and read-only and does **not** reach the system prompt's skill
index. The distribution's copy at `distribution/skills/soil-amendment-engine/` is what makes
it discoverable.

Plugin tools register at session start, so **open a new session** before expecting
`soil_amendment` to be callable.

## Use

As a tool, from the agent:

```
soil_amendment(coa_path="...", crop="Ginger")
soil_test_read(coa_path="...")            # parse only, no program
```

From the command line, from this directory (the engine is stdlib-only, so any Python 3.11+
works):

```bash
python3 -m soilengine.cli <coa.csv> --crop Ginger --out out/run1
python3 -m soilengine.cli <coa.csv> --sample 2 --json
python3 -m soilengine.cli <coa.csv> --inspect        # parsed test, no program
python3 -m soilengine.cli --list-profiles

# physical overrides, in precedence order: factor > bulk density > texture table
python3 -m soilengine.cli <coa.csv> --bd 1.62        # measured bulk density, t/m3
python3 -m soilengine.cli <coa.csv> --depth-cm 10
python3 -m soilengine.cli <coa.csv> --factor 2.5     # reproduce a historical constant

# context flags that change the answer
--system organic --certification organic --legume --cu-fungicide
--foliar-wettable --budget --crop-class high_k
```

## What the tool returns

JSON per sample: the parsed test, the calculated program, the element requirement
table, site flags, ratio imbalances, and:

- `rule_codes` — every code that fired, named not numbered
- `rule_text` — code to wording, so a narrative layer has the commentary to hand
- `instructions` — an explicit reminder that the figures are calculated and must not be
  recalculated or adjusted

## The five steps, and the two rules that must not be broken

Order is **phosphorus → magnesium → calcium → nitrogen/potassium/sulfur → traces**.

1. **A combined phosphorus and calcium source carries ~20% calcium.** Calculating
   calcium before phosphorus therefore over-applies calcium. The calcium requirement in
   step 3 is netted against what steps 1 and 2 already supply.
2. **Total calcium from all forms is capped per year.** Anything above the ceiling is
   returned as `deferred_ppm` and flagged — reported, never silently dropped.

Sulfur and calcium supplied by one input are likewise deducted from the next
requirement, and every product has an annual application ceiling.

## The physical basis

The ppm → kg/ha conversion is **derived per sample**, not a constant:

```
kg/ha = ppm x sampling_depth(m) x bulk_density(t/m3) x 10
```

Bulk density **falls as clay content rises** — clay aggregates, so it holds less mass
per unit volume — which means a light sandy soil needs *more* product per ppm than a
clay. At 15 cm: sand 2.475, sandy soil 2.325, loam 2.250, clay loam 2.175, clay 2.025.

Densities are typical values for each texture class, not measurements; compaction
raises them. `--bd` takes a measured value. Two hazards are flagged rather than hidden:
a deep or subsoil sample, and a depth given without a unit.

## Soil-test traps the reader handles

- Two report layouts: Report-ID-first with several samples, and method-first with one.
- **Parameter names repeat within a file**, and only the unit disambiguates:
  `('Calcium','%')` is a base saturation, `('Calcium','mg/kg')` is a total
  acid-extractable reserve. Keys are `(name, unit)`.
- Below-LOR results (`< 2`) are not zero; LOR/2 is used only for balance arithmetic.
- **Molybdenum and cobalt on a total-acid pack are reserves** two orders of magnitude
  above an available-test target, so no deficit is derived from them.
- **Sodium and aluminium are excesses**, never deficiencies.

## Profiles — the deployment layer

Everything a deployment changes is in a JSON profile:

| Section | Contents |
|---|---|
| `branding` | report title, subtitle, disclaimer |
| `ideal_ppm` | target soil levels |
| `base_saturation_by_tec` | target base saturations per exchange-capacity band |
| `high_k_tec_overrides` | potassium target for high-potassium crops |
| `max_kg_ha_yr` | per-product annual ceilings |
| `product_selections` | which product is chosen for each situation |
| `messages.codes` | wording for every rule code |
| `thresholds` | pH cut-offs, ratio tolerances, alert levels |
| `bulk_density_by_texture` | typical density per texture class |

To rebrand or change supplier: copy `profiles/default.json`, change the product names
and analysis percentages in `product_selections` and `max_kg_ha_yr` (adding new
products to both), and edit `messages.codes`. No code changes.

Genuine customer-facing product names belong in a profile, never in the engine — a test
enforces this by scanning both trees for brand strings.

## Testing

The suite is stdlib `unittest` — the repo carries no test dependency — and runs with any
Python 3.11+:

```bash
python3 -m unittest discover -s tests -t tests -v   # from this directory
./scripts/test.sh python                            # from the repo root, with the rest
```

`tests/test_plugin.py` loads the plugin exactly as Hermes does (importlib from
`__init__.py`, `register(ctx)` against a stub context) and calls the tool handlers, so a
broken entry point fails here rather than at session start.

### Running the engine by hand

The CLI is a development surface, not a shipped one — the profile a customer runs has no
terminal, so the skill tells the model to use the tools. In the repository it is the fastest
way to see what the engine does with a file:

```bash
cd plugins/soil-amendment
python3 -m soilengine.cli tests/fixtures/example-soil-multi-sample.csv
python3 -m soilengine.cli <coa.csv> --inspect        # the parsed test, no program
python3 -m soilengine.cli <coa.csv> --list-profiles  # which profiles exist
```

The verification block used to live in the skill, which put shell commands on a machine whose
distribution has no terminal and broke the house rule that a skill is instructions, not
scaffolding (the internal security audit A19-DIST-4). It belongs here.

The regression test locks exact figures for one fixture sample. If a change moves them, decide
whether the change was intended before editing the test. `./scripts/test.sh python` from the
repo root runs the whole suite, and `hermes -p pantler plugins validate "$PWD/plugins/soil-amendment"`
asks the engine's own validator.

Fixtures are **synthetic**. Real client certificates must never be committed here. The
fixtures deliberately reproduce every structural feature the reader has to survive:
both layouts, repeated parameter names, below-LOR values, several depth notations, a
textureless sample, and a plant test that must be refused.

## Scope

The engine stops at the calculated soil requirement. It does not schedule a program
(no seed treatments, foliar programs, tank-mix order or seasonal timing), does not model
pH or lime requirement (pH only chooses between a carbonate and a sulfate calcium
source), and does not generate prose. Plant tissue and sap tests are a different problem
with different units and targets, and are refused rather than coerced.
