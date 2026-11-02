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

import { app, BrowserWindow, dialog } from 'electron'
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

const HERE = path.dirname(fileURLToPath(import.meta.url))
const supervisor = new Supervisor()
let mainWindow = null
let shuttingDown = false
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

const UPDATE_INTERVAL_MS = 6 * 60 * 60 * 1000

/**
 * The update check. Off unless the build is packaged and the machine opted in: until the
 * installer is code-signed, an update is an unsigned download Windows will interrupt, and a feed
 * we do not sign is a code path we do not control. `PANTLER_UPDATE_FEED` points a test at a stub.
 */
async function startUpdates() {
  if (!app.isPackaged) {
    trace('updates: skipped (not a packaged build)')
    return
  }
  if (process.env.PANTLER_UPDATES !== '1') {
    trace('updates: off (PANTLER_UPDATES is not 1)')
    return
  }
  // electron-updater is CommonJS: `autoUpdater` is a getter on `module.exports`, which the ESM
  // loader cannot see as a named export. `import { autoUpdater }` therefore throws while the
  // module graph is still linking — before `boot` and before the window — and the installed app
  // never opens (v0.0.3 shipped exactly that). Take the CommonJS default, and take it here
  // rather than at the top so a broken updater can only turn updates off.
  const { autoUpdater } = (await import('electron-updater')).default
  const feed = (process.env.PANTLER_UPDATE_FEED || '').trim()
  if (feed) {
    autoUpdater.setFeedURL({ provider: 'generic', url: feed })
    trace(`updates: feed ${feed}`)
  }
  autoUpdater.autoDownload = true
  autoUpdater.autoInstallOnAppQuit = true
  autoUpdater.logger = {
    info: message => trace(`updates: ${message}`),
    warn: message => trace(`updates: warn ${message}`),
    error: message => trace(`updates: error ${message}`),
    debug: () => {}
  }
  for (const event of [
    'checking-for-update',
    'update-available',
    'update-not-available',
    'update-downloaded',
    'error'
  ]) {
    autoUpdater.on(event, payload => {
      const detail =
        payload instanceof Error ? payload.message : payload ? JSON.stringify(payload) : ''
      trace(`updates: ${event}${detail ? ` ${detail}` : ''}`)
    })
  }
  const check = () =>
    autoUpdater
      .checkForUpdatesAndNotify()
      .catch(error => trace(`updates: check failed ${error?.message ?? error}`))
  check()
  const timer = setInterval(check, UPDATE_INTERVAL_MS)
  if (typeof timer?.unref === 'function') timer.unref()
}

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
  trace(`boot: engine ${engineBin} ${[...enginePrefix, '-p', paths.profile, 'gateway', 'run'].join(' ')}`)
  supervisor.start(
    'engine',
    engineBin,
    [...enginePrefix, '-p', paths.profile, 'gateway', 'run'],
    {
      env: engineEnvironment(paths, process.env, enginePort),
      cwd: paths.engineHome
    }
  )
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
