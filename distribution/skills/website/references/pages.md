# A one-page site, as an argument

A landing page for a food business is not a brochure. It is a page that has to answer three
questions before somebody closes it: *what is this, is it for me, and how do I get it.* Everything
else is decoration.

## Write the argument before the page

List the page as claims, one per line, each with the proof that belongs under it. Then delete every
section whose claim is empty.

> **Claim** — "Picked the morning you get it."
> **Proof** — the harvest card, the delivery day, or a photograph of the crate with the date.
>
> **Claim** — "One farm, one box."
> **Proof** — the boxes the business actually sells, and the day they go out.
>
> **Claim** — "You can check us."
> **Proof** — the certificate number, the producer's name, the address of the stall.

If a claim has no proof, it does not go on the page. That is the same rule as the cards and the
captions, and it is what stops a site making a promise the business has to walk back.

## The sections, in order

Only the ones with something real in them.

| Section | What it holds | What it must not do |
|---|---|---|
| **Opening** | one line: what they do, who for; one action beside it | a carousel, a video, a slogan with no noun |
| **What is ready** | three to six items, no invented prices | a grid of nine "features" |
| **How to buy** | the one action, in plain words, repeated | three competing actions |
| **Find us** | the market, the address, the phone — only the ones supplied | an embedded map with no address |
| **Proof** | a certificate number, a review with permission, a photograph of the actual thing | a logo wall of brands that are not customers |
| **Footer** | a plain line, the remaining blanks | social icons for accounts that do not exist |

### Three page archetypes

These are the three blueprints `design_page` builds; pick one before writing any words.

1. **`producer`** — the producer's page: opening, what's ready, a paragraph in the grower's own
   voice, proof, contact. The page you send someone who asks what you do.
2. **`order`** — the order page: opening, what's ready, the one action, contact. For a box scheme or
   a delivery business. The blueprint refuses a page with no action.
3. **`stall`** — the stall page: opening, where and when, what's coming. The page is a sign; the
   whole thing fits on one phone screen.

Pick the archetype before you write any HTML. A page that is half of each is the page that says
nothing.

## Typography on a page

- **One display face for the opening**, one text face for everything else. The studio's pairings are
  built for this; take the brand's.
- **The opening is 48–72 px at 1280**, and it never wraps into more than three lines. If it needs
  four, the sentence is too long.
- **Paragraphs are 16–19 px, 55–75 characters wide.** A full-width paragraph at 1440 is unreadable.
- **Two or three sizes below the opening.** Not six.
- **Uppercase labels take tracking**; body copy never does.

## Layout rules that stop the page looking generated

- **A grid you can name**: one column, or a 12-column grid with a 2-column offset. Not "whatever fits".
- **Alternating full-bleed and inset sections** is fine; alternating tinted cards is not.
- **One accent**, used for the action and one word. Not for every heading.
- **Real photographs, or none.** A stock photo of hands holding soil is the fastest way to look like
  every other farm site.
- **No icon row.** Three icons with captions is the most recognisable generated-page shape there is.
- **The footer is quiet.** It is not another call to action.

## The check before hand-over

`scripts/render_site.py` runs the measurable checks — overflow, clipping, title, alt text, contrast,
placeholders — and writes desktop and phone previews when a browser is available. Then read the two
previews with the vision tool, and ask the three questions from the top of this page: what is this,
is it for me, how do I get it. If any answer takes more than a glance, the page is not finished.
