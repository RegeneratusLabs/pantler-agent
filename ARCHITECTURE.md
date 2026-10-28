# How Pantler is put together

Five pieces, each with one job, and the rules that keep them from leaking into each other. The
rules are requirements, not preferences: breaking one makes the thing unsafe.

```
app/          the application      React shell · Python BFF · shared wire types
  ↓ talks to
engine        Hermes, pinned       the agent loop, tools, approvals, sessions
  ↑ loads
distribution/ the installed profile SOUL.md · config · packs · plugins · skills
  ↑ declared by
packs/        record types         farm · money · trade
  ↑ implemented by
plugins/      tools                soil · spray · records · availability · claims · consent · connectors
  ↑ built on
core/         the kernel           pack parsing · the record store · the pack vocabulary
```

## The pieces

**`core/` is the kernel.** It parses pack declarations and answers questions about them, and it
owns the record store. It is standard library only: it imports no engine, no LLM client and no
transport. `scripts/check-seam.py` is that claim as a build failure — it parses every module and
fails on an import that leaves the package.

**`packs/` declare records.** A pack is a `pack.toml` naming the record kinds a business keeps —
blocks and applications, invoices and lines, consent and campaigns — with their fields, their
units and the screens that show them. The kernel knows record *types*, never meanings.

**`plugins/` expose tools.** A plugin is a Python package with a `plugin.yaml` and a `tools.py`,
loaded by the engine as tools the assistant can call. Eight ship. Each one's promise is the same:
**the tool result is the record.** If the plugin cannot reach the store it says `saved: false`,
and the skill passes that on. Nothing claims more than it did.

**`distribution/` is the installed profile.** It is what `hermes profile install` copies: the
persona (`SOUL.md`), the config that enables the plugins, the packs, the plugins and twenty-one
skills. `distribution.yaml` declares which paths the distribution owns; everything else in a
profile — memories, sessions, credentials, records, attachments — belongs to the operator and
survives an update.

**`app/` is the interface.** `app/web` is the React shell, `app/server` is the BFF that stands
between the browser and the engine, and `app/shared` is the contract they share. The BFF is the
only thing that holds an engine key; the browser never does.

## The rules

1. **The model never computes.** It extracts intent; deterministic code resolves IDs, prices, unit
   conversions and tax. Low confidence becomes a question, never a guess.
2. **The kernel stays domain-neutral.** An invoice is a pack's declaration, not something `core/`
   has heard of. If a new market needs a kernel, engine or shell change, the pack boundary is
   wrong.
3. **Nothing outbound without a human decision.** Sending in the operator's name, moving money,
   changing a price, deleting or merging records, or creating a future-dated record stops at the
   engine's approval card.
4. **One business's data stays in its profile.** The assistant's file, terminal, vision and
   browser tools may use the active profile's workspace, its uploads and its own state. Another
   profile's workspace, output or state is refused, and the app's by-path previews are scoped the
   same way.
5. **Pin the engine, never track `main`.** `engine-pin.json` names a commit; the build asserts the
   checkout is at it. A tag can move, so the tag is a label and the commit is the fact.
6. **MIT only in the shipped path.** Copyleft is fine over HTTP, never vendored.
7. **Assert the tool surface.** `baseline/pantler-toolsets.json` is the captured surface; a change
   to it fails the build until somebody re-captures it deliberately. It is a change detector, not
   a security control.
8. **First-party content only.** Skills execute Python when they are imported and plugins run with
   the app's authority, so nothing third-party enters a user's install.

## The vendored kernel

Each plugin carries its own copy of `pantler_core` under `vendor/`, because the engine loads a
plugin as a self-contained package. The copies are generated, never hand-edited:

```sh
./scripts/check-distribution.py --sync-plugins   # after any change under core/
```

`scripts/check-distribution.py` also checks the distribution's own coherence: that every skill the
manifest lists exists, that no skill cites a path the payload does not carry, and that the shipped
plugins are the plugins. CI runs it, so the copies cannot drift silently.

## The tests

| Command | What it proves |
|---|---|
| `./scripts/test.sh python` | the seam, the distribution preflight, the kernel, the harness scripts, the BFF, every plugin |
| `./scripts/test.sh web` | typecheck, the identity guard, the unit tests |
| `./scripts/test.sh engine` | the engine pin and the captured tool surface |

The Python tests use `unittest`, not pytest: the kernel promises `dependencies = []`, and a test
runner that has to be installed undercuts that for no benefit at this size.
