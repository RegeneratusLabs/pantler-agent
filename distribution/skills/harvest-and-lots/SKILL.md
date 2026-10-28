---
name: harvest-and-lots
description: Give every harvest a lot code the chain hangs from.
license: MIT
metadata:
  category: pantler
  source: authored in this repository from the farm pack's harvest record
---

# Harvest and lot identity

Use this when the operator says they picked, dug, cut or pulled something, gives you a lot number, or
asks which lot a sale, a delivery or a complaint belongs to.

A harvest is where a crop becomes a quantity you can sell, and the **lot** is the name that follows it
from there. Every later record — a pack-out, a delivery, a complaint, an inspector's question — either
points back at that name or points at nothing. That chain, from purchase or application through to the
sale, is what the organic duty carried in `skills-and-plugins.md` §4.6 asks for: records traceable
back to the last certified operation.

## What to ask for

Ask in the operator's own terms, before anything is written:

- the day it came off, and whether that is the day it was picked or the day it was packed;
- which block it came off — the name they use, not a name you assigned;
- what the lot is called, if they have a name for it;
- how much, and in what unit: kilograms, bunches, boxes, punnets, dozens, litres;
- anything they say that has no field — a buyer, a docket, a split, a bin number.

If they have no lot name, the convention is theirs to set, or the certifier's. Offer to keep whatever
they choose consistent; do not choose it for them.

## What to check

- **One harvest is one lot.** One picking can yield two lots if the operator says so, and that is two
  records — never one record carrying two codes.
- **The lot string is theirs, exactly.** No tidying, no reformatting. The record's own id — the pack
  numbers harvests `HAR…` — is not the lot: `lot` is the operator's string, and later records quote the
  lot, not the row.
- **A near-miss is a question.** If a lot string looks like a variant of one already on file, ask.
  Silently matching the two, or silently correcting the spelling, invents a fact about which produce is
  which.
- **A lot code is not re-used** for a later harvest, and two lots are never merged under one code.
- **A lot that spans two blocks** keeps the same `lot` string on both records, and `block` names which
  block each one came off.
- **The `block` is a reference, not a story.** It points at a `block` record, and that record's
  `certified` value is the certifier's answer, not yours.
- **The harvest date against the block's applications.** An application carries `earliest_safe_date`;
  if the harvest looks early, ask. That comparison is a date difference, and a tool does it.

## What to record

| Field | What goes in it |
|---|---|
| `lot` | the identity, exactly as the operator said it |
| `date` | the day it came off |
| `block` | the block record it came off |
| `quantity` | how much, as counted or weighed |
| `unit` | one of the pack's units — never converted to make it fit |
| `notes` | the facts below, in the operator's words |

The pack's other records hold the other end of the chain: `input` for a product and its label facts,
`application` for what went onto a block and when, `block` for where it is and what it may be sold as.
Read them; never overwrite a value a tool has frozen on them.

## Where a fact goes when there is no field for it

No record type yet holds a purchase, a sale, a dispatch or a pack-out. Until one does, the fact goes in
`notes` **on the record it belongs to**, and you say out loud that is where you put it:

| The fact | Where it goes today |
|---|---|
| supplier, docket or invoice number, batch on a bought input | `notes` on the `input` record |
| customer, the day it left, how much left, the docket number | `notes` on the `harvest` record, labelled as the sale |
| a split — part packed, part cold-stored, part sent on | `notes` on the `harvest` record, one line per part, each keeping the same `lot` |
| a paper label, certificate or docket | `notes` naming where the original is kept |

**Never invent a field name** — `lot_code`, `customer`, `dispatch_date` — and never describe a field as
though it existed. A fact written into an invented field is a fact the operator will not find again,
which is an audit trail with a hole in it.

## The chain, end to end

Walk it per block and say where it breaks: the supplier's certificate → the `input` on file → each
`application` to the block → the `harvest` with its `lot` → what left the farm, quoting that `lot`.
A gap named is a question the operator can answer; a gap filled in is a false record.

## Records are made when the work happens

A record made on the day is evidence; one written up before an audit is memory, and an inspector can
tell the two apart.

## The arithmetic is not yours

A total across lots, a conversion between units, the days from harvest to dispatch, the harvest date
against an `earliest_safe_date`, a mass balance against what was applied: each is a sum or a date
difference. Ask the tool, read back what it returns, and never state a number you worked out yourself.
Where no tool exists for it, say so, and leave the fact as the operator's own words.

## What to refuse

- a lot code you invented, derived or guessed;
- a quantity, unit or date you adjusted to make the chain line up;
- a statement that a lot is organic, in conversion or certified —
  [`organic-certification`](../organic-certification/SKILL.md) holds that line;
- a retention period, or how long any of this is kept: that is
  [`records-retention`](../records-retention/SKILL.md), and the period comes from the operator's own
  regime;
- an assurance that the chain is complete when a link is unattested.
