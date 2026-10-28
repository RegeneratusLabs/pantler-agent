# Which organic standards exist, and which may be quoted

One level deep, as the house rules require. This file answers one question for the assistant: **may I
quote this document, or may I only say where it is?**

The map was verified from the standards manifest in `AusOrganicBot` (MIT) and re-checked against
pantler's own licence ladder (`skills-and-plugins.md` §1). Nothing
here is standards text; it is a list of documents and their terms.

## The rule in one line

**The law can be pinned; the certifier's standard cannot.** National and supranational rules are
mostly reusable; the two Australian certifier standards are not, and those are the ones most
Australian operators are actually audited against.

## The map

"Position" is what pantler may do, not what the document's own terms allow in general.

| Jurisdiction | Document | Edition | Terms | Position |
|---|---|---|---|---|
| AU | National Standard for Organic and Bio-Dynamic Produce | 3.8 — **current** | CC BY 4.0 (Commonwealth of Australia) | **consume with attribution** — usable, not vendorable |
| AU | National Standard … | 3.7 — superseded | CC BY 4.0 | consume with attribution; **never cite as current** |
| AU | Australian Certified Organic Standard (ACO) | 2023 | All rights reserved, written permission required | **reject** — point at it; read the operator's own copy |
| AU | NASAA Organic and Biodynamic Standard | 2016 | *Unconfirmed — treat as all rights reserved* | **reject** — the honest default when a licence cannot be established |
| NZ | Organic Products and Production Act 2023 | No 14, as at 10 July 2026 | NZ Crown copyright — reproduction permitted | consume only, and treat the licence string as **unverified** until someone resolves it |
| NZ | Organic Products and Production Regulations 2025 | 2025/196 | NZ Crown copyright — reproduction permitted | as above |
| EU | Reg (EU) 2018/848 on organic production and labelling | OJ L 150, 14.6.2018 | EU legislation, reuse with attribution | consume with attribution |
| EU | Implementing Reg (EU) 2021/1165 (authorised products and substances) | OJ L 253, 16.7.2021 | EU legislation, reuse with attribution | consume with attribution |
| UK | Council Reg (EC) 834/2007, as retained | 2007 | **OGL v3.0** | **vendorable** |
| UK | Commission Reg (EC) 889/2008, as retained | 2008 | **OGL v3.0** | **vendorable** |
| UK | The Organic Products Regulations 2009 | SI 2009/842 | **OGL v3.0** | **vendorable** |
| US | USDA National Organic Program, 7 CFR Part 205 | 2025 | Public domain (US federal work) | **vendorable** |

Four of twelve are vendorable, six are consumable only, and two are refused.

## How to use the map

- **Quoting** a vendorable or consumable document is fine **only when it is in front of you** — the
  file the operator added, or the pinned copy the tool returned. Never from memory, never from a
  summary, never from another country's rule.
- **An ACO or NASAA standard is the operator's own copy.** Ask for it, read it, quote it back to them
  with the clause. Do not treat "I have seen it before" as having it.
- **Superseded editions stay listed on purpose.** A record made under an older edition was made under
  that edition; cite the one that applied on the date of the record, and say that it has been
  superseded.
- **Two editions can share an id** in the source manifest — the uniqueness key is `(id, edition)`. If
  you keep a copy of this map in data, do not key on the id alone.
- **A jurisdiction's rules are not interchangeable.** An input, a period or a labelling threshold from
  one scheme does not carry to another, and saying so is more useful than a comparison.

## What this file deliberately does not contain

No conversion periods, no buffer-zone widths, no retention periods, no labelling percentages, no
inspection frequencies, and no penalties. Every one of those is a number that changes by scheme and by
edition, and a number stated from memory is the failure this whole approach exists to prevent. Each is
one question to the operator's own document, or one to their certifier.

## If this map is kept as data

The shape worth copying from the source manifest, because it is what made this map trustworthy:
per source — `id`, `name`, `edition`, `status` (`active` or `superseded`), `effective_date`, `url`,
`sha256`, a `license` string, and a `redistribute` flag that **defaults to false**; a validator that
refuses `redistribute: true` without a declared licence; and retrieval that excludes superseded
editions rather than deleting them. Pantler's ladder is stricter than that flag, so the position
column above, not the flag, decides what may be quoted.
