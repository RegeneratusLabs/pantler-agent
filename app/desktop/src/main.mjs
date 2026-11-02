/**
 * The Electron host: the same web bundle, with the engine and the BFF as its children.
 *
 * This file owns only what a browser cannot do — the process lifetime, the window, the first-run
 * key, and the shutdown order. Where things live is `paths.mjs`; how a child is restarted is
 * `supervisor.mjs`; both are Electron-free and tested without a display.
 *
 * The window loads the BFF's own origin. `/seam` is forwarded from there with the engine's key,
 * so the renderer never holds a credential and the engine stays on loopback
 * (the desktop notes §3–4).
 */

import { app, BrowserWindow, dialog, ipcMain } from 'electron'
import { writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import {
  desktopPaths,
  ensureDirectories,
  ensureEngineKey,
  engineEnvironment,
  freePort,
  bffEnvironment,
  installProfile,
  waitForJson
} from './paths.mjs'
import { Supervisor } from './supervisor.mjs'
import { createUpdater } from './updates.mjs'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const supervisor = new Supervisor()
let mainWindow = null
let shuttingDown = false
// What the engine was started with. `restartEngine` reuses it: the API key and port are decided
// once, and a restart must not move them out from under the BFF.
let engineRuntime = null
// Set once the updater is built. `null` is "not available in this build", answered as disabled.
let updates = null
// Loaded in `boot`: a packaged build reads the identity from `resources/identity`, because the
// module lives outside `app/desktop` and cannot be inside the asar's own relative tree.
let identity = null
// A boot trace costs one small append per stage and is the difference between "it did not
// start" and a line to fix. It never carries a secret: stages and errors only.
let traceFile = null

function trace(line) {
  if (!traceFile) return
  try {
    writeFileSync(traceFile, `${new Date().toISOString()} ${line}\n`, { flag: 'a' })
  } catch {
    // Diagnostics must never take the app down.
  }
}

async function loadIdentity() {
  if (!app.isPackaged) {
    return (await import('../../identity/identity.mjs')).default
  }
  const file = path.join(process.resourcesPath, 'identity', 'identity.mjs')
  return (await import(pathToFileURL(file).href)).default
}

function createWindow(url) {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 860,
    minWidth: 960,
    minHeight: 640,
    backgroundColor: '#f6f1e7',
    title: identity?.displayName ?? 'pantler',
    show: false,
    webPreferences: {
      preload: path.join(HERE, 'preload.mjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true
    }
  })
  mainWindow.once('ready-to-show', () => mainWindow?.show())
  mainWindow.on('closed', () => {
    mainWindow = null
  })
  mainWindow.loadURL(url)
}

/**
 * The updater's state, mirrored for the window.
 *
 * `null` until `startUpdates` runs; `disabled` is the honest answer for a development build or a
 * machine that opted out. The renderer reads it on mount and then follows the broadcasts.
 */
let updateState = null

function disabledUpdateState() {
  return {
    status: 'disabled',
    currentVersion: app.getVersion(),
    version: null,
    percent: null,
    error: null,
    checkedAt: null
  }
}

function broadcastUpdate(state) {
  updateState = state
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('pantler:update-state', state)
  }
}

/**
 * The update check. On for a packaged build unless the machine opts out with
 * `PANTLER_UPDATES=0`; `PANTLER_UPDATE_FEED` points a test at a stub.
 *
 * The controller stops the engine and the BFF before the installer runs. They execute from the
 * directory the installer replaces, and Windows will not replace a running binary — without that
 * order the update installs nothing and leaves the old version in place.
 *
 * `electron-updater` is CommonJS: `autoUpdater` is a getter on `module.exports`, which the ESM
 * loader cannot see as a named export. `import { autoUpdater }` therefore throws while the module
 * graph is still linking — before `boot` and before the window — and the installed app never
 * opens (v0.0.3 shipped exactly that). Take the CommonJS default, and take it here rather than at
 * the top so a broken updater can only turn updates off.
 */
