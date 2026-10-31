---
name: brand-identity
description: Give a business a name, mark, colours and type.
license: MIT
metadata:
  category: pantler
  source: authored in this repository; the renderer is the studio plugin's, and the interview is drawn from the product's own brand work
---

# Brand identity

Use this when the operator has no logo, no colours, no consistent look — or when they have one and
everything they make looks like a different business. The job is not a logo. It is **a decision they
can keep making from**, written down once so every later card, page, sign and label belongs to the
same business.

A designed card is `design`; a page is `website`; a photo is `product-photos`. This skill owns the
identity those three are built from.

## Before anything: does a brand already exist?

Look for `output/brand/brand.json` in this workspace. If it is there, read it and build on it — do
not interview again, and do not quietly replace it.

If it is not there, the business has no contract yet, and the honest answer is that you cannot make
a consistent design without one. Do not invent colours and call it their brand. Run the interview
below, then save the kit. **A design job with no brand starts one** — that rule is what stops the
operator receiving six unrelated looks.

## The interview

Two waves. The first is two questions, answerable on a phone. The second is one short list, every
item optional. Never more than this, never a form, never a survey of their records.

### Wave one — in the first reply

Name the job in one line, then ask exactly these two:

> Yes — I'll set you a brand you can design from: a mark, a colour or two, and the type. Two things:
>
> **1. How should it feel?** Pick the closest — *warm and rustic*, *clean and modern*, *bold and
> market*, *quiet and editorial*, or *playful and handmade*.
>
> **2. Where will people meet it first?** A feed, a market stall, a label, or a website.

If they cannot choose, offer your reading in one line and let them correct it: "From what you've
told me — garlic, a stall, a label — I'd say bold and market. Say if that's wrong."

### Wave two — after they answer, one list

> Four more, and anything you don't have is a fine answer:
>
> 3. Do you already use a colour — or one you'd never use?
> 4. Do you have a logo file? If yes, its path. If no, "none" is the answer.
> 5. How is the name written — as it is, lower case, or with a line under it?
> 6. What should it look like it costs — everyday, honest mid, or special?
>
> And if you have two or three things you like — a shop, a label, a photo, a link — send them.

The full question set, with what each answer changes and what to do when the operator does not
answer, is [`references/interview.md`](references/interview.md). Read it once before the second
wave; it is the difference between an interview and an interrogation.

## From answers to three directions

Never present one look as the answer. Call `design_brand` with `stage: "directions"` and the
answers; it deals three directions that fit the posture and renders a board for each — colours, type
specimen, the argument for it.

```json
{"stage": "directions",
 "answers": {"name": "Bellview Garlic", "tagline": "Hardneck, from the hills",
             "posture": "warm", "kind": "market garden",
             "avoid_directions": ["06-bread-and-ledger"]}}
```

Then show the three boards (each PNG with `MEDIA:` on its own line) and ask **one** question: which
of these is closer to you? Say what each one is for in a line, and say which you would pick and why.
Do not blend two; a kit that is half of each is nobody's.

If none of the three is right, ask which one is closest and change one thing — the accent, the
display face, the case of the name — rather than dealing a fresh set.

## Saving the kit

Call `design_brand` with `stage: "save"` and the chosen direction, their colours and their type.
It writes:

- `output/brand/brand.json` — the contract every later design reads;
- `brand-sheet.png` — colours with their hex and measured contrast, the type in its three roles,
  and the usage rules;
- `wordmark-horizontal`, `wordmark-stacked`, `wordmark-monogram` — SVG and PNG;
- `icon-1024/180/32/16.png`.

Then say, in one line each: this is a **starter** identity; a designer should review it before it
goes on packaging or a sign; and Pantler has not run a trademark search. If the operator confirms it
after seeing it used, save it again with `status: "confirmed"`.

## The mark

The mark is type-led: the business's name set properly, with an optional monogram for the icon. That
is a real, defensible identity for a small producer, and it is honest about what it is.

- **One colour**, on the ground. No gradient, no shadow, no outline, no badge, no swoosh.
- **Clear space** is half the mark's height on every side. The sheet states it; keep it.
- **Minimum sizes** are on the sheet. Below them the monogram survives and the name does not.
- **Never redraw the operator's existing logo.** If they have a file, place it on the ground at its
  own proportions and build the palette and type around it. Do not trace it, recolour it, add a
  frame or "modernise" it.
- **No fake mark.** A leaf, a sun, a wheat sheaf or a stylised animal drawn by a model is the visual
  equivalent of an invented testimonial. If they want an illustrated mark, say plainly that this is
  beyond what the studio draws and a designer should make it.

## The colours

Take theirs when they have them. When they do not, use the direction's palette and say it is a
starting point they can change. The tool measures every pair: ink on ground must clear 4.5:1, and an
accent that cannot carry type is used as a rule or a fill, never as words. Never "adjust" a colour
until it passes — choose a different one.

## What this skill will not do

- It will not invent a name, a tagline, a story, a date, a certification or a claim.
- It will not present a starter kit as a finished identity, or claim a trademark search.
- It will not produce a full identity system (stationery, packaging dielines, a typeface). Say what
  it does produce, and what a designer is still for.
- It will not put Pantler's own brand on the operator's business.

## Hand it over

`MEDIA:` the brand sheet, then the three wordmark PNGs, then the 1024 icon. Give the path to
`brand.json` and say every later design will read it. Ask for one change, not a redraw.
