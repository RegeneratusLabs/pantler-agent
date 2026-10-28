---
name: speech-to-lines
description: Turn a spoken order into lines you read back first.
license: MIT
metadata:
  category: pantler
  source: distilled from the parser behaviour in invoiceyarn and the Phase 0 resolution rules in the design notes
---

# Speech into lines

Use this when the operator says something that becomes records: an order, a spray, a delivery, a
purchase, a batch. The sentence becomes **lines**, and every line is read back before anything is
created.

## The contract

**You extract names, quantities and units. Code resolves identity, price, tax, unit conversion and
totals.** You say what the operator said; the tool says what it means.

| The operator says | You pass on | Code decides |
|---|---|---|
| "twelve kilos of beans and four dozen eggs, to Bellview" | beans 12 kg, eggs 4 dozen, customer "Bellview" | which beans, which Bellview, the price, the tax, the total |

**Never state a number you were not given by the tool.** Not a price, not a total, not a tax amount,
not a conversion. If the operator asks what it comes to, that is a question for the tool, not for you.

## Never invent

An item, a customer, a quantity, a unit, a delivery day. If it was not said and it is not in the
records, it does not exist yet — and the honest answer is a question.

## The transcript will be wrong

Speech recognition mangles produce names and numbers: "eight months of the kale" is eight bunches of
kale, "three range eggs" is three free-range eggs, "a punnet of cherry toms" is one punnet. Read the
intent, and let the read-back catch you.

The distinction that matters: **a wrong-sounding word that changes *how much* is safe to interpret; a
wrong-sounding word that changes *what* is not.** "Kale" heard as "cale" is fine — the catalogue
resolves it. "Carrots" heard as "parsnips" is not: say what you heard and ask.

## Self-corrections and asides

- **The last number wins.** "Six — no, eight" is eight. "The usual, make it a box" is a box.
- **Asides are not lines.** "Invoice that to Mary", "drop it Tuesday", "they still owe me" — those are
  a customer, a delivery instruction and a note. They belong on the record, not in the item list.
- **Repeats combine only when they are clearly the same line.** "Beans, and more beans" is one line;
  "beans, then beetroot" is two.

## Ambiguity has three levels, and you never skip the third

1. **Exact** — one product matches. Carry on.
2. **Plausible** — one or two close matches. Offer them, in the operator's words, and let them pick.
   Never choose on their behalf, however obvious it looks.
3. **Nothing** — no match, or a match that is wrong in a way that matters. Ask, or keep the line with
   the words the operator used and mark it unmatched, so nothing is lost.

The same ladder applies to a customer name. Two customers can share a first name, and billing the
wrong one is worse than a question.

## Units are where quiet errors live

If the catalogue sells an item by the dozen and the operator said kilos, **say so**: "Eggs are sold by
the dozen — how many dozen?" Do not convert silently. If the tool supplies a conversion, use it and
show it; if it does not, ask.

## Read back before creating

Before anything is written, say the lines back — item, quantity, unit, customer, and any date — and
name what you could not match or had to guess. One short block, not a paragraph. Then create.

If the operator corrects something, fix that line and read the whole thing back again. A record made
from a half-corrected conversation is worse than one made twice.

## When the tool is not available

Say so plainly and keep the operator's words intact — the transcript, or the sentence they said. A
record written down late beats a record invented now.
