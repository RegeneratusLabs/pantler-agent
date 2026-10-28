# Pantler

**The assistant that does the paperwork for your food business.**

Pantler lives on your own computer. You talk to it the way you would talk to a good office
manager — *"invoice Bellview for last week's boxes"*, *"log the copper spray on the north block"*,
*"draft a post about the new honey"* — and it keeps the records, writes the document, and shows
you what it is about to send before it sends it.

Your records stay in your files, on your machine. There is no Pantler account and no cloud in the
middle: the only thing that leaves your computer is the model call you configure yourself.

---

## What it takes off your desk

| | |
|---|---|
| **Invoices** | Drafts from your own price book — customers, items, quantities, tax — with the totals worked out by code, not guessed by a language model |
| **Spray and harvest records** | Block, product, rate, date, withholding period; the record is saved, and the tool says so or says it could not |
| **Certification and compliance** | Organic certification, EUDR due diligence, packaging and EPR, and record retention — as procedures the assistant follows, with the questions it must ask first |
| **Labels and product copy** | Descriptions, batch labels, and the rules that decide what may be claimed |
| **The writing nobody has time for** | Supplier email, newsletters, social posts in batches, and replies to reviews |
| **Jobs that repeat** | A task plus a day and a time, in your words. Pantler runs it and keeps the output where you can read it |
| **Your own records** | Ask for a new kind of log — a flock, a paddock, a batch — and it becomes a page that lists it, exports it as CSV and prints it |

Twenty-one skills ship in the box, and eight plugins give the assistant its hands: records, soil
amendments, spray, availability, claims, consent, connectors and the profile guard.

## Why it is built this way

**Your data is yours.** Records, invoices, attachments and conversations live in files on your
machine. Nothing is uploaded, and there is no subscription to lose access to.

**The model never does arithmetic.** It reads your intent; deterministic code resolves the
customer, the price, the unit and the tax. When it is not sure, it asks instead of guessing.

**Nothing goes out in your name without you.** Sending an email, moving money, changing a price,
deleting a record, or creating a future-dated entry stops at an approval card. You see exactly
what would be sent.

**It connects to the tools you already use.** Twenty services — Gmail, Outlook, Google Calendar,
Sheets, Drive and Docs, QuickBooks, Square, Stripe, Mailchimp, Canva, Shippo and more — through
your own Composio account, with a key you provision yourself. Reads go straight through; writes
wait for your approval.

**One business, one profile.** Run two businesses from one machine and neither can see the
other's workspace, records or credentials.

## Getting started

You need **Python 3.11 or newer**, **Node 24**, and the [Hermes](https://github.com/NousResearch/hermes-agent)
engine — the open-source agent runtime Pantler is built on. Pantler pins one commit of it, so the
behaviour you test is the behaviour that ships.

```sh
# 1. The engine, at the pinned commit (a tag can move; the commit cannot).
git clone https://github.com/NousResearch/hermes-agent.git
PIN_COMMIT="$(python3 -c 'import json;print(json.load(open("engine-pin.json"))["commit"])')"
git -C hermes-agent checkout --detach "$PIN_COMMIT"
hermes-agent/setup-hermes.sh

# 2. Pantler, installed as a Hermes profile.
hermes profile install ./distribution --name pantler -y

# 3. A model. Any provider the engine supports — Pantler supplies no key of its own.
hermes -p pantler config set model.provider <provider>
hermes -p pantler config set model.default  <model>
hermes -p pantler config set approvals.mode manual

# 4. Start it.
hermes gateway run
```

In a second terminal, the app:

```sh
PYTHONPATH=core/src python app/server/pantler_server.py --port 8650 --profile-dir ~/.hermes/profiles/pantler
cd app/web && npm ci && npm run dev
```

Open **<http://127.0.0.1:5175>** and ask it for an invoice. `examples/bellview/` is a fictional
business with a price book, so the invoice tools have something to read before you add your own.

## A first week with it

1. Answer the four setup questions — what to call you, your business, what it does, how you sound.
2. Import your price book, or copy `examples/bellview/pricebook.json` and edit it.
3. Ask for one real thing: *"invoice Acme for 40 boxes of cos lettuce at last week's price"*.
4. Approve it, and check the record on the Records page.
5. Add the job you forget: *"every Monday at 7, remind me what needs spraying this week"*.

## Requirements, honestly

- **Your own model key.** Pantler does not pay for inference and does not proxy it for you.
- **A local machine that can run the engine.** This is a desktop-class tool, not a hosted service.
- **The skills lean Australian.** Organic certification, labelling and retention rules cite
  Australian frameworks. The structure travels; the citations do not.

## Status

**Early release, 0.0.1.** The assistant works end to end and the test suites are green, but this is
the first public cut: paths will change, and records written today are worth copying somewhere
safe until automatic backup lands.

## Open source

MIT — see [LICENSE](LICENSE). Skills, plugins, packs and the app are all in this repository, with
no closed parts. The Fraunces typeface in `brand/font` is under the SIL Open Font License, included
beside it.

Want to build on it? [ARCHITECTURE.md](ARCHITECTURE.md) explains how the pieces fit and the rules
that keep them apart; [CONTRIBUTING.md](CONTRIBUTING.md) has the working tree and the test commands.

Found a security problem? Please read [SECURITY.md](SECURITY.md) and report it privately.
