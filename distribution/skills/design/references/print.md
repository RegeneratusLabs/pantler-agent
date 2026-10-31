# Print, signs and label proofs

A screen card is forgiving: a phone rescales it, a thumb scrolls past. Print is not. A sign with the
wrong trim is a bin liner.

## Sizes

| What | Template | Finished size | Render |
|---|---|---|---|
| Poster | `poster-a3` | A3 297 × 420 mm | SVG at mm, 300 dpi PNG proof |
| Stall sign | `sign-a3` | A3 420 × 297 mm | SVG at mm, 300 dpi PNG proof |
| Menu or price list | `menu-a4` | A4 210 × 297 mm | SVG at mm, then `documents` for the PDF |
| Label front | `label-proof` | 100 × 150 mm | proof only — see below |

The print templates derive their pixel size from the millimetres and the dpi, and the SVG is written
with `width="297mm"`, so it opens at A3 in a print application instead of at "3508 pixels". The
report says `physical_mm`; quote that, not the pixels.

State the size in millimetres in the reply. A pixel size is not a print size.

## Bleed, trim and margin

- **3 mm bleed** on every edge for a cut piece. The artwork extends into it; no words do.
- **Trim** is the finished edge. Every word and every logo's clear space sits inside it.
- **Safe margin** is 5 mm inside the trim for a sign, more for a menu.
- A background colour or a photograph must reach the bleed edge, or the cut shows a white hairline.

## Type

- **2.5 mm cap height is the floor** for anything read at arm's length; below that it is decoration.
- **At three metres** — a stall sign — the headline wants 25 mm or more. Measure the viewing
  distance, then the type: roughly 1 mm of cap height per 300 mm of distance, doubled for comfort.
- **Tracked capitals** on a sign read better than mixed case at distance; tracked lowercase does not.
- **Reverse type** (light on dark) looks heavier in print. Go one weight lighter than you would on
  screen, and never set a paragraph reversed at small size.

## Colour

- **Ink on ground 4.5:1 minimum**, exactly as on screen. Sunlight and cheap vinyl only make it worse.
- **Rich black** (`#000000` with the printer's own build) for large areas; a four-colour "looks black"
  prints muddy.
- **No RGB-only accents** that the printer cannot match. If they ask for a Pantone, that is their
  printer's conversation, not ours.

## Label proofs — the honest boundary

A label has mandatory particulars: product name, net quantity, ingredients, allergens, a lot or
date mark, the producer's name and address, and — where it applies — country of origin, storage and
use-by. **Those are not this skill's to invent.** `labelling-honey-and-juices` and
`packaging-and-epr` own the checklist for the products this product serves, and the label proof is
where they are checked against the actual artwork.

What the studio contributes to a label is the layout: the panel, the type sizes, the contrast, the
room the particulars need. It does not decide what must appear, and it never draws a certification
mark — that artwork belongs to the certifier and is licensed to the business, not to us.

## Handing print work over

- The **SVG** is the deliverable; the PNG is a proof for the chat only.
- Name the file by what it is and the day: `market-sign-a3-2026-11-01.svg`.
- Say the finished size, the bleed and the colour of the ground in one line.
- Say plainly that the file has not been checked by a printer, and that a proof is the next step.
- Fold, hole and eyelet positions are the operator's or the printer's decision. Do not invent them.
