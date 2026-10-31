---
name: invoicing
description: Draft an invoice from the price book, never guessing.
license: MIT
metadata:
  category: pantler
  hermes:
    tags: "invoicing, drafting, customers, prices, gst"
---

# Invoicing

How drafting works. Read this before creating an invoice.

**Drafting only.** There is no send tool and no approval step: nothing here leaves the
business. Sending, payments and the rest of money handling are not built yet, and when they
are they will live in their own pack rather than here. If the operator asks you to send an
invoice, say plainly that you can prepare the draft but cannot send it.

## The one rule

You never work out a price. The price book holds every customer, every item, every price
and the tax rate. Your job is to say what the operator said; `invoice_create` resolves it.
If a price looks wrong to you, say so and let the operator change the price book — do not
adjust the number yourself.

## Creating a draft

1. Call `invoice_create` with the customer and the lines exactly as the operator described
   them: the item words, the quantity, and the unit. Pass the unit the operator used
   ("kilos", "dozen") and let the tool convert it.
2. Read the draft back. It is a draft, and nothing has been sent.
3. If the tool asks which customer or which item you meant, ask the operator in one short
   question and call the tool again with their answer. Never pick one yourself.
4. If the tool says the price book is not configured, that is the operator's first-run step:
   tell them the setting to add (`plugins.entries.pantler.pricebook_path` in `config.yaml`,
   or a `pricebook.json` in their Hermes home) and stop. Never invent a customer, an item or
   a price to get past it.

## Looking one up

`invoice_show` takes an invoice number and reads the draft back. Use it when the operator
refers to an invoice by number instead of describing it again.

## When something does not add up

- **The customer name matches more than one account.** Ask. Two customers can share a
  first name.
- **The item is not in the price book.** Say what is in the price book. Do not bill a
  similar item instead.
- **The unit does not fit the item.** Eggs are sold by the dozen, not by the kilo. Ask
  how many.
- **Tax is missing from the total.** The operator has not set a tax rate yet. Say the
  total excludes tax rather than applying a rate you found somewhere.

## Delivery days

A customer's delivery day is a fact, not a skill: it lives in memory, or in the customer's
record when one exists. If the operator names a delivery day, use the day on file — say which
day is on file and ask which they mean if it differs. The draft carries no date unless
`invoice_create` returns one; never quote a date the tool did not return.

## Recurring work

Standing orders and repeat customers are not built yet. Until they are, create each
invoice explicitly and tell the operator you have done so.
