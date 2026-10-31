# Contributing to Pantler

Thanks for looking. This is a small project with a firm idea of what it is, so the fastest way to
land a change is to know the shape of it before writing code.

## Before you start

Open an issue describing the problem and the smallest change that fixes it. If the change is
user-visible, say what the user sees before and after. If it is ambiguous, we will ask rather than
guess — an assistant that quietly does the wrong thing is worse than one that asks.

## Getting a working tree

```sh
# Python 3.11+ and Node 24.

# 1. The engine, at the pin, in an isolated home so your own install is untouched.
export HERMES_HOME="$PWD/.hermes-dev"
PIN_COMMIT="$(python3 -c 'import json;print(json.load(open("engine-pin.json"))["commit"])')"
git clone https://github.com/NousResearch/hermes-agent.git "$HERMES_HOME/src/hermes-agent"
git -C "$HERMES_HOME/src/hermes-agent" checkout --detach "$PIN_COMMIT"
"$HERMES_HOME/src/hermes-agent/setup-hermes.sh"
export ENGINE="$HERMES_HOME/src/hermes-agent/.hermes/bin/hermes"

# 2. Install the distribution as a profile and point it at the working tree.
"$ENGINE" profile install "$PWD/distribution" --name pantler -y
mkdir -p "$HERMES_HOME/profiles/pantler/plugins"
for plugin in plugins/*/; do
  ln -sfn "$PWD/${plugin%/}" "$HERMES_HOME/profiles/pantler/plugins/$(basename "$plugin")"
done
cp examples/bellview/pricebook.json "$HERMES_HOME/profiles/pantler/pricebook.json"

# 3. A model. Any provider the engine supports; the app supplies no key.
"$ENGINE" -p pantler config set model.provider <provider>
"$ENGINE" -p pantler config set model.default  <model>
"$ENGINE" -p pantler config set approvals.mode manual
```

Then, in two shells:

```sh
"$ENGINE" gateway run
PYTHONPATH=core/src python app/server/pantler_server.py --port 8650 --profile-dir "$HERMES_HOME/profiles/pantler"
cd app/web && npm ci && npm run dev
```

## What a change has to pass

```sh
./scripts/test.sh python
./scripts/test.sh web
./scripts/test.sh engine     # needs a gateway for the tool surface; skips honestly without one
```

CI runs the same three commands. A pull request that adds behaviour without a test for it will be
asked for one, and a change that moves the tool surface without re-capturing
`baseline/pantler-toolsets.json` deliberately will fail.

A merged change is carried into the next release. Releases replace the published tree but keep
the history, so your commit stays in it.

If you changed anything under `core/`, regenerate the vendored copies first:

```sh
./scripts/check-distribution.py --sync-plugins
```

## The two rules most likely to bite

- **Do not hand-edit `plugins/*/vendor/`** (or `distribution/plugins/`). They are generated from
  `core/` and CI will disagree with you.
- **Do not add a dependency to `core/`.** It is standard library only, and `check-seam.py` fails
  the build if it is not. The same applies to the plugins and the BFF: they are standard library
  Python. The web app's npm closure is the only dependency surface, and it is licence-checked.

## Where to put things

- A new record type belongs in a pack, not in `core/`.
- A new tool belongs in a plugin, with the kernel vendored by the sync script.
- A new prompt or procedure belongs in a skill under `distribution/skills/`.
- A new screen belongs in `app/web/src/pages/`, and its data comes through the BFF — never a
  direct engine call from the browser.

[ARCHITECTURE.md](ARCHITECTURE.md) explains why each of those is where it is.

## Licence

Contributions are accepted under the MIT licence in [LICENSE](LICENSE) — in and out the same.
By opening a pull request you confirm you have the right to contribute the code under it.