async function startUpdates() {
  if (!app.isPackaged) {
    trace('updates: skipped (not a packaged build)')
    broadcastUpdate(disabledUpdateState())
    return
  }
  if (process.env.PANTLER_UPDATES === '0') {
    trace('updates: off (PANTLER_UPDATES=0)')
    broadcastUpdate(disabledUpdateState())
    return
  }

  let autoUpdater
  try {
    autoUpdater = (await import('electron-updater')).default.autoUpdater
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    trace(`updates: unavailable ${message}`)
    broadcastUpdate({ ...disabledUpdateState(), status: 'error', error: message })
    return
  }

  const feed = (process.env.PANTLER_UPDATE_FEED || '').trim()
  if (feed) {
    autoUpdater.setFeedURL({ provider: 'generic', url: feed })
    trace(`updates: feed ${feed}`)
  }
  autoUpdater.logger = {
    info: message => trace(`updates: ${message}`),
    warn: message => trace(`updates: warn ${message}`),
    error: message => trace(`updates: error ${message}`),
    debug: () => {}
  }

  updates = createUpdater({
    updater: autoUpdater,
    stopChildren: () => supervisor.stopAll(),
    onState: broadcastUpdate,
    trace,
    currentVersion: app.getVersion()
  })
  updates.start()
  broadcastUpdate(updates.snapshot())
}

ipcMain.handle('pantler:update-state', () => updateState ?? disabledUpdateState())

ipcMain.handle('pantler:update-check', async () => {
  if (!updates) return disabledUpdateState()
  return updates.check()
})

ipcMain.handle('pantler:update-install', async event => {
  if (!mainWindow || event.sender !== mainWindow.webContents) {
    return { ok: false, error: 'This request did not come from the Pantler window.' }
  }
  if (!updates) return { ok: false, error: 'Updates are not available in this build.' }
  return updates.install()
})

/**
 * Start the engine child. Called at boot and again when a model is connected in the app: the key
 * is written to the profile's `.env`, and the engine reads that file when the gateway starts.
 */
function startEngine() {
  if (!engineRuntime) throw new Error('the engine has not been configured')
  const spec = engineRuntime
  supervisor.start(
    'engine',
    spec.bin,
    [...spec.prefix, '-p', spec.paths.profile, 'gateway', 'run'],
    {
      env: engineEnvironment(spec.paths, process.env, spec.port),
      cwd: spec.paths.engineHome
    }
  )
}

/**
 * Stop and start the engine, then wait until it answers again. The BFF keeps its own URL and key,
 * so it does not need restarting; only the engine does, and only because `.env` is read at start.
 */
async function restartEngine() {
  if (!engineRuntime) return { ok: false, error: 'The engine has not started yet.' }
  trace('engine: restart requested')
  // `restart`, not stop-then-start: the supervisor keeps the child's command and environment, and
  // `start` refuses a name it already knows.
  await supervisor.restart('engine')
  await waitForJson(`http://127.0.0.1:${engineRuntime.port}/v1/capabilities`, {
    headers: { Authorization: `Bearer ${engineRuntime.key}` },
    timeoutMs: 120_000
  })
  trace('engine: restarted')
  return { ok: true }
}

ipcMain.handle('pantler:restart-engine', async event => {
  // Only the window we created may ask. The bridge is exposed to the page, and a page that is not
  // ours has no business stopping a child process.
  if (!mainWindow || event.sender !== mainWindow.webContents) {
    return { ok: false, error: 'This request did not come from the Pantler window.' }
  }
  try {
    return await restartEngine()
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    trace(`engine: restart failed ${message}`)
    return { ok: false, error: message }
  }
})

