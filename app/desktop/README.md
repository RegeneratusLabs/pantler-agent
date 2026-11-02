# The desktop host

The Electron shell that makes the web bundle an installed application. The plan is
the desktop notes; this file is how to work on it.

## The shape

```
main process        src/main.mjs          window, single instance, first-run key, boot order
  supervisor        src/supervisor.mjs    spawn, log, restart with backoff, deliberate stop
  paths             src/paths.mjs         where the payload, profile and logs live; readiness
  preload           src/preload.mjs       the renderer's only door (almost empty on purpose)
```

The window loads the **BFF's** origin, not the engine's. The BFF serves the built shell and forwards
`/seam` with the engine's key, so the renderer never holds a credential and the engine stays on
loopback.

## Payload contract

`src/paths.mjs` is the contract with the staging script:

```
<resources>/shell/          app/web/dist
<resources>/server/         app/server
<resources>/packs/          packs/
<resources>/runtime/        CPython, the engine at the pin, site-packages, launcher
<userData>/engine/          HERMES_HOME — profiles, sessions, records, credentials
<userData>/logs/            child output
```

User data never lives under `<resources>`: an update replaces the payload.

## Development

```sh
# the fast loop: the browser build, with the shell loading the dev server and supervising nothing
PANTLER_DEV_URL=http://127.0.0.1:5175 npm run desktop:dev

# the real boot order, against the checkout (no packaging)
PANTLER_ENGINE_HOME="$PWD/../../.hermes-dev" \
PANTLER_ENGINE_BIN="$PWD/../../.hermes-dev/src/hermes-agent/.hermes/bin/hermes" \
PANTLER_PYTHON="$(command -v python3)" \
PANTLER_SERVER="$PWD/../server" PANTLER_SHELL="$PWD/../web/dist" PANTLER_PACKS="$PWD/../../packs" \
npm start
```

`npm start` calls `ensureEngineKey` on the profile's `.env`: a profile with no `API_SERVER_KEY` gets
one, 0600, on first run.

## Tests

```sh
npm test          # node --test, no Electron and no display
```

They cover the parts that decide whether a child starts, restarts or is stopped, and where a file
lives. The window itself needs a display and a packaged payload, so it is verified on a machine,
not here.

## The internal Windows build

```sh
npm run build:win   # electron-builder, NSIS x64, per-user, unsigned
```

Unsigned while the product is internal. The payload (`payload/runtime`) is staged by
`scripts/build-windows-payload.ps1` (still to be written) and is the next piece: a venv's
`python.exe` is a redirector Windows refuses under a packaged interpreter, so the runtime launches
the bundled interpreter with an explicit `sys.path`.

## Updates

The feed is the public releases page, `releases/latest/download`, via `electron-updater`. The
release workflow builds `latest.yml` beside the installer and attaches both; the app reads that one
file, so no GitHub API token or rate limit is involved.

A packaged build checks after launch (about 15 s) and every four hours, downloads in the background,
and **asks** before installing: the shell shows a strip and Settings → About has the state and the
buttons. Nothing installs on quit (`autoInstallOnAppQuit` is off). `PANTLER_UPDATES=0` disables the
updater, and `PANTLER_UPDATE_FEED` points a test at a stub feed.

**The engine and the BFF are stopped before the installer runs.** `quitAndInstall` spawns the
installer and *then* quits, and both children execute from the directory the installer replaces —
Windows will not replace a running `runtime/python.exe`. That order is `updates.mjs::install`, and
`test/updates.test.mjs` holds it.

The installer is unsigned, so `electron-updater` skips Authenticode verification: `app-update.yml`
carries no `publisherName` and `NsisUpdater.verifySignature` returns `null` rather than failing
(`out/NsisUpdater.js`). The update is still checked against the SHA-512 in `latest.yml` over TLS, but
**the trust is the repository, not a publisher signature** — whoever can publish a release can ship
code to every install. Code signing is the gate that closes that, not a cosmetic step.

`electron-updater` is CommonJS and exposes `autoUpdater` as a getter on `module.exports`, which the
ESM loader cannot see as a named export. `import { autoUpdater } from 'electron-updater'` therefore
throws while the main module links — before `boot` — and the installed app shows "A JavaScript
error occurred in the main process" instead of opening. v0.0.3 shipped exactly that. Import the
CommonJS default lazily inside `startUpdates`, never at the top of `main.mjs`, so a broken updater
can only turn updates off; `test/update-config.test.mjs` holds the shape.

To ship an update: bump `distribution/distribution.yaml` **and** `app/desktop/package.json` (the
release job refuses a mismatch), write `export/release-notes/vX.Y.Z.md`, run
`scripts/export-public.sh` (which tags the public commit), and the public release workflow installs
the installer it just built, boots it headless, and only then attaches it and `latest.yml`.

**0.0.4 cannot update itself.** It has no working updater (it does not even open); 0.0.5 is the first
build that can, so the first self-update is 0.0.5 → 0.0.6.

## Not here yet

- payload staging and a committed lockfile (`npm ci`)
- a `windows-latest` CI job that builds, silent-installs and smoke-launches
- the clean-Windows-11 acceptance run
- a real 0.0.5 → 0.0.6 update on Windows (the Linux dev box cannot exercise the installer)
- code signing (a separate gate, needed before the trust can move off the repository)
