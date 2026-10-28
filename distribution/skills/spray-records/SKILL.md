---
name: spray-records
description: Record a spray with the label's withholding period.
license: MIT
metadata:
  category: pantler
  source: authored in this repository from the farm pack's application record
---

# Spray records

Use this when the operator says they sprayed, applied, fertigated or dusted something — or asks what
they applied to a block, or when it is safe to pick.

## The one rule

**The tool computes; you narrate.** You never multiply a rate by an area, never convert a rate unit,
never count days and never supply a withholding period. Say what the operator said, call
`spray_record`, and read back what it returns. If you find yourself working out a number, you have
taken a job that belongs to the tool — and the number on a spray record is the one an auditor reads.

## What to pass, and how

Pass the operator's own words; the tool resolves them against **the operator's own records** — the
blocks and inputs they have set up, which is the same list the app shows them. If the result says it
resolved against a *file* instead, say so: it means their records hold nothing yet, and blocks or
inputs they set up in the app are not in the one it used.

| They said | You pass |
|---|---|
| "sprayed the north block" | `block: "north block"` |
| "with copper" | `product: "copper"` |
| "two and a half kilos a hectare" | `rate: 2.5, rate_unit: "kg/ha"` |
| "yesterday" | `applied:` yesterday's date, as `YYYY-MM-DD` — checked against today, not guessed |
| "over three and a half hectares" | `area_ha: 3.5` — omit it and the tool uses the block's own area |

Never convert a unit or a rate to make it fit. `L/ha` and `mL/100L` are different sums, and the tool
says which one it can compute; passing a converted number hides which the operator actually used.

## What comes back, and what to do with it

The result carries the record, a one-line summary, `warnings` and `questions`, and either the saved
record's id or a plain statement that nothing was written.

**Read back the id.** `APP-0004: Copper oxychloride 500 at 2.5 kg/ha …` is a record that exists in
the spray book and can be found again; "recorded" without an id is a claim about a file nobody has
seen. If the result says `saved: false`, say that plainly — the figures are computed and *nothing was
written* — rather than reporting it as recorded.

- **Questions** are the things that must be settled first — an unknown block, a name that could be
  two products, a block with no area, a rate above the label maximum. Ask them, in the operator's
  own terms, and make the call again with their answer. Never pick a name yourself.
- **Warnings** are true things worth one line: that the block's area on file was used, that a
  concentration rate does not give a total, that the total could not be expressed in the unit the
  product is sold in. Say them; do not pad them.

## When there is no withholding period on file

The tool leaves the field empty and says so. **That is the correct answer, not a gap to fill.**

Say it plainly — the withholding period comes off the label of the specific product, and you do not
have one. Offer to add it to the input record once the operator reads it out, and say what that
would unlock: the earliest safe harvest date on this record, and on every later one.

If they tell you the period from the label, the place it goes is the **input record**, not this
application's narrative: enter it there so every future application carries it. Never type a number
you were not given.

## When the rate is above the label maximum

The tool records the rate as given and asks whether that is what was applied. Ask the operator. A
record that quietly adjusted a rate would be worse than useless — it would be evidence that does not
match what happened.

## Re-entry

If the product has a re-entry period on file the tool returns it. Say it when somebody is about to
go into the block, and only then — it is a safety fact, not a courtesy.

## If there is no spray book yet

That is the operator's first-run step, not a reason to improvise one. The tool says which of the two
routes applies: blocks and inputs set up in the app, or
`plugins.entries.spray.catalogue_path` pointing at a spray book JSON file (or `PANTLER_SPRAYBOOK`,
or a `spraybook.json` in the Hermes home). Tell them that sentence and stop — **never invent a block,
a product, a rate or a withholding period** to get past it. A record against a block that does not
exist is worse than no record: it is a compliance document that names the wrong paddock.

## What the record is for

This is the spray book an organic certifier or a customer audit asks for: what went on, where, when,
at what rate, by whom, and when it is safe to harvest. Write it when the work happens, from what the
operator says, and leave the arithmetic and the label facts to the tools that hold them.