async function boot() {
  identity = await loadIdentity()
  if (process.platform === 'win32') app.setAppUserModelId(identity.appId)

  const paths = desktopPaths({
    userData: app.getPath('userData'),
    resources: process.resourcesPath
  })
  ensureDirectories(paths)
  supervisor.logDir = paths.logs
  traceFile = path.join(paths.logs, 'boot-trace.log')
  trace(`boot: userData=${paths.userData} resources=${process.resourcesPath}`)
  supervisor.onEvent = event =>
    trace(
      `child: ${event.name} ${event.type}` +
        (event.error?.message ? ` ${event.error.message}` : '') +
        (event.code !== undefined ? ` code=${event.code}` : '')
    )

  // The development shape: point the shell at the Vite dev server and supervise nothing. The
  // browser build stays the fast loop; this is what makes working on the shell cheap
  // (the desktop notes §2).
  if (process.env.PANTLER_DEV_URL) {
    trace('boot: dev url, no children')
    createWindow(process.env.PANTLER_DEV_URL)
    return
  }

  // A first run copies the profile the payload was built with; it does not run an installer, ask
  // for a terminal or touch the network. An existing profile is the operator's and is left alone.
  trace(`boot: profile template copied=${installProfile(paths)}`)
  const key = ensureEngineKey(paths.envFile)
  // A free port, told to the engine and to the BFF: the engine's API server defaults to 8642,
  // and the dev multiplexer's 8644 is not a number an installed app may assume.
  const enginePort = Number(process.env.PANTLER_ENGINE_PORT || (await freePort()))
  const bffPort = await freePort()

  // The payload runs the bundled interpreter with the launcher shim. A development checkout can
  // point `PANTLER_ENGINE_BIN` at the mirror's own `hermes` launcher instead.
  const engineBin = process.env.PANTLER_ENGINE_BIN || paths.python
  const enginePrefix = process.env.PANTLER_ENGINE_BIN ? [] : [paths.launcher]
  engineRuntime = { bin: engineBin, prefix: enginePrefix, paths, port: enginePort, key }
  trace(`boot: engine ${engineBin} ${[...enginePrefix, '-p', paths.profile, 'gateway', 'run'].join(' ')}`)
  startEngine()
  // The shipped profile carries `gateway.standalone: true`, so its API server answers on the
  // bare route; the `/p/<name>/` shape belongs to the host multiplexer the dev box runs.
  await waitForJson(`http://127.0.0.1:${enginePort}/v1/capabilities`, {
    headers: { Authorization: `Bearer ${key}` },
    timeoutMs: 180_000
  })
  trace('boot: engine ready')

  trace(`boot: bff on ${bffPort}`)
  supervisor.start(
    'bff',
    paths.python,
    [
      path.join(paths.server, 'pantler_server.py'),
      '--host',
      '127.0.0.1',
      '--port',
      String(bffPort),
      '--store',
      paths.store,
      '--packs',
      paths.packs,
      '--profile-dir',
      paths.profileDir,
      '--static',
      paths.shell,
      '--engine-url',
      `http://127.0.0.1:${enginePort}`,
      '--engine-key-file',
      paths.envFile
    ],
    { cwd: paths.server, env: bffEnvironment(paths) }
  )
  await waitForJson(`http://127.0.0.1:${bffPort}/api/health`, { timeoutMs: 120_000 })
  trace('boot: bff ready')

  // A packaging smoke run proves the boot order without opening a window: the installer job
  // waits for this marker, so "it installed" and "it starts" are two different checks.
  if (process.env.PANTLER_SMOKE === '1') {
    writeFileSync(path.join(paths.userData, 'smoke-ok'), 'engine and bff ready\n')
    app.quit()
    return
  }

  createWindow(`http://127.0.0.1:${bffPort}`)
  // Updates are optional. A failure to load or check them is a trace line, never a dead window:
  // the app has already booted, and the only thing that should change is that updates are off.
  await startUpdates().catch(error =>
    trace(`updates: unavailable ${error?.message ?? error}`)
  )
}

function fail(error) {
  const message = error instanceof Error ? error.message : String(error)
  if (traceFile) {
    try {
      writeFileSync(path.join(path.dirname(traceFile), 'boot-error.txt'), `${message}\n\n${error?.stack ?? ''}`)
    } catch {
      // Diagnostics only.
    }
  }
  dialog.showErrorBox(
    `${identity?.displayName ?? 'pantler'} could not start`,
    `${message}\n\nLogs: ${path.join(app.getPath('userData'), 'logs')}`
  )
  app.quit()
}

if (!app.requestSingleInstanceLock()) {
  app.quit()
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore()
      mainWindow.focus()
    }
  })

  app.whenReady().then(async () => {
    try {
      await boot()
    } catch (error) {
      trace(`boot: failed ${error instanceof Error ? error.stack : String(error)}`)
      fail(error)
    }
  })

  app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') app.quit()
  })

  // Children exit before the app does: a gateway left behind holds the profile's database and the
  // next launch finds it locked.
  app.on('before-quit', event => {
    if (shuttingDown) return
    event.preventDefault()
    shuttingDown = true
    supervisor.stopAll().finally(() => app.quit())
  })
}
