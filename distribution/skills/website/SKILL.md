---
name: website
description: Make a one-page website or landing page.
license: MIT
metadata:
  category: pantler
  source: authored in this repository; the page generator, blueprints and checks are the studio plugin's
---

# Website

Use this when the operator wants a website, a landing page or a page to send people to. It makes a
local page they can open and hand to a host later. It does not publish, deploy or buy a domain.

A card or poster is `design`; a PDF to print or send is `documents`; captions with no page are
`social-post-batch`. "Does my site look right?" about a site that already exists is `design-review`.

## The first reply is the job

**Do not call `record_types` or `record_find` before the first reply.** A page is built from the
operator's words; if it needs a product, a price or a market day, ask. The records can be read after
they answer, and a draft with a marked blank is better than a records survey.

A website request is usually four facts short: what the business is called, what it sells, where it
is, and how someone buys. Ask for the two that change the page most, then make a draft.

> Yes — I'll make a one-page site: what you sell this week, how to order, and where to find you.
> Two things: what should the first line say, and do people order by phone, message or at a market?
> If you don't have the words yet, I'll draft the page and mark the blanks.

- **Ask at most two questions.** The rest can be a marked blank in the draft.
- **Make the draft when the words are enough.** A marked blank the operator can fill is better than
  a third question.

## The brief

| What | Where it comes from |
|---|---|
| Business name | the operator; never the profile id |
| What they sell | the operator, or a product record they pointed at |
| Where they are | the operator; never a guessed town |
| How to buy | the operator — phone, message, market, order form |
| The first line | their words, or one short line you offer for approval |
| Photos | only files they supplied; otherwise type and colour |

A page that has no answer for "how do I buy?" is a poster, not a website. The generator refuses one,
which is the point.

## The look comes from the brand

Read `output/brand/brand.json` first — the same file `design` and `brand-identity` write. It gives the
page its ground, ink, accent and type pairing, so the site and the cards are visibly the same
business.

- **No brand yet?** Do not invent one. Ask the two questions in `brand-identity` (how it should
  feel, where people meet it first), save a starter kit, and build from it.
- **Fonts travel with the page.** The generator copies the pairing's licensed files into
  `assets/fonts/` and declares them itself. Never fetch a font from a CDN.
- **The same direction as the cards**, so the page's type and accent match the post announcing it.

## Choose a blueprint, then build

Ask `design_templates` for the library and pick one of the three blueprints:

| Blueprint | Order | For |
|---|---|---|
| `producer` | opening · what's ready · a short text · proof · contact | a farm, a market garden, a maker |
| `order` | opening · what's ready · the action · contact | a box scheme or a delivery business |
| `stall` | opening · where and when · what's coming | a market stall |

Then build it with `design_page`:

```json
{"spec": {
  "blueprint": "producer",
  "brand": "output/brand/brand.json",
  "out": "output/site",
  "content": {
    "name": "Bellview Garlic",
    "tagline": "Hardneck, from the hills",
    "eyebrow": "Pomona markets · Saturdays",
    "opening": "Garlic grown on the hills at Bellview, picked the week you get it.",
    "sections": [
      {"kind": "list", "title": "What's ready", "items": ["Hardneck garlic | $18/kg", "Honey 500 g | $14"]},
      {"kind": "text", "title": "How we grow", "body": "One block, hand-planted in April."},
      {"kind": "proof", "title": "You can check us", "items": ["Certified organic since 2019"]},
      {"kind": "contact", "title": "Find us", "lines": ["Pomona markets, Saturdays 7–1"]}
    ],
    "footer": "Bellview Garlic · Pomona"
  }
}}
```

- **The tool writes the page, not you.** It owns the CSS, the type scale, the section order and the
  checks. Do not hand-write HTML beside it: a page nobody measured is the thing this replaced.
- **Sections are few on purpose** — `list`, `text`, `proof`, `contact`, `action`. A producer has
  three true facts, not nine features. If you want a feature grid, the page is for the wrong
  business.
- **Never invent a fact.** A price, phone, address, certification or review is theirs. Leave
  `[TOWN]`, `[PHONE]`, `[PRICE]`; the report lists every one.
- **One image, with alt text.** A photo they supplied, described honestly. No stock, no generated
  produce.

The argument behind the order, and the three archetypes, are in
[`references/pages.md`](references/pages.md).

## What comes back

- `index.html` — the page, with its CSS in one block and its fonts beside it.
- `assets/fonts/` — the licensed faces the page uses.
- `preview-desktop.png` and `preview-phone.png` — the **first screen** at 1280 and 390, when a
  browser is available. They are previews, not the whole page; say so.
- `report.json` — every check, and every placeholder still to fill.

If no browser is found the report says so and no preview exists. Say that plainly rather than
describing a page you have not looked at.

## Check before hand-over

- `report.ok` is true. If a hard check failed, fix the brief and build again.
- Read both previews with `vision_analyze`: the opening line and the action are the first things a
  reader sees, and nothing is cut off at 390.
- Every blank is listed, and every price, phone and address came from the operator.
- The page does not claim to be live, published, indexed or hosted.

## Hand it over

- Put the HTML path and both preview paths in the reply.
- Use `MEDIA:/absolute/path.png` on a line of its own for each preview.
- Say what is a placeholder in one line, and what you need to replace it.
- Say plainly that this is a local file: publishing needs a host and a domain, and that is a
  separate decision.
- Offer one revision.

## What not to do

- Do not publish, deploy, buy a domain or promise a URL.
- Do not invent a business fact, a price, a review, a certification or a photo.
- Do not use Pantler's brand on the operator's page.
- Do not fetch a font, a script or an image from the network.
- Do not hand over only a screenshot; the HTML is the thing they keep.
- Do not use the engine's bundled web-design skills in this product.
