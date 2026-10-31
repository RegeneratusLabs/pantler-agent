---
name: availability-list
description: Turn a spoken field walk into a what's-available list.
license: MIT
metadata:
  category: pantler
  source: distilled from the availability workflow in invoiceyarn (behaviour re-authored)
---

# The availability list

Use this when the operator walks the rows and tells you what is ready, or asks for the list they send
to chefs, shops and market customers.

This is a **forward-looking, unpriced** document: what is there, how much of it, and anything the buyer
needs to know. It is not an invoice and it carries no prices — a price belongs to a quote, an invoice
or a price list, and mixing the two is how an availability note becomes a disputed order.

## What the operator says, and what you take from it

The operator will talk while walking: quantities, units, comments about quality or timing, and asides
about customers and deliveries. Take the produce and leave the rest.

| They said | You take |
|---|---|
| "eight bunches of kale, the cavolo nero's small this week" | kale, 8, bunch; note on the cavolo nero |
| "tomatoes are done, we've got about two kilos left" | tomatoes, 2, kg, with a note that it is the last of them |
| "zucchini ready from Tuesday" | zucchini, with *ready from Tuesday* as its note — not on another item |
| "invoice that to Mary, drop it Tuesday" | nothing. That is an order or a delivery, not availability |
| "the kale, no wait, six" | kale, 6 — the last number wins |

Rules that keep it honest:

1. **Only what was said is on the list.** Never add a product because it is usually available, and
   never invent an item that was not spoken.
2. **When no quantity is given, ask.** Never write a quantity that was not said: a list is a
   promise, and the tool flags the line as `quantity to confirm` rather than guessing one.
3. **When no unit is given, use the unit the product is sold in** — bunches for kale, kilograms for
   tomatoes — and if the product is not in the catalogue, say the unit you assumed.
4. **Combine repeated mentions only when it is clearly the same thing twice.** "Kale and more kale" is
   probably one line; "kale, then cavolo nero" is two.
5. **The same item mentioned with a correction is one line**, with the corrected quantity.
6. **Notes stay with the item they were said about.** "Ready from Tuesday" attaches to whatever was
   being discussed, not to the list.

## Unmatched items are kept, not dropped

A grower with a new crop, or a name you do not recognise, is normal. Keep the line with the words the
operator used, flag it as not matching a catalogue product, and offer to add it to the catalogue — an
availability list that quietly drops the thing the chef is most interested in is worse than one with a
rough name in it.

## What the code does, and what you do

**Code:** normalises the unit, keeps a line with no quantity and flags it for you to ask about, matches
item names against the
catalogue with a scoring threshold, decides between accepting a match, offering alternatives and
asking, keeps the rows in the order they were spoken, and lays out the document.

**You:** read the intent out of spoken language, decide what counts as an aside, phrase the notes, and
ask when a match is genuinely uncertain. If a name sits between "clearly that product" and "something
else", show the operator what you think it is and let them choose — never pick silently.

## If there is no catalogue yet

The tool resolves every spoken name against the operator's price book, and it says so when there is
none: `plugins.entries.availability.pricebook_path` in `config.yaml`, or `PANTLER_PRICEBOOK`, or a
`pricebook.json` in the Hermes home. Pass that on and stop. The list itself is still worth building
without it — unmatched rows are kept as first-class rows on purpose — but the *names* stay exactly as
the operator said them, and nothing is priced.

## Before the list goes out

Read it back. A list leaving the farm is a commitment about what exists this week:

- quantities and units, as they will be read by a buyer;
- the general note, if there is one — picking days, delivery days, anything that applies to the whole
  list;
- the date, because an availability list without a date is a guess about which week it meant.

Then it is a page the operator can send: their business name and contact details, the date, the items
and quantities, and the notes. **No prices, no tax, no bank details** — those belong to the invoice
that follows.
